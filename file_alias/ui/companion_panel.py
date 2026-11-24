"""Clean Light optional docked Companion Panel beside Explorer and Open/Save File Dialogs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os

from PySide6.QtCore import QFileSystemWatcher, QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QClipboard, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigManager
from ..models import AliasEntry, WindowContext, is_ascii_safe_path, normalize_key, normalize_path
from ..storage import AliasStore
from .dpi import phys_rect_to_qt
from .toast import GWL_EXSTYLE, WS_EX_TOOLWINDOW, _GetWindowLongW, _SetWindowLongW
from .widgets import FileTypeIcon


class _DirEntryRow(QWidget):
    """Minimal clean row inside the optional Companion Panel."""

    editRequested = Signal(str)

    def __init__(self, full_path: str, name: str, is_dir: bool, entry: AliasEntry | None) -> None:
        super().__init__()
        self.full_path = full_path

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(8)

        outer.addWidget(FileTypeIcon(is_dir=is_dir, size=22), 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(1)

        if entry is not None:
            alias_lbl = QLabel(entry.alias)
            alias_lbl.setStyleSheet("font-size: 13px; font-weight: 600; color: #18181B; background: transparent;")
            sub_lbl = QLabel(name)
            sub_lbl.setStyleSheet(
                "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; color: #71717A; background: transparent;"
            )
            mid.addWidget(alias_lbl)
            mid.addWidget(sub_lbl)
        else:
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet(
                "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 12px; color: #52525B; background: transparent;"
            )
            mid.addWidget(name_lbl)

        outer.addLayout(mid, 1)

        act_btn = QPushButton("编辑" if entry else "+ 别名")
        act_btn.setObjectName("GhostBtn")
        act_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        act_btn.setFixedHeight(24)
        act_btn.clicked.connect(lambda: self.editRequested.emit(self.full_path))
        outer.addWidget(act_btn, 0, Qt.AlignmentFlag.AlignVCenter)


class CompanionPanel(QWidget):
    """Optional Light floating sidecar beside Explorer and #32770 Open/Save File Dialogs."""

    requestEditAlias = Signal(str)
    requestNavigateDir = Signal(str)
    requestSelectOrFillFile = Signal(str)
    requestOpenSearch = Signal()
    requestOpenManager = Signal()
    requestToggleAliasMode = Signal()

    def __init__(self, store: AliasStore, config_mgr: ConfigManager) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.store = store
        self.config_mgr = config_mgr
        self._ctx: WindowContext | None = None
        self._current_dir: str = ""
        self._collapsed: bool = False
        self._manual_drag_pos: QPoint | None = None
        self._drag_offset: QPoint | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("CompanionRoot")

        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _: self.refresh_list())
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(
            """
            QWidget#CompanionRoot {
                background-color: #FFFFFF;
                border: 1px solid #E4E4E7;
                border-radius: 10px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title_bar = QHBoxLayout()
        title_bar.setSpacing(6)

        self._mode_badge = QLabel("目录联动")
        self._mode_badge.setStyleSheet("font-size: 12px; font-weight: 600; color: #18181B;")
        self._ascii_lbl = QLabel("")
        self._ascii_lbl.setStyleSheet("font-size: 11px; color: #059669;")

        self._btn_collapse = QPushButton("收起")
        self._btn_collapse.setObjectName("GhostBtn")
        self._btn_collapse.setFixedHeight(24)
        self._btn_collapse.clicked.connect(self._toggle_collapse)

        title_bar.addWidget(self._mode_badge)
        title_bar.addWidget(self._ascii_lbl)
        title_bar.addStretch(1)
        title_bar.addWidget(self._btn_collapse)
        root.addLayout(title_bar)

        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)

        dir_card = QFrame()
        dir_card.setStyleSheet("QFrame { background-color: #F8FAFC; border: 1px solid #F1F5F9; border-radius: 7px; }")
        dc_layout = QVBoxLayout(dir_card)
        dc_layout.setContentsMargins(10, 7, 10, 7)
        dc_layout.setSpacing(2)

        dc_top = QHBoxLayout()
        self._dir_alias_lbl = QLabel("")
        self._dir_alias_lbl.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #18181B; border: none;")
        self._btn_dir_alias = QPushButton("设目录别名")
        self._btn_dir_alias.setObjectName("GhostBtn")
        self._btn_dir_alias.setFixedHeight(22)
        self._btn_dir_alias.clicked.connect(lambda: self.requestEditAlias.emit(self._current_dir) if self._current_dir else None)
        dc_top.addWidget(self._dir_alias_lbl, 1)
        dc_top.addWidget(self._btn_dir_alias)
        dc_layout.addLayout(dc_top)

        self._dir_path_lbl = QLabel("")
        self._dir_path_lbl.setWordWrap(True)
        self._dir_path_lbl.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; color: #71717A; border: none;"
        )
        dc_layout.addWidget(self._dir_path_lbl)
        body_layout.addWidget(dir_card)

        self._file_guard_banner = QLabel("")
        self._file_guard_banner.setWordWrap(True)
        self._file_guard_banner.setStyleSheet(
            "background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 6px; padding: 5px 8px; font-size: 11.5px; color: #1D4ED8;"
        )
        self._file_guard_banner.hide()
        body_layout.addWidget(self._file_guard_banner)

        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("筛选当前目录...")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self.refresh_list)
        body_layout.addWidget(self._filter_edit)

        chk_row = QHBoxLayout()
        self._count_lbl = QLabel("0 项")
        self._count_lbl.setStyleSheet("font-size: 11px; color: #71717A;")
        self._chk_unaliased = QCheckBox("显示未设别名文件")
        self._chk_unaliased.setStyleSheet("font-size: 11px; color: #71717A;")
        self._chk_unaliased.setChecked(self.config_mgr.config.show_unaliased_in_panel)
        self._chk_unaliased.toggled.connect(self._on_toggle_unaliased)
        chk_row.addWidget(self._count_lbl)
        chk_row.addStretch(1)
        chk_row.addWidget(self._chk_unaliased)
        body_layout.addLayout(chk_row)

        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_item_menu)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        body_layout.addWidget(self._list, 1)

        bot_row = QHBoxLayout()
        bot_row.setSpacing(6)
        btn_search = QPushButton("全局查询")
        btn_search.clicked.connect(self.requestOpenSearch.emit)
        btn_mgr = QPushButton("管理中心")
        btn_mgr.clicked.connect(self.requestOpenManager.emit)
        bot_row.addWidget(btn_search, 1)
        bot_row.addWidget(btn_mgr, 1)
        body_layout.addLayout(bot_row)

        root.addWidget(self._body, 1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            style = _GetWindowLongW(hwnd, GWL_EXSTYLE)
            _SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 36:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self._manual_drag_pos = new_pos
            self.move(new_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def update_for_context(self, ctx: WindowContext | None) -> None:
        prev_hwnd = self._ctx.hwnd if self._ctx else 0
        self._ctx = ctx
        if ctx is None or ctx.is_minimized or not ctx.current_dir:
            self.hide()
            return
        if ctx.hwnd != prev_hwnd:
            self._manual_drag_pos = None

        self._mode_badge.setText("保存窗口" if ctx.kind == "file_dialog" else "资源管理器")
        dir_changed = normalize_key(ctx.current_dir) != normalize_key(self._current_dir)
        if dir_changed:
            old_dirs = self._watcher.directories()
            if old_dirs:
                self._watcher.removePaths(old_dirs)
            if os.path.isdir(ctx.current_dir):
                self._watcher.addPath(ctx.current_dir)
            self._current_dir = ctx.current_dir

        self._refresh_header_and_guard()
        if dir_changed:
            self.refresh_list()
        self._dock_beside_target(ctx)
        if not self.isVisible():
            self.show()

    def _refresh_header_and_guard(self) -> None:
        if not self._current_dir:
            return
        if is_ascii_safe_path(self._current_dir):
            self._ascii_lbl.setText("· 纯英文路径")
            self._ascii_lbl.setStyleSheet("font-size: 11px; color: #059669;")
        else:
            self._ascii_lbl.setText("· 含中文路径")
            self._ascii_lbl.setStyleSheet("font-size: 11px; color: #D97706;")

        self._dir_path_lbl.setText(self._current_dir)
        dir_entry = self.store.get(self._current_dir)
        if dir_entry:
            self._dir_alias_lbl.setText(dir_entry.alias)
            self._btn_dir_alias.setText("编辑")
        else:
            self._dir_alias_lbl.setText(os.path.basename(self._current_dir) or self._current_dir)
            self._btn_dir_alias.setText("设别名")

        if self._ctx and self._ctx.kind == "file_dialog" and self._ctx.filename_text:
            fn = self._ctx.filename_text.strip()
            matched = self.store.resolve_item_in_dir(self._current_dir, fn)
            if matched:
                self._file_guard_banner.setText(f"当前文件名已绑别名：{matched.alias}")
                self._file_guard_banner.show()
                return
        self._file_guard_banner.hide()

    def refresh_all(self) -> None:
        self._refresh_header_and_guard()
        self.refresh_list()

    def refresh_list(self) -> None:
        self._list.clear()
        if not self._current_dir or not os.path.isdir(self._current_dir):
            self._count_lbl.setText("0 项")
            return

        query = self._filter_edit.text().strip().lower()
        aliased_in_dir = self.store.list_in_dir(self._current_dir)
        aliased_keys = {e.path_key for e in aliased_in_dir}

        rows_data: list[tuple[str, str, bool, AliasEntry | None]] = []
        for e in aliased_in_dir:
            if query and query not in f"{e.alias} {e.name} {e.note}".lower():
                continue
            rows_data.append((e.path, e.name, e.is_dir, e))

        if self._chk_unaliased.isChecked():
            try:
                un_dirs, un_files = [], []
                with os.scandir(self._current_dir) as it:
                    for dent in it:
                        if dent.name.startswith(".") or dent.name.lower() in ("desktop.ini", "thumbs.db"):
                            continue
                        norm_p = normalize_path(dent.path)
                        if normalize_key(norm_p) in aliased_keys:
                            continue
                        if query and query not in dent.name.lower():
                            continue
                        (un_dirs if dent.is_dir() else un_files).append((norm_p, dent.name, dent.is_dir(), None))
                un_dirs.sort(key=lambda x: x[1].lower())
                un_files.sort(key=lambda x: x[1].lower())
                rows_data.extend((un_dirs + un_files)[:100])
            except Exception:
                pass

        self._count_lbl.setText(f"已设 {len(aliased_in_dir)} 项")
        for full_path, name, is_d, entry in rows_data:
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, (full_path, is_d))
            widget = _DirEntryRow(full_path=full_path, name=name, is_dir=is_d, entry=entry)
            widget.editRequested.connect(self.requestEditAlias.emit)
            item.setSizeHint(widget.sizeHint() + QSize(0, 2))
            self._list.setItemWidget(item, widget)

    def _dock_beside_target(self, ctx: WindowContext) -> None:
        panel_w = self.config_mgr.config.companion_width
        target_qt, screen = phys_rect_to_qt(ctx.rect)
        avail = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        panel_h = 44 if self._collapsed else min(max(360, target_qt.height()), avail.height() - 24)
        self.resize(panel_w, panel_h)
        if self._manual_drag_pos is not None:
            self.move(self._manual_drag_pos)
            return
        side = self.config_mgr.config.companion_dock_side
        gap = 6
        x = (target_qt.left() - panel_w - gap) if side == "left" else (target_qt.right() + gap)
        if x < avail.left() + 4 or x + panel_w > avail.right() - 4:
            x = avail.right() - panel_w - 12
        y = max(avail.top() + 8, min(target_qt.top(), avail.bottom() - panel_h - 8))
        self.move(x, y)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        self._btn_collapse.setText("展开" if self._collapsed else "收起")
        if self._ctx:
            self._dock_beside_target(self._ctx)

    def _on_toggle_unaliased(self, checked: bool) -> None:
        self.config_mgr.update(show_unaliased_in_panel=checked)
        self.refresh_list()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        full_path, is_d = data
        if is_d:
            self.requestNavigateDir.emit(full_path)
        else:
            self.requestSelectOrFillFile.emit(full_path)

    def _show_item_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        full_path, _ = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_edit = QAction("编辑别名", self)
        act_edit.triggered.connect(lambda: self.requestEditAlias.emit(full_path))
        menu.addAction(act_edit)
        act_copy = QAction("复制英文路径", self)
        act_copy.triggered.connect(lambda: QGuiApplication.clipboard().setText(full_path, QClipboard.Mode.Clipboard))
        menu.addAction(act_copy)
        menu.exec(self._list.mapToGlobal(pos))
