"""
Win32 NTFS FileId (64-bit File Reference Number + Volume Serial Number) tracker.
Resolves renamed or moved files & directories in < 0.1ms via `OpenFileById` + `GetFinalPathNameByHandleW`,
with automatic `$Recycle.Bin` exclusion so deleted files are never mistakenly tracked into Recycle Bin.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from .models import normalize_path


OPEN_EXISTING = 3
FILE_SHARE_ALL = 0x00000001 | 0x00000002 | 0x00000004
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
VOLUME_NAME_DOS = 0x0


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


class _FILE_ID_UNION(ctypes.Union):
    _fields_ = [
        ("FileId", ctypes.c_longlong),
        ("ObjectId", ctypes.c_ubyte * 16),  # Ensures exact 24-byte sizeof(_FILE_ID_DESCRIPTOR) per winbase.h
    ]


class _FILE_ID_DESCRIPTOR(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Type", ctypes.c_int),             # 0 = FileIdType (64-bit FileId)
        ("u", _FILE_ID_UNION),
    ]


_kernel32 = ctypes.windll.kernel32

_CreateFileW = _kernel32.CreateFileW
_CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_CreateFileW.restype = wintypes.HANDLE

_CloseHandle = _kernel32.CloseHandle
_CloseHandle.argtypes = [wintypes.HANDLE]
_CloseHandle.restype = wintypes.BOOL

_GetFileInformationByHandle = _kernel32.GetFileInformationByHandle
_GetFileInformationByHandle.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION),
]
_GetFileInformationByHandle.restype = wintypes.BOOL

_OpenFileById = _kernel32.OpenFileById
_OpenFileById.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(_FILE_ID_DESCRIPTOR),
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_OpenFileById.restype = wintypes.HANDLE

_GetFinalPathNameByHandleW = _kernel32.GetFinalPathNameByHandleW
_GetFinalPathNameByHandleW.argtypes = [
    wintypes.HANDLE,
    wintypes.LPWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
]
_GetFinalPathNameByHandleW.restype = wintypes.DWORD

_GetLogicalDrives = _kernel32.GetLogicalDrives
_GetLogicalDrives.argtypes = []
_GetLogicalDrives.restype = wintypes.DWORD


def _is_valid_handle(h) -> bool:
    return bool(h) and int(h) != INVALID_HANDLE_VALUE


def _strip_extended_prefix(raw_path: str) -> str:
    if raw_path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + raw_path[8:]
    if raw_path.startswith("\\\\?\\"):
        return raw_path[4:]
    return raw_path


def _is_recycle_bin_path(path: str) -> bool:
    low = path.lower()
    return "\\$recycle.bin\\" in low or low.endswith("\\$recycle.bin")


def get_file_identity(path: str) -> tuple[int, int] | None:
    """
    Return `(volume_serial, file_id_64)` for any existing file or folder on NTFS/ReFS.
    Uses `dwDesiredAccess = 0` so locked files and directories open without contention.
    """
    norm = normalize_path(path)
    if not norm or not os.path.exists(norm):
        return None

    h = _CreateFileW(
        norm,
        0,
        FILE_SHARE_ALL,
        None,
        OPEN_EXISTING,
        FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if not _is_valid_handle(h):
        return None

    try:
        info = _BY_HANDLE_FILE_INFORMATION()
        if not _GetFileInformationByHandle(h, ctypes.byref(info)):
            return None
        vol_serial = int(info.dwVolumeSerialNumber)
        file_id = (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        if vol_serial == 0 or file_id == 0:
            return None
        return vol_serial, file_id
    finally:
        _CloseHandle(h)


def _open_matching_volume_handle(volume_serial: int, hint_path: str = "") -> wintypes.HANDLE | None:
    """Open a root directory handle whose `dwVolumeSerialNumber` matches `volume_serial`."""
    candidates: list[str] = []
    if len(hint_path) >= 2 and hint_path[1] == ":":
        candidates.append(hint_path[:2].upper() + "\\")

    bitmask = _GetLogicalDrives()
    for i in range(26):
        if bitmask & (1 << i):
            drv = f"{chr(ord('A') + i)}:\\"
            if drv not in candidates:
                candidates.append(drv)

    for root in candidates:
        h = _CreateFileW(
            root,
            0,
            FILE_SHARE_ALL,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if not _is_valid_handle(h):
            continue
        info = _BY_HANDLE_FILE_INFORMATION()
        if _GetFileInformationByHandle(h, ctypes.byref(info)) and int(info.dwVolumeSerialNumber) == volume_serial:
            return h
        _CloseHandle(h)
    return None


def resolve_path_by_identity(
    volume_serial: int,
    file_id: int,
    hint_path: str = "",
) -> str | None:
    """
    Locate the current filesystem path of `(volume_serial, file_id)` via Win32 `OpenFileById`.
    Returns None if deleted (or moved to `$Recycle.Bin`) or volume is offline.
    """
    if not volume_serial or not file_id:
        return None

    h_vol = _open_matching_volume_handle(volume_serial, hint_path=hint_path)
    if h_vol is None:
        return None

    try:
        desc = _FILE_ID_DESCRIPTOR()
        desc.dwSize = ctypes.sizeof(_FILE_ID_DESCRIPTOR)
        desc.Type = 0  # FileIdType
        # Store unsigned 64-bit integer safely into signed 64-bit c_longlong union field
        desc.u.FileId = ctypes.c_longlong(file_id & 0xFFFFFFFFFFFFFFFF).value

        h_target = _OpenFileById(
            h_vol,
            ctypes.byref(desc),
            0,
            FILE_SHARE_ALL,
            None,
            FILE_FLAG_BACKUP_SEMANTICS,
        )
        if not _is_valid_handle(h_target):
            return None

        try:
            buf = ctypes.create_unicode_buffer(2048)
            length = _GetFinalPathNameByHandleW(h_target, buf, 2048, VOLUME_NAME_DOS)
            if length == 0 or length >= 2048:
                return None
            clean = normalize_path(_strip_extended_prefix(buf.value))
            if not clean or _is_recycle_bin_path(clean) or not os.path.exists(clean):
                return None
            return clean
        finally:
            _CloseHandle(h_target)
    finally:
        _CloseHandle(h_vol)
