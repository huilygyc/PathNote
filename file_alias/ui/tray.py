"""
Master Application Controller & System Tray Integration for FileAlias (影名).
Coordinates global hotkeys, Windows Explorer / File Dialog inspection, inline '(别名或用途)'
suffix rendering, optional Companion Panel / Hover Bubble, Quick Search, and Main Window.
"""

from __future__ import annotations

import os
from PySide6.QtCore import QFileSystemWatcher, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import ConfigManager
from ..hotkeys import GlobalHotkeyManager
from ..inline_sensor import InlineSensorWorker, InlineViewSnapshot
from ..models import DEFAULT_CATEGORY, HoverTarget, WindowContext, normalize_key, normalize_path
from ..storage import AliasStore
from ..win_events import WinEventMonitor
from ..win_inspector import HoverSensorWorker, WindowInspector, _get_visible_frame_rect
from .companion_panel import CompanionPanel
from .edit_dialog import EditAliasDialog
from .hover_bubble import HoverAliasBubble
from .inline_overlay import InlineAliasOverlay
from .main_window import MainWindow
from .quick_search import QuickSearchLauncher
from .theme import create_app_icon, create_tray_icon, get_stylesheet
from .toast import StatusToast


class FileAliasController(QObject):
    """Central coordinator tying system sensors, hotkeys, and UI surfaces together."""

    def __init__(
        self,
        app: QApplication,
        store: AliasStore | None = None,
        config_mgr: ConfigManager | None = None,
    ) -> None:
        super().__init__()
        self.app = app
        self.config_mgr = config_mgr or ConfigManager()
        self.store = store or AliasStore()

        self.app.setStyleSheet(get_stylesheet(self.config_mgr.config.theme))
        self.app.setQuitOnLastWindowClosed(False)

        # Core Services & Event-Driven Sensors
        self.hotkeys = GlobalHotkeyManager(self)
        self.win_events = WinEventMonitor(self)
        self.inspector = WindowInspector(own_pid=os.getpid(), parent=self)
        self.inline_worker = InlineSensorWorker(self.store, own_pid=os.getpid(), parent=self)
        self.hover_worker = HoverSensorWorker(own_pid=os.getpid(), parent=self)
        self._dir_watcher = QFileSystemWatcher(self)
        self._watched_dir: str = ""

        # UI Surfaces
        self.toast = StatusToast()
        self.inline_overlay = InlineAliasOverlay(self.config_mgr)
        self.hover_bubble = HoverAliasBubble()
        self.companion = CompanionPanel(self.store, self.config_mgr)
        self.quick_search = QuickSearchLauncher(self.store)
        self.main_window = MainWindow(self.store, self.config_mgr)

        self._active_edit_dialog: EditAliasDialog | None = None
        self._last_valid_ctx: WindowContext | None = None

        # Tray Icon
        self.tray = QSystemTrayIcon(self)
        self._setup_tray()
        self._connect_signals()

        # Activate hotkeys & event-driven sensors
        self.apply_hotkeys()
        self._sync_sensor_state()
        self.win_events.start()
        self.inspector.start()
        self.inline_worker.start()
        self.hover_worker.start()

    def _setup_tray(self) -> None:
        self._tray_menu = QMenu()

        self._act_toggle = QAction("", self)
        self._act_toggle.triggered.connect(self.toggle_alias_mode)
        self._tray_menu.addAction(self._act_toggle)

        act_search = QAction("快速查询别名", self)
        act_search.triggered.connect(self.open_quick_search)
        self._tray_menu.addAction(act_search)

        act_quick_add = QAction("为指向/选中文件设别名", self)
        act_quick_add.triggered.connect(self.quick_add_alias_for_active)
        self._tray_menu.addAction(act_quick_add)

        self._tray_menu.addSeparator()

        self._act_companion = QAction("显示侧边伴侣面板", self)
        self._act_companion.setCheckable(True)
        self._act_companion.setChecked(self.config_mgr.config.show_companion_panel)
        self._act_companion.toggled.connect(self._on_tray_toggle_companion)
        self._tray_menu.addAction(self._act_companion)

        act_mgr = QAction("打开管理中心", self)
        act_mgr.triggered.connect(self.show_main_window)
        self._tray_menu.addAction(act_mgr)

        self._tray_menu.addSeparator()

        act_quit = QAction("退出", self)
        act_quit.triggered.connect(self.shutdown)
        self._tray_menu.addAction(act_quit)

        self.tray.setContextMenu(self._tray_menu)
        self.tray.activated.connect(self._on_tray_activated)
        self._refresh_tray_appearance()
        self.tray.show()

    def _on_tray_toggle_companion(self, checked: bool) -> None:
        self.config_mgr.update(show_companion_panel=checked)
        self.main_window.sync_settings_controls()
        self._sync_sensor_state()
        self._on_window_context_changed(self.inspector.force_refresh())

    def _refresh_tray_appearance(self) -> None:
        cfg = self.config_mgr.config
        enabled = cfg.alias_enabled
        self.app.setWindowIcon(create_app_icon())
        self.tray.setIcon(create_tray_icon(enabled))
        state_str = "已开启" if enabled else "已暂停"
        self.tray.setToolTip(
            f"PathNote · 路径备注 — {state_str}\n"
            f"开关：{cfg.hotkey_toggle}  |  设备注：{cfg.hotkey_quick_add}  |  查询：{cfg.hotkey_search}"
        )
        self._act_toggle.setText(
            f"{'关闭' if enabled else '开启'}行尾别名显示 ({cfg.hotkey_toggle})"
        )
        self._act_companion.blockSignals(True)
        self._act_companion.setChecked(cfg.show_companion_panel)
        self._act_companion.blockSignals(False)
        self.main_window.sync_mode_button()

    def _connect_signals(self) -> None:
        self.hotkeys.triggered.connect(self._on_hotkey_triggered)
        self.win_events.foregroundOrStateChanged.connect(self.inspector.force_refresh)
        self.win_events.trackedWindowMoved.connect(self._on_tracked_window_moved)
        self.win_events.viewContentChanged.connect(lambda: self.inline_worker.request_refresh(0.45))
        self._dir_watcher.directoryChanged.connect(self._on_active_dir_fs_changed)

        self.inspector.contextChanged.connect(self._on_window_context_changed)
        self.inline_worker.snapshotChanged.connect(self._on_inline_snapshot_changed)
        self.inline_worker.pathsReconciled.connect(self._on_paths_reconciled)
        self.hover_worker.hoverChanged.connect(self._on_hover_changed)

        # Companion signals
        self.companion.requestEditAlias.connect(self.open_edit_dialog)
        self.companion.requestNavigateDir.connect(
            lambda d: self.inspector.navigate_to_directory(self.inspector.current_context, d)
        )
        self.companion.requestSelectOrFillFile.connect(
            lambda f: self.inspector.fill_or_select_file(self.inspector.current_context, f)
        )
        self.companion.requestOpenSearch.connect(self.open_quick_search)
        self.companion.requestOpenManager.connect(self.show_main_window)
        self.companion.requestToggleAliasMode.connect(self.toggle_alias_mode)

        # Quick search signals
        self.quick_search.requestJumpDir.connect(self.inspector.navigate_to_directory)
        self.quick_search.requestSelectOrFillFile.connect(self.inspector.fill_or_select_file)
        self.quick_search.requestRevealExplorer.connect(self.inspector.reveal_in_explorer)
        self.quick_search.requestEditAlias.connect(self.open_edit_dialog)
        self.quick_search.requestToast.connect(lambda msg: self.toast.show_toast(msg, "#38BDF8"))

        # Main window signals
        self.main_window.requestToggleAliasMode.connect(self.toggle_alias_mode)
        self.main_window.requestEditAlias.connect(
            lambda p: self.open_edit_dialog(p, self.main_window.active_category_for_new)
        )
        self.main_window.requestNewAliasInCategory.connect(
            lambda cat: self.open_edit_dialog("", cat)
        )
        self.main_window.requestRevealExplorer.connect(self.inspector.reveal_in_explorer)
        self.main_window.requestOpenQuickSearch.connect(self.open_quick_search)
        self.main_window.configUpdated.connect(self._on_config_updated)

    def apply_hotkeys(self) -> dict[str, str]:
        cfg = self.config_mgr.config
        errors = self.hotkeys.register_bindings(
            {
                "toggle": cfg.hotkey_toggle,
                "search": cfg.hotkey_search,
                "quick_add": cfg.hotkey_quick_add,
            }
        )
        self.main_window.set_hotkey_feedback(errors)
        return errors

    def _on_config_updated(self) -> None:
        self.apply_hotkeys()
        self._refresh_tray_appearance()
        self._sync_sensor_state()
        self.inline_worker.request_refresh()
        self.inline_overlay.update()
        self._on_window_context_changed(self.inspector.force_refresh())

    def _sync_sensor_state(self) -> None:
        cfg = self.config_mgr.config
        inline_active = bool(cfg.alias_enabled and cfg.show_inline_suffix)
        self.inline_worker.set_enabled(inline_active)
        if not inline_active:
            self.inline_overlay.hide()

        hover_active = bool(cfg.alias_enabled and cfg.show_hover_bubble)
        self.hover_worker.set_enabled(hover_active)
        if not hover_active:
            self.hover_bubble.hide()

        if not (cfg.alias_enabled and cfg.show_companion_panel):
            self.companion.hide()

    # ---- Hotkey & Action Handlers ----

    def _on_hotkey_triggered(self, action: str) -> None:
        if action == "toggle":
            self.toggle_alias_mode()
        elif action == "search":
            if self.quick_search.isVisible():
                self.quick_search.hide()
            else:
                self.open_quick_search()
        elif action == "quick_add":
            self.quick_add_alias_for_active()

    def toggle_alias_mode(self) -> None:
        new_state = not self.config_mgr.config.alias_enabled
        self.config_mgr.update(alias_enabled=new_state)
        self._refresh_tray_appearance()
        self._sync_sensor_state()

        hk = self.config_mgr.config.hotkey_toggle
        if new_state:
            self.toast.show_toast(f"文件别名显示：已开启 ({hk})", "#10B981")
            ctx = self.inspector.force_refresh()
            self._on_window_context_changed(ctx)
            self.inline_worker.request_refresh()
        else:
            self.inline_overlay.hide()
            self.companion.hide()
            self.hover_bubble.hide()
            self.toast.show_toast(f"文件别名显示：已关闭 ({hk})", "#94A3B8")

    def open_quick_search(self) -> None:
        self.store.reconcile_moved_files(force=True)
        ctx = self.inspector.current_context or self._last_valid_ctx
        self.inline_overlay.hide()
        self.quick_search.open_with_context(ctx)

    def quick_add_alias_for_active(self) -> None:
        ctx = self.inspector.force_refresh()
        target_path = ""
        if ctx:
            # 1. Item under mouse cursor (super fast: point & press Alt+S!)
            hovered = self.inspector.probe_item_under_cursor(ctx)
            if hovered:
                target_path = hovered
            # 2. Selected item in Explorer
            elif ctx.selected_paths:
                target_path = ctx.selected_paths[0]
            # 3. Typed/selected filename in Save/Open Dialog
            elif ctx.kind == "file_dialog" and ctx.filename_text and ctx.current_dir:
                fn = ctx.filename_text.strip()
                if fn and "\\" not in fn and "/" not in fn:
                    target_path = normalize_path(os.path.join(ctx.current_dir, fn))
            # 4. Current directory itself
            elif ctx.current_dir:
                target_path = ctx.current_dir
        self.open_edit_dialog(target_path)

    def open_edit_dialog(self, initial_path: str = "", default_category: str = DEFAULT_CATEGORY) -> None:
        if self._active_edit_dialog is not None and self._active_edit_dialog.isVisible():
            self._active_edit_dialog.raise_()
            self._active_edit_dialog.activateWindow()
            return

        self.inline_overlay.hide()
        dlg = EditAliasDialog(self.store, initial_path=initial_path, default_category=default_category)
        self._active_edit_dialog = dlg
        if dlg.exec():
            if dlg.saved_entry:
                self.toast.show_toast(f"已保存：({dlg.saved_entry.alias})", "#10B981")
            elif dlg.deleted_path:
                self.toast.show_toast("已移除别名记录", "#F59E0B")
            self.companion.refresh_all()
            self.main_window.refresh_table()
        self._active_edit_dialog = None
        self.inline_worker.request_refresh()

    def show_main_window(self) -> None:
        self.inline_overlay.hide()
        self.store.reconcile_moved_files(force=True)
        self.main_window.refresh_table()
        self.main_window.showNormal()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.toggle_alias_mode()

    # ---- Sensor Callbacks ----

    def _on_tracked_window_moved(self, hwnd: int) -> None:
        new_rect = _get_visible_frame_rect(hwnd)
        if not self.inline_overlay.sync_host_window_move(new_rect):
            # Window resized -> wake UIA sensor for layout update
            self.inline_worker.request_refresh(0.30)
        if self.companion.isVisible() and self._last_valid_ctx and self._last_valid_ctx.hwnd == hwnd:
            self._last_valid_ctx.rect = new_rect
            self.companion._dock_beside_target(self._last_valid_ctx)

    def _on_active_dir_fs_changed(self, _path: str) -> None:
        # File/folder renamed, moved, or created inside the active directory ->
        # stay awake 1.4s so we catch Explorer's asynchronous ReadDirectoryChangesW UI redraw immediately!
        self.inline_worker.request_refresh(1.40, force_reconcile=True)

    def _on_paths_reconciled(self) -> None:
        if self.main_window.isVisible():
            self.main_window.refresh_table()
        if self.companion.isVisible():
            self.companion.refresh_all()

    def _update_watched_dir(self, dir_path: str) -> None:
        if normalize_key(dir_path) == normalize_key(self._watched_dir):
            return
        old = self._dir_watcher.directories()
        if old:
            self._dir_watcher.removePaths(old)
        self._watched_dir = dir_path
        if dir_path and os.path.isdir(dir_path):
            self._dir_watcher.addPath(dir_path)

    def _on_window_context_changed(self, ctx: WindowContext | None) -> None:
        if ctx is not None:
            self._last_valid_ctx = ctx
            self.win_events.set_tracked_hwnd(ctx.hwnd)
            self._update_watched_dir(ctx.current_dir)
        else:
            self._last_valid_ctx = None
            self.win_events.set_tracked_hwnd(0)
            self._update_watched_dir("")

        self.inline_worker.set_context(ctx)
        self.hover_worker.set_context(ctx)

        cfg = self.config_mgr.config
        if cfg.alias_enabled and cfg.show_companion_panel and ctx is not None:
            self.companion.update_for_context(ctx)
        else:
            self.companion.hide()

        if ctx is None:
            self.inline_overlay.hide()
            self.hover_bubble.hide()

    def _on_inline_snapshot_changed(self, snapshot: InlineViewSnapshot | None) -> None:
        cfg = self.config_mgr.config
        if (
            not (cfg.alias_enabled and cfg.show_inline_suffix)
            or self._active_edit_dialog is not None
            or self.quick_search.isVisible()
            or self.main_window.isActiveWindow()
        ):
            self.inline_overlay.hide()
            return
        self.inline_overlay.update_snapshot(snapshot)

    def _on_hover_changed(self, target: HoverTarget | None) -> None:
        cfg = self.config_mgr.config
        if not (cfg.alias_enabled and cfg.show_hover_bubble) or target is None:
            self.hover_bubble.hide()
            return

        ctx = self.inspector.current_context
        entry = self.store.get(target.path)
        if entry is None and ctx and ctx.current_dir and target.item_name:
            entry = self.store.resolve_item_in_dir(ctx.current_dir, target.item_name)

        if entry is not None:
            self.hover_bubble.show_for_target(entry, target)
        else:
            self.hover_bubble.hide()

    def shutdown(self) -> None:
        self.win_events.stop()
        self.inspector.stop()
        self.inline_worker.stop_worker()
        self.hover_worker.stop_worker()
        self.hotkeys.unregister_all()
        self.inline_overlay.close()
        self.companion.close()
        self.hover_bubble.close()
        self.quick_search.close()
        self.toast.close()
        self.tray.hide()
        self.store.close()
        self.app.quit()
