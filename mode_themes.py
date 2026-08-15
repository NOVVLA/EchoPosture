"""Shared visual personality for EchoPosture vision modes.

Mode-specific differences are intentionally limited to these five dimensions:
accent color, icon geometry, easing, duration scale, and breathing period. Shared
card geometry, typography, material, and status colors belong to the controls.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QEasingCurve, QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen

from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_PROFESSIONAL_BETA,
    VISION_MODE_STANDARD,
)


@dataclass(frozen=True)
class ModeTheme:
    accent: str
    soft_accent: str
    duration_scale: float
    breathing_ms: int
    easing: int
    icon_kind: str


MODE_THEMES = {
    VISION_MODE_COMPATIBILITY: ModeTheme(
        accent="#c3c8cf",
        soft_accent="#50c3c8cf",
        duration_scale=1.20,
        breathing_ms=4200,
        easing=QEasingCurve.InOutSine,
        icon_kind="ring",
    ),
    VISION_MODE_STANDARD: ModeTheme(
        accent="#ff2f43",
        soft_accent="#58ff2f43",
        duration_scale=1.00,
        breathing_ms=3200,
        easing=QEasingCurve.OutCubic,
        icon_kind="focus",
    ),
    VISION_MODE_PROFESSIONAL_BETA: ModeTheme(
        accent="#4fd6e8",
        soft_accent="#504fd6e8",
        duration_scale=0.85,
        breathing_ms=2400,
        easing=QEasingCurve.OutBack,
        icon_kind="prism",
    ),
}


def theme_for_mode(mode: str) -> ModeTheme:
    try:
        return MODE_THEMES[mode]
    except KeyError as exc:
        raise ValueError(f"unknown vision mode: {mode}") from exc


def paint_mode_icon(
    painter: QPainter,
    rect: QRectF,
    mode: str,
    *,
    progress: float = 0.0,
    enabled: bool = True,
) -> None:
    """Draw a compact blueprint icon without filters or external assets."""
    theme = theme_for_mode(mode)
    color = QColor(theme.accent)
    if not enabled:
        color.setAlpha(92)
    pen = QPen(color, 1.35)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    cx, cy = rect.center().x(), rect.center().y()
    side = min(rect.width(), rect.height())
    if theme.icon_kind == "ring":
        radius = side * (0.31 + 0.018 * progress)
        painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.drawLine(QPointF(cx - radius * 0.65, cy), QPointF(cx + radius * 0.65, cy))
    elif theme.icon_kind == "focus":
        offsets = (-side * 0.16, 0.0, side * 0.16)
        for index, offset in enumerate(offsets):
            pulse = max(0.0, 1.0 - abs(progress * 3.0 - index))
            w = side * (0.43 + pulse * 0.04)
            h = side * (0.58 + pulse * 0.05)
            painter.drawRoundedRect(QRectF(cx - w / 2 + offset, cy - h / 2, w, h), 1.8, 1.8)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(cx, cy), 2.0, 2.0)
    else:
        angle = progress * 90.0
        painter.translate(cx, cy)
        painter.rotate(angle)
        path = QPainterPath()
        path.moveTo(0, -side * 0.34)
        path.lineTo(side * 0.31, side * 0.25)
        path.lineTo(-side * 0.31, side * 0.25)
        path.closeSubpath()
        painter.drawPath(path)
        painter.rotate(-angle)
        painter.drawLine(QPointF(side * 0.24, -side * 0.08), QPointF(side * 0.43, -side * 0.22))
        painter.drawLine(QPointF(side * 0.28, 0), QPointF(side * 0.48, 0))
        painter.drawLine(QPointF(side * 0.24, side * 0.08), QPointF(side * 0.43, side * 0.22))
    painter.restore()


__all__ = ["MODE_THEMES", "ModeTheme", "paint_mode_icon", "theme_for_mode"]
