"""Clean modern Windows 11 Fluent / Linear-Light stylesheet and crisp geometric app icon."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap


INLINE_TEXT_COLOR_PRESETS = [
    ("#0F6CBD", "静谧蓝"),
    ("#64748B", "岩石灰"),
    ("#059669", "青松绿"),
    ("#B45309", "暖琥珀"),
    ("#6D28D9", "暮光紫"),
]


def create_app_icon(enabled: bool = True, size: int = 64) -> QIcon:
    """Render a minimal, refined rounded squircle icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    m = size * 0.07
    rect = QRectF(m, m, size - 2 * m, size - 2 * m)
    radius = size * 0.24

    grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
    if enabled:
        grad.setColorAt(0.0, QColor("#2563EB"))
        grad.setColorAt(1.0, QColor("#1D4ED8"))
    else:
        grad.setColorAt(0.0, QColor("#94A3B8"))
        grad.setColorAt(1.0, QColor("#64748B"))

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.fillPath(path, grad)

    # Crisp "(A)" parenthetical alias glyph
    font = QFont("Segoe UI", int(size * 0.34), QFont.Weight.DemiBold)
    p.setFont(font)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(rect.adjusted(0, -size * 0.01, 0, 0), Qt.AlignmentFlag.AlignCenter, "(名)")

    if enabled:
        dot_r = size * 0.11
        dot_c = QPointF(size - m - dot_r * 0.5, size - m - dot_r * 0.5)
        p.setPen(QPen(QColor("#FFFFFF"), max(1.5, size * 0.035)))
        p.setBrush(QColor("#10B981"))
        p.drawEllipse(dot_c, dot_r, dot_r)

    p.end()
    return QIcon(pix)


def get_stylesheet(_theme: str = "light") -> str:
    """Refined modern Light design system."""
    return """
    QWidget {
        font-family: "Microsoft YaHei UI", "Segoe UI Variable Text", "Segoe UI", sans-serif;
        font-size: 13px;
        color: #18181B;
    }
    QMainWindow {
        background-color: #F5F6F8;
    }
    QDialog {
        background-color: #FFFFFF;
    }
    QLineEdit, QPlainTextEdit, QComboBox {
        background-color: #FFFFFF;
        border: 1px solid #E4E4E7;
        border-radius: 7px;
        padding: 7px 11px;
        color: #18181B;
        selection-background-color: #DBEAFE;
        selection-color: #1E3A8A;
    }
    QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover {
        border-color: #D4D4D8;
    }
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
        border: 1.5px solid #2563EB;
        background-color: #FFFFFF;
    }
    QComboBox::drop-down {
        border: none;
        width: 24px;
    }
    QComboBox QAbstractItemView {
        background-color: #FFFFFF;
        border: 1px solid #E4E4E7;
        border-radius: 7px;
        color: #18181B;
        selection-background-color: #EFF6FF;
        selection-color: #1D4ED8;
        padding: 4px;
    }
    QPushButton {
        background-color: #FFFFFF;
        border: 1px solid #E4E4E7;
        border-radius: 7px;
        padding: 6px 14px;
        color: #27272A;
        font-weight: 500;
    }
    QPushButton:hover {
        background-color: #F8FAFC;
        border-color: #D4D4D8;
    }
    QPushButton:pressed {
        background-color: #F1F5F9;
    }
    QPushButton#PrimaryBtn {
        background-color: #2563EB;
        border: 1px solid #2563EB;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton#PrimaryBtn:hover {
        background-color: #1D4ED8;
        border-color: #1D4ED8;
    }
    QPushButton#PrimaryBtn:pressed {
        background-color: #1E40AF;
    }
    QPushButton#GhostBtn {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 4px 9px;
        color: #52525B;
    }
    QPushButton#GhostBtn:hover {
        background-color: #F1F5F9;
        color: #18181B;
    }
    QPushButton#DangerGhostBtn {
        background-color: transparent;
        border: 1px solid transparent;
        border-radius: 6px;
        padding: 4px 9px;
        color: #DC2626;
    }
    QPushButton#DangerGhostBtn:hover {
        background-color: #FEF2F2;
    }
    QListWidget {
        background-color: #FFFFFF;
        border: none;
        outline: none;
    }
    QListWidget::item {
        border-bottom: 1px solid #F4F4F5;
        padding: 0px;
    }
    QListWidget::item:hover {
        background-color: #FAFAFA;
    }
    QListWidget::item:selected {
        background-color: #F0F7FF;
        color: #18181B;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 7px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #D4D4D8;
        border-radius: 3px;
        min-height: 28px;
    }
    QScrollBar::handle:vertical:hover {
        background: #A1A1AA;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QMenu {
        background-color: #FFFFFF;
        border: 1px solid #E4E4E7;
        border-radius: 8px;
        padding: 5px;
        color: #18181B;
    }
    QMenu::item {
        padding: 7px 22px 7px 12px;
        border-radius: 5px;
    }
    QMenu::item:selected {
        background-color: #EFF6FF;
        color: #1D4ED8;
    }
    QMenu::separator {
        height: 1px;
        background: #F1F5F9;
        margin: 4px 6px;
    }
    """
