"""
Redesigned Main Window for FileAlias (影名) — Clean Windows 11 Fluent / Linear-Light UI.
Includes left navigation rail with dynamic Category management (默认分类 + custom categories),
custom modern list cards, animated ToggleSwitches, and grouped preference cards.
"""

from __future__ import annotations

import os
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QClipboard, QDragEnterEvent, QDropEvent, QGuiApplication
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..autostart import is_autostart_enabled, set_autostart_enabled
from ..config import ConfigManager
from ..context_menu import (
    is_context_menu_registered,
    register_context_menu,
    unregister_context_menu,
)
from ..models import DEFAULT_CATEGORY, AliasEntry, normalize_path
from ..storage import AliasStore
from .inline_overlay import format_inline_parenthetical
from .theme import INLINE_TEXT_COLOR_PRESETS, create_app_icon
from .widgets import FileTypeIcon, SettingItemRow, ToggleSwitch


_NAV_ACTIVE_CSS = (
    "QPushButton { text-align: left; padding: 0px 12px; border-radius: 8px; "
    "background-color: #FFFFFF; border: 1px solid #E4E4E7; color: #18181B; font-weight: 600; }"
)
_NAV_IDLE_CSS = (
    "QPushButton { text-align: left; padding: 0px 12px; border-radius: 8px; "
    "background-color: transparent; border: 1px solid transparent; color: #52525B; font-weight: 500; }"
    "QPushButton:hover { background-color: #ECEEF2; color: #18181B; }"
)


class _LibraryEntryCard(QWidget):
    """Clean modern list row showing file/folder name, inline '(别名)' preview, category pill, and actions."""

    editClicked = Signal(str)
    revealClicked = Signal(str)
    deleteClicked = Signal(object)

    def __init__(self, entry: AliasEntry, accent_hex: str) -> None:
        super().__init__()
        self.entry = entry

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 11, 14, 11)
        row.setSpacing(12)

        row.addWidget(FileTypeIcon(is_dir=entry.is_dir, size=28), 0, Qt.AlignmentFlag.AlignVCenter)

        info_col = QVBoxLayout()
        info_col.setContentsMargins(0, 0, 0, 0)
        info_col.setSpacing(3)

        top_line = QHBoxLayout()
        top_line.setContentsMargins(0, 0, 0, 0)
        top_line.setSpacing(7)

        name_lbl = QLabel(entry.name)
        name_lbl.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #18181B; background: transparent;")
        top_line.addWidget(name_lbl)

        suffix_txt = format_inline_parenthetical(entry.alias, entry.note, include_note=True)
        if len(suffix_txt) > 24:
            suffix_txt = suffix_txt[:23] + "…)"
        suffix_lbl = QLabel(suffix_txt)
        suffix_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: 500; color: {accent_hex}; background: transparent;"
        )
        top_line.addWidget(suffix_lbl)

        # Category badge
        cat_pill = QLabel(entry.category)
        if entry.category == DEFAULT_CATEGORY:
            cat_pill.setStyleSheet(
                "font-size: 11px; color: #64748B; background-color: #F1F5F9; "
                "border-radius: 4px; padding: 1px 6px;"
            )
        else:
            cat_pill.setStyleSheet(
                "font-size: 11px; font-weight: 600; color: #1D4ED8; background-color: #EFF6FF; "
                "border-radius: 4px; padding: 1px 6px;"
            )
        top_line.addWidget(cat_pill)

        for tag in entry.tags[:2]:
            tag_pill = QLabel(tag)
            tag_pill.setStyleSheet(
                "font-size: 11px; color: #52525B; background-color: #F4F4F5; "
                "border-radius: 4px; padding: 1px 6px;"
            )
            top_line.addWidget(tag_pill)

        if not entry.exists:
            miss_pill = QLabel("路径未找到")
            miss_pill.setStyleSheet(
                "font-size: 11px; color: #DC2626; background-color: #FEF2F2; "
                "border-radius: 4px; padding: 1px 6px;"
            )
            top_line.addWidget(miss_pill)

        top_line.addStretch(1)
        info_col.addLayout(top_line)

        path_lbl = QLabel(entry.path)
        path_lbl.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11.5px; "
            "color: #71717A; background: transparent;"
        )
        info_col.addWidget(path_lbl)
        row.addLayout(info_col, 1)

        btn_reveal = QPushButton("定位")
        btn_reveal.setObjectName("GhostBtn")
        btn_reveal.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_reveal.clicked.connect(lambda: self.revealClicked.emit(entry.path))

        btn_edit = QPushButton("编辑")
        btn_edit.setObjectName("GhostBtn")
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.clicked.connect(lambda: self.editClicked.emit(entry.path))

        btn_del = QPushButton("删除")
        btn_del.setObjectName("DangerGhostBtn")
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_del.clicked.connect(lambda: self.deleteClicked.emit(entry))

        row.addWidget(btn_reveal)
        row.addWidget(btn_edit)
        row.addWidget(btn_del)


class MainWindow(QMainWindow):
    """Minimalist modern desktop management center for FileAlias."""

    requestToggleAliasMode = Signal()
    requestEditAlias = Signal(str)
    requestNewAliasInCategory = Signal(str)  # emits preferred default_category
    requestRevealExplorer = Signal(str)
    requestOpenQuickSearch = Signal()
    configUpdated = Signal()

    def __init__(self, store: AliasStore, config_mgr: ConfigManager) -> None:
        super().__init__()
        self.store = store
        self.config_mgr = config_mgr
        self._current_nav = "all"  # "all" | "dirs" | "files" | "cat:<name>" | "settings"
        self._selected_inline_color = self.config_mgr.config.inline_text_color or "#0F6CBD"

        self.setWindowTitle("PathNote · 路径备注")
        self.resize(980, 630)
        self.setMinimumSize(800, 520)
        self.setAcceptDrops(True)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(14)

        outer.addWidget(self._build_sidebar())

        self._stack = QStackedWidget()
        self._page_library = self._build_library_page()
        self._page_settings = self._build_settings_page()
        self._stack.addWidget(self._page_library)
        self._stack.addWidget(self._page_settings)
        outer.addWidget(self._stack, 1)

        self._select_nav("all")
        self.sync_mode_button()

    @property
    def active_category_for_new(self) -> str:
        """Return currently selected category in sidebar, or '默认分类'."""
        if self._current_nav.startswith("cat:"):
            return self._current_nav[4:] or DEFAULT_CATEGORY
        return DEFAULT_CATEGORY

    # ---- Left Navigation Sidebar with Dynamic Categories ----

    def _build_sidebar(self) -> QWidget:
        rail = QWidget()
        rail.setFixedWidth(206)
        layout = QVBoxLayout(rail)
        layout.setContentsMargins(4, 6, 4, 4)
        layout.setSpacing(5)

        # App Brand Header
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 2, 8, 10)
        brand_row.setSpacing(10)

        self._brand_icon_lbl = QLabel()
        self._brand_icon_lbl.setFixedSize(32, 32)
        brand_row.addWidget(self._brand_icon_lbl)

        b_text = QVBoxLayout()
        b_text.setContentsMargins(0, 0, 0, 0)
        b_text.setSpacing(0)
        t1 = QLabel("PathNote")
        t1.setStyleSheet("font-size: 15px; font-weight: 700; color: #18181B;")
        t2 = QLabel("路径备注助手")
        t2.setStyleSheet("font-size: 11px; color: #71717A;")
        b_text.addWidget(t1)
        b_text.addWidget(t2)
        brand_row.addLayout(b_text, 1)
        layout.addLayout(brand_row)

        # Fixed Views
        self._nav_btns: dict[str, QPushButton] = {}
        for key, label in (("all", "全部别名"), ("dirs", "文件夹"), ("files", "文件")):
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.clicked.connect(lambda _=False, k=key: self._select_nav(k))
            self._nav_btns[key] = btn
            layout.addWidget(btn)

        # Categories Section Header
        layout.addSpacing(8)
        cat_hdr = QHBoxLayout()
        cat_hdr.setContentsMargins(10, 0, 4, 0)
        lbl_cat_sec = QLabel("分类")
        lbl_cat_sec.setStyleSheet("font-size: 11.5px; font-weight: 600; color: #71717A;")
        btn_add_cat = QPushButton("+ 新建")
        btn_add_cat.setObjectName("GhostBtn")
        btn_add_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add_cat.setFixedHeight(24)
        btn_add_cat.setStyleSheet(
            "QPushButton { font-size: 11.5px; color: #2563EB; background: transparent; border: none; padding: 0px 6px; border-radius: 5px; }"
            "QPushButton:hover { background-color: #EFF6FF; }"
        )
        btn_add_cat.clicked.connect(self._prompt_create_category)
        cat_hdr.addWidget(lbl_cat_sec)
        cat_hdr.addStretch(1)
        cat_hdr.addWidget(btn_add_cat)
        layout.addLayout(cat_hdr)

        # Scrollable Category Buttons Container
        self._cat_scroll = QScrollArea()
        self._cat_scroll.setWidgetResizable(True)
        self._cat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._cat_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self._cat_container = QWidget()
        self._cat_container.setObjectName("SidebarCatContainer")
        self._cat_container.setStyleSheet("QWidget#SidebarCatContainer { background: transparent; }")
        self._cat_layout = QVBoxLayout(self._cat_container)
        self._cat_layout.setContentsMargins(0, 2, 0, 2)
        self._cat_layout.setSpacing(3)
        self._cat_layout.addStretch(1)
        self._cat_scroll.setWidget(self._cat_container)
        layout.addWidget(self._cat_scroll, 1)

        self._cat_btns: dict[str, QPushButton] = {}

        # Preferences Nav Item
        btn_settings = QPushButton("偏好设置")
        btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_settings.setFixedHeight(34)
        btn_settings.clicked.connect(lambda: self._select_nav("settings"))
        self._nav_btns["settings"] = btn_settings
        layout.addWidget(btn_settings)

        layout.addSpacing(4)

        # Master Live Toggle Card
        status_card = QFrame()
        status_card.setStyleSheet(
            "QFrame { background-color: #FFFFFF; border: 1px solid #E4E4E7; border-radius: 10px; }"
        )
        sc_layout = QVBoxLayout(status_card)
        sc_layout.setContentsMargins(13, 10, 13, 10)
        sc_layout.setSpacing(4)

        sc_top = QHBoxLayout()
        lbl_sw = QLabel("显示行尾别名")
        lbl_sw.setStyleSheet("font-size: 13px; font-weight: 600; color: #18181B; border: none;")
        self._master_switch = ToggleSwitch(self.config_mgr.config.alias_enabled)
        self._master_switch.toggled.connect(lambda _: self.requestToggleAliasMode.emit())
        sc_top.addWidget(lbl_sw)
        sc_top.addStretch(1)
        sc_top.addWidget(self._master_switch)
        sc_layout.addLayout(sc_top)

        self._hk_hint_lbl = QLabel("")
        self._hk_hint_lbl.setStyleSheet("font-size: 11px; color: #71717A; border: none;")
        sc_layout.addWidget(self._hk_hint_lbl)

        layout.addWidget(status_card)
        return rail

    def _rebuild_sidebar_categories(self) -> None:
        """Refresh category buttons and item counts in the left sidebar."""
        while self._cat_layout.count() > 0:
            item = self._cat_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._cat_btns.clear()

        counts = self.store.category_counts()
        for cat_name in self.store.list_categories():
            cnt = counts.get(cat_name, 0)
            nav_key = f"cat:{cat_name}"
            btn = QPushButton(f"{cat_name}  ({cnt})")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.setStyleSheet(_NAV_ACTIVE_CSS if self._current_nav == nav_key else _NAV_IDLE_CSS)
            btn.clicked.connect(lambda _=False, k=nav_key: self._select_nav(k))

            if cat_name != DEFAULT_CATEGORY:
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, b=btn, c=cat_name: self._show_category_menu(b, c, pos)
                )
            self._cat_btns[nav_key] = btn
            self._cat_layout.addWidget(btn)

        self._cat_layout.addStretch(1)

    def _prompt_create_category(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分类", "请输入新分类名称：")
        if ok and name.strip():
            created = self.store.add_category(name.strip())
            self._select_nav(f"cat:{created}")

    def _show_category_menu(self, btn: QPushButton, cat_name: str, pos: QPoint) -> None:
        menu = QMenu(self)
        act_ren = QAction("重命名分类...", self)
        act_ren.triggered.connect(lambda: self._rename_category_ui(cat_name))
        menu.addAction(act_ren)

        act_del = QAction("删除分类（内部条目归入默认分类）", self)
        act_del.triggered.connect(lambda: self._delete_category_ui(cat_name))
        menu.addAction(act_del)

        menu.exec(btn.mapToGlobal(pos))

    def _rename_category_ui(self, old_name: str) -> None:
        new_name, ok = QInputDialog.getText(self, "重命名分类", "请输入新的分类名称：", text=old_name)
        if ok and new_name.strip() and new_name.strip() != old_name:
            self.store.rename_category(old_name, new_name.strip())
            if self._current_nav == f"cat:{old_name}":
                self._current_nav = f"cat:{new_name.strip()}"
            self._select_nav(self._current_nav)

    def _delete_category_ui(self, cat_name: str) -> None:
        ans = QMessageBox.question(
            self,
            "删除分类",
            f"确定删除分类「{cat_name}」吗？\n该分类下的别名不会丢失，将自动归入「{DEFAULT_CATEGORY}」。",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.store.delete_category(cat_name)
            if self._current_nav == f"cat:{cat_name}":
                self._current_nav = "all"
            self._select_nav(self._current_nav)

    def _select_nav(self, key: str) -> None:
        self._current_nav = key
        for k, btn in self._nav_btns.items():
            btn.setStyleSheet(_NAV_ACTIVE_CSS if k == key else _NAV_IDLE_CSS)
        for k, btn in self._cat_btns.items():
            btn.setStyleSheet(_NAV_ACTIVE_CSS if k == key else _NAV_IDLE_CSS)

        if key == "settings":
            self._stack.setCurrentWidget(self._page_settings)
        else:
            if key.startswith("cat:"):
                cat_title = key[4:]
                self._page_title_lbl.setText(f"分类 · {cat_title}")
            else:
                titles = {"all": "全部别名", "dirs": "文件夹别名", "files": "文件别名"}
                self._page_title_lbl.setText(titles.get(key, "全部别名"))
            self._stack.setCurrentWidget(self._page_library)
            self.refresh_table()

    # ---- Page 1: Modern Alias Library ----

    def _build_library_page(self) -> QWidget:
        card = QFrame()
        card.setObjectName("LibrarySurface")
        card.setStyleSheet(
            "QFrame#LibrarySurface { background-color: #FFFFFF; border: 1px solid #E4E4E7; border-radius: 12px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setStyleSheet("QFrame { border-bottom: 1px solid #F1F5F9; background: transparent; }")
        h_row = QHBoxLayout(header)
        h_row.setContentsMargins(20, 15, 18, 15)
        h_row.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._page_title_lbl = QLabel("全部别名")
        self._page_title_lbl.setStyleSheet("font-size: 16px; font-weight: 700; color: #18181B; border: none;")
        sub_hint = QLabel("指向文件按 Alt + S 快速设别名，或直接拖入窗口")
        sub_hint.setStyleSheet("font-size: 11.5px; color: #71717A; border: none;")
        title_col.addWidget(self._page_title_lbl)
        title_col.addWidget(sub_hint)
        h_row.addLayout(title_col, 1)

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("搜索别名、分类或路径...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setFixedWidth(210)
        self._search_input.setStyleSheet(
            "QLineEdit { background-color: #F8FAFC; border: 1px solid #E4E4E7; border-radius: 7px; padding: 6px 10px; }"
            "QLineEdit:focus { background-color: #FFFFFF; border: 1.5px solid #2563EB; }"
        )
        self._search_input.textChanged.connect(self.refresh_table)
        h_row.addWidget(self._search_input)

        btn_more = QPushButton("备份")
        more_menu = QMenu(btn_more)
        act_imp = QAction("导入 JSON 备份...", self)
        act_imp.triggered.connect(self._import_backup)
        act_exp = QAction("导出 JSON 备份...", self)
        act_exp.triggered.connect(self._export_backup)
        more_menu.addAction(act_imp)
        more_menu.addAction(act_exp)
        btn_more.setMenu(more_menu)
        h_row.addWidget(btn_more)

        btn_add = QPushButton("+ 新建别名")
        btn_add.setObjectName("PrimaryBtn")
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_add.clicked.connect(lambda: self.requestNewAliasInCategory.emit(self.active_category_for_new))
        h_row.addWidget(btn_add)

        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_list_menu)
        self._list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self._list, 1)

        self._empty_widget = QWidget()
        emp_layout = QVBoxLayout(self._empty_widget)
        emp_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emp_layout.setSpacing(6)
        e1 = QLabel("当前分类下暂无别名记录")
        e1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e1.setStyleSheet("font-size: 14px; font-weight: 600; color: #52525B;")
        e2 = QLabel("点击右上角「+ 新建别名」，或将英文文件/文件夹拖入此处")
        e2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        e2.setStyleSheet("font-size: 12px; color: #A1A1AA;")
        emp_layout.addWidget(e1)
        emp_layout.addWidget(e2)
        self._empty_widget.hide()
        layout.addWidget(self._empty_widget, 1)

        footer = QFrame()
        footer.setStyleSheet("QFrame { border-top: 1px solid #F4F4F5; background: #FAFAFA; border-bottom-left-radius: 12px; border-bottom-right-radius: 12px; }")
        f_row = QHBoxLayout(footer)
        f_row.setContentsMargins(20, 8, 18, 8)
        self._stats_lbl = QLabel("共 0 项")
        self._stats_lbl.setStyleSheet("font-size: 11.5px; color: #71717A; border: none;")
        btn_qs = QPushButton("快速查询面板 (Alt+Q)")
        btn_qs.setObjectName("GhostBtn")
        btn_qs.setStyleSheet("font-size: 11.5px; color: #2563EB; border: none;")
        btn_qs.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_qs.clicked.connect(self.requestOpenQuickSearch.emit)
        f_row.addWidget(self._stats_lbl)
        f_row.addStretch(1)
        f_row.addWidget(btn_qs)
        layout.addWidget(footer)

        return card

    # ---- Page 2: Clean Grouped Preferences ----

    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        container = QWidget()
        container.setObjectName("SettingsContainer")
        container.setStyleSheet("QWidget#SettingsContainer { background: transparent; }")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 8, 16)
        layout.setSpacing(14)

        cfg = self.config_mgr.config

        title = QLabel("偏好设置")
        title.setStyleSheet("font-size: 17px; font-weight: 700; color: #18181B; padding-left: 4px;")
        layout.addWidget(title)

        sec1_lbl = QLabel("原位行尾括号样式")
        sec1_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #71717A; padding-left: 4px;")
        layout.addWidget(sec1_lbl)

        card1 = QFrame()
        card1.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E4E4E7; border-radius: 10px; }")
        c1_layout = QVBoxLayout(card1)
        c1_layout.setContentsMargins(0, 0, 0, 0)
        c1_layout.setSpacing(0)

        self._sw_inline = ToggleSwitch(cfg.show_inline_suffix)
        self._sw_inline.toggled.connect(lambda _: self._auto_save_toggles())
        c1_layout.addWidget(
            SettingItemRow(
                "在文件名末尾直接显示括号别名",
                "在资源管理器和“打开/另存为”对话框的文件右侧原位显示，如：AsusMCenterAppstore (华硕中心)",
                self._sw_inline,
            )
        )

        self._sw_inline_note = ToggleSwitch(cfg.inline_include_note)
        self._sw_inline_note.toggled.connect(lambda _: self._auto_save_toggles())
        c1_layout.addWidget(
            SettingItemRow(
                "括号内同时展示补充用途",
                "有补充说明时合并展示，如：coad (代码工程 · 日常练习)",
                self._sw_inline_note,
            )
        )

        swatch_bar = QWidget()
        sb_layout = QHBoxLayout(swatch_bar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(8)
        self._color_btns: dict[str, QPushButton] = {}
        for hex_c, c_label in INLINE_TEXT_COLOR_PRESETS:
            b = QPushButton("")
            b.setToolTip(c_label)
            b.setFixedSize(22, 22)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, c=hex_c: self._pick_inline_color(c))
            self._color_btns[hex_c] = b
            sb_layout.addWidget(b)
        c1_layout.addWidget(
            SettingItemRow(
                "行尾括号文字色调",
                "选择在资源管理器中紧跟文件名后方的括号文字颜色",
                swatch_bar,
            )
        )

        self._sw_pill = ToggleSwitch(cfg.inline_pill_style)
        self._sw_pill.toggled.connect(lambda _: self._auto_save_toggles())
        c1_layout.addWidget(
            SettingItemRow(
                "浅色胶囊标签底框",
                "默认关闭以呈现纯净无底框文字（即使选中整行蓝色高亮也毫无违和感）",
                self._sw_pill,
                show_bottom_border=False,
            )
        )
        layout.addWidget(card1)

        sec2_lbl = QLabel("全局快捷键")
        sec2_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #71717A; padding-left: 4px;")
        layout.addWidget(sec2_lbl)

        card2 = QFrame()
        card2.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E4E4E7; border-radius: 10px; }")
        c2_layout = QVBoxLayout(card2)
        c2_layout.setContentsMargins(0, 0, 0, 0)
        c2_layout.setSpacing(0)

        self._hk_toggle_edit = QLineEdit(cfg.hotkey_toggle)
        self._hk_toggle_edit.setFixedWidth(136)
        self._hk_toggle_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c2_layout.addWidget(SettingItemRow("开启 / 关闭别名显示", "在任意界面一键切换行尾括号显示状态", self._hk_toggle_edit))

        self._hk_add_edit = QLineEdit(cfg.hotkey_quick_add)
        self._hk_add_edit.setFixedWidth(136)
        self._hk_add_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c2_layout.addWidget(SettingItemRow("指向文件快速设置别名", "鼠标指向或选中某个英文文件/文件夹直接弹出备注输入框", self._hk_add_edit))

        self._hk_search_edit = QLineEdit(cfg.hotkey_search)
        self._hk_search_edit.setFixedWidth(136)
        self._hk_search_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hk_save_wrap = QWidget()
        hkw_row = QHBoxLayout(hk_save_wrap)
        hkw_row.setContentsMargins(0, 0, 0, 0)
        hkw_row.setSpacing(8)
        hkw_row.addWidget(self._hk_search_edit)
        btn_apply_hk = QPushButton("应用热键")
        btn_apply_hk.setObjectName("PrimaryBtn")
        btn_apply_hk.clicked.connect(self._save_settings)
        hkw_row.addWidget(btn_apply_hk)
        c2_layout.addWidget(
            SettingItemRow("唤起全局别名搜索", "按中文别名搜索文件并支持让保存窗口直接跳转目录", hk_save_wrap, show_bottom_border=False)
        )
        layout.addWidget(card2)

        self._hk_status_lbl = QLabel("")
        self._hk_status_lbl.setStyleSheet("font-size: 12px; color: #059669; padding-left: 4px;")
        self._hk_status_lbl.hide()
        layout.addWidget(self._hk_status_lbl)

        sec3_lbl = QLabel("系统集成与扩展视图")
        sec3_lbl.setStyleSheet("font-size: 12px; font-weight: 600; color: #71717A; padding-left: 4px;")
        layout.addWidget(sec3_lbl)

        card3 = QFrame()
        card3.setStyleSheet("QFrame { background-color: #FFFFFF; border: 1px solid #E4E4E7; border-radius: 10px; }")
        c3_layout = QVBoxLayout(card3)
        c3_layout.setContentsMargins(0, 0, 0, 0)
        c3_layout.setSpacing(0)

        self._sw_autostart = ToggleSwitch(is_autostart_enabled())
        self._sw_autostart.toggled.connect(self._on_toggle_autostart)
        c3_layout.addWidget(
            SettingItemRow(
                "开机自动后台启动",
                "登录 Windows 时自动最小化驻留托盘（无需管理员权限）",
                self._sw_autostart,
            )
        )

        self._sw_ctx_menu = ToggleSwitch(is_context_menu_registered())
        self._sw_ctx_menu.toggled.connect(self._on_toggle_ctx_menu)
        c3_layout.addWidget(
            SettingItemRow(
                "资源管理器右键菜单「设置中文别名」",
                "右键任意文件或文件夹可直接设置别名（当前用户级注册，无需管理员权限）",
                self._sw_ctx_menu,
            )
        )

        self._sw_panel = ToggleSwitch(cfg.show_companion_panel)
        self._sw_panel.toggled.connect(lambda _: self._auto_save_toggles())
        c3_layout.addWidget(
            SettingItemRow(
                "侧边目录伴侣面板",
                "在文件窗口旁额外显示独立目录清单面板（默认关闭，仅用原位行尾括号更清爽）",
                self._sw_panel,
            )
        )

        self._sw_hover = ToggleSwitch(cfg.show_hover_bubble)
        self._sw_hover.toggled.connect(lambda _: self._auto_save_toggles())
        c3_layout.addWidget(
            SettingItemRow(
                "鼠标悬停浮动卡片",
                "鼠标指向文件时额外弹出详细备注卡片",
                self._sw_hover,
                show_bottom_border=False,
            )
        )
        layout.addWidget(card3)

        layout.addStretch(1)
        self._refresh_color_swatches()
        scroll.setWidget(container)
        return scroll

    # ---- State Sync & Refresh ----

    def sync_mode_button(self) -> None:
        enabled = self.config_mgr.config.alias_enabled
        hk = self.config_mgr.config.hotkey_toggle
        icon = create_app_icon(enabled, 64)
        self.setWindowIcon(icon)
        self._brand_icon_lbl.setPixmap(icon.pixmap(32, 32))

        self._master_switch.blockSignals(True)
        self._master_switch.setChecked(enabled)
        self._master_switch.blockSignals(False)
        self._hk_hint_lbl.setText(f"{'已开启' if enabled else '已关闭'} · 快捷键 {hk}")

    def sync_settings_controls(self) -> None:
        cfg = self.config_mgr.config
        for sw, val in (
            (self._sw_inline, cfg.show_inline_suffix),
            (self._sw_inline_note, cfg.inline_include_note),
            (self._sw_pill, cfg.inline_pill_style),
            (self._sw_panel, cfg.show_companion_panel),
            (self._sw_hover, cfg.show_hover_bubble),
        ):
            sw.blockSignals(True)
            sw.setChecked(val)
            sw.blockSignals(False)
        self._selected_inline_color = cfg.inline_text_color or "#0F6CBD"
        self._refresh_color_swatches()

    def _refresh_color_swatches(self) -> None:
        for hex_c, btn in self._color_btns.items():
            if hex_c.lower() == self._selected_inline_color.lower():
                btn.setStyleSheet(
                    f"background-color: {hex_c}; border: 2.5px solid #18181B; border-radius: 11px;"
                )
            else:
                btn.setStyleSheet(
                    f"background-color: {hex_c}; border: 1px solid #D4D4D8; border-radius: 11px;"
                )

    def _pick_inline_color(self, hex_c: str) -> None:
        self._selected_inline_color = hex_c
        self._refresh_color_swatches()
        self._auto_save_toggles()
        self.refresh_table()

    def refresh_table(self) -> None:
        self._rebuild_sidebar_categories()

        q = self._search_input.text().strip()
        only_dirs = self._current_nav == "dirs"
        cat_filter = self._current_nav[4:] if self._current_nav.startswith("cat:") else ""

        entries = self.store.search(
            query=q,
            category_filter=cat_filter,
            only_dirs=only_dirs,
        )
        if self._current_nav == "files":
            entries = [e for e in entries if not e.is_dir]

        self._list.clear()
        accent_hex = self.config_mgr.config.inline_text_color or "#0F6CBD"

        if not entries:
            self._list.hide()
            self._empty_widget.show()
        else:
            self._empty_widget.hide()
            self._list.show()
            for entry in entries:
                item = QListWidgetItem(self._list)
                item.setData(Qt.ItemDataRole.UserRole, entry)
                card = _LibraryEntryCard(entry, accent_hex=accent_hex)
                card.editClicked.connect(self.requestEditAlias.emit)
                card.revealClicked.connect(self.requestRevealExplorer.emit)
                card.deleteClicked.connect(self._delete_entry)
                item.setSizeHint(card.sizeHint() + QSize(0, 2))
                self._list.setItemWidget(item, card)

        total = self.store.count()
        self._nav_btns["all"].setText(f"全部别名  ({total})" if total else "全部别名")
        self._stats_lbl.setText(f"当前显示 {len(entries)} 项 · 共 {total} 项记录")

    # ---- List Context Menu & Drag-Drop ----

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        entry: AliasEntry | None = item.data(Qt.ItemDataRole.UserRole)
        if entry:
            self.requestEditAlias.emit(entry.path)

    def _show_list_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if not item:
            return
        entry: AliasEntry | None = item.data(Qt.ItemDataRole.UserRole)
        if not entry:
            return

        menu = QMenu(self)
        act_edit = QAction("编辑别名与分类", self)
        act_edit.triggered.connect(lambda: self.requestEditAlias.emit(entry.path))
        menu.addAction(act_edit)

        # Quick move-to-category submenu
        move_menu = menu.addMenu("移动到分类")
        for c in self.store.list_categories():
            act_c = QAction(c, self)
            act_c.setCheckable(True)
            act_c.setChecked(entry.category == c)
            act_c.triggered.connect(lambda _=False, target_c=c, e=entry: self._move_entry_category(e, target_c))
            move_menu.addAction(act_c)

        act_reveal = QAction("在资源管理器中定位", self)
        act_reveal.triggered.connect(lambda: self.requestRevealExplorer.emit(entry.path))
        menu.addAction(act_reveal)

        act_copy = QAction("复制纯英文路径", self)
        act_copy.triggered.connect(
            lambda: QGuiApplication.clipboard().setText(entry.path, QClipboard.Mode.Clipboard)
        )
        menu.addAction(act_copy)

        menu.addSeparator()
        act_reloc = QAction("重新绑定路径 (移动/改名后修复)...", self)
        act_reloc.triggered.connect(lambda: self._relocate_entry(entry))
        menu.addAction(act_reloc)

        act_del = QAction("删除别名", self)
        act_del.triggered.connect(lambda: self._delete_entry(entry))
        menu.addAction(act_del)

        menu.exec(self._list.mapToGlobal(pos))

    def _move_entry_category(self, entry: AliasEntry, new_cat: str) -> None:
        self.store.upsert(
            raw_path=entry.path,
            alias=entry.alias,
            note=entry.note,
            category=new_cat,
            tags=entry.tags,
            color=entry.color,
            pinned=entry.pinned,
            is_dir=entry.is_dir,
        )
        self.refresh_table()

    def _relocate_entry(self, entry: AliasEntry) -> None:
        if entry.is_dir:
            new_p = QFileDialog.getExistingDirectory(self, f"为「{entry.alias}」选择新目录", os.path.dirname(entry.path))
        else:
            new_p, _ = QFileDialog.getOpenFileName(self, f"为「{entry.alias}」选择新文件", os.path.dirname(entry.path))
        if new_p:
            cnt = self.store.relocate_path(entry.path, new_p)
            self.refresh_table()
            QMessageBox.information(self, "路径已更新", f"已更新 {cnt} 条关联记录的路径。")

    def _delete_entry(self, entry: AliasEntry) -> None:
        ans = QMessageBox.question(
            self,
            "删除别名",
            f"确定移除「{entry.name} ({entry.alias})」的别名备注吗？\n（不会影响磁盘上的真实文件）",
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.store.delete(entry.path)
            self.refresh_table()

    def _export_backup(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "导出备份", "file_aliases_backup.json", "JSON (*.json)")
        if target:
            cnt = self.store.export_json(target)
            QMessageBox.information(self, "导出完成", f"已导出 {cnt} 条记录。")

    def _import_backup(self) -> None:
        src, _ = QFileDialog.getOpenFileName(self, "导入备份", "", "JSON (*.json)")
        if src:
            cnt = self.store.import_json(src, overwrite=True)
            self.refresh_table()
            QMessageBox.information(self, "导入完成", f"已导入 {cnt} 条记录。")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile():
            self.requestEditAlias.emit(normalize_path(urls[0].toLocalFile()))

    # ---- Settings Persistence ----

    def _on_toggle_autostart(self, checked: bool) -> None:
        set_autostart_enabled(checked)
        actual = is_autostart_enabled()
        self._sw_autostart.blockSignals(True)
        self._sw_autostart.setChecked(actual)
        self._sw_autostart.blockSignals(False)

    def _on_toggle_ctx_menu(self, checked: bool) -> None:
        if checked:
            register_context_menu()
        else:
            unregister_context_menu()
        actual = is_context_menu_registered()
        self._sw_ctx_menu.blockSignals(True)
        self._sw_ctx_menu.setChecked(actual)
        self._sw_ctx_menu.blockSignals(False)

    def _auto_save_toggles(self) -> None:
        self.config_mgr.update(
            show_inline_suffix=self._sw_inline.isChecked(),
            inline_include_note=self._sw_inline_note.isChecked(),
            inline_pill_style=self._sw_pill.isChecked(),
            inline_text_color=self._selected_inline_color,
            show_companion_panel=self._sw_panel.isChecked(),
            show_hover_bubble=self._sw_hover.isChecked(),
        )
        self.configUpdated.emit()

    def _save_settings(self) -> None:
        self.config_mgr.update(
            hotkey_toggle=self._hk_toggle_edit.text().strip() or "Alt+A",
            hotkey_search=self._hk_search_edit.text().strip() or "Alt+Q",
            hotkey_quick_add=self._hk_add_edit.text().strip() or "Alt+S",
            show_inline_suffix=self._sw_inline.isChecked(),
            inline_include_note=self._sw_inline_note.isChecked(),
            inline_pill_style=self._sw_pill.isChecked(),
            inline_text_color=self._selected_inline_color,
            show_companion_panel=self._sw_panel.isChecked(),
            show_hover_bubble=self._sw_hover.isChecked(),
        )
        self.sync_mode_button()
        self._hk_status_lbl.show()
        self.configUpdated.emit()

    def set_hotkey_feedback(self, errors: dict[str, str]) -> None:
        if errors:
            self._hk_status_lbl.setText("；".join(errors.values()))
            self._hk_status_lbl.setStyleSheet("font-size: 12px; color: #D97706; padding-left: 4px;")
            self._hk_status_lbl.show()
        else:
            self._hk_status_lbl.setText("快捷键已应用生效")
            self._hk_status_lbl.setStyleSheet("font-size: 12px; color: #059669; padding-left: 4px;")

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
