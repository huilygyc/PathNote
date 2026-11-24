"""
Transparent click-through In-Place Overlay that renders '(别名或用途)' directly at the end
of each file/folder name inside Windows Explorer and #32770 Open/Save File Dialogs.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

from ..config import ConfigManager
from ..inline_sensor import InlineItemAnchor, InlineViewSnapshot
from .dpi import phys_rect_to_qt
from .toast import make_click_through_noactivate


HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040


def format_inline_parenthetical(alias: str, note: str, include_note: bool = True) -> str:
    """Format the inline suffix text, e.g. '(华硕应用中心)' or '(代码工程 · 算法练习)'."""
    a = alias.strip()
    n = note.replace("\n", " ").strip()
    if include_note and a and n and n != a:
        if len(n) > 20:
            n = n[:19] + "…"
        return f"({a} · {n})"
    text = a or n
    return f"({text})" if text else ""


class InlineAliasOverlay(QWidget):
    """
    Frameless, non-activating, 100% click-through canvas aligned over the Explorer / File Dialog
    item list viewport. Draws crisp '(别名或用途)' inline right after filenames with zero box artifacts
    on white, hovered, or blue-selected Explorer rows.
    """

    def __init__(self, config_mgr: ConfigManager) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.config_mgr = config_mgr
        self._snapshot: InlineViewSnapshot | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Match Windows Explorer's native item list font (Microsoft YaHei UI 9pt)
        self._explorer_font = QFont("Microsoft YaHei UI", 9)
        self._alias_font = QFont("Microsoft YaHei UI", 9)

    def update_snapshot(self, snapshot: InlineViewSnapshot | None) -> None:
        if snapshot is None or not snapshot.items:
            self._snapshot = None
            if self.isVisible():
                self.hide()
            return

        self._snapshot = snapshot
        vp_qt, _ = phys_rect_to_qt(snapshot.viewport_rect)
        if self.geometry() != vp_qt:
            self.setGeometry(vp_qt)

        if not self.isVisible():
            self.show()
            make_click_through_noactivate(self)
            try:
                ctypes.windll.user32.SetWindowPos(
                    wintypes.HWND(int(self.winId())),
                    wintypes.HWND(HWND_TOPMOST),
                    0,
                    0,
                    0,
                    0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                )
            except Exception:
                pass
        self.update()

    def paintEvent(self, _event) -> None:
        snap = self._snapshot
        if snap is None or not snap.items:
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        vp_qt, _ = phys_rect_to_qt(snap.viewport_rect)
        clip_region = QRegion(self.rect())
        if snap.occluding_rects:
            for occ_phys in snap.occluding_rects:
                occ_qt, _ = phys_rect_to_qt(occ_phys)
                local_occ = occ_qt.translated(-vp_qt.topLeft())
                clip_region = clip_region.subtracted(QRegion(local_occ))

        if clip_region.isEmpty():
            p.end()
            return
        p.setClipRegion(clip_region)
        fm_exp = QFontMetricsF(self._explorer_font)
        fm_alias = QFontMetricsF(self._alias_font)

        cfg = self.config_mgr.config
        include_note = getattr(cfg, "inline_include_note", True)
        pill_style = getattr(cfg, "inline_pill_style", False)
        custom_hex = getattr(cfg, "inline_text_color", "#0F6CBD") or "#0F6CBD"

        for anchor in snap.items:
            self._draw_item_suffix(
                p=p,
                anchor=anchor,
                vp_left=vp_qt.left(),
                vp_top=vp_qt.top(),
                vp_width=vp_qt.width(),
                is_dark=snap.is_dark_bg,
                fm_exp=fm_exp,
                fm_alias=fm_alias,
                include_note=include_note,
                pill_style=pill_style,
                custom_hex=custom_hex,
            )

        p.end()

    def _draw_item_suffix(
        self,
        p: QPainter,
        anchor: InlineItemAnchor,
        vp_left: int,
        vp_top: int,
        vp_width: int,
        is_dark: bool,
        fm_exp: QFontMetricsF,
        fm_alias: QFontMetricsF,
        include_note: bool,
        pill_style: bool,
        custom_hex: str,
    ) -> None:
        suffix = format_inline_parenthetical(anchor.alias, anchor.note, include_note=include_note)
        if not suffix:
            return

        item_qt, _ = phys_rect_to_qt(anchor.name_rect)
        rel_x = float(item_qt.left() - vp_left)
        rel_y = float(item_qt.top() - vp_top)
        col_right = float(item_qt.right() - vp_left)
        row_cy = rel_y + item_qt.height() / 2.0

        # Measure where Explorer's filename text ends inside System.ItemNameDisplay
        name_advance = fm_exp.horizontalAdvance(anchor.display_name)
        ideal_x = rel_x + name_advance + 8.0
        start_x = min(ideal_x, max(rel_x + 24.0, col_right - 4.0))

        max_avail_w = float(vp_width) - start_x - 6.0
        if max_avail_w < 36.0:
            return

        col_avail = col_right - start_x - 6.0
        needs_overflow_backing = False
        if col_avail >= 48.0:
            draw_str = fm_alias.elidedText(suffix, Qt.TextElideMode.ElideRight, col_avail)
        else:
            # Name column is too narrow; allow subtle pill overflow so user still sees the alias
            draw_str = fm_alias.elidedText(suffix, Qt.TextElideMode.ElideRight, min(max_avail_w, 200.0))
            needs_overflow_backing = True

        text_w = fm_alias.horizontalAdvance(draw_str)

        if pill_style or needs_overflow_backing:
            pill_h = 18.0
            pad_x = 5.0
            bg_rect = QRectF(start_x - pad_x, row_cy - pill_h / 2.0, text_w + pad_x * 2, pill_h)
            path = QPainterPath()
            path.addRoundedRect(bg_rect, 4.0, 4.0)
            if is_dark:
                p.fillPath(path, QColor(30, 41, 59, 230))
                p.setPen(QPen(QColor(100, 116, 139, 90), 0.8))
                p.drawPath(path)
            else:
                p.fillPath(path, QColor(243, 246, 251, 236))
                p.setPen(QPen(QColor(203, 213, 225, 160), 0.8))
                p.drawPath(path)

        # Pure transparent background in normal mode -> blends seamlessly over white, hover, and blue-selected rows!
        if is_dark:
            text_color = QColor("#60A5FA") if custom_hex == "#0F6CBD" else QColor(custom_hex).lighter(135)
        else:
            text_color = QColor(custom_hex)

        p.setFont(self._alias_font)
        p.setPen(text_color)
        text_rect = QRectF(start_x, row_cy - 11.0, text_w + 4.0, 22.0)
        p.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine),
            draw_str,
        )
