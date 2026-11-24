"""System-wide Win32 global hotkey manager integrated with Qt's native event loop."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal


WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

VK_MAP: dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): ord(str(d)) for d in range(0, 10)},
    **{f"F{i}": 0x70 + i - 1 for i in range(1, 13)},
    "SPACE": 0x20,
    "TAB": 0x09,
    "RETURN": 0x0D,
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "BACKSPACE": 0x08,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "UP": 0x26,
    "DOWN": 0x28,
    "LEFT": 0x25,
    "RIGHT": 0x27,
    "`": 0xC0,
    "~": 0xC0,
    "-": 0xBD,
    "=": 0xBB,
    "[": 0xDB,
    "]": 0xDD,
    ";": 0xBA,
    "'": 0xDE,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "\\": 0xDC,
}


def parse_hotkey(shortcut: str) -> tuple[int, int] | None:
    """Parse human-readable shortcut like 'Alt+A' or 'Ctrl+Shift+Space' into (modifiers, vk)."""
    if not shortcut or not shortcut.strip():
        return None
    parts = [p.strip().upper() for p in shortcut.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None

    mods = MOD_NOREPEAT
    vk = 0
    for part in parts:
        if part in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif part == "ALT":
            mods |= MOD_ALT
        elif part == "SHIFT":
            mods |= MOD_SHIFT
        elif part in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        elif part in VK_MAP:
            vk = VK_MAP[part]
        else:
            return None

    if vk == 0:
        return None
    return mods, vk


class _WinHotkeyEventFilter(QAbstractNativeEventFilter):
    """Intercepts WM_HOTKEY messages from Windows thread queue."""

    def __init__(self, callback: Callable[[int], None]) -> None:
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, eventType, message):
        if eventType in (b"windows_generic_MSG", b"windows_dispatcher_MSG", "windows_generic_MSG", "windows_dispatcher_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    self._callback(int(msg.wParam))
                    return True, 0
            except Exception:
                pass
        return False, 0


class GlobalHotkeyManager(QObject):
    """Registers and manages global Windows hotkeys cleanly."""

    triggered = Signal(str)  # emits action_name ("toggle", "search", "quick_add", ...)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._user32 = ctypes.windll.user32
        self._next_id = 1001
        self._id_to_action: dict[int, str] = {}
        self._action_to_shortcut: dict[str, str] = {}
        self._failed_actions: dict[str, str] = {}
        self._filter = _WinHotkeyEventFilter(self._on_wm_hotkey)
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    def _on_wm_hotkey(self, hotkey_id: int) -> None:
        action = self._id_to_action.get(hotkey_id)
        if action:
            self.triggered.emit(action)

    def unregister_all(self) -> None:
        for hid in list(self._id_to_action.keys()):
            try:
                self._user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
        self._id_to_action.clear()
        self._action_to_shortcut.clear()
        self._failed_actions.clear()

    def register_bindings(self, bindings: dict[str, str]) -> dict[str, str]:
        """
        Register {action_name: shortcut_str}.
        Returns {action_name: error_reason} for any binding that failed (e.g. conflict).
        """
        self.unregister_all()
        errors: dict[str, str] = {}
        for action, shortcut in bindings.items():
            if not shortcut or not shortcut.strip():
                continue
            parsed = parse_hotkey(shortcut)
            if parsed is None:
                errors[action] = f"快捷键格式无效: {shortcut}"
                continue
            mods, vk = parsed
            hid = self._next_id
            self._next_id += 1
            ok = bool(self._user32.RegisterHotKey(None, hid, mods, vk))
            if ok:
                self._id_to_action[hid] = action
                self._action_to_shortcut[action] = shortcut
            else:
                errors[action] = f"快捷键 {shortcut} 已被其他程序占用"
        self._failed_actions = errors
        return errors

    @property
    def active_shortcuts(self) -> dict[str, str]:
        return dict(self._action_to_shortcut)

    @property
    def failed_shortcuts(self) -> dict[str, str]:
        return dict(self._failed_actions)
