"""
Windows Explorer (Win10/Win11 multi-tab) & Common File Dialog (#32770 Open/Save)
real-time inspection, hover/selection UIAutomation sensing, and directory navigation.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import re
import subprocess
import threading
import time

import comtypes
from comtypes import GUID, IUnknown, COMMETHOD, HRESULT
import pythoncom
import uiautomation as auto
import win32api
import win32con
import win32com.client
import win32gui
import win32process
from PySide6.QtCore import QObject, QThread, QTimer, Signal

from .models import HoverTarget, WindowContext, normalize_path


WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E
WM_SETTEXT = 0x000C
EM_SETSEL = 0x00B1
BM_CLICK = 0x00F5


class _IServiceProvider(IUnknown):
    _iid_ = GUID("{6D5140C1-7436-11CE-8034-00AA006009FA}")
    _methods_ = [
        COMMETHOD(
            [],
            HRESULT,
            "QueryService",
            (["in"], ctypes.POINTER(GUID), "guidService"),
            (["in"], ctypes.POINTER(GUID), "riid"),
            (["out"], ctypes.POINTER(ctypes.c_void_p), "ppvObject"),
        ),
    ]


class _IOleWindow(IUnknown):
    _iid_ = GUID("{00000114-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetWindow", (["out"], ctypes.POINTER(wintypes.HWND), "phwnd")),
        COMMETHOD([], HRESULT, "ContextSensitiveHelp", (["in"], wintypes.BOOL, "fEnterMode")),
    ]


SID_STopLevelBrowser = GUID("{4C96BE40-915C-11CF-99D3-00AA004AE837}")
IID_IShellBrowser = GUID("{000214E2-0000-0000-C000-000000000046}")


_user32 = ctypes.windll.user32
_SendMessageTimeoutW = _user32.SendMessageTimeoutW
_SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
_SendMessageTimeoutW.restype = wintypes.LPARAM


def get_window_text_cross_proc(hwnd: int, max_chars: int = 1024) -> str:
    """Read live text from cross-process Edit/ComboBox controls via WM_GETTEXT."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return ""
    buf = ctypes.create_unicode_buffer(max_chars)
    res = ctypes.c_size_t(0)
    ok = _SendMessageTimeoutW(
        wintypes.HWND(hwnd),
        WM_GETTEXT,
        wintypes.WPARAM(max_chars),
        wintypes.LPARAM(ctypes.addressof(buf)),
        0x0002,  # SMTO_ABORTIFHUNG
        150,
        ctypes.byref(res),
    )
    if ok:
        return buf.value
    try:
        return win32gui.GetWindowText(hwnd)
    except Exception:
        return ""


def set_window_text_cross_proc(hwnd: int, text: str) -> bool:
    """Set text of a cross-process Edit control cleanly."""
    if not hwnd or not win32gui.IsWindow(hwnd):
        return False
    buf = ctypes.create_unicode_buffer(text)
    res = ctypes.c_size_t(0)
    ok = _SendMessageTimeoutW(
        wintypes.HWND(hwnd),
        WM_SETTEXT,
        wintypes.WPARAM(0),
        wintypes.LPARAM(ctypes.addressof(buf)),
        0x0002,
        200,
        ctypes.byref(res),
    )
    return bool(ok)


def build_known_folder_map() -> dict[str, str]:
    """Map localized Windows Known Folder display names (e.g. '桌面', '下载') to real disk paths."""
    mapping: dict[str, str] = {}
    shell_tokens = [
        "shell:Desktop",
        "shell:Personal",
        "shell:Downloads",
        "shell:My Pictures",
        "shell:My Music",
        "shell:My Video",
    ]
    try:
        sh = win32com.client.Dispatch("Shell.Application")
        for token in shell_tokens:
            try:
                ns = sh.NameSpace(token)
                if ns and ns.Self and ns.Self.Path:
                    real_path = normalize_path(ns.Self.Path)
                    if ns.Title:
                        mapping[ns.Title.strip().lower()] = real_path
                    base = os.path.basename(real_path)
                    if base:
                        mapping[base.lower()] = real_path
            except Exception:
                continue
    except Exception:
        pass

    # Standard fallbacks
    home = os.path.expanduser("~")
    fallbacks = {
        "desktop": os.path.join(home, "Desktop"),
        "桌面": os.path.join(home, "Desktop"),
        "documents": os.path.join(home, "Documents"),
        "文档": os.path.join(home, "Documents"),
        "downloads": os.path.join(home, "Downloads"),
        "下载": os.path.join(home, "Downloads"),
        "pictures": os.path.join(home, "Pictures"),
        "图片": os.path.join(home, "Pictures"),
        "music": os.path.join(home, "Music"),
        "音乐": os.path.join(home, "Music"),
        "videos": os.path.join(home, "Videos"),
        "视频": os.path.join(home, "Videos"),
    }
    for k, v in fallbacks.items():
        if k not in mapping and os.path.exists(v):
            mapping[k] = normalize_path(v)
    return mapping


def _get_shell_window_tab_hwnd(sw_disp) -> int:
    """Query exact ShellTabWindowClass HWND from an IWebBrowser2 dispatch for Win11 multi-tab accuracy."""
    try:
        iunk_ptr = int(sw_disp._oleobj_.GetInterface(pythoncom.IID_IUnknown))
        unk = ctypes.cast(iunk_ptr, ctypes.POINTER(IUnknown))
        sp = unk.QueryInterface(_IServiceProvider)
        raw_ptr = sp.QueryService(ctypes.byref(SID_STopLevelBrowser), ctypes.byref(_IOleWindow._iid_))
        if raw_ptr:
            ole_win = ctypes.cast(raw_ptr, ctypes.POINTER(_IOleWindow))
            tab_hwnd = ole_win.GetWindow()
            return int(tab_hwnd) if tab_hwnd else 0
    except Exception:
        pass
    return 0


_WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_EnumChildWindows = _user32.EnumChildWindows
_EnumChildWindows.argtypes = [wintypes.HWND, _WNDENUMPROC, wintypes.LPARAM]
_EnumChildWindows.restype = wintypes.BOOL


def _enum_children(hwnd: int) -> list[tuple[int, str, str, bool]]:
    """Return [(child_hwnd, class_name, window_text, is_visible), ...] using pure ctypes (immune to stale LastError)."""
    results: list[tuple[int, str, str, bool]] = []
    if not hwnd or not win32gui.IsWindow(hwnd):
        return results

    def _cb(ch: int, _lparam: int) -> bool:
        try:
            ih = int(ch)
            cls = win32gui.GetClassName(ih)
            txt = win32gui.GetWindowText(ih)
            vis = bool(win32gui.IsWindowVisible(ih))
            results.append((ih, cls, txt, vis))
        except Exception:
            pass
        return True

    try:
        ctypes.windll.kernel32.SetLastError(0)
        _EnumChildWindows(wintypes.HWND(hwnd), _WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return results


def _get_visible_frame_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Use DWMWA_EXTENDED_FRAME_BOUNDS for crisp shadow-free docking on Win10/11."""
    rect = wintypes.RECT()
    DWMWA_EXTENDED_FRAME_BOUNDS = 9
    try:
        hr = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd),
            wintypes.DWORD(DWMWA_EXTENDED_FRAME_BOUNDS),
            ctypes.byref(rect),
            ctypes.sizeof(rect),
        )
        if hr == 0:
            return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        pass
    try:
        return win32gui.GetWindowRect(hwnd)
    except Exception:
        return (0, 0, 0, 0)


class WindowInspector(QObject):
    """
    Polls foreground Explorer and #32770 Open/Save File Dialog windows lightly,
    maintaining seamless pairing when the user interacts with FileAlias's own UI.
    """

    contextChanged = Signal(object)  # WindowContext | None

    def __init__(self, own_pid: int | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._own_pid = own_pid or os.getpid()
        self._known_folders = build_known_folder_map()
        self._last_ctx: WindowContext | None = None
        self._paired_hwnd: int = 0
        self._iuia = None
        self._crumb_cache_req = None
        self._crumb_cond = None
        self._timer = QTimer(self)
        # Safety fallback heartbeat only; primary updates are 0ms event-driven via WinEventMonitor!
        self._timer.setInterval(1200)
        self._timer.timeout.connect(self._poll)

    def _ensure_uia(self) -> bool:
        if self._iuia is not None:
            return True
        try:
            uia_mod = comtypes.client.GetModule("UIAutomationCore.dll")
            self._iuia = comtypes.CoCreateInstance(
                uia_mod.CUIAutomation._reg_clsid_,
                interface=uia_mod.IUIAutomation,
            )
            self._crumb_cache_req = self._iuia.CreateCacheRequest()
            self._crumb_cache_req.AddProperty(30005)  # Name
            self._crumb_cache_req.AddProperty(30012)  # ClassName
            self._crumb_cond = self._iuia.CreatePropertyCondition(
                30012, "FileExplorerExtensions.BreadcrumbBarItemControl"
            )
            return True
        except Exception:
            self._iuia = None
            return False

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
            self._poll()

    def stop(self) -> None:
        self._timer.stop()

    @property
    def current_context(self) -> WindowContext | None:
        return self._last_ctx

    def force_refresh(self) -> WindowContext | None:
        self._poll()
        return self._last_ctx

    def resolve_breadcrumb_text(self, raw_text: str) -> str:
        """Convert ToolbarWindow32 address text (e.g. '地址: D:\\AI' or '地址: 桌面\\sub') into a real disk path."""
        txt = raw_text.strip()
        for prefix in ("地址:", "Address:", "Адрес:", "Adresse:"):
            if txt.lower().startswith(prefix.lower()):
                txt = txt[len(prefix):].strip()
                break
        if not txt:
            return ""
        if len(txt) >= 2 and txt[1] == ":":
            norm = normalize_path(txt)
            return norm if os.path.isdir(norm) else ""
        if txt.startswith("\\\\"):
            norm = normalize_path(txt)
            return norm if os.path.isdir(norm) else ""

        # Known Folder prefix resolution (e.g. '桌面' or '桌面\test')
        parts = txt.replace("/", "\\").split("\\", 1)
        head = parts[0].strip().lower()
        if head in self._known_folders:
            base = self._known_folders[head]
            full = os.path.join(base, parts[1]) if len(parts) > 1 else base
            norm = normalize_path(full)
            return norm if os.path.isdir(norm) else ""
        return ""

    def inspect_hwnd(self, hwnd: int) -> WindowContext | None:
        """Inspect a specific top-level HWND if it is an Explorer window or #32770 File Dialog."""
        if not hwnd or not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return None
        try:
            cls = win32gui.GetClassName(hwnd)
        except Exception:
            return None

        is_min = bool(win32gui.IsIconic(hwnd))
        placement = win32gui.GetWindowPlacement(hwnd)
        is_max = placement[1] == win32con.SW_SHOWMAXIMIZED
        rect = _get_visible_frame_rect(hwnd)
        title = win32gui.GetWindowText(hwnd)

        if cls in ("CabinetWClass", "ExploreWClass"):
            return self._inspect_explorer(hwnd, title, rect, is_min, is_max)
        if cls == "#32770":
            return self._inspect_file_dialog(hwnd, title, rect, is_min, is_max)
        return None

    @staticmethod
    def _walk_crumb_segments(base_dir: str, segments: list[str]) -> str:
        """Resolve breadcrumb segments from `base_dir`, translating localized system folder names like '用户' -> 'Users'."""
        cur = normalize_path(base_dir)
        localized_sys_dirs = {
            "用户": "Users",
            "公用": "Public",
            "程序文件": "Program Files",
        }
        for seg in segments:
            cand = os.path.join(cur, seg)
            if os.path.isdir(cand):
                cur = cand
                continue
            mapped = localized_sys_dirs.get(seg)
            if mapped:
                cand2 = os.path.join(cur, mapped)
                if os.path.isdir(cand2):
                    cur = cand2
                    continue
            return ""
        return normalize_path(cur) if os.path.isdir(cur) else ""

    def _read_win11_xaml_breadcrumb(self, children: list[tuple[int, str, str, bool]]) -> str:
        """
        Read current folder path directly from Windows 11 24H2/25H2 XAML DesktopChildSiteBridge
        BreadcrumbBarItemControl elements in ~1.5ms (100% accurate even when ShellWindows omits tabs).
        """
        bridges = [ch for ch, cls, _, vis in children if "DesktopChildSiteBridge" in cls and vis]
        if not bridges or not self._ensure_uia():
            return ""
        try:
            for bridge_hwnd in bridges:
                el_bridge = self._iuia.ElementFromHandle(bridge_hwnd)
                arr = el_bridge.FindAllBuildCache(4, self._crumb_cond, self._crumb_cache_req)
                if not arr or arr.Length == 0:
                    continue
                crumbs = []
                for i in range(arr.Length):
                    nm = str(arr.GetElement(i).CachedName or "").strip()
                    if nm and nm not in ("更多", "More"):
                        crumbs.append(nm)
                if not crumbs:
                    continue
                # 1. Drive letter root (e.g. 'OS (C:)', '新加卷 (D:)', 'D:')
                drive_idx = -1
                base_path = ""
                for idx, c in enumerate(crumbs):
                    m = re.search(r"\(([A-Za-z]:)\)", c)
                    if m:
                        base_path = m.group(1) + "\\"
                        drive_idx = idx
                        break
                    if len(c) == 2 and c[1] == ":":
                        base_path = c + "\\"
                        drive_idx = idx
                        break
                if drive_idx >= 0:
                    resolved = self._walk_crumb_segments(base_path, crumbs[drive_idx + 1:])
                    if resolved:
                        return resolved
                # 2. Known Folders (e.g. ['桌面', 'subfolder'])
                for idx, c in enumerate(crumbs):
                    cl = c.lower()
                    if cl in self._known_folders:
                        resolved = self._walk_crumb_segments(self._known_folders[cl], crumbs[idx + 1:])
                        if resolved:
                            return resolved
        except Exception:
            pass
        return ""

    def _find_matching_shell_window(self, hwnd: int, xaml_hint_dir: str = ""):
        """
        Find the exact active-tab COM ShellWindow for `hwnd`.
        Handles Win10 (sw.HWND == top-level), Win11 tabbed Explorer, and Win11 26200
        where IWebBrowser2::get_HWND may return a non-matching internal handle.
        """
        target_top = int(hwnd)
        children = _enum_children(target_top)
        all_tab_hwnds = {ch for ch, cls, _, _ in children if cls == "ShellTabWindowClass"}
        visible_tabs = [ch for ch, cls, _, vis in children if cls == "ShellTabWindowClass" and vis]
        active_tab_hwnd = visible_tabs[0] if visible_tabs else 0
        active_tab_title = win32gui.GetWindowText(active_tab_hwnd).strip() if active_tab_hwnd else ""
        if not active_tab_title:
            win_title = win32gui.GetWindowText(target_top).strip()
            for suffix in (" - 文件资源管理器", " - File Explorer"):
                if win_title.endswith(suffix):
                    active_tab_title = win_title[:-len(suffix)].strip()
                    break

        sh = win32com.client.Dispatch("Shell.Application")
        wins = sh.Windows()
        exact_hwnd_matches = []
        title_matches = []
        all_valid = []

        for i in range(wins.Count):
            try:
                sw = wins.Item(i)
                if sw is None:
                    continue
                all_valid.append(sw)
                sw_h = int(sw.HWND)
                if active_tab_hwnd and sw_h == active_tab_hwnd:
                    return sw
                if sw_h == target_top or sw_h in all_tab_hwnds:
                    exact_hwnd_matches.append(sw)
                    continue
                if win32gui.IsWindow(sw_h):
                    root_h = int(ctypes.windll.user32.GetAncestor(wintypes.HWND(sw_h), win32con.GA_ROOT))
                    if root_h == target_top:
                        exact_hwnd_matches.append(sw)
                        continue
                # Win11 26200 fallback: match by XAML path hint or active tab title
                if xaml_hint_dir:
                    try:
                        sw_path = normalize_path(str(sw.Document.Folder.Self.Path))
                        if sw_path.lower() == xaml_hint_dir.lower():
                            return sw
                    except Exception:
                        pass
                if active_tab_title:
                    loc_name = str(sw.LocationName or "").strip()
                    if loc_name and loc_name.lower() == active_tab_title.lower():
                        title_matches.append(sw)
            except Exception:
                continue

        candidates = exact_hwnd_matches or title_matches
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            if xaml_hint_dir:
                for sw in candidates:
                    try:
                        sw_path = normalize_path(str(sw.Document.Folder.Self.Path))
                        if sw_path.lower() == xaml_hint_dir.lower():
                            return sw
                    except Exception:
                        continue
            return candidates[-1]
        if len(all_valid) == 1 and not active_tab_title:
            return all_valid[0]
        return None

    def _inspect_explorer(
        self,
        hwnd: int,
        title: str,
        rect: tuple[int, int, int, int],
        is_min: bool,
        is_max: bool,
    ) -> WindowContext:
        current_dir = ""
        selected_paths: list[str] = []

        # Primary fast & reliable path on Win11: read live XAML BreadcrumbBarItemControl directly from `hwnd`
        children = _enum_children(hwnd)
        xaml_dir = self._read_win11_xaml_breadcrumb(children)
        if xaml_dir:
            current_dir = xaml_dir

        try:
            sw = self._find_matching_shell_window(hwnd, xaml_hint_dir=xaml_dir)
            if sw is not None:
                try:
                    doc = sw.Document
                    if not current_dir and doc and doc.Folder and doc.Folder.Self:
                        raw_p = str(doc.Folder.Self.Path)
                        if raw_p and not raw_p.startswith("::"):
                            norm = normalize_path(raw_p)
                            if os.path.isdir(norm):
                                current_dir = norm
                    if doc:
                        # Only trust sw.Document.SelectedItems() if sw's path matches current_dir!
                        sw_path = normalize_path(str(doc.Folder.Self.Path)) if (doc.Folder and doc.Folder.Self) else ""
                        if not current_dir or sw_path.lower() == current_dir.lower():
                            sel = doc.SelectedItems()
                            if sel is not None:
                                for i in range(sel.Count):
                                    sp = str(sel.Item(i).Path)
                                    if sp and not sp.startswith("::"):
                                        selected_paths.append(normalize_path(sp))
                except Exception:
                    pass
                if not current_dir:
                    try:
                        loc_url = str(sw.LocationURL or "")
                        if loc_url.lower().startswith("file:"):
                            norm = normalize_path(loc_url)
                            if os.path.isdir(norm):
                                current_dir = norm
                    except Exception:
                        pass
        except Exception:
            pass

        # Fallback to classic ToolbarWindow32 breadcrumb (Win10 Explorer)
        if not current_dir:
            for _, c_cls, c_txt, _ in children:
                if c_cls == "ToolbarWindow32" and c_txt:
                    resolved = self.resolve_breadcrumb_text(c_txt)
                    if resolved:
                        current_dir = resolved
                        break

        return WindowContext(
            hwnd=hwnd,
            kind="explorer",
            title=title,
            current_dir=current_dir,
            rect=rect,
            selected_paths=selected_paths,
            is_minimized=is_min,
            is_maximized=is_max,
        )

    def _inspect_file_dialog(
        self,
        hwnd: int,
        title: str,
        rect: tuple[int, int, int, int],
        is_min: bool,
        is_max: bool,
    ) -> WindowContext | None:
        children = _enum_children(hwnd)
        classes = {c_cls for _, c_cls, _, _ in children}
        # Must be a genuine file browser dialog, not an ordinary #32770 MessageBox!
        is_real_file_dlg = bool(
            classes.intersection({"SHELLDLL_DefView", "DUIViewWndClassName", "ExplorerBrowser"})
            or ("SysListView32" in classes and "ComboBox" in classes and "ToolbarWindow32" in classes)
        )
        if not is_real_file_dlg:
            return None

        current_dir = ""
        filename_text = ""

        # 1. Extract current directory from Breadcrumb ToolbarWindow32 ('地址: ...' / 'Address: ...')
        for _, c_cls, c_txt, _ in children:
            if c_cls == "ToolbarWindow32" and c_txt:
                resolved = self.resolve_breadcrumb_text(c_txt)
                if resolved:
                    current_dir = resolved
                    break

        # 2. Extract live filename Edit text (visible Edit inside DUIViewWndClassName / dialog)
        edit_hwnd = self.find_dialog_filename_edit(hwnd, children)
        if edit_hwnd:
            filename_text = get_window_text_cross_proc(edit_hwnd).strip()

        return WindowContext(
            hwnd=hwnd,
            kind="file_dialog",
            title=title,
            current_dir=current_dir,
            rect=rect,
            selected_paths=[],
            filename_text=filename_text,
            is_minimized=is_min,
            is_maximized=is_max,
        )

    @staticmethod
    def find_dialog_filename_edit(
        dialog_hwnd: int,
        children: list[tuple[int, str, str, bool]] | None = None,
    ) -> int:
        """Locate the visible File Name Edit control inside a #32770 Open/Save File Dialog."""
        if children is None:
            children = _enum_children(dialog_hwnd)
        # In modern Common Item Dialog, the visible Edit whose parent is a visible ComboBox
        # (and grandparent is NOT ComboBoxEx32 address bar) is the File Name input.
        fallback_edit = 0
        for ch, c_cls, _, vis in children:
            if c_cls == "Edit" and vis:
                try:
                    parent = win32gui.GetParent(ch)
                    p_cls = win32gui.GetClassName(parent) if parent else ""
                    gparent = win32gui.GetParent(parent) if parent else 0
                    gp_cls = win32gui.GetClassName(gparent) if gparent else ""
                    if p_cls == "ComboBox" and gp_cls != "ComboBoxEx32":
                        return ch
                    if not fallback_edit:
                        fallback_edit = ch
                except Exception:
                    continue
        return fallback_edit

    def _poll(self) -> None:
        fg = win32gui.GetForegroundWindow()
        ctx: WindowContext | None = None

        if fg:
            try:
                _, fg_pid = win32process.GetWindowThreadProcessId(fg)
            except Exception:
                fg_pid = 0

            if fg_pid == self._own_pid:
                # User clicked our Companion Panel / Edit Modal / Quick Search:
                # Keep tracking the paired Explorer / File Dialog if still open!
                if self._paired_hwnd and win32gui.IsWindow(self._paired_hwnd):
                    ctx = self.inspect_hwnd(self._paired_hwnd)
            else:
                ctx = self.inspect_hwnd(fg)
                if ctx is not None:
                    self._paired_hwnd = ctx.hwnd
                else:
                    # Keep paired Explorer/Dialog active when its own context menu / XAML popup takes foreground
                    fg_cls = ""
                    try:
                        fg_cls = win32gui.GetClassName(fg)
                    except Exception:
                        pass
                    if (
                        self._paired_hwnd
                        and win32gui.IsWindow(self._paired_hwnd)
                        and fg_cls in (
                            "Microsoft.UI.Content.PopupWindowSiteBridge",
                            "#32768",
                            "Xaml_WindowedPopupClass",
                        )
                    ):
                        ctx = self.inspect_hwnd(self._paired_hwnd)
                    else:
                        self._paired_hwnd = 0

        if not self._contexts_equal(self._last_ctx, ctx):
            self._last_ctx = ctx
            self.contextChanged.emit(ctx)

    @staticmethod
    def _contexts_equal(a: WindowContext | None, b: WindowContext | None) -> bool:
        if a is None and b is None:
            return True
        if a is None or b is None:
            return False
        return (
            a.hwnd == b.hwnd
            and a.kind == b.kind
            and a.current_dir == b.current_dir
            and a.rect == b.rect
            and a.selected_paths == b.selected_paths
            and a.filename_text == b.filename_text
            and a.is_minimized == b.is_minimized
            and a.is_maximized == b.is_maximized
        )

    # ---- Interactive Navigation & Filename Filling Actions ----

    def navigate_to_directory(self, ctx: WindowContext | None, target_dir: str) -> bool:
        """Navigate the paired Explorer or #32770 Open/Save Dialog directly to `target_dir`."""
        norm_dir = normalize_path(target_dir)
        if not norm_dir or not os.path.isdir(norm_dir):
            return False

        if ctx is None or not win32gui.IsWindow(ctx.hwnd):
            self.reveal_in_explorer(norm_dir)
            return True

        if ctx.kind == "explorer":
            try:
                sw = self._find_matching_shell_window(ctx.hwnd)
                if sw is not None:
                    sw.Navigate2(norm_dir)
                    try:
                        win32gui.SetForegroundWindow(ctx.hwnd)
                    except Exception:
                        pass
                    return True
            except Exception:
                pass
            self.reveal_in_explorer(norm_dir)
            return True

        if ctx.kind == "file_dialog":
            edit_hwnd = self.find_dialog_filename_edit(ctx.hwnd)
            if not edit_hwnd:
                return False
            saved_name = get_window_text_cross_proc(edit_hwnd).strip()
            # Don't restore if saved_name was already a path
            if "\\" in saved_name or "/" in saved_name or os.path.isdir(saved_name):
                saved_name = ""

            try:
                win32gui.SetForegroundWindow(ctx.hwnd)
            except Exception:
                pass

            if not set_window_text_cross_proc(edit_hwnd, norm_dir):
                return False

            # Send VK_RETURN to the filename edit control so Common Item Dialog enters the directory
            win32api.PostMessage(edit_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            win32api.PostMessage(edit_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)

            if saved_name:
                QTimer.singleShot(180, lambda: set_window_text_cross_proc(edit_hwnd, saved_name))
            return True

        return False

    def fill_or_select_file(self, ctx: WindowContext | None, file_path: str) -> bool:
        """
        In #32770 Save/Open dialog: navigate to parent dir if needed and fill basename into Filename box.
        In Explorer: select the file in the current Explorer window (or reveal it).
        """
        norm_file = normalize_path(file_path)
        if not norm_file:
            return False
        parent_dir = os.path.dirname(norm_file)
        basename = os.path.basename(norm_file)

        if ctx is None or not win32gui.IsWindow(ctx.hwnd):
            self.reveal_in_explorer(norm_file)
            return True

        if ctx.kind == "file_dialog":
            edit_hwnd = self.find_dialog_filename_edit(ctx.hwnd)
            if not edit_hwnd:
                return False
            if parent_dir and ctx.current_dir.lower() != parent_dir.lower() and os.path.isdir(parent_dir):
                self.navigate_to_directory(ctx, parent_dir)
                QTimer.singleShot(220, lambda: self._set_and_focus_edit(ctx.hwnd, edit_hwnd, basename))
            else:
                self._set_and_focus_edit(ctx.hwnd, edit_hwnd, basename)
            return True

        if ctx.kind == "explorer":
            try:
                sw = self._find_matching_shell_window(ctx.hwnd)
                if sw is not None and sw.Document:
                    if parent_dir and ctx.current_dir.lower() != parent_dir.lower() and os.path.isdir(parent_dir):
                        sw.Navigate2(parent_dir)
                        return True
                    folder = sw.Document.Folder
                    if folder:
                        item = folder.ParseName(basename)
                        if item is not None:
                            # 1 = SVSI_SELECT, 4 = SVSI_DESELECTOTHERS, 8 = SVSI_ENSUREVISIBLE, 16 = SVSI_FOCUSED
                            sw.Document.SelectItem(item, 1 | 4 | 8 | 16)
                            return True
            except Exception:
                pass
            self.reveal_in_explorer(norm_file)
            return True

        return False

    @staticmethod
    def _set_and_focus_edit(dialog_hwnd: int, edit_hwnd: int, text: str) -> None:
        set_window_text_cross_proc(edit_hwnd, text)
        try:
            win32gui.SetForegroundWindow(dialog_hwnd)
            ctypes.windll.user32.SendMessageW(
                wintypes.HWND(edit_hwnd),
                EM_SETSEL,
                wintypes.WPARAM(0),
                wintypes.LPARAM(len(text)),
            )
        except Exception:
            pass

    @staticmethod
    def resolve_disk_item_in_dir(dir_path: str, displayed_name: str) -> str:
        """Resolve displayed item name to real disk path (handles Explorer hiding file extensions)."""
        clean = displayed_name.strip()
        if not clean or not dir_path:
            return ""
        exact = normalize_path(os.path.join(dir_path, clean))
        if os.path.exists(exact):
            return exact
        target_stem = clean.lower()
        try:
            with os.scandir(dir_path) as it:
                for dent in it:
                    if dent.is_file():
                        stem = os.path.splitext(dent.name)[0].lower()
                        if stem == target_stem:
                            return normalize_path(dent.path)
        except Exception:
            pass
        return exact

    def probe_item_under_cursor(self, ctx: WindowContext | None) -> str:
        """Return full disk path of the Explorer / File Dialog list item currently under the mouse cursor."""
        if ctx is None or not ctx.current_dir:
            return ""
        try:
            x, y = win32api.GetCursorPos()
            hwnd_at_pt = win32gui.WindowFromPoint((x, y))
            if not hwnd_at_pt:
                return ""
            root_hwnd = win32gui.GetAncestor(hwnd_at_pt, win32con.GA_ROOT)
            if root_hwnd != ctx.hwnd:
                return ""
            pt_cls = win32gui.GetClassName(hwnd_at_pt).lower()
            if pt_cls not in ("directuihwnd", "syslistview32", "shelldll_defview"):
                return ""
            with auto.UIAutomationInitializerInThread():
                ctrl = auto.ControlFromPoint(x, y)
                curr = ctrl
                for _ in range(5):
                    if curr is None:
                        break
                    ctype = curr.ControlTypeName
                    if ctype == "ListItemControl":
                        name = (curr.Name or "").strip()
                        if name:
                            return self.resolve_disk_item_in_dir(ctx.current_dir, name)
                        break
                    if ctype in ("WindowControl", "PaneControl", "ListControl"):
                        break
                    curr = curr.GetParentControl()
        except Exception:
            pass
        return ""

    @staticmethod
    def reveal_in_explorer(target_path: str) -> None:
        """Open Windows Explorer at `target_path` (selecting the file if it is a file)."""
        norm = normalize_path(target_path)
        if not norm:
            return
        if os.path.isfile(norm):
            subprocess.Popen(["explorer.exe", f"/select,{norm}"])
        elif os.path.isdir(norm):
            os.startfile(norm)
        else:
            parent = os.path.dirname(norm)
            if parent and os.path.isdir(parent):
                os.startfile(parent)


class HoverSensorWorker(QThread):
    """
    Background STA worker using Windows UIAutomation to detect hovered list items
    inside Explorer and #32770 File Dialogs with zero main-thread latency.
    """

    hoverChanged = Signal(object)  # HoverTarget | None

    def __init__(self, own_pid: int | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._own_pid = own_pid or os.getpid()
        self._lock = threading.Lock()
        self._running = True
        self._enabled = True
        self._ctx: WindowContext | None = None
        self._last_emitted_key: tuple | None = None

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._emit_if_changed(None)

    def set_context(self, ctx: WindowContext | None) -> None:
        with self._lock:
            self._ctx = ctx
            if ctx is None:
                self._emit_if_changed(None)

    def stop_worker(self) -> None:
        with self._lock:
            self._running = False
        self.wait(1000)

    def _emit_if_changed(self, target: HoverTarget | None) -> None:
        key = (target.path, target.item_name, target.item_rect, target.source) if target else None
        if key != self._last_emitted_key:
            self._last_emitted_key = key
            self.hoverChanged.emit(target)

    def run(self) -> None:
        with auto.UIAutomationInitializerInThread():
            last_pt = (-9999, -9999)
            cached_hover: HoverTarget | None = None
            cached_dir = ""

            while True:
                with self._lock:
                    if not self._running:
                        break
                    enabled = self._enabled
                    ctx = self._ctx

                if not enabled or ctx is None or ctx.is_minimized or not ctx.current_dir:
                    self._emit_if_changed(None)
                    time.sleep(0.15)
                    continue

                try:
                    pt = win32api.GetCursorPos()
                except Exception:
                    time.sleep(0.15)
                    continue

                l, t, r, b = ctx.rect
                cursor_inside_target = (l <= pt[0] <= r) and (t <= pt[1] <= b)

                if cursor_inside_target:
                    # Only invoke UIA ControlFromPoint when cursor actually moved or directory changed
                    moved = abs(pt[0] - last_pt[0]) > 3 or abs(pt[1] - last_pt[1]) > 3
                    if moved or cached_dir != ctx.current_dir:
                        last_pt = pt
                        cached_dir = ctx.current_dir
                        cached_hover = self._probe_point(pt[0], pt[1], ctx)

                    if cached_hover is not None:
                        # Refresh cursor_pos if needed
                        updated = HoverTarget(
                            path=cached_hover.path,
                            item_name=cached_hover.item_name,
                            item_rect=cached_hover.item_rect,
                            cursor_pos=pt,
                            source="hover",
                        )
                        self._emit_if_changed(updated)
                        time.sleep(0.10)
                        continue

                # Fallback: if not hovering a list item, surface single selection in Explorer
                if len(ctx.selected_paths) == 1:
                    sel_path = ctx.selected_paths[0]
                    sel_target = HoverTarget(
                        path=sel_path,
                        item_name=os.path.basename(sel_path),
                        item_rect=ctx.rect,
                        cursor_pos=pt,
                        source="selection",
                    )
                    self._emit_if_changed(sel_target)
                else:
                    self._emit_if_changed(None)

                time.sleep(0.12)

    def _probe_point(self, x: int, y: int, ctx: WindowContext) -> HoverTarget | None:
        """Query UIAutomation ControlFromPoint to find hovered Explorer/Dialog ListItemControl."""
        try:
            hwnd_at_pt = win32gui.WindowFromPoint((x, y))
            if not hwnd_at_pt:
                return None
            _, pid = win32process.GetWindowThreadProcessId(hwnd_at_pt)
            if pid == self._own_pid:
                return None
            root_hwnd = win32gui.GetAncestor(hwnd_at_pt, win32con.GA_ROOT)
            if root_hwnd != ctx.hwnd:
                return None
            pt_cls = win32gui.GetClassName(hwnd_at_pt).lower()
            # Only inspect inside Explorer/Dialog item view surfaces (case-insensitive for DirectUIHWND / DIRECTUIHWND)
            if pt_cls not in ("directuihwnd", "syslistview32", "shelldll_defview"):
                return None

            ctrl = auto.ControlFromPoint(x, y)
            if not ctrl:
                return None

            # Walk up max 5 levels to find the enclosing ListItemControl (file/folder row)
            curr = ctrl
            list_item = None
            for _ in range(5):
                if curr is None:
                    break
                ctype = curr.ControlTypeName
                if ctype == "ListItemControl":
                    list_item = curr
                    break
                if ctype in ("WindowControl", "PaneControl", "ListControl"):
                    break
                curr = curr.GetParentControl()

            if list_item is None:
                return None

            name = (list_item.Name or "").strip()
            if not name:
                return None

            br = list_item.BoundingRectangle
            item_rect = (int(br.left), int(br.top), int(br.right), int(br.bottom))
            # Verify cursor is actually inside the item's bounding rect
            if not (item_rect[0] <= x <= item_rect[2] and item_rect[1] <= y <= item_rect[3]):
                return None

            candidate_path = normalize_path(os.path.join(ctx.current_dir, name))
            return HoverTarget(
                path=candidate_path,
                item_name=name,
                item_rect=item_rect,
                cursor_pos=(x, y),
                source="hover",
            )
        except Exception:
            return None
