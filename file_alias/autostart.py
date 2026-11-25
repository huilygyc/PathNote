"""Per-user (HKCU, zero-admin) Windows startup auto-run helper for FileAlias."""

from __future__ import annotations

from pathlib import Path
import sys
import winreg


RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "PathNote"
LEGACY_VALUE_NAME = "FileAlias"


def get_autostart_command() -> str:
    """Build command string for launching FileAlias minimized in tray at login."""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --minimized'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = str(pythonw if pythonw.exists() else exe)
    main_script = str(Path(__file__).resolve().parent.parent / "main.py")
    return f'"{runner}" "{main_script}" --minimized'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            for name in (RUN_VALUE_NAME, LEGACY_VALUE_NAME):
                try:
                    val, _ = winreg.QueryValueEx(key, name)
                    if val:
                        return True
                except FileNotFoundError:
                    continue
            return False
    except OSError:
        return False


def set_autostart_enabled(enabled: bool) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, LEGACY_VALUE_NAME)
            except FileNotFoundError:
                pass
            if enabled:
                winreg.SetValueEx(key, RUN_VALUE_NAME, 0, winreg.REG_SZ, get_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, RUN_VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
