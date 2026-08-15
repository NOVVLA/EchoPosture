"""Partially submerged cyclic mode wheel for the central console."""

from __future__ import annotations

import math
from typing import Mapping, Optional

from PyQt5.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QWidget

from i18n import _t, add_listener, remove_listener
from mode_themes import paint_mode_icon, theme_for_mode
from vision_modes import ModeAvailability, VISION_MODE_SPECS, mode_spec


WHEEL_W = 400
WHEEL_H = 126
_CENTER = QPointF(WHEEL_W / 2, 200)
_RING_RADIUS = 174.0
_ITEM_RADIUS = 145.0
_ITEM_W = 104.0
_ITEM_H = 50.0

_SHORT_LABEL_KEYS = {
    "compatibility": "console_mode_compat_short",
    "standard": "console_mode_standard_short",
    "professional_beta": "console_mode_professional_short",
}


class ModeWheelSelector(QWidget):
    mode_requested = pyqtSignal(str)

    def __init__(
        self,
        availability: Mapping[str, ModeAvailability],
        current_mode: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._modes = [spec.mode for spec in VISION_MODE_SPECS]
        self._availability = dict(availability)
        self._current_index = self._modes.index(current_mode)
        self._visual_shift = 0.0
        self._hover_mode: Optional[str] = None
        self._busy = False
        self._shake = 0.0
        self._animation: Optional[QVariantAnimation] = None
        self.setFixedSize(WHEEL_W, WHEEL_H)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(_t("console_mode_selector"))
        add_listener(self._on_language_changed)

    @property
    def current_mode(self) -> str:
        return self._modes[self._current_index]

    def set_current_mode(self, mode: str) -> None:
        if mode not in self._modes or mode == self.current_mode:
            return
        self._current_index = self._modes.index(mode)
        self._visual_shift = 0.0
        self._busy = False
        self.update()

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self.setCursor(Qt.BusyCursor if busy else Qt.PointingHandCursor)
        self.update()

    def set_availability(self, availability: Mapping[str, ModeAvailability]) -> None:
        self._availability = dict(availability)
        self.update()

    def closeEvent(self, event) -> None:
        remove_listener(self._on_language_changed)
        super().closeEvent(event)

    def wheelEvent(self, event) -> None:
        if not self._busy:
            direction = 1 if event.angleDelta().y() < 0 else -1
            self._request_neighbor(direction)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Left, Qt.Key_Up):
            self._request_neighbor(-1)
            event.accept()
            return
        if event.key() in (Qt.Key_Right, Qt.Key_Down):
            self._request_neighbor(1)
            event.accept()
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.mode_requested.emit(self.current_mode)
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        hovered = self._mode_at(event.pos())
        if hovered != self._hover_mode:
            self._hover_mode = hovered
            availability = self._availability.get(hovered) if hovered else None
            self.setToolTip(
                _t(availability.reason_key)
                if availability is not None and not availability.available and availability.reason_key
                else ""
            )
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover_mode = None
        self.setToolTip("")
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton or self._busy or self._is_animating():
            event.accept()
            return
        mode = self._mode_at(event.pos())
        if mode is None:
            event.accept()
            return
        availability = self._availability.get(mode, ModeAvailability(True))
        if not availability.available:
            self._animate_shake()
            event.accept()
            return
        if mode == self.current_mode:
            self.mode_requested.emit(mode)
        else:
            current = self._current_index
            target = self._modes.index(mode)
            forward = (target - current) % len(self._modes)
            signed_steps = forward if forward <= len(self._modes) / 2 else forward - len(self._modes)
            self._animate_to(mode, signed_steps)
        event.accept()

    def _request_neighbor(self, direction: int) -> None:
        if self._busy or self._is_animating():
            return
        for distance in range(1, len(self._modes) + 1):
            index = (self._current_index + direction * distance) % len(self._modes)
            mode = self._modes[index]
            if self._availability.get(mode, ModeAvailability(True)).available:
                self._animate_to(mode, direction * distance)
                return

    def _is_animating(self) -> bool:
        return self._animation is not None and self._animation.state() == QAbstractAnimation.Running

    def _animate_to(self, mode: str, signed_steps: int) -> None:
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(float(-signed_steps))
        animation.setDuration(360 + max(0, abs(signed_steps) - 1) * 150)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(self._set_visual_shift)

        def finish() -> None:
            self._current_index = self._modes.index(mode)
            self._visual_shift = 0.0
            self._busy = True
            self.setCursor(Qt.BusyCursor)
            self.update()
            self.mode_requested.emit(mode)

        animation.finished.connect(finish)
        self._animation = animation
        animation.start()

    def _set_visual_shift(self, value) -> None:
        self._visual_shift = float(value)
        self.update()

    def _animate_shake(self) -> None:
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(260)
        animation.valueChanged.connect(
            lambda value: self._set_shake(math.sin(float(value) * math.pi * 4.0) * 3.0)
        )
        animation.finished.connect(lambda: self._set_shake(0.0))
        animation.start()
        self._animation = animation

    def _set_shake(self, value: float) -> None:
        self._shake = value
        self.update()

    def _mode_positions(self) -> list[tuple[str, QRectF, float]]:
        positions = []
        count = len(self._modes)
        for offset in range(-(count - 1), count):
            mode = self._modes[(self._current_index + offset) % count]
            visual_offset = offset + self._visual_shift
            if abs(visual_offset) > 1.55:
                continue
            angle = math.radians(-90.0 + visual_offset * 36.0)
            center = QPointF(
                _CENTER.x() + math.cos(angle) * _ITEM_RADIUS,
                _CENTER.y() + math.sin(angle) * _ITEM_RADIUS,
            )
            scale = max(0.78, 1.0 - abs(visual_offset) * 0.12)
            width, height = _ITEM_W * scale, _ITEM_H * scale
            positions.append((mode, QRectF(center.x() - width / 2, center.y() - height / 2, width, height), visual_offset))
        return positions

    def _mode_at(self, point) -> Optional[str]:
        for mode, rect, _offset in sorted(self._mode_positions(), key=lambda item: abs(item[2])):
            if rect.contains(point):
                return mode
        return None

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(self._shake, 0)

        ring_glow = QRadialGradient(QPointF(_CENTER.x(), 78), 220)
        ring_glow.setColorAt(0.0, QColor(255, 255, 255, 18))
        ring_glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(ring_glow)
        painter.drawRect(self.rect())

        ring_pen = QPen(QColor(210, 216, 224, 44), 1.0)
        ring_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(ring_pen)
        painter.setBrush(QColor(10, 11, 14, 224))
        painter.drawEllipse(_CENTER, _RING_RADIUS, _RING_RADIUS)
        painter.setPen(QPen(QColor(255, 255, 255, 17), 1))
        painter.drawEllipse(_CENTER, _RING_RADIUS - 9, _RING_RADIUS - 9)

        painter.setFont(_font(7, 3.0))
        painter.setPen(QColor("#7d838c"))
        painter.drawText(QRectF(0, 4, WHEEL_W, 15), int(Qt.AlignHCenter | Qt.AlignVCenter), _t("console_mode_selector"))

        positions = sorted(self._mode_positions(), key=lambda item: abs(item[2]), reverse=True)
        for mode, rect, offset in positions:
            availability = self._availability.get(mode, ModeAvailability(True))
            selected = abs(offset) < 0.35
            hovered = mode == self._hover_mode
            theme = theme_for_mode(mode)
            accent = QColor(theme.accent)
            alpha = 0.35 if not availability.available else 1.0
            painter.setOpacity(alpha * (1.0 if selected else 0.70))

            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0.0, QColor(255, 255, 255, 18 if selected else 10))
            fill.setColorAt(1.0, QColor(255, 255, 255, 5))
            border_alpha = 100 if selected else 35 + (28 if hovered else 0)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), border_alpha), 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5, 5)

            icon_rect = QRectF(rect.left() + 8, rect.top() + 9, 30, 30)
            paint_mode_icon(
                painter,
                icon_rect,
                mode,
                progress=1.0 if selected or hovered else 0.0,
                enabled=availability.available,
            )
            painter.setFont(_font(8 if not selected else 9, 0.5))
            painter.setPen(accent if selected else QColor("#c3c8cf"))
            painter.drawText(
                QRectF(rect.left() + 41, rect.top(), rect.width() - 46, rect.height()),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                _t(_SHORT_LABEL_KEYS[mode]),
            )
        painter.setOpacity(1.0)
        if self._busy:
            painter.setFont(_font(7, 0.6))
            painter.setPen(QColor("#d8a94a"))
            painter.drawText(QRectF(0, 107, WHEEL_W, 15), int(Qt.AlignHCenter), _t("console_mode_switching"))

    def _on_language_changed(self) -> None:
        self.setAccessibleName(_t("console_mode_selector"))
        self.update()


def _font(pixel: int, spacing: float = 0.0) -> QFont:
    font = QFont("Microsoft YaHei")
    font.setPixelSize(pixel)
    font.setWeight(QFont.Light)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


__all__ = ["ModeWheelSelector", "WHEEL_H", "WHEEL_W"]
