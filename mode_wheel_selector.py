"""Partially submerged rotating mode wheel for the central console.

The wheel is a real disc: slots repeat around a full circle, and every painted
element (ticks, spokes, labels) rotates with it, so a mode change reads as the
disc turning under a fixed notch rather than three cards sliding along an arc.
"""

from __future__ import annotations

import math
from typing import Mapping, Optional

from PyQt5.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QRadialGradient
from PyQt5.QtWidgets import QWidget

from i18n import _t, add_listener, remove_listener
from mode_themes import paint_mode_icon, theme_for_mode
from vision_modes import ModeAvailability, VISION_MODE_SPECS

WHEEL_W = 400
WHEEL_H = 126
_CENTER = QPointF(WHEEL_W / 2, 200)
_RING_RADIUS = 174.0
_ITEM_RADIUS = 143.0
_ITEM_W = 92.0
_ITEM_H = 40.0

# Three modes repeated three times fill the disc exactly, so the slot sequence
# is seamless in both directions and the wheel never runs out of face.
_REPEATS = 3
_SLOT_DEGREES = 360.0 / (len(VISION_MODE_SPECS) * _REPEATS)
_VISIBLE_DEGREES = 74.0

_SHORT_LABEL_KEYS = {
    "compatibility": "console_mode_compat_short",
    "standard": "console_mode_standard_short",
    "professional_beta": "console_mode_professional_short",
}


def _wrap_degrees(value: float) -> float:
    return (value + 180.0) % 360.0 - 180.0


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
        self._slot_count = len(self._modes) * _REPEATS
        self._availability = dict(availability)
        self._current_index = self._modes.index(current_mode)
        # Absolute disc rotation in degrees; the selected slot sits at the top
        # when this equals -current_index * _SLOT_DEGREES.
        self._wheel_angle = -self._current_index * _SLOT_DEGREES
        self._spin_rate = 0.0
        self._hover_mode: Optional[str] = None
        self._busy = False
        self._shake = 0.0
        self._animation: Optional[QVariantAnimation] = None
        self.setFixedSize(WHEEL_W, WHEEL_H)
        # WA_TranslucentBackground only applies to top-level windows. As a child
        # of the console viewport the wheel needs the same styled-transparent
        # treatment as DragBar, or its unpainted corners render as a dark slab.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setAutoFillBackground(False)
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
        self._settle_on(self._modes.index(mode), self._shortest_steps(mode))
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
            self._animate_to(mode, self._shortest_steps(mode))
        event.accept()

    def _shortest_steps(self, mode: str) -> int:
        count = len(self._modes)
        forward = (self._modes.index(mode) - self._current_index) % count
        return forward if forward <= count / 2 else forward - count

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

    def _settle_on(self, mode_index: int, signed_steps: int) -> None:
        self._current_index = mode_index
        self._wheel_angle -= signed_steps * _SLOT_DEGREES
        self._spin_rate = 0.0

    def _animate_to(self, mode: str, signed_steps: int) -> None:
        target_index = self._modes.index(mode)
        start_angle = self._wheel_angle
        end_angle = start_angle - signed_steps * _SLOT_DEGREES
        animation = QVariantAnimation(self)
        animation.setStartValue(start_angle)
        animation.setEndValue(end_angle)
        animation.setDuration(420 + max(0, abs(signed_steps) - 1) * 160)
        # Slight overshoot then settle, so the disc reads as detenting into place.
        curve = QEasingCurve(QEasingCurve.OutBack)
        curve.setOvershoot(1.12)
        animation.setEasingCurve(curve)
        animation.valueChanged.connect(self._set_wheel_angle)

        def finish() -> None:
            self._current_index = target_index
            self._wheel_angle = end_angle
            self._spin_rate = 0.0
            self._busy = True
            self.setCursor(Qt.BusyCursor)
            self.update()
            self.mode_requested.emit(mode)

        animation.finished.connect(finish)
        self._animation = animation
        animation.start()

    def _set_wheel_angle(self, value) -> None:
        angle = float(value)
        self._spin_rate = min(1.0, abs(angle - self._wheel_angle) / 6.0)
        self._wheel_angle = angle
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

    def _slot_offsets(self) -> list[tuple[str, float]]:
        """Return (mode, offset-in-slots-from-the-top-notch) for visible slots."""
        visible = []
        for slot in range(self._slot_count):
            degrees = _wrap_degrees(slot * _SLOT_DEGREES + self._wheel_angle)
            if abs(degrees) > _VISIBLE_DEGREES:
                continue
            visible.append((self._modes[slot % len(self._modes)], degrees / _SLOT_DEGREES))
        return visible

    def _slot_rect(self, offset: float) -> QRectF:
        """Untransformed item rect, in the slot's own rotated frame."""
        scale = max(0.74, 1.0 - abs(offset) * 0.13)
        width, height = _ITEM_W * scale, _ITEM_H * scale
        return QRectF(-width / 2, -_ITEM_RADIUS - height / 2, width, height)

    def _mode_positions(self) -> list[tuple[str, QRectF, float]]:
        """Axis-aligned bounding rects in widget coordinates, for hit testing."""
        positions = []
        for mode, offset in self._slot_offsets():
            angle = math.radians(offset * _SLOT_DEGREES - 90.0)
            center = QPointF(
                _CENTER.x() + math.cos(angle) * _ITEM_RADIUS,
                _CENTER.y() + math.sin(angle) * _ITEM_RADIUS,
            )
            rect = self._slot_rect(offset)
            positions.append(
                (
                    mode,
                    QRectF(
                        center.x() - rect.width() / 2,
                        center.y() - rect.height() / 2,
                        rect.width(),
                        rect.height(),
                    ),
                    offset,
                )
            )
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

        selected_theme = theme_for_mode(self.current_mode)
        accent = QColor(selected_theme.accent)

        self._paint_disc(painter, accent)
        self._paint_ticks(painter, accent)
        self._paint_slots(painter)
        # Dissolve the flanks before the fixed chrome, so the notch and captions
        # stay fully opaque while the disc itself fades out at the edges.
        self._paint_edge_fade(painter)
        self._paint_notch(painter, accent)

        painter.setOpacity(1.0)
        painter.setFont(_font(7, 3.0))
        painter.setPen(QColor("#7d838c"))
        painter.drawText(
            QRectF(0, 3, WHEEL_W, 14),
            int(Qt.AlignHCenter | Qt.AlignVCenter),
            _t("console_mode_selector"),
        )
        if self._busy:
            painter.setFont(_font(7, 0.6))
            painter.setPen(QColor("#d8a94a"))
            painter.drawText(QRectF(0, 108, WHEEL_W, 15), int(Qt.AlignHCenter), _t("console_mode_switching"))

    def _paint_disc(self, painter: QPainter, accent: QColor) -> None:
        face = QRadialGradient(_CENTER, _RING_RADIUS)
        face.setColorAt(0.0, QColor(22, 25, 30, 238))
        face.setColorAt(0.86, QColor(14, 16, 20, 242))
        face.setColorAt(1.0, QColor(7, 8, 10, 246))
        painter.setBrush(face)
        painter.setPen(QPen(QColor(210, 216, 224, 52), 1.0))
        painter.drawEllipse(_CENTER, _RING_RADIUS, _RING_RADIUS)

        # A tight accent bloom under the notch, clipped to the disc so it can
        # never paint a lit rectangle over the console behind the widget.
        painter.save()
        painter.setClipRect(QRectF(self.rect()))
        halo = QRadialGradient(QPointF(_CENTER.x(), _CENTER.y() - _RING_RADIUS + 16), 118)
        halo.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 30))
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(_CENTER, _RING_RADIUS - 1, _RING_RADIUS - 1)
        painter.restore()

        painter.setBrush(Qt.NoBrush)
        for radius, alpha in ((_RING_RADIUS - 8.0, 26), (_ITEM_RADIUS - 27.0, 17)):
            painter.setPen(QPen(QColor(255, 255, 255, alpha), 1))
            painter.drawEllipse(_CENTER, radius, radius)

    def _paint_ticks(self, painter: QPainter, accent: QColor) -> None:
        """Ticks and spokes rotate with the disc; they carry the sense of motion."""
        painter.save()
        painter.translate(_CENTER)
        boost = int(self._spin_rate * 46)
        minor_step = _SLOT_DEGREES / 5.0
        steps = int(round(360.0 / minor_step))
        for index in range(steps):
            degrees = _wrap_degrees(index * minor_step + self._wheel_angle - 90.0)
            if abs(degrees + 90.0) > _VISIBLE_DEGREES + 8.0:
                continue
            major = index % 5 == 0
            painter.save()
            painter.rotate(degrees + 90.0)
            if major:
                painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 128 + boost), 1.3))
                painter.drawLine(QPointF(0, -_RING_RADIUS + 3), QPointF(0, -_RING_RADIUS + 15))
                painter.setPen(QPen(QColor(255, 255, 255, 30 + boost // 2), 1))
                painter.drawLine(QPointF(0, -_RING_RADIUS + 17), QPointF(0, -_ITEM_RADIUS + 24))
            else:
                painter.setPen(QPen(QColor(255, 255, 255, 52 + boost), 1))
                painter.drawLine(QPointF(0, -_RING_RADIUS + 4), QPointF(0, -_RING_RADIUS + 10))
            painter.restore()
        painter.restore()

    def _paint_slots(self, painter: QPainter) -> None:
        for mode, offset in sorted(self._slot_offsets(), key=lambda item: abs(item[1]), reverse=True):
            availability = self._availability.get(mode, ModeAvailability(True))
            selected = abs(offset) < 0.34
            hovered = mode == self._hover_mode
            theme = theme_for_mode(mode)
            accent = QColor(theme.accent)
            fade = max(0.0, 1.0 - max(0.0, abs(offset) - 0.6) / 1.25)
            opacity = (0.35 if not availability.available else 1.0) * (1.0 if selected else 0.72 * fade)
            if opacity <= 0.02:
                continue
            painter.setOpacity(opacity)

            painter.save()
            painter.translate(_CENTER)
            # Items ride the disc: they tilt tangentially instead of staying level.
            painter.rotate(offset * _SLOT_DEGREES)
            rect = self._slot_rect(offset)

            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0.0, QColor(255, 255, 255, 20 if selected else 11))
            fill.setColorAt(1.0, QColor(255, 255, 255, 5))
            border_alpha = 110 if selected else 34 + (30 if hovered else 0)
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), border_alpha), 1))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 5, 5)

            icon_rect = QRectF(rect.left() + 6, rect.center().y() - 12, 24, 24)
            paint_mode_icon(
                painter,
                icon_rect,
                mode,
                progress=1.0 if selected or hovered else 0.0,
                enabled=availability.available,
            )
            painter.setFont(_font(9 if selected else 8, 0.4))
            painter.setPen(accent if selected else QColor("#c3c8cf"))
            painter.drawText(
                QRectF(rect.left() + 32, rect.top(), rect.width() - 36, rect.height()),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                _t(_SHORT_LABEL_KEYS[mode]),
            )
            painter.restore()
        painter.setOpacity(1.0)

    def _paint_edge_fade(self, painter: QPainter) -> None:
        """Dissolve both flanks so the disc reads as continuing past the viewport.

        This erases alpha rather than painting a dark band: the widget is
        translucent, so an opaque overlay would show up as a hard-edged box on
        top of the console instead of blending into it.
        """
        fade = QLinearGradient(QPointF(0, 0), QPointF(WHEEL_W, 0))
        fade.setColorAt(0.00, QColor(0, 0, 0, 0))
        fade.setColorAt(0.16, QColor(0, 0, 0, 130))
        fade.setColorAt(0.30, QColor(0, 0, 0, 255))
        fade.setColorAt(0.70, QColor(0, 0, 0, 255))
        fade.setColorAt(0.84, QColor(0, 0, 0, 130))
        fade.setColorAt(1.00, QColor(0, 0, 0, 0))
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fade)
        painter.drawRect(self.rect())
        painter.restore()

    def _paint_notch(self, painter: QPainter, accent: QColor) -> None:
        """A fixed detent above the disc: the wheel turns, this never moves."""
        top = _CENTER.y() - _RING_RADIUS
        cx = _CENTER.x()
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 176), 1.2))
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 150))
        marker = QPointF(cx, top - 3.0)
        painter.drawPolygon(
            marker,
            QPointF(cx - 4.5, top - 10.0),
            QPointF(cx + 4.5, top - 10.0),
        )
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 54), 1))
        painter.drawLine(QPointF(cx - 30, top - 10.0), QPointF(cx - 9, top - 10.0))
        painter.drawLine(QPointF(cx + 9, top - 10.0), QPointF(cx + 30, top - 10.0))

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
