"""Painted mode card used by the production onboarding toast."""

from __future__ import annotations

import math
from typing import Optional

from PyQt5.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient
from PyQt5.QtWidgets import QWidget

from i18n import _t, add_listener, remove_listener
from mode_themes import paint_mode_icon, theme_for_mode
from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_PROFESSIONAL_BETA,
    VISION_MODE_STANDARD,
    mode_spec,
)


CARD_W = 296
CARD_H = 52
CARD_REASON_H = 72

_DESC_KEYS = {
    VISION_MODE_COMPATIBILITY: "onb_mode_compat_desc",
    VISION_MODE_STANDARD: "onb_mode_standard_desc",
    VISION_MODE_PROFESSIONAL_BETA: "onb_mode_pro_desc",
}


class ModeSelectCard(QWidget):
    activated = pyqtSignal(str)
    unavailable_requested = pyqtSignal(str, str)
    height_changed = pyqtSignal()

    def __init__(
        self,
        mode: str,
        *,
        available: bool = True,
        reason_key: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        mode_spec(mode)
        self.mode = mode
        self.available = bool(available)
        self.reason_key = reason_key
        self.selected = False
        self.dimmed = False
        self._hover_progress = 0.0
        self._select_progress = 0.0
        self._reason_progress = 0.0
        self._shake_offset = 0.0
        self._appearance_progress = 1.0
        self._base: Optional[QPixmap] = None
        self._animations: list[QVariantAnimation] = []
        self.setFixedSize(CARD_W, CARD_H)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(_t(mode_spec(mode).label_key))
        if reason_key:
            self.setToolTip(_t(reason_key))
        add_listener(self._on_language_changed)

    def closeEvent(self, event) -> None:
        remove_listener(self._on_language_changed)
        super().closeEvent(event)

    def set_selected(self, selected: bool) -> None:
        if selected == self.selected:
            return
        self.selected = selected
        if selected:
            self._animate("_select_progress", self._select_progress, 1.0, 420)
        else:
            self._select_progress = 0.0
            self.update()

    def set_dimmed(self, dimmed: bool) -> None:
        self.dimmed = dimmed
        self.update()

    def set_available(self, available: bool, reason_key: Optional[str] = None) -> None:
        self.available = bool(available)
        self.reason_key = reason_key
        self.setToolTip(_t(reason_key) if reason_key else "")
        self._base = None
        self.update()

    def prepare_reveal(self) -> None:
        self._appearance_progress = 0.0
        self.update()

    def reveal(self) -> None:
        theme = theme_for_mode(self.mode)
        self._animate(
            "_appearance_progress",
            self._appearance_progress,
            1.0,
            round(320 * theme.duration_scale),
            easing=theme.easing,
        )

    def enterEvent(self, event) -> None:
        self._animate("_hover_progress", self._hover_progress, 1.0, 180)
        if not self.available and self.reason_key:
            self._show_reason(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate("_hover_progress", self._hover_progress, 0.0, 180)
        if not self.available and not self.selected:
            self._show_reason(False)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self._activate()
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._activate()
            event.accept()
            return
        super().keyPressEvent(event)

    def _activate(self) -> None:
        if self.available:
            self.activated.emit(self.mode)
            return
        self._show_reason(True)
        self._shake()
        self.unavailable_requested.emit(self.mode, self.reason_key or "")

    def _show_reason(self, show: bool) -> None:
        target = 1.0 if show else 0.0
        if target == self._reason_progress:
            return
        start_height = self.height()
        end_height = CARD_REASON_H if show else CARD_H
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(220)
        animation.setEasingCurve(QEasingCurve.OutCubic)

        def tick(value) -> None:
            progress = float(value)
            self._reason_progress = progress if show else 1.0 - progress
            self.setFixedHeight(round(start_height + (end_height - start_height) * progress))
            self.height_changed.emit()
            self.update()

        animation.valueChanged.connect(tick)
        animation.start()
        self._animations.append(animation)

    def _shake(self) -> None:
        animation = QVariantAnimation(self)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setDuration(260)
        animation.valueChanged.connect(
            lambda value: self._set_shake(3.0 * math.sin(float(value) * 4.0 * math.pi))
        )
        animation.finished.connect(lambda: self._set_shake(0.0))
        animation.start()
        self._animations.append(animation)

    def _set_shake(self, value: float) -> None:
        self._shake_offset = value
        self.update()

    def _animate(
        self,
        name: str,
        start: float,
        end: float,
        duration: int,
        *,
        easing: int = QEasingCurve.OutCubic,
    ) -> None:
        animation = QVariantAnimation(self)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        animation.valueChanged.connect(lambda value: self._set_progress(name, float(value)))
        animation.start()
        self._animations.append(animation)

    def _set_progress(self, name: str, value: float) -> None:
        setattr(self, name, value)
        self.update()

    def _on_language_changed(self) -> None:
        self._base = None
        self.setAccessibleName(_t(mode_spec(self.mode).label_key))
        self.setToolTip(_t(self.reason_key) if self.reason_key else "")
        self.update()

    def paintEvent(self, event) -> None:
        del event
        if self._base is None:
            self._base = self._render_base()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity((0.25 if self.dimmed else 1.0) * self._appearance_progress)
        painter.translate(self._shake_offset, 10.0 * (1.0 - self._appearance_progress))
        painter.drawPixmap(0, 0, self._base)

        theme = theme_for_mode(self.mode)
        accent = QColor(theme.accent)
        if self.selected or self._hover_progress > 0.01:
            alpha = int(30 + 42 * max(self._hover_progress, self._select_progress))
            painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), alpha), 1.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(0.5, 0.5, CARD_W - 1, self.height() - 1), 6, 6)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), int(120 * self._hover_progress + 90)))
            painter.drawRoundedRect(QRectF(0.5, 9, 2, max(18, self.height() - 18)), 1, 1)

        if self._select_progress > 0.01:
            glow = QRadialGradient(self.rect().center(), CARD_W * 0.45)
            glow.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), int(35 * self._select_progress)))
            glow.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(QRectF(self.rect()), 6, 6)

        paint_mode_icon(
            painter,
            QRectF(10, 10, 31, 31),
            self.mode,
            progress=max(self._hover_progress, self._select_progress),
            enabled=self.available,
        )

        if self._reason_progress > 0.01 and self.reason_key:
            painter.setOpacity((0.25 if self.dimmed else 1.0) * self._reason_progress)
            painter.setFont(_font(8, 0.4))
            painter.setPen(QColor("#9aa0a8"))
            painter.drawText(
                QRectF(47, 49, CARD_W - 59, 18),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                _t(self.reason_key),
            )

    def _render_base(self) -> QPixmap:
        dpr = self.devicePixelRatioF()
        pixmap = QPixmap(int(CARD_W * dpr), int(CARD_REASON_H * dpr))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
        painter.setBrush(QColor(255, 255, 255, 8 if self.available else 5))
        painter.drawRoundedRect(QRectF(0.5, 0.5, CARD_W - 1, CARD_H - 1), 6, 6)

        opacity = 1.0 if self.available else 0.38
        painter.setOpacity(opacity)
        painter.setFont(_font(11, 1.2))
        painter.setPen(QColor("#eef1f4"))
        painter.drawText(
            QRectF(47, 8, 174, 18),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            _t(mode_spec(self.mode).label_key),
        )
        painter.setFont(_font(8, 0.5))
        painter.setPen(QColor("#7d838c"))
        painter.drawText(
            QRectF(47, 27, 226, 16),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            _t(_DESC_KEYS[self.mode]),
        )

        badge = None
        if not self.available:
            badge = _t("onb_mode_badge_unavailable")
        elif self.mode == VISION_MODE_STANDARD:
            badge = _t("onb_mode_badge_recommended")
        elif self.mode == VISION_MODE_PROFESSIONAL_BETA:
            badge = _t("onb_mode_badge_beta")
        if badge:
            theme = theme_for_mode(self.mode)
            color = QColor(theme.accent)
            painter.setFont(_font(7, 0.7, QFont.Normal))
            width = max(34, painter.fontMetrics().horizontalAdvance(badge) + 12)
            badge_rect = QRectF(CARD_W - width - 10, 8, width, 17)
            painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 130), 1))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 16))
            painter.drawRoundedRect(badge_rect, 3, 3)
            painter.setPen(color)
            painter.drawText(badge_rect, int(Qt.AlignCenter), badge)
        painter.end()
        return pixmap


def _font(pixel: int, spacing: float = 0.0, weight: int = QFont.Light) -> QFont:
    font = QFont("Microsoft YaHei")
    font.setPixelSize(pixel)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


__all__ = ["CARD_H", "CARD_REASON_H", "CARD_W", "ModeSelectCard"]
