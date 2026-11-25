"""
System-wide Win32 `SetWinEventHook` event monitor (`WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS`).
Delivers 0ms notifications for:
- Foreground / minimize / popup menu window changes
- Native refresh-rate (120Hz+) Explorer / File Dialog window dragging (`trackedWindowMoved`)
- Mouse-wheel / scrollbar scrolling, item selection, and breadcrumb navigation (`viewContentChanged`)
Allows background UIA sensors to sleep at 0.00% CPU when idle!
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

from PySide6.QtCore import QObject, Signal
import win32con


WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002

EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MENUSTART = 0x0004
EVENT_SYSTEM_MENUEND = 0x0005
EVENT_SYSTEM_MENUPOPUPSTART = 0x0006
EVENT_SYSTEM_MENUPOPUPEND = 0x0007
EVENT_SYSTEM_MOVESIZESTART = 0x000A
EVENT_SYSTEM_MOVESIZEEND = 0x000B
EVENT_SYSTEM_SCROLLINGSTART = 0x0012
EVENT_SYSTEM_SCROLLINGEND = 0x0013
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017

EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_FOCUS = 0x8005
EVENT_OBJECT_SELECTION = 0x8006
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
EVENT_OBJECT_NAMECHANGE = 0x800C

OBJID_WINDOW = 0

WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)

_user32 = ctypes.windll.user32

_SetWinEventHook = _user32.SetWinEventHook
_SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
_SetWinEventHook.restype = wintypes.HANDLE

_UnhookWinEvent = _user32.UnhookWinEvent
_UnhookWinEvent.argtypes = [wintypes.HANDLE]
_UnhookWinEvent.restype = wintypes.BOOL

_GetAncestor = _user32.GetAncestor
_GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_GetAncestor.restype = wintypes.HWND


class WinEventMonitor(QObject):
    """Lightweight event-driven Win32 hook running on Qt's main GUI message pump."""

    foregroundOrStateChanged = Signal()
    trackedWindowMoved = Signal(int)     # emits tracked top-level hwnd at full drag FPS
    viewContentChanged = Signal()        # emits throttled wake signal on scroll/popup/navigate

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tracked_hwnd: int = 0
        self._hooks: list[wintypes.HANDLE] = []
        self._last_content_emit: float = 0.0
        # Keep strong reference to C callback so Python GC never collects it while hooked!
        self._proc_ref = WINEVENTPROC(self._on_win_event)

    def set_tracked_hwnd(self, hwnd: int) -> None:
        self._tracked_hwnd = int(hwnd) if hwnd else 0

    def start(self) -> None:
        if self._hooks:
            return
        flags = WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS
        ranges = [
            (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MOVESIZEEND),
            (EVENT_SYSTEM_SCROLLINGSTART, EVENT_SYSTEM_MINIMIZEEND),
            (EVENT_OBJECT_SHOW, EVENT_OBJECT_NAMECHANGE),
        ]
        for ev_min, ev_max in ranges:
            h = _SetWinEventHook(ev_min, ev_max, None, self._proc_ref, 0, 0, flags)
            if h:
                self._hooks.append(h)

    def stop(self) -> None:
        for h in self._hooks:
            try:
                _UnhookWinEvent(h)
            except Exception:
                pass
        self._hooks.clear()

    def _emit_content_throttled(self, min_interval: float = 0.015) -> None:
        now = time.monotonic()
        if (now - self._last_content_emit) >= min_interval:
            self._last_content_emit = now
            self.viewContentChanged.emit()

    def _on_win_event(
        self,
        _h_hook,
        event: int,
        hwnd,
        id_object: int,
        _id_child: int,
        _thread_id: int,
        _ms_time: int,
    ) -> None:
        try:
            ih = int(hwnd) if hwnd else 0

            # 1. System-level foreground / minimize / menu transitions
            if event in (
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_MINIMIZESTART,
                EVENT_SYSTEM_MINIMIZEEND,
            ):
                self.foregroundOrStateChanged.emit()
                return

            if event in (
                EVENT_SYSTEM_MENUSTART,
                EVENT_SYSTEM_MENUEND,
                EVENT_SYSTEM_MENUPOPUPSTART,
                EVENT_SYSTEM_MENUPOPUPEND,
                EVENT_SYSTEM_MOVESIZEEND,
            ):
                self.foregroundOrStateChanged.emit()
                self._emit_content_throttled(0.0)
                return

            tracked = self._tracked_hwnd
            if not tracked or not ih:
                return

            # 2. Exact top-level tracked window move/resize -> 0ms lockstep overlay translation!
            if ih == tracked and id_object == OBJID_WINDOW and event == EVENT_OBJECT_LOCATIONCHANGE:
                self.trackedWindowMoved.emit(tracked)
                return

            # 3. Top-level popup/menu window shown or hidden (e.g. Win11 PopupWindowSiteBridge)
            if id_object == OBJID_WINDOW and event in (EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE):
                self._emit_content_throttled(0.010)
                return

            # 4. Events inside the tracked Explorer / File Dialog hierarchy (scrolling, folder nav, rename)
            if event in (
                EVENT_SYSTEM_SCROLLINGSTART,
                EVENT_SYSTEM_SCROLLINGEND,
                EVENT_OBJECT_LOCATIONCHANGE,
                EVENT_OBJECT_NAMECHANGE,
                EVENT_OBJECT_SELECTION,
                EVENT_OBJECT_FOCUS,
            ):
                if ih == tracked:
                    if event == EVENT_OBJECT_NAMECHANGE:
                        self.foregroundOrStateChanged.emit()
                    self._emit_content_throttled(0.015)
                    return

                root = _GetAncestor(wintypes.HWND(ih), win32con.GA_ROOT)
                if root and int(root) == tracked:
                    if event == EVENT_OBJECT_NAMECHANGE:
                        self.foregroundOrStateChanged.emit()
                    self._emit_content_throttled(0.015)
        except Exception:
            pass
