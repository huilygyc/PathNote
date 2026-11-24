"""Exact Win32 physical pixel <-> Qt logical DIP conversion across arbitrary DPI scales (e.g. 150%)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QGuiApplication, QScreen
import win32api


def find_screen_for_phys_point(px: int, py: int) -> tuple[QScreen, tuple[int, int, int, int]]:
    """Return matching (QScreen, win32_monitor_phys_rect) for physical screen coordinates (px, py)."""
    screens = QGuiApplication.screens()
    primary = QGuiApplication.primaryScreen()
    try:
        hmon = win32api.MonitorFromPoint((int(px), int(py)), 2)  # MONITOR_DEFAULTTONEAREST
        info = win32api.GetMonitorInfo(hmon)
        mon_rect = info["Monitor"]  # (l, t, r, b) in physical pixels
        dev_name = info.get("Device", "")
        for s in screens:
            if dev_name and s.name() == dev_name:
                return s, mon_rect
    except Exception:
        mon_rect = (0, 0, 2560, 1600)

    s = primary or (screens[0] if screens else None)
    return s, mon_rect


def phys_point_to_qt(px: int, py: int) -> tuple[QPoint, QScreen]:
    """Convert Win32 physical pixel coordinates (px, py) to Qt logical DIP QPoint."""
    screen, mon_phys = find_screen_for_phys_point(px, py)
    if screen is None:
        return QPoint(px, py), None
    dpr = screen.devicePixelRatio() or 1.0
    s_geo = screen.geometry()
    lx = s_geo.left() + round((px - mon_phys[0]) / dpr)
    ly = s_geo.top() + round((py - mon_phys[1]) / dpr)
    return QPoint(lx, ly), screen


def phys_rect_to_qt(phys_rect: tuple[int, int, int, int]) -> tuple[QRect, QScreen]:
    """Convert Win32 physical (left, top, right, bottom) to Qt logical QRect."""
    l, t, r, b = phys_rect
    cx = (l + r) // 2
    cy = (t + b) // 2
    screen, mon_phys = find_screen_for_phys_point(cx, cy)
    if screen is None:
        return QRect(l, t, max(1, r - l), max(1, b - t)), None
    dpr = screen.devicePixelRatio() or 1.0
    s_geo = screen.geometry()
    ql = s_geo.left() + round((l - mon_phys[0]) / dpr)
    qt_top = s_geo.top() + round((t - mon_phys[1]) / dpr)
    qw = max(1, round((r - l) / dpr))
    qh = max(1, round((b - t) / dpr))
    return QRect(ql, qt_top, qw, qh), screen
