"""
High-speed (2ms) IUIAutomation batch item sensor for rendering inline '(别名或用途)'
directly after file and folder names inside Windows 10/11 Explorer and #32770 Open/Save Dialogs.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import threading
import time
import winreg

import comtypes
import comtypes.client
import pythoncom
import win32gui
import win32process
from PySide6.QtCore import QObject, QThread, Signal

from .models import AliasEntry, WindowContext
from .storage import AliasStore


UIA_BoundingRectanglePropertyId = 30001
UIA_ControlTypePropertyId = 30003
UIA_NamePropertyId = 30005
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_IsOffscreenPropertyId = 30022
UIA_ValueValuePropertyId = 30045

UIA_HeaderItemControlTypeId = 50031
TreeScope_Descendants = 4

GUI_INMENUMODE = 0x00000004
GUI_SYSTEMMENUMODE = 0x00000008
GUI_POPUPMENUMODE = 0x00000010


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


@dataclass(frozen=True)
class InlineItemAnchor:
    """Exact screen bounding rect of a visible file/folder's name cell and its matched AliasEntry."""

    path_key: str
    display_name: str
    alias: str
    note: str
    color: str
    name_rect: tuple[int, int, int, int]      # Physical pixels (left, top, right, bottom)


@dataclass(frozen=True)
class InlineViewSnapshot:
    """Complete snapshot of all aliased items currently visible inside Explorer / File Dialog."""

    hwnd: int
    viewport_rect: tuple[int, int, int, int]                  # Clipped DirectUIHWND rect below column header
    is_dark_bg: bool
    items: tuple[InlineItemAnchor, ...]
    occluding_rects: tuple[tuple[int, int, int, int], ...] = ()  # Menus/popups/windows above `hwnd` in Z-order


GW_HWNDPREV = 3
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
DWMWA_CLOAKED = 14

_user32 = ctypes.windll.user32
_dwmapi = ctypes.windll.dwmapi

_GetGUIThreadInfo = _user32.GetGUIThreadInfo
_GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]
_GetGUIThreadInfo.restype = wintypes.BOOL

_IsChild = _user32.IsChild
_IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
_IsChild.restype = wintypes.BOOL

_GetWindow = _user32.GetWindow
_GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
_GetWindow.restype = wintypes.HWND

_GetWindowLongW = _user32.GetWindowLongW
_GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongW.restype = ctypes.c_long


def _is_window_cloaked(hwnd: int) -> bool:
    cloaked = ctypes.c_int(0)
    try:
        hr = _dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_CLOAKED),
            ctypes.byref(cloaked),
            ctypes.sizeof(cloaked),
        )
        return hr == 0 and bool(cloaked.value)
    except Exception:
        return False


def _is_inline_renaming(target_hwnd: int, def_view_hwnd: int) -> bool:
    """Return True if the user is actively typing an inline F2 filename rename inside SHELLDLL_DefView."""
    try:
        tid, _ = win32process.GetWindowThreadProcessId(target_hwnd)
        if tid and def_view_hwnd:
            gti = _GUITHREADINFO()
            gti.cbSize = ctypes.sizeof(_GUITHREADINFO)
            if _GetGUIThreadInfo(wintypes.DWORD(tid), ctypes.byref(gti)):
                if gti.hwndFocus and _IsChild(wintypes.HWND(def_view_hwnd), wintypes.HWND(gti.hwndFocus)):
                    if win32gui.GetClassName(int(gti.hwndFocus)) == "Edit":
                        return True
    except Exception:
        pass
    return False


def collect_occluding_rects(
    target_hwnd: int,
    viewport_rect: tuple[int, int, int, int],
    own_pid: int,
) -> tuple[tuple[int, int, int, int], ...]:
    """
    Walk the Win32 Z-order chain ABOVE `target_hwnd` (GW_HWNDPREV) and collect bounding rects
    of all visible, uncloaked menus/popups/windows (including Win11 PopupWindowSiteBridge right-click
    menus, classic #32768 menus, dropdowns, tooltips, and overlapping windows) that intersect `viewport_rect`.
    """
    vp_l, vp_t, vp_r, vp_b = viewport_rect
    occluders: list[tuple[int, int, int, int]] = []
    cur = _GetWindow(wintypes.HWND(target_hwnd), GW_HWNDPREV)
    steps = 0

    while cur and steps < 120:
        steps += 1
        ih = int(cur)
        cur = _GetWindow(wintypes.HWND(ih), GW_HWNDPREV)

        try:
            if not win32gui.IsWindowVisible(ih) or win32gui.IsIconic(ih):
                continue
            _, pid = win32process.GetWindowThreadProcessId(ih)
            if pid == own_pid:
                continue

            cls = win32gui.GetClassName(ih)
            if "InputIndicator" in cls or cls in ("Progman", "WorkerW", "IME", "MSCTFIME UI"):
                continue

            ex = _GetWindowLongW(wintypes.HWND(ih), GWL_EXSTYLE) & 0xFFFFFFFF
            # Skip click-through transparent HUD overlays (except tooltips which should still occlude)
            if (ex & WS_EX_TRANSPARENT) and (ex & WS_EX_LAYERED) and cls != "tooltips_class32":
                continue

            l, t, r, b = win32gui.GetWindowRect(ih)
            if (r - l) <= 4 or (b - t) <= 4:
                continue

            # Fast AABB intersection with our file list viewport
            ix1 = max(vp_l, l)
            iy1 = max(vp_t, t)
            ix2 = min(vp_r, r)
            iy2 = min(vp_b, b)
            if ix2 <= ix1 or iy2 <= iy1:
                continue

            if _is_window_cloaked(ih):
                continue

            # Expand by 2px so antialiased glyphs never kiss the border of a rounded context menu
            occluders.append((max(vp_l, l - 2), max(vp_t, t - 2), min(vp_r, r + 2), min(vp_b, b + 2)))
        except Exception:
            continue

    return tuple(occluders)


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _find_visible_file_view_hwnds(top_hwnd: int) -> tuple[int, int]:
    """Return (shelldll_defview_hwnd, directui_or_listview_hwnd) using pure ctypes enumeration."""
    def_views: list[tuple[int, int]] = []

    def _cb(ch: int, _lparam: int) -> bool:
        try:
            ih = int(ch)
            if win32gui.IsWindowVisible(ih) and win32gui.GetClassName(ih) == "SHELLDLL_DefView":
                l, t, r, b = win32gui.GetWindowRect(ih)
                area = max(0, r - l) * max(0, b - t)
                if area > 1000:
                    def_views.append((area, ih))
        except Exception:
            pass
        return True

    try:
        ctypes.windll.kernel32.SetLastError(0)
        ctypes.windll.user32.EnumChildWindows(wintypes.HWND(top_hwnd), _WNDENUMPROC(_cb), 0)
    except Exception:
        return 0, 0

    if not def_views:
        return 0, 0

    def_views.sort(reverse=True)
    def_view = def_views[0][1]

    for cls_name in ("DirectUIHWND", "DIRECTUIHWND", "SysListView32"):
        child = win32gui.FindWindowEx(def_view, 0, cls_name, None)
        if child and win32gui.IsWindowVisible(child):
            return def_view, child
    return def_view, def_view


def _is_windows_app_dark_mode() -> bool:
    """Read Windows 10/11 AppsUseLightTheme setting cleanly without GDI screen sampling."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(val) == 0
    except Exception:
        return False


class InlineSensorWorker(QThread):
    """
    Background STA worker using raw COM IUIAutomation.FindAllBuildCache (~2ms per frame)
    to track exact row/filename coordinates inside Explorer and #32770 File Dialogs.
    """

    snapshotChanged = Signal(object)  # InlineViewSnapshot | None

    def __init__(self, store: AliasStore, own_pid: int | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._own_pid = own_pid or os.getpid()
        self._lock = threading.Lock()
        self._running = True
        self._enabled = True
        self._ctx: WindowContext | None = None
        self._force_tick = False
        self._last_snapshot: InlineViewSnapshot | None = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
            self._force_tick = True

    def set_context(self, ctx: WindowContext | None) -> None:
        with self._lock:
            self._ctx = ctx
            self._force_tick = True

    def request_refresh(self) -> None:
        with self._lock:
            self._force_tick = True

    def stop_worker(self) -> None:
        with self._lock:
            self._running = False
        self.wait(1200)

    def _emit_if_changed(self, snap: InlineViewSnapshot | None) -> None:
        if snap != self._last_snapshot:
            self._last_snapshot = snap
            self.snapshotChanged.emit(snap)

    def run(self) -> None:
        pythoncom.CoInitialize()
        try:
            uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
            iuia = comtypes.CoCreateInstance(
                uia_mod.CUIAutomation._reg_clsid_,
                interface=uia_mod.IUIAutomation,
            )
            cache_req = iuia.CreateCacheRequest()
            for prop_id in (
                UIA_BoundingRectanglePropertyId,
                UIA_ControlTypePropertyId,
                UIA_NamePropertyId,
                UIA_AutomationIdPropertyId,
                UIA_ClassNamePropertyId,
                UIA_IsOffscreenPropertyId,
                UIA_ValueValuePropertyId,
            ):
                cache_req.AddProperty(prop_id)

            cond_name_prop = iuia.CreatePropertyCondition(
                UIA_AutomationIdPropertyId, "System.ItemNameDisplay"
            )

            bg_cache_key: tuple[int, str] = (0, "")
            bg_cache_dark: bool = False
            bg_cache_time: float = 0.0

            cached_view_hwnd: int = 0
            cached_el_view = None

            while True:
                with self._lock:
                    if not self._running:
                        break
                    enabled = self._enabled
                    ctx = self._ctx
                    self._force_tick = False

                if not enabled or ctx is None or ctx.is_minimized or not ctx.current_dir:
                    self._emit_if_changed(None)
                    time.sleep(0.10)
                    continue

                # Zero-cost fast path: skip UIAutomation completely if current folder has 0 aliases!
                if not self.store.list_in_dir(ctx.current_dir):
                    self._emit_if_changed(None)
                    time.sleep(0.12)
                    continue

                if not win32gui.IsWindow(ctx.hwnd) or not win32gui.IsWindowVisible(ctx.hwnd):
                    self._emit_if_changed(None)
                    time.sleep(0.10)
                    continue

                def_view, view_hwnd = _find_visible_file_view_hwnds(ctx.hwnd)
                if not view_hwnd:
                    self._emit_if_changed(None)
                    time.sleep(0.10)
                    continue

                if _is_inline_renaming(ctx.hwnd, def_view):
                    self._emit_if_changed(None)
                    time.sleep(0.08)
                    continue

                try:
                    dui_l, dui_t, dui_r, dui_b = win32gui.GetWindowRect(view_hwnd)
                except Exception:
                    self._emit_if_changed(None)
                    time.sleep(0.10)
                    continue

                now = time.monotonic()
                if (view_hwnd, ctx.current_dir) != bg_cache_key or (now - bg_cache_time) > 3.0:
                    bg_cache_dark = _is_windows_app_dark_mode()
                    bg_cache_key = (view_hwnd, ctx.current_dir)
                    bg_cache_time = now

                try:
                    if view_hwnd != cached_view_hwnd or cached_el_view is None:
                        cached_el_view = iuia.ElementFromHandle(view_hwnd)
                        cached_view_hwnd = view_hwnd

                    arr = cached_el_view.FindAllBuildCache(
                        TreeScope_Descendants, cond_name_prop, cache_req
                    )
                except Exception:
                    cached_el_view = None
                    cached_view_hwnd = 0
                    self._emit_if_changed(None)
                    time.sleep(0.10)
                    continue

                header_bottom = dui_t
                raw_rows: list[tuple[str, tuple[int, int, int, int]]] = []

                count = arr.Length if arr else 0
                for i in range(count):
                    try:
                        el = arr.GetElement(i)
                        ctype = el.CachedControlType
                        cls_name = el.CachedClassName or ""
                        rc = el.CachedBoundingRectangle
                        rect_tuple = (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))

                        if ctype == UIA_HeaderItemControlTypeId or cls_name == "UIColumnHeader":
                            if rect_tuple[3] > header_bottom and rect_tuple[3] < dui_b:
                                header_bottom = rect_tuple[3]
                            continue

                        if el.CachedIsOffscreen:
                            continue

                        val_prop = el.GetCachedPropertyValue(UIA_ValueValuePropertyId)
                        disp_name = str(val_prop).strip() if val_prop else ""
                        if not disp_name:
                            continue

                        raw_rows.append((disp_name, rect_tuple))
                    except Exception:
                        continue

                clip_top = max(dui_t, header_bottom + 1)
                # Leave 18px on right for vertical scrollbar so overlay never draws over scrollbar thumb
                clip_right = max(dui_l + 20, dui_r - 18)
                viewport_rect = (dui_l, clip_top, clip_right, dui_b)

                matched_anchors: list[InlineItemAnchor] = []
                for disp_name, r_box in raw_rows:
                    # Must be within visible list viewport vertically and horizontally
                    if r_box[3] <= clip_top + 3 or r_box[1] >= dui_b - 2:
                        continue
                    if r_box[0] >= clip_right or r_box[2] <= dui_l:
                        continue

                    entry: AliasEntry | None = self.store.resolve_item_in_dir(
                        ctx.current_dir, disp_name
                    )
                    if entry is not None:
                        matched_anchors.append(
                            InlineItemAnchor(
                                path_key=entry.path_key,
                                display_name=disp_name,
                                alias=entry.alias,
                                note=entry.note,
                                color=entry.color,
                                name_rect=r_box,
                            )
                        )

                if matched_anchors:
                    occluders = collect_occluding_rects(ctx.hwnd, viewport_rect, self._own_pid)
                    snap = InlineViewSnapshot(
                        hwnd=ctx.hwnd,
                        viewport_rect=viewport_rect,
                        is_dark_bg=bg_cache_dark,
                        items=tuple(matched_anchors),
                        occluding_rects=occluders,
                    )
                    self._emit_if_changed(snap)
                else:
                    self._emit_if_changed(None)

                time.sleep(0.038)
        finally:
            pythoncom.CoUninitialize()
