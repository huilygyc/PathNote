"""Clean, minimalist modal dialog to add or edit a file/folder alias with category selection and live preview."""

from __future__ import annotations

import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..models import DEFAULT_CATEGORY, AliasEntry, is_ascii_safe_path, normalize_category, normalize_path
from ..storage import AliasStore
from .inline_overlay import format_inline_parenthetical
from .widgets import FileTypeIcon


class EditAliasDialog(QDialog):
    """Refined Light modal for creating or editing an inline '(别名或用途)' record with category selection."""

    def __init__(
        self,
        store: AliasStore,
        initial_path: str = "",
        default_category: str = DEFAULT_CATEGORY,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store = store
        self.saved_entry: AliasEntry | None = None
        self.deleted_path: str = ""

        self.setWindowTitle("设置别名与用途")
        self.setWindowFlags(
            (self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
            & ~Qt.WindowType.WindowContextHelpButtonHint
        )
        self.setFixedWidth(490)

        norm_initial = normalize_path(initial_path) if initial_path else ""
        existing = self.store.get(norm_initial) if norm_initial else None
        target_cat = existing.category if existing else normalize_category(default_category)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(13)

        # 1. Target Path Section
        path_hdr = QHBoxLayout()
        lbl_target = QLabel("目标路径")
        lbl_target.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #3F3F46;")
        self._ascii_pill = QLabel("")
        path_hdr.addWidget(lbl_target)
        path_hdr.addStretch(1)
        path_hdr.addWidget(self._ascii_pill)
        root.addLayout(path_hdr)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        self._path_edit = QLineEdit(norm_initial)
        self._path_edit.setPlaceholderText("选择或输入需要加备注的英文文件 / 文件夹路径")
        self._path_edit.textChanged.connect(self._on_path_edited)

        btn_file = QPushButton("选择文件")
        btn_file.clicked.connect(self._browse_file)
        btn_dir = QPushButton("选择目录")
        btn_dir.clicked.connect(self._browse_dir)

        path_row.addWidget(self._path_edit, 1)
        path_row.addWidget(btn_file)
        path_row.addWidget(btn_dir)
        root.addLayout(path_row)

        # 2. Primary Alias Input
        lbl_alias = QLabel("括号内显示的别名或用途")
        lbl_alias.setStyleSheet("font-size: 12.5px; font-weight: 600; color: #3F3F46;")
        root.addWidget(lbl_alias)

        self._alias_edit = QLineEdit(existing.alias if existing else "")
        self._alias_edit.setPlaceholderText("例如：华硕应用中心 / YOLOv8 最优收敛权重")
        self._alias_edit.setStyleSheet("font-size: 14px; padding: 8px 12px;")
        self._alias_edit.textChanged.connect(self._on_inputs_changed)
        root.addWidget(self._alias_edit)

        # 3. Category Selection Row (defaults to '默认分类' when untouched)
        cat_col = QVBoxLayout()
        cat_col.setSpacing(5)
        lbl_cat = QLabel("所属分类（不选则自动归入「默认分类」）")
        lbl_cat.setStyleSheet("font-size: 12px; font-weight: 600; color: #3F3F46;")
        cat_col.addWidget(lbl_cat)

        cat_row = QHBoxLayout()
        cat_row.setSpacing(6)
        self._cat_combo = QComboBox()
        self._populate_categories(selected=target_cat)
        btn_new_cat = QPushButton("+ 新建分类")
        btn_new_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_new_cat.clicked.connect(self._prompt_new_category)
        cat_row.addWidget(self._cat_combo, 1)
        cat_row.addWidget(btn_new_cat)
        cat_col.addLayout(cat_row)
        root.addLayout(cat_col)

        # 4. Optional Extra Note & Tags
        extra_row = QHBoxLayout()
        extra_row.setSpacing(10)

        col_note = QVBoxLayout()
        col_note.setSpacing(5)
        lbl_n = QLabel("补充说明（选填）")
        lbl_n.setStyleSheet("font-size: 12px; color: #71717A;")
        self._note_edit = QLineEdit(existing.note.replace("\n", " ") if existing else "")
        self._note_edit.setPlaceholderText("附加说明文字")
        self._note_edit.textChanged.connect(self._on_inputs_changed)
        col_note.addWidget(lbl_n)
        col_note.addWidget(self._note_edit)

        col_tags = QVBoxLayout()
        col_tags.setSpacing(5)
        lbl_t = QLabel("标签（选填）")
        lbl_t.setStyleSheet("font-size: 12px; color: #71717A;")
        init_tags = ", ".join(existing.tags) if existing and existing.tags else ""
        self._tags_edit = QLineEdit(init_tags)
        self._tags_edit.setPlaceholderText("如：模型, 备份")
        col_tags.addWidget(lbl_t)
        col_tags.addWidget(self._tags_edit)

        extra_row.addLayout(col_note, 3)
        extra_row.addLayout(col_tags, 2)
        root.addLayout(extra_row)

        # 5. Live Explorer Inline Preview Card
        preview_card = QFrame()
        preview_card.setStyleSheet(
            "QFrame { background-color: #F8FAFC; border: 1px solid #E4E4E7; border-radius: 8px; }"
        )
        pv_layout = QHBoxLayout(preview_card)
        pv_layout.setContentsMargins(12, 10, 12, 10)
        pv_layout.setSpacing(8)

        pv_tag = QLabel("资源管理器预览")
        pv_tag.setStyleSheet("font-size: 11.5px; color: #71717A; border: none;")
        pv_layout.addWidget(pv_tag)
        pv_layout.addSpacing(4)

        is_d = os.path.isdir(norm_initial) if norm_initial and os.path.exists(norm_initial) else (existing.is_dir if existing else True)
        self._pv_icon = FileTypeIcon(is_dir=is_d, size=20)
        pv_layout.addWidget(self._pv_icon)

        self._pv_name = QLabel("")
        self._pv_name.setStyleSheet("font-size: 13px; color: #18181B; border: none;")
        pv_layout.addWidget(self._pv_name)

        self._pv_suffix = QLabel("")
        self._pv_suffix.setStyleSheet("font-size: 13px; color: #0F6CBD; border: none;")
        pv_layout.addWidget(self._pv_suffix, 1)

        root.addWidget(preview_card)

        self._err_lbl = QLabel("")
        self._err_lbl.setStyleSheet("color: #DC2626; font-size: 12px;")
        self._err_lbl.hide()
        root.addWidget(self._err_lbl)

        # 6. Footer Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._del_btn = QPushButton("删除别名")
        self._del_btn.setObjectName("DangerGhostBtn")
        self._del_btn.clicked.connect(self._on_delete)
        self._del_btn.setVisible(existing is not None)

        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("保存")
        btn_save.setObjectName("PrimaryBtn")
        btn_save.setDefault(True)
        btn_save.setMinimumWidth(84)
        btn_save.clicked.connect(self._on_save)

        btn_row.addWidget(self._del_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        root.addLayout(btn_row)

        self._on_inputs_changed()
        if norm_initial:
            self._alias_edit.setFocus()
            self._alias_edit.selectAll()
        else:
            self._path_edit.setFocus()

    def _populate_categories(self, selected: str = DEFAULT_CATEGORY) -> None:
        self._cat_combo.clear()
        cats = self.store.list_categories()
        if DEFAULT_CATEGORY not in cats:
            cats.insert(0, DEFAULT_CATEGORY)
        for c in cats:
            self._cat_combo.addItem(c, c)
        target = normalize_category(selected)
        idx = self._cat_combo.findData(target)
        if idx < 0:
            self._cat_combo.addItem(target, target)
            idx = self._cat_combo.count() - 1
        self._cat_combo.setCurrentIndex(max(0, idx))

    def _prompt_new_category(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分类", "请输入分类名称：")
        if ok and name.strip():
            clean = self.store.add_category(name.strip())
            self._populate_categories(selected=clean)

    def _on_path_edited(self, text: str) -> None:
        norm = normalize_path(text)
        if norm:
            existing = self.store.get(norm)
            if existing and not self._alias_edit.text().strip():
                self._alias_edit.setText(existing.alias)
                self._note_edit.setText(existing.note.replace("\n", " "))
                self._tags_edit.setText(", ".join(existing.tags))
                self._populate_categories(selected=existing.category)
                self._del_btn.setVisible(True)
        self._on_inputs_changed()

    def _on_inputs_changed(self) -> None:
        raw_p = self._path_edit.text().strip()
        norm = normalize_path(raw_p)

        if not norm:
            self._ascii_pill.setText("")
        elif is_ascii_safe_path(norm):
            self._ascii_pill.setText("纯英文路径")
            self._ascii_pill.setStyleSheet(
                "font-size: 11px; font-weight: 600; color: #059669; "
                "background-color: #ECFDF5; border-radius: 4px; padding: 2px 7px;"
            )
        else:
            self._ascii_pill.setText("路径含非英文字符")
            self._ascii_pill.setStyleSheet(
                "font-size: 11px; font-weight: 600; color: #D97706; "
                "background-color: #FFFBEB; border-radius: 4px; padding: 2px 7px;"
            )

        base = os.path.basename(norm) if norm else "example_folder"
        if not base:
            base = norm or "example_folder"
        is_d = os.path.isdir(norm) if (norm and os.path.exists(norm)) else ("." not in base)
        self._pv_icon.is_dir = is_d
        self._pv_icon.update()
        self._pv_name.setText(base)

        alias_txt = self._alias_edit.text().strip()
        note_txt = self._note_edit.text().strip()
        suffix = format_inline_parenthetical(alias_txt or "在此显示别名", note_txt, include_note=True)
        if len(suffix) > 18:
            suffix = suffix[:17] + "…)"
        self._pv_suffix.setText(suffix)

    def _browse_file(self) -> None:
        start = self._path_edit.text().strip() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "选择需要设置别名的文件", start)
        if path:
            self._path_edit.setText(normalize_path(path))
            self._alias_edit.setFocus()

    def _browse_dir(self) -> None:
        start = self._path_edit.text().strip() or os.path.expanduser("~")
        path = QFileDialog.getExistingDirectory(self, "选择需要设置别名的文件夹", start)
        if path:
            self._path_edit.setText(normalize_path(path))
            self._alias_edit.setFocus()

    def _on_save(self) -> None:
        raw_path = self._path_edit.text().strip()
        alias = self._alias_edit.text().strip()
        if not raw_path:
            self._err_lbl.setText("请选择或输入目标文件/文件夹路径")
            self._err_lbl.show()
            return
        if not alias:
            self._err_lbl.setText("请填写括号内需要显示的别名或用途")
            self._err_lbl.show()
            self._alias_edit.setFocus()
            return

        chosen_cat = normalize_category(self._cat_combo.currentData() or self._cat_combo.currentText())
        raw_tags = self._tags_edit.text().replace("，", ",").replace(";", ",")
        tags = [p.strip() for chunk in raw_tags.split(",") for p in chunk.strip().split() if p.strip()]

        existing = self.store.get(raw_path)
        self.saved_entry = self.store.upsert(
            raw_path=raw_path,
            alias=alias,
            note=self._note_edit.text().strip(),
            category=chosen_cat,
            tags=tags,
            color=existing.color if existing else "#0F6CBD",
            pinned=existing.pinned if existing else False,
        )
        self.accept()

    def _on_delete(self) -> None:
        raw_path = self._path_edit.text().strip()
        if raw_path:
            self.store.delete(raw_path)
            self.deleted_path = normalize_path(raw_path)
        self.accept()
