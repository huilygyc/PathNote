"""Clean modern Light Spotlight-style quick search launcher (default Alt+Q)."""

from __future__ import annotations

import os
from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QClipboard, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..models import AliasEntry, WindowContext
from ..storage import AliasStore
from .inline_overlay import format_inline_parenthetical
from .widgets import FileTypeIcon


class _SearchResultRow(QWidget):
    """Refined two-line search result row."""

    def __init__(self, entry: AliasEntry) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)

        layout.addWidget(FileTypeIcon(is_dir=entry.is_dir, size=26), 0, Qt.AlignmentFlag.AlignVCenter)

        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(2)

        top = QHBoxLayout()
        top.setSpacing(8)
        name_lbl = QLabel(entry.name)
        name_lbl.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #18181B; background: transparent;")
        suffix_str = format_inline_parenthetical(entry.alias, entry.note, include_note=True)
        alias_lbl = QLabel(suffix_str)
        alias_lbl.setStyleSheet("font-size: 13px; color: #0F6CBD; background: transparent;")

        top.addWidget(name_lbl)
        top.addWidget(alias_lbl)
        top.addStretch(1)
        mid.addLayout(top)

        path_lbl = QLabel(entry.path)
        path_lbl.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11.5px; "
            "color: #71717A; background: transparent;"
        )
        mid.addWidget(path_lbl)
        layout.addLayout(mid, 1)


class QuickSearchLauncher(QWidget):
    """Minimalist Light Spotlight-style launcher for searching aliases and jumping to English paths."""

    requestJumpDir = Signal(object, str)
    requestSelectOrFillFile = Signal(object, str)
    requestRevealExplorer = Signal(str)
    requestEditAlias = Signal(str)
    requestToast = Signal(str)

    def __init__(self, store: AliasStore) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.store = store
        self._paired_ctx: WindowContext | None = None

        self.setObjectName("QuickSearchRoot")
        self.resize(640, 430)
        self.setStyleSheet(
            """
            QWidget#QuickSearchRoot {
                background-color: #FFFFFF;
                border: 1px solid #D4D4D8;
                border-radius: 12px;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(8)

        self._ctx_banner = QLabel("")
        self._ctx_banner.setStyleSheet(
            "background-color: #EFF6FF; border: 1px solid #BFDBFE; "
            "border-radius: 6px; padding: 5px 10px; font-size: 12px; color: #1D4ED8;"
        )
        self._ctx_banner.hide()
        root.addWidget(self._ctx_banner)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("输入中文别名、用途或英文文件名查询...")
        self._search_edit.setStyleSheet(
            "font-size: 14.5px; padding: 9px 12px; border-radius: 8px; "
            "background-color: #F8FAFC; border: 1px solid #E4E4E7;"
        )
        self._search_edit.textChanged.connect(self._refresh_results)
        self._search_edit.installEventFilter(self)
        root.addWidget(self._search_edit)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._activate_selected())
        root.addWidget(self._list, 1)

        footer = QFrame()
        footer.setStyleSheet("border-top: 1px solid #F4F4F5;")
        f_layout = QHBoxLayout(footer)
        f_layout.setContentsMargins(4, 6, 4, 0)
        hint = QLabel("Enter 跳转目录/定位   ·   Ctrl+C 复制路径   ·   Ctrl+E 编辑   ·   Esc 关闭")
        hint.setStyleSheet("font-size: 11.5px; color: #71717A; border: none;")
        self._total_lbl = QLabel("")
        self._total_lbl.setStyleSheet("font-size: 11.5px; color: #A1A1AA; border: none;")
        f_layout.addWidget(hint)
        f_layout.addStretch(1)
        f_layout.addWidget(self._total_lbl)
        root.addWidget(footer)

    def open_with_context(self, paired_ctx: WindowContext | None) -> None:
        self._paired_ctx = paired_ctx
        if paired_ctx and paired_ctx.kind == "file_dialog":
            self._ctx_banner.setText(
                f"已关联「{paired_ctx.title or '打开/保存'}」窗口 — 按 Enter 可直接跳转到目标英文目录"
            )
            self._ctx_banner.show()
        elif paired_ctx and paired_ctx.kind == "explorer":
            self._ctx_banner.setText("已关联当前资源管理器窗口 — 按 Enter 直接跳转目录")
            self._ctx_banner.show()
        else:
            self._ctx_banner.hide()

        self._search_edit.clear()
        self._refresh_results()

        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.move(
                avail.center().x() - self.width() // 2,
                avail.top() + int(avail.height() * 0.18),
            )

        self.show()
        self.raise_()
        self.activateWindow()
        self._search_edit.setFocus()

    def _refresh_results(self) -> None:
        q = self._search_edit.text().strip()
        results = self.store.search(q)
        self._list.clear()
        self._total_lbl.setText(f"{len(results)} 项")

        for entry in results[:80]:
            item = QListWidgetItem(self._list)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            row = _SearchResultRow(entry)
            item.setSizeHint(row.sizeHint() + QSize(0, 2))
            self._list.setItemWidget(item, row)

        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _current_entry(self) -> AliasEntry | None:
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _activate_selected(self) -> None:
        entry = self._current_entry()
        if not entry:
            return
        ctx = self._paired_ctx
        self.hide()

        if ctx is not None:
            if entry.is_dir:
                self.requestJumpDir.emit(ctx, entry.path)
            elif ctx.kind == "file_dialog":
                parent_dir = os.path.dirname(entry.path)
                if parent_dir and os.path.isdir(parent_dir):
                    self.requestJumpDir.emit(ctx, parent_dir)
            else:
                self.requestSelectOrFillFile.emit(ctx, entry.path)
        else:
            self.requestRevealExplorer.emit(entry.path)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._search_edit and event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event
            key = ke.key()
            mods = ke.modifiers()

            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
            if key == Qt.Key.Key_Down:
                row = self._list.currentRow()
                if row + 1 < self._list.count():
                    self._list.setCurrentRow(row + 1)
                return True
            if key == Qt.Key.Key_Up:
                row = self._list.currentRow()
                if row > 0:
                    self._list.setCurrentRow(row - 1)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate_selected()
                return True
            if key == Qt.Key.Key_C and (mods & Qt.KeyboardModifier.ControlModifier):
                if not self._search_edit.selectedText():
                    entry = self._current_entry()
                    if entry:
                        QGuiApplication.clipboard().setText(entry.path, QClipboard.Mode.Clipboard)
                        self.hide()
                        self.requestToast.emit(f"已复制路径: {entry.path}")
                        return True
            if key == Qt.Key.Key_E and (mods & Qt.KeyboardModifier.ControlModifier):
                entry = self._current_entry()
                if entry:
                    self.hide()
                    self.requestEditAlias.emit(entry.path)
                    return True
        return super().eventFilter(obj, event)
