"""Clean modern Windows 11 Fluent / Linear-Light stylesheet and sculpted Fluent 3D app icon."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)


INLINE_TEXT_COLOR_PRESETS = [
    ("#0F6CBD", "静谧蓝"),
    ("#64748B", "岩石灰"),
    ("#059669", "青松绿"),
    ("#B45309", "暖琥珀"),
    ("#6D28D9", "暮光紫"),
]


def render_fluent_icon_pixmap(size: int = 256, muted: bool = False) -> QPixmap:
    """
    Render a sculpted Windows 11 Fluent Design multi-layered icon on a 512x512 supersampled canvas:
    - True transparent silhouette (no boxy square background, no text characters, no status dot)
    - Warm golden-amber folder backplate & tab
    - Crisp white note sheet peeking out from inside
    - Sunlit golden front folder pocket with specular highlight
    - Overlapping sapphire-blue tag/note badge at bottom-right
    """
    base = 512
    img = QImage(base, base, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)

    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    # 1. Soft ambient ground shadow under folder
    shadow_path = QPainterPath()
    shadow_path.addRoundedRect(QRectF(42, 184, 392, 266), 48, 48)
    p.fillPath(shadow_path, QColor(15, 23, 42, 34))

    # 2. Folder Backplate + Sculpted Top-Left Tab
    back_path = QPainterPath()
    r = 40.0
    back_path.moveTo(36, 120)
    back_path.quadTo(36, 76, 80, 76)
    back_path.lineTo(182, 76)
    back_path.cubicTo(208, 76, 218, 114, 246, 114)
    back_path.lineTo(392, 114)
    back_path.quadTo(432, 114, 432, 154)
    back_path.lineTo(432, 396)
    back_path.quadTo(432, 436, 392, 436)
    back_path.lineTo(76, 436)
    back_path.quadTo(36, 436, 36, 396)
    back_path.closeSubpath()

    back_grad = QLinearGradient(QPointF(36, 76), QPointF(432, 436))
    if muted:
        back_grad.setColorAt(0.0, QColor("#94A3B8"))
        back_grad.setColorAt(1.0, QColor("#64748B"))
    else:
        back_grad.setColorAt(0.0, QColor("#F59E0B"))
        back_grad.setColorAt(1.0, QColor("#D97706"))
    p.fillPath(back_path, back_grad)

    # 3. Crisp White Note Card peeking out from inside the folder
    card_shadow = QPainterPath()
    card_shadow.addRoundedRect(QRectF(78, 122, 312, 190), 26, 26)
    p.fillPath(card_shadow, QColor(0, 0, 0, 28))

    card_rect = QRectF(78, 114, 312, 190)
    card_path = QPainterPath()
    card_path.addRoundedRect(card_rect, 26, 26)
    card_grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomLeft())
    card_grad.setColorAt(0.0, QColor("#FFFFFF"))
    card_grad.setColorAt(1.0, QColor("#F1F5F9"))
    p.fillPath(card_path, card_grad)

    # Subtle accent lines on the peeking white note sheet
    p.setPen(
        QPen(
            QColor("#94A3B8" if muted else "#60A5FA"),
            12,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
        )
    )
    p.drawLine(QPointF(114, 146), QPointF(224, 146))

    # 4. Luminous Front Folder Pocket
    front_rect = QRectF(36, 174, 396, 262)
    front_path = QPainterPath()
    front_path.addRoundedRect(front_rect, r, r)

    front_grad = QLinearGradient(QPointF(234, 174), QPointF(234, 436))
    if muted:
        front_grad.setColorAt(0.0, QColor("#CBD5E1"))
        front_grad.setColorAt(0.5, QColor("#94A3B8"))
        front_grad.setColorAt(1.0, QColor("#64748B"))
    else:
        front_grad.setColorAt(0.0, QColor("#FDE68A"))
        front_grad.setColorAt(0.18, QColor("#FCD34D"))
        front_grad.setColorAt(0.65, QColor("#FBBF24"))
        front_grad.setColorAt(1.0, QColor("#F59E0B"))
    p.fillPath(front_path, front_grad)

    # Specular top glass highlight on front pocket
    p.save()
    p.setClipPath(front_path)
    p.setPen(QPen(QColor(255, 255, 255, 195), 5.0))
    p.drawLine(QPointF(52, 176.5), QPointF(416, 176.5))
    p.restore()

    # 5. Overlapping Sapphire Bookmark / Note Pill Badge (Bottom-Right)
    badge_shadow = QPainterPath()
    badge_shadow.addRoundedRect(QRectF(232, 286, 244, 162), 46, 46)
    p.fillPath(badge_shadow, QColor(15, 23, 42, 68))

    badge_rect = QRectF(232, 274, 244, 162)
    badge_path = QPainterPath()
    badge_path.addRoundedRect(badge_rect, 46, 46)

    badge_grad = QLinearGradient(badge_rect.topLeft(), badge_rect.bottomRight())
    if muted:
        badge_grad.setColorAt(0.0, QColor("#64748B"))
        badge_grad.setColorAt(1.0, QColor("#475569"))
    else:
        badge_grad.setColorAt(0.0, QColor("#38BDF8"))
        badge_grad.setColorAt(0.42, QColor("#2563EB"))
        badge_grad.setColorAt(1.0, QColor("#1D4ED8"))
    p.fillPath(badge_path, badge_grad)

    # Crisp glass rim around badge
    p.setPen(QPen(QColor(255, 255, 255, 150), 3.5))
    p.drawPath(badge_path)

    # Tag punch-hole ring + two clean note lines inside badge
    p.setPen(QPen(QColor("#FFFFFF"), 13.0))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(290, 355), 18, 18)

    p.setPen(QPen(QColor("#FFFFFF"), 15.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(336, 336), QPointF(432, 336))
    p.setPen(QPen(QColor(255, 255, 255, 215), 15.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(336, 375), QPointF(404, 375))

    p.end()

    pix = QPixmap.fromImage(img)
    if size != base:
        pix = pix.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pix


def create_app_icon(enabled: bool = True, size: int = 256) -> QIcon:
    """Pure multi-resolution window/taskbar/exe icon (never draws a green status dot on taskbar!)."""
    _ = enabled
    icon = QIcon()
    for s in (256, 128, 64, 48, 32, 24, 16):
        icon.addPixmap(render_fluent_icon_pixmap(s, muted=False))
    return icon


def create_tray_icon(enabled: bool = True) -> QIcon:
    """System notification area tray icon (vibrant when active, muted slate when paused)."""
    icon = QIcon()
    for s in (64, 32, 24, 16):
        icon.addPixmap(render_fluent_icon_pixmap(s, muted=not enabled))
    return icon


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
