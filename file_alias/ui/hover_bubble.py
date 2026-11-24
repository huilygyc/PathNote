"""Clean Light floating tooltip card when hover bubble option is enabled."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..models import AliasEntry, HoverTarget
from .dpi import phys_point_to_qt, phys_rect_to_qt
from .toast import make_click_through_noactivate


class HoverAliasBubble(QWidget):
    """Minimal clean white tooltip card."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMaximumWidth(340)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(3)

        self._alias_lbl = QLabel("")
        self._alias_lbl.setWordWrap(True)
        self._alias_lbl.setStyleSheet(
            "font-size: 13.5px; font-weight: 600; color: #18181B; background: transparent;"
        )
        root.addWidget(self._alias_lbl)

        self._note_lbl = QLabel("")
        self._note_lbl.setWordWrap(True)
        self._note_lbl.setStyleSheet("font-size: 12px; color: #52525B; background: transparent;")
        root.addWidget(self._note_lbl)

        self._name_lbl = QLabel("")
        self._name_lbl.setStyleSheet(
            "font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 11px; "
            "color: #71717A; background: transparent;"
        )
        root.addWidget(self._name_lbl)

    def show_for_target(self, entry: AliasEntry, target: HoverTarget) -> None:
        self._alias_lbl.setText(entry.alias)
        if entry.note:
            self._note_lbl.setText(entry.note)
            self._note_lbl.show()
        else:
            self._note_lbl.hide()
        self._name_lbl.setText(entry.name)

        self.adjustSize()
        w = min(340, max(160, self.sizeHint().width()))
        self.resize(w, self.sizeHint().height())

        if target.source == "hover":
            pt_qt, screen = phys_point_to_qt(target.cursor_pos[0], target.cursor_pos[1])
            x = pt_qt.x() + 16
            y = pt_qt.y() + 18
        else:
            win_rect_qt, screen = phys_rect_to_qt(target.item_rect)
            x = win_rect_qt.left() + 18
            y = win_rect_qt.bottom() - self.height() - 42

        if screen is not None:
            avail = screen.availableGeometry()
            if x + self.width() > avail.right() - 8:
                x = max(avail.left() + 8, x - self.width() - 28)
            if y + self.height() > avail.bottom() - 8:
                y = max(avail.top() + 8, avail.bottom() - self.height() - 10)

        self.move(x, y)
        if not self.isVisible():
            self.show()
            make_click_through_noactivate(self)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 8.0, 8.0)
        p.fillPath(path, QColor(255, 255, 255, 250))
        p.setPen(QPen(QColor("#E4E4E7"), 1.0))
        p.drawPath(path)
        p.end()
