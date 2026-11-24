"""Custom crisp vector widgets: animated ToggleSwitch, vector File/Folder icons, and SettingCard."""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class ToggleSwitch(QWidget):
    """Smooth animated Windows 11 / iOS style pill toggle switch."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = bool(checked)
        self._pos = 1.0 if self._checked else 0.0
        self.setFixedSize(40, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"thumbPos", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        checked = bool(checked)
        if self._checked == checked:
            return
        self._checked = checked
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()
        self.update()

    def get_thumb_pos(self) -> float:
        return self._pos

    def set_thumb_pos(self, val: float) -> None:
        self._pos = float(val)
        self.update()

    thumbPos = Property(float, get_thumb_pos, set_thumb_pos)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.setChecked(not self._checked)
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w, h = float(self.width()), float(self.height())
        track_rect = QRectF(1.0, 1.0, w - 2.0, h - 2.0)

        # Interpolate track color between #D4D4D8 (off) and #2563EB (on)
        off_c = QColor("#D4D4D8")
        on_c = QColor("#2563EB")
        t = self._pos
        r = round(off_c.red() + (on_c.red() - off_c.red()) * t)
        g = round(off_c.green() + (on_c.green() - off_c.green()) * t)
        b = round(off_c.blue() + (on_c.blue() - off_c.blue()) * t)

        path = QPainterPath()
        path.addRoundedRect(track_rect, (h - 2.0) / 2.0, (h - 2.0) / 2.0)
        p.fillPath(path, QColor(r, g, b))

        thumb_d = h - 6.0
        min_x = 3.0
        max_x = w - 3.0 - thumb_d
        cur_x = min_x + (max_x - min_x) * t
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(cur_x, 3.0, thumb_d, thumb_d))
        p.end()


class FileTypeIcon(QWidget):
    """Crisp anti-aliased vector folder or file icon (replaces inconsistent system emojis)."""

    def __init__(self, is_dir: bool, size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.is_dir = is_dir
        self.setFixedSize(size, size)

    def sizeHint(self) -> QSize:
        return self.size()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        s = float(self.width())

        if self.is_dir:
            # Clean Windows 11 warm amber vector folder
            back = QPainterPath()
            back.addRoundedRect(QRectF(s * 0.10, s * 0.20, s * 0.36, s * 0.22), 2.5, 2.5)
            p.fillPath(back, QColor("#F59E0B"))

            front = QPainterPath()
            front.addRoundedRect(QRectF(s * 0.10, s * 0.28, s * 0.80, s * 0.54), 3.5, 3.5)
            p.fillPath(front, QColor("#FBBF24"))
            p.setPen(QPen(QColor("#F59E0B"), 0.8))
            p.drawPath(front)
        else:
            # Clean slate/blue vector document icon
            doc = QPainterPath()
            doc.addRoundedRect(QRectF(s * 0.20, s * 0.12, s * 0.60, s * 0.76), 3.0, 3.0)
            p.fillPath(doc, QColor("#F1F5F9"))
            p.setPen(QPen(QColor("#CBD5E1"), 1.0))
            p.drawPath(doc)

            # Subtle text lines inside document
            p.setPen(QPen(QColor("#94A3B8"), 1.3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QRectF(s * 0.32, s * 0.36, s * 0.36, 0).topLeft(), QRectF(s * 0.32, s * 0.36, s * 0.36, 0).topRight())
            p.drawLine(QRectF(s * 0.32, s * 0.50, s * 0.36, 0).topLeft(), QRectF(s * 0.32, s * 0.50, s * 0.36, 0).topRight())
            p.drawLine(QRectF(s * 0.32, s * 0.64, s * 0.22, 0).topLeft(), QRectF(s * 0.32, s * 0.64, s * 0.22, 0).topRight())
        p.end()


class SettingItemRow(QFrame):
    """Windows 11 Settings style row: title + subtitle on left, control widget on right."""

    def __init__(
        self,
        title: str,
        subtitle: str,
        control: QWidget,
        show_bottom_border: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("SettingItemRow")
        border_css = "border-bottom: 1px solid #F1F5F9;" if show_bottom_border else "border: none;"
        self.setStyleSheet(f"QFrame#SettingItemRow {{ background: transparent; {border_css} }}")

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 13, 16, 13)
        row.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(2)

        lbl_t = QLabel(title)
        lbl_t.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #18181B; border: none;")
        text_col.addWidget(lbl_t)

        if subtitle:
            lbl_s = QLabel(subtitle)
            lbl_s.setWordWrap(True)
            lbl_s.setStyleSheet("font-size: 12px; color: #71717A; border: none;")
            text_col.addWidget(lbl_s)

        row.addLayout(text_col, 1)
        row.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
