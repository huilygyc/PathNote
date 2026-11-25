"""
Per-user (HKCU, zero-admin) Windows Explorer context menu registration
for '设置中文别名 / 用途 (FileAlias)'.
"""

from __future__ import annotations

from pathlib import Path
import sys
import winreg


MENU_KEY_NAME = "PathNoteSetAlias"
LEGACY_MENU_KEY = "FileAliasSetAlias"
MENU_LABEL = "设置路径备注 (PathNote)"

_TARGETS = [
    (r"Software\Classes\*\shell", "%1"),
    (r"Software\Classes\Directory\shell", "%1"),
    (r"Software\Classes\Directory\Background\shell", "%V"),
]


def _get_pythonw_command(arg_token: str) -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}" --edit "{arg_token}"'
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    runner = str(pythonw if pythonw.exists() else exe)
    main_script = str(Path(__file__).resolve().parent.parent / "main.py")
    return f'"{runner}" "{main_script}" --edit "{arg_token}"'


def is_context_menu_registered() -> bool:
    try:
        key_path = f"{_TARGETS[1][0]}\\{MENU_KEY_NAME}\\command"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ):
            return True
    except OSError:
        return False


def register_context_menu() -> bool:
    """Register Explorer right-click menu entries under HKCU (no UAC/Admin needed)."""
    try:
        exe_icon = sys.executable
        for base_shell, token in _TARGETS:
            menu_path = f"{base_shell}\\{MENU_KEY_NAME}"
            cmd_path = f"{menu_path}\\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, menu_path) as k_menu:
                winreg.SetValueEx(k_menu, "", 0, winreg.REG_SZ, MENU_LABEL)
                winreg.SetValueEx(k_menu, "Icon", 0, winreg.REG_SZ, exe_icon)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_path) as k_cmd:
                winreg.SetValueEx(k_cmd, "", 0, winreg.REG_SZ, _get_pythonw_command(token))
        return True
    except OSError:
        return False


def unregister_context_menu() -> bool:
    """Cleanly remove Explorer right-click menu entries from HKCU."""
    ok = True
    for base_shell, _ in _TARGETS:
        for kname in (MENU_KEY_NAME, LEGACY_MENU_KEY):
            cmd_path = f"{base_shell}\\{kname}\\command"
            menu_path = f"{base_shell}\\{kname}"
            for sub in (cmd_path, menu_path):
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
                except FileNotFoundError:
                    pass
                except OSError:
                    ok = False
    return ok
