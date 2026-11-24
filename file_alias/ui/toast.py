"""Clean minimal Windows 11 Light floating pill toast notification."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

_user32 = ctypes.windll.user32
_GetWindowLongW = _user32.GetWindowLongW
_GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongW.restype = ctypes.c_long

_SetWindowLongW = _user32.SetWindowLongW
_SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
_SetWindowLongW.restype = ctypes.c_long


def make_click_through_noactivate(widget: QWidget) -> None:
    """Ensure an overlay widget never steals focus or intercepts mouse clicks."""
    try:
        hwnd = wintypes.HWND(int(widget.winId()))
        style = _GetWindowLongW(hwnd, GWL_EXSTYLE)
        _SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
    except Exception:
        pass


class StatusToast(QWidget):
    """Minimal clean pill toast displayed near top-center of the screen."""

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._dot_color = QColor("#10B981")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 9, 20, 9)
        layout.setSpacing(9)

        self._dot = QLabel("●")
        self._dot.setStyleSheet("font-size: 11px; color: #10B981; background: transparent;")
        self._label = QLabel("")
        self._label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #18181B; background: transparent;"
        )

        layout.addWidget(self._dot)
        layout.addWidget(self._label)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)
        self._fading_out = False

    def show_toast(self, text: str, accent_hex: str = "#10B981", duration_ms: int = 1600) -> None:
        self._dot_color = QColor(accent_hex)
        self._dot.setStyleSheet(f"font-size: 11px; color: {accent_hex}; background: transparent;")
        self._label.setText(text)
        self.adjustSize()

        screen = QGuiApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            x = avail.center().x() - self.width() // 2
            y = avail.top() + 34
            self.move(x, y)

        self._anim.stop()
        self._fading_out = False
        self.setWindowOpacity(0.0)
        self.show()
        make_click_through_noactivate(self)

        self._anim.setStartValue(0.0)
        self._anim.setEndValue(0.98)
        self._anim.start()
        self._hide_timer.start(duration_ms)
        self.update()

    def _fade_out(self) -> None:
        self._fading_out = True
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if self._fading_out:
            self.hide()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        r = rect.height() / 2.0
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        p.fillPath(path, QColor(255, 255, 255, 248))
        p.setPen(QPen(QColor("#E4E4E7"), 1.0))
        p.drawPath(path)
        p.end()
