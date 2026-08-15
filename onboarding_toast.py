"""
EchoPosture 开场弹窗：右下角系统提醒 + 苹果式滑条开关。

视觉、几何、配色与时间轴复刻 ui/onboarding.html 的 .toast / .switch 部分
（onboarding.html 是开场流程的演示参考，本模块只复用其数值，不读取它）。

流程：show_bottom_right() 入场 → 用户拨动开关（旋钮里的眼睛旋转睁开）→
发出 armed 信号 → 820ms 后弹窗轻沉淡出 → 发出 finished 信号，宿主接管
（tray_app 在此进入启动校准倒计时）。

高流畅度要点：
- 玻璃卡片底 + logo 蓝图衬底 + 三段静态文字预渲染成一张 pixmap；
  入场/退场只动 windowOpacity 和窗口位置（交给系统合成器，不逐帧重绘内容）。
- 开关用单条 QVariantAnimation 时间轴驱动，paint 内按通道取样
  （滑动 / 旋转 / 睁眼 / 虹膜 / 轨道变色各有自己的起点、时长与缓动），
  每帧只重绘开关自身的小区域。
- 不使用 QGraphicsEffect（实时模糊/阴影代价高），阴影与辉光全部手绘。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Mapping, Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QEvent,
    QParallelAnimationGroup,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtWidgets import QApplication, QWidget

from i18n import _t, add_listener, remove_listener
from mode_select_card import CARD_H, ModeSelectCard
from mode_themes import theme_for_mode
from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_SPECS,
    VISION_MODE_STANDARD,
    ModeAvailability,
    mode_spec,
)

# ---- 配色（取自 onboarding.html 的 :root，仅复用数值） ----
SILVER_HI = QColor("#eef1f4")
SILVER_LO = QColor("#7d838c")
RED = QColor("#ff2f43")
RED_SOFT = QColor("#ff6473")

# 弹窗几何（CSS px；高 DPI 由 Qt 的缩放属性接管）
TOAST_W = 340
BOOT_H = 187
TOAST_H = 302
TOAST_MARGIN = 34
TOAST_RADIUS = 14
PAD_X = 22

# 开关几何：轨道 66×38，控件四周留 6px 给辉光/阴影
SWITCH_PAD = 6
TRACK_W, TRACK_H = 66, 38
KNOB_D = 30
KNOB_TRAVEL = 28

# 行内布局（自上而下：head / title / sub / row）
Y_HEAD = 20
Y_TITLE = 44
Y_SUB = 71
Y_ROW = 127


def _font(family: str, pixel: int, spacing: float = 0.0,
          weight: int = QFont.Light) -> QFont:
    font = QFont(family)
    font.setPixelSize(pixel)
    font.setWeight(weight)
    if spacing:
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    return font


class _Channel:
    """时间轴上的一个动画通道：起点 + 时长 + 缓动，按毫秒取样。"""

    def __init__(self, start_ms: float, dur_ms: float, curve: QEasingCurve) -> None:
        self.start = start_ms
        self.dur = dur_ms
        self.curve = curve

    def at(self, t_ms: float) -> float:
        if self.dur <= 0:
            return 1.0 if t_ms >= self.start else 0.0
        x = (t_ms - self.start) / self.dur
        x = 0.0 if x < 0.0 else 1.0 if x > 1.0 else x
        return self.curve.valueForProgress(x)


def _out_back(overshoot: float) -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.OutBack)
    curve.setOvershoot(overshoot)
    return curve


def render_glass_card(width: int, height: int, dpr: float) -> QPixmap:
    """深色玻璃卡片 + 右侧 logo 蓝图衬底 + 1px 高光描边，预渲染成 pixmap。

    开场弹窗与托盘浮窗共用，保证所有右下角浮层观感一致。
    """
    pm = QPixmap(int(width * dpr), int(height * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)

    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    card = QRectF(0.5, 0.5, width - 1, height - 1)
    path = QPainterPath()
    path.addRoundedRect(card, TOAST_RADIUS, TOAST_RADIUS)

    # 深色玻璃底
    glass = QLinearGradient(QPointF(0, 0), QPointF(0, height))
    glass.setColorAt(0.0, QColor(20, 22, 26, 222))
    glass.setColorAt(1.0, QColor(12, 13, 16, 240))
    p.setPen(Qt.NoPen)
    p.fillPath(path, QBrush(glass))

    # 右侧 logo 蓝图衬底：向左渐隐，给文字让出空间
    p.save()
    p.setClipPath(path)
    _paint_logo_backdrop(p, width, height, dpr)
    p.restore()

    # 1px 高光描边 + 顶部内侧高光线
    p.setPen(QPen(QColor(255, 255, 255, 26), 1))
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.setPen(QPen(QColor(255, 255, 255, 15), 1))
    p.drawLine(QPointF(TOAST_RADIUS, 1.5), QPointF(width - TOAST_RADIUS, 1.5))
    p.end()
    return pm


def _paint_logo_backdrop(p: QPainter, width: int, height: int, dpr: float) -> None:
    """复刻 CSS：background-size auto 152%、position 118% 38%、opacity .5、
    向左渐隐的 mask。先把 logo + 渐隐 mask 合成到临时层，再半透明叠加。"""
    logo_path = Path(__file__).resolve().with_name("logo.png")
    logo = QPixmap(str(logo_path))
    if logo.isNull():
        return

    ih = height * 1.52
    iw = ih * logo.width() / max(logo.height(), 1)
    ix = (width - iw) * 1.18
    iy = (height - ih) * 0.38

    layer = QPixmap(int(width * dpr), int(height * dpr))
    layer.setDevicePixelRatio(dpr)
    layer.fill(Qt.transparent)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.SmoothPixmapTransform, True)
    lp.drawPixmap(QRectF(ix, iy, iw, ih), logo, QRectF(logo.rect()))

    mask = QLinearGradient(QPointF(0, 0), QPointF(width, 0))
    mask.setColorAt(0.0, QColor(0, 0, 0, 0))
    mask.setColorAt(0.40, QColor(0, 0, 0, 0))
    mask.setColorAt(0.74, QColor(0, 0, 0, 140))
    mask.setColorAt(1.0, QColor(0, 0, 0, 255))
    lp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
    lp.fillRect(QRectF(0, 0, width, height), QBrush(mask))
    lp.end()

    p.setOpacity(0.5)
    p.drawPixmap(0, 0, layer)
    p.setOpacity(1.0)


class EyeSlideSwitch(QWidget):
    """苹果式滑条开关，旋钮 = 闭眼图标；拨开时旋钮滑动、轨道变红、眼睛旋转睁开。

    复刻 onboarding.html .switch 的通道节奏：
      滑动 .5s cubic-bezier(.34,1.3,.4,1)（带回弹）
      旋钮内 svg 旋转一周 .6s
      眼形 scaleY(.09→1) 延迟 .18s，带回弹
      虹膜淡入 .25s 延迟 .4s
      轨道变色 .45s
    one_shot=True：开场用，只允许拨开一次（防连点），与演示一致。
    one_shot=False：托盘浮窗用，双向切换（关闭时时间轴倒放，眼睛旋回闭合）。
    """

    toggled_on = pyqtSignal()       # 一次性拨开（开场弹窗）
    toggled = pyqtSignal(bool)      # 双向切换（托盘浮窗）

    TIMELINE_MS = 700.0

    def __init__(self, parent: Optional[QWidget] = None, one_shot: bool = True) -> None:
        super().__init__(parent)
        self.setFixedSize(TRACK_W + SWITCH_PAD * 2, TRACK_H + SWITCH_PAD * 2)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAccessibleName(_t("onb_accessible_name"))

        self._one_shot = one_shot
        self._t = 0.0           # 时间轴位置（ms）
        self._on = False
        self._hover = False

        self._ch_slide = _Channel(0, 500, _out_back(1.2))
        self._ch_rot = _Channel(0, 600, QEasingCurve(QEasingCurve.OutCubic))
        self._ch_open = _Channel(180, 500, _out_back(1.4))
        self._ch_iris = _Channel(400, 250, QEasingCurve(QEasingCurve.OutCubic))
        self._ch_color = _Channel(0, 450, QEasingCurve(QEasingCurve.InOutCubic))

        self._anim = QVariantAnimation(self)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(self._on_tick)

    def is_on(self) -> bool:
        return self._on

    def set_on(self, on: bool, animate: bool = True) -> None:
        """程序化设置开关状态（不发信号）。animate=False 用于浮窗打开时同步。"""
        if on == self._on:
            return
        self._on = on
        if animate:
            self._animate_to(self.TIMELINE_MS if on else 0.0)
        else:
            self._anim.stop()
            self._t = self.TIMELINE_MS if on else 0.0
            self.update()

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(target)
        self._anim.setDuration(int(abs(target - self._t)))
        self._anim.start()

    def _on_tick(self, value) -> None:
        self._t = float(value)
        self.update()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            if self._one_shot:
                if not self._on:
                    self._on = True
                    self.setCursor(Qt.ArrowCursor)
                    self._animate_to(self.TIMELINE_MS)
                    self.toggled_on.emit()
            else:
                self.set_on(not self._on, animate=True)
                self.toggled.emit(self._on)
        event.accept()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        t = self._t
        slide = self._ch_slide.at(t)
        rot = self._ch_rot.at(t)
        open_t = self._ch_open.at(t)
        iris_t = self._ch_iris.at(t)
        color_t = self._ch_color.at(t)

        track = QRectF(SWITCH_PAD, SWITCH_PAD, TRACK_W, TRACK_H)
        radius = TRACK_H / 2.0

        # hover 白色微光（仅未拨开时）
        if self._hover and not self._on:
            pen = QPen(QColor(255, 255, 255, 40), 4)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(track.adjusted(-1, -1, 1, 1), radius, radius)

        # 拨开后的红色辉光（手绘多圈描边，替代 box-shadow）
        if color_t > 0.01:
            for width, alpha in ((6.0, 26), (4.0, 50), (2.0, 80)):
                pen = QPen(QColor(255, 47, 67, int(alpha * color_t)), width)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(track.adjusted(-1, -1, 1, 1), radius, radius)

        # 轨道：灰底 → 红色渐变交叉淡化
        p.setPen(QPen(QColor(255, 255, 255, 31), 1))
        p.setBrush(QColor("#3a3f47"))
        p.drawRoundedRect(track, radius, radius)
        if color_t > 0.001:
            grad = QLinearGradient(track.topLeft(), track.bottomRight())
            grad.setColorAt(0.0, QColor("#ff5a6c"))
            grad.setColorAt(0.55, QColor("#ff2f43"))
            grad.setColorAt(1.0, QColor("#c41326"))
            p.setOpacity(color_t)
            p.setPen(QPen(QColor(255, 120, 135, 153), 1))
            p.setBrush(QBrush(grad))
            p.drawRoundedRect(track, radius, radius)
            p.setOpacity(1.0)

        # 旋钮（含下方柔影）
        knob_x = track.left() + 4 + KNOB_TRAVEL * slide
        knob_y = track.top() + 4
        center = QPointF(knob_x + KNOB_D / 2.0, knob_y + KNOB_D / 2.0)

        shadow = QRadialGradient(center + QPointF(0, 2.5), KNOB_D / 2.0 + 3)
        shadow.setColorAt(0.6, QColor(0, 0, 0, 100))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(shadow))
        p.drawEllipse(center + QPointF(0, 2.5), KNOB_D / 2.0 + 3, KNOB_D / 2.0 + 3)

        knob_grad = QLinearGradient(QPointF(knob_x, knob_y),
                                    QPointF(knob_x + KNOB_D, knob_y + KNOB_D))
        knob_grad.setColorAt(0.0, QColor("#ffffff"))
        knob_grad.setColorAt(0.55, QColor("#e7eaee"))
        knob_grad.setColorAt(1.0, QColor("#c9ced5"))
        p.setBrush(QBrush(knob_grad))
        p.drawEllipse(center, KNOB_D / 2.0, KNOB_D / 2.0)

        self._paint_eye(p, center, rot, open_t, iris_t)

    def _paint_eye(self, p: QPainter, center: QPointF,
                   rot: float, open_t: float, iris_t: float) -> None:
        """旋钮内 22px 迷你眼睛。坐标系 = 演示里的 viewBox(-50,-34,100,68)。"""
        p.save()
        p.translate(center)
        p.rotate(360.0 * rot)
        p.scale(0.22, 0.22)

        # 眼形开合：默认压成一条缝（scaleY .09），拨开后睁到 1
        sy = 0.09 + 0.91 * open_t
        p.scale(1.0, sy)

        almond = QPainterPath()
        almond.moveTo(-46, 0)
        almond.quadTo(0, -27, 46, 0)
        almond.quadTo(0, 27, -46, 0)
        almond.closeSubpath()

        p.setBrush(QColor("#0e0f12"))
        p.setPen(QPen(SILVER_LO, 3))
        p.drawPath(almond)

        # 眼白 + 虹膜（裁剪在眼形内）
        p.save()
        p.setClipPath(almond)
        p.setPen(Qt.NoPen)
        p.setBrush(SILVER_HI)
        p.drawRect(QRectF(-46, -28, 92, 56))
        if iris_t > 0.001:
            p.setOpacity(iris_t)
            iris = QRadialGradient(QPointF(6, -1.5), 17)
            iris.setColorAt(0.0, QColor("#aeb7c2"))
            iris.setColorAt(0.55, QColor("#5d646e"))
            iris.setColorAt(1.0, QColor("#23272d"))
            p.setBrush(QBrush(iris))
            p.drawEllipse(QPointF(6, 0), 17, 17)
            p.setBrush(QColor("#0c0d0f"))
            p.drawEllipse(QPointF(6, 0), 7.5, 7.5)
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPointF(1, -5), 3, 3)
            p.setOpacity(1.0)
        p.restore()

        # 上睑描边
        lid = QPainterPath()
        lid.moveTo(-46, 0)
        lid.quadTo(0, -27, 46, 0)
        p.setBrush(Qt.NoBrush)
        pen = QPen(QColor("#3a3f47"), 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPath(lid)
        p.restore()


class OnboardingToast(QWidget):
    """Fixed-geometry onboarding surface with honest mode initialization state."""

    armed = pyqtSignal()
    mode_selected = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(
        self,
        availability: Optional[Mapping[str, ModeAvailability]] = None,
        *,
        persisted_mode: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setFixedSize(TOAST_W, TOAST_H)
        self.setWindowTitle("EchoPosture")
        self.setMouseTracking(True)

        self._availability = dict(availability or {})
        self._persisted_mode = persisted_mode
        self._boot_card: Optional[QPixmap] = None
        self._mode_card: Optional[QPixmap] = None
        self._final_pos = QPoint(0, 0)
        self._booted = False
        self._phase = "boot"
        self._selected_mode: Optional[str] = None
        self._reveal_progress = 0.0
        self._progress = 0.0
        self._progress_message_key = "onb_mode_loading"
        self._failure_detail = ""
        self._countdown_seconds = 15
        self._countdown_cancelled = False
        self._close_hover = False
        self._anims: List = []  # 持有动画引用，防止被回收

        self._state_text = _t("onb_state_off")
        self._state_color = QColor(SILVER_LO)
        self._state_font = _font("Microsoft YaHei", 10, 3.0)

        self.switch = EyeSlideSwitch(self)
        self.switch.move(
            TOAST_W - PAD_X - TRACK_W - SWITCH_PAD,
            TOAST_H - BOOT_H + Y_ROW - SWITCH_PAD,
        )
        self.switch.toggled_on.connect(self._on_armed)

        self._mode_clip = QWidget(self)
        self._mode_clip.setAttribute(Qt.WA_TranslucentBackground, True)
        self._mode_clip.setGeometry(0, TOAST_H - BOOT_H, TOAST_W, BOOT_H)
        self._mode_clip.hide()
        self.mode_cards: dict[str, ModeSelectCard] = {}
        for index, spec in enumerate(VISION_MODE_SPECS):
            available = self._availability.get(spec.mode, ModeAvailability(True))
            card = ModeSelectCard(
                spec.mode,
                available=available.available,
                reason_key=available.reason_key,
                parent=self._mode_clip,
            )
            card.activated.connect(self._choose_mode)
            card.unavailable_requested.connect(self._on_unavailable_requested)
            card.height_changed.connect(self._layout_mode_cards)
            card.installEventFilter(self)
            card.hide()
            self.mode_cards[spec.mode] = card
        self._layout_mode_cards()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_step)
        self._slow_timer = QTimer(self)
        self._slow_timer.setSingleShot(True)
        self._slow_timer.setInterval(8000)
        self._slow_timer.timeout.connect(self._mark_loading_slow)

        # 监听全局语言变更：刷新状态文本 + 让卡片缓存失效重绘
        add_listener(self._on_language_changed)

    def closeEvent(self, event) -> None:
        self._countdown_timer.stop()
        self._slow_timer.stop()
        remove_listener(self._on_language_changed)
        for card in self.mode_cards.values():
            remove_listener(card._on_language_changed)
        super().closeEvent(event)

    # ---- 对外入口 ----
    def show_bottom_right(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - TOAST_W - TOAST_MARGIN
        y = screen.y() + screen.height() - TOAST_H - TOAST_MARGIN
        self._final_pos = QPoint(x, y)

        # 入场前先停在终点下方 16px、全透明；450ms 后开始上浮淡入
        self.move(x, y + 16)
        self.setWindowOpacity(0.0)
        self.show()
        QTimer.singleShot(450, self._animate_in)
        if self._persisted_mode is not None:
            QTimer.singleShot(720, self._show_persisted_mode)

    # ---- 入场 / 谢幕（只动 windowOpacity + 位置，内容零重绘） ----
    def _animate_in(self) -> None:
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(900)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        rise = QPropertyAnimation(self, b"pos")
        rise.setDuration(900)
        rise.setStartValue(self._final_pos + QPoint(0, 16))
        rise.setEndValue(self._final_pos)
        rise.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(rise)
        group.start()
        self._anims.append(group)

    def _animate_out(self) -> None:
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(520)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.InQuad)
        sink = QPropertyAnimation(self, b"pos")
        sink.setDuration(520)
        sink.setStartValue(self.pos())
        sink.setEndValue(self._final_pos + QPoint(0, 10))
        sink.setEasingCurve(QEasingCurve.InQuad)
        group.addAnimation(fade)
        group.addAnimation(sink)
        group.finished.connect(self._on_gone)
        group.start()
        self._anims.append(group)

    def _on_gone(self) -> None:
        self.hide()
        self.finished.emit()

    # ---- 开关拨开：状态行变色 → 820ms 后同窗展开模式区 ----
    def _on_armed(self) -> None:
        if self._booted:
            return
        self._booted = True
        self._state_text = _t("onb_state_on")

        recolor = QVariantAnimation(self)
        recolor.setStartValue(QColor(SILVER_LO))
        recolor.setEndValue(QColor(RED_SOFT))
        recolor.setDuration(400)
        recolor.valueChanged.connect(self._set_state_color)
        recolor.start()
        self._anims.append(recolor)

        self.armed.emit()
        QTimer.singleShot(820, self._show_modes)

    def _set_state_color(self, color) -> None:
        self._state_color = QColor(color)
        self.update()

    def _show_persisted_mode(self) -> None:
        if self._phase != "boot" or self._persisted_mode is None:
            return
        self._booted = True
        self.switch.hide()
        self._show_modes(auto_countdown=False)
        QTimer.singleShot(620, lambda: self._choose_mode(self._persisted_mode or VISION_MODE_COMPATIBILITY))

    def _show_modes(self, auto_countdown: bool = True) -> None:
        if self._phase != "boot":
            return
        self._phase = "modes"
        self.switch.hide()
        self._mode_clip.show()
        reveal = QVariantAnimation(self)
        reveal.setStartValue(0.0)
        reveal.setEndValue(1.0)
        reveal.setDuration(520)
        reveal.setEasingCurve(QEasingCurve.OutCubic)
        reveal.valueChanged.connect(self._set_reveal_progress)
        reveal.start()
        self._anims.append(reveal)
        for index, card in enumerate(self.mode_cards.values()):
            card.prepare_reveal()
            QTimer.singleShot(80 + index * 100, lambda item=card: self._reveal_card(item))
        if auto_countdown:
            QTimer.singleShot(520, self._begin_countdown)

    def _set_reveal_progress(self, value) -> None:
        self._reveal_progress = float(value)
        self._layout_mode_cards()
        self.update()

    def _reveal_card(self, card: ModeSelectCard) -> None:
        if self._phase not in {"modes", "loading", "failed", "complete"}:
            return
        card.show()
        card.reveal()

    def _layout_mode_cards(self) -> None:
        visible_height = round(BOOT_H + (TOAST_H - BOOT_H) * self._reveal_progress)
        source_y = TOAST_H - visible_height
        self._mode_clip.setGeometry(0, source_y, TOAST_W, visible_height)
        absolute_y = 91
        for card in self.mode_cards.values():
            card.move(PAD_X, absolute_y - source_y)
            absolute_y += card.height() + 7

    def _begin_countdown(self) -> None:
        if self._phase != "modes" or self._countdown_cancelled:
            return
        self._countdown_seconds = 15
        self._countdown_timer.start()
        self.update()

    def _countdown_step(self) -> None:
        if self._phase != "modes":
            self._countdown_timer.stop()
            return
        self._countdown_seconds -= 1
        if self._countdown_seconds <= 0:
            self._countdown_timer.stop()
            self._choose_mode(self.default_mode())
        self.update()

    def default_mode(self) -> str:
        standard = self._availability.get(VISION_MODE_STANDARD, ModeAvailability(True))
        return VISION_MODE_STANDARD if standard.available else VISION_MODE_COMPATIBILITY

    def _choose_mode(self, mode: str) -> None:
        if self._phase != "modes":
            return
        available = self._availability.get(mode, ModeAvailability(True))
        if not available.available:
            return
        self._phase = "loading"
        self._selected_mode = mode
        self._countdown_timer.stop()
        for card_mode, card in self.mode_cards.items():
            card.set_selected(card_mode == mode)
            card.set_dimmed(card_mode != mode)
        self._progress = 0.0
        self._progress_message_key = "onb_mode_loading"
        self._slow_timer.start()
        self.mode_selected.emit(mode)
        self.update()

    def _on_unavailable_requested(self, mode: str, reason_key: str) -> None:
        del mode
        self._failure_detail = _t(reason_key) if reason_key else ""
        self.update()

    def set_loading_progress(self, progress: int, message_key: Optional[str] = None) -> None:
        if self._phase not in {"loading", "failed"}:
            return
        if message_key:
            self._progress_message_key = message_key
        target = max(self._progress, min(100.0, float(progress)))
        animation = QVariantAnimation(self)
        animation.setStartValue(self._progress)
        animation.setEndValue(target)
        animation.setDuration(260)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.valueChanged.connect(self._set_progress)
        animation.start()
        self._anims.append(animation)

    def _set_progress(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _mark_loading_slow(self) -> None:
        if self._phase == "loading" and self._progress < 100:
            self._progress_message_key = "onb_mode_loading_slow"
            self.update()

    def show_mode_failure(self, detail: str, fallback_mode: str = VISION_MODE_COMPATIBILITY) -> None:
        self._slow_timer.stop()
        self._phase = "failed"
        message_key = (
            "onb_mode_failed_fallback_standard"
            if fallback_mode == VISION_MODE_STANDARD
            else "onb_mode_failed_fallback"
        )
        self._failure_detail = _t(message_key, detail=detail)
        self._selected_mode = fallback_mode
        for mode, card in self.mode_cards.items():
            card.set_selected(mode == fallback_mode)
            card.set_dimmed(mode != fallback_mode)
        self.update()

    def show_terminal_failure(self, detail: str) -> None:
        """Show that no backend became usable; do not imply a successful fallback."""
        self._slow_timer.stop()
        self._phase = "failed"
        self._failure_detail = _t("onb_mode_failed_terminal", detail=detail)
        self._selected_mode = None
        for card in self.mode_cards.values():
            card.set_selected(False)
            card.set_dimmed(True)
        self.update()

    def complete_mode(self, mode: str) -> None:
        self._slow_timer.stop()
        self._phase = "complete"
        self._selected_mode = mode
        self._progress = 100.0
        for card_mode, card in self.mode_cards.items():
            card.set_selected(card_mode == mode)
            card.set_dimmed(card_mode != mode)
        self.update()
        QTimer.singleShot(560, self._animate_out)

    def enterEvent(self, event) -> None:
        self._cancel_countdown()
        super().enterEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched in self.mode_cards.values() and event.type() in (QEvent.Enter, QEvent.MouseMove):
            self._cancel_countdown()
        return super().eventFilter(watched, event)

    def _cancel_countdown(self) -> None:
        if self._phase == "modes":
            self._countdown_cancelled = True
            self._countdown_timer.stop()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        hover = QRectF(310, 9, 18, 18).contains(event.pos())
        if hover != self._close_hover:
            self._close_hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and QRectF(310, 9, 18, 18).contains(event.pos()):
            if self._phase == "modes":
                self._choose_mode(self.default_mode())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ---- 绘制：两张静态卡缓存 + 少量裁切/进度逐帧绘制 ----
    def paintEvent(self, event) -> None:
        del event
        if self._boot_card is None:
            self._boot_card = self._render_boot_card()
        if self._mode_card is None:
            self._mode_card = self._render_mode_card()
        p = QPainter(self)
        if self._phase == "boot":
            y = TOAST_H - BOOT_H
            p.drawPixmap(0, y, self._boot_card)
            p.setFont(self._state_font)
            p.setPen(self._state_color)
            p.drawText(
                QRectF(PAD_X, y + Y_ROW, 200, TRACK_H),
                int(Qt.AlignLeft | Qt.AlignVCenter),
                self._state_text,
            )
            return

        visible_height = round(BOOT_H + (TOAST_H - BOOT_H) * self._reveal_progress)
        source_y = TOAST_H - visible_height
        p.save()
        p.setClipRect(QRectF(0, source_y, TOAST_W, visible_height))
        p.drawPixmap(0, 0, self._mode_card)
        p.restore()
        if self._close_hover and self._phase == "modes":
            p.setPen(QPen(QColor("#c3c8cf"), 1.1))
            p.drawLine(QPointF(315, 14), QPointF(323, 22))
            p.drawLine(QPointF(323, 14), QPointF(315, 22))

        if self._phase in {"loading", "failed", "complete"}:
            self._paint_progress(p)
        elif self._phase == "modes" and not self._countdown_cancelled:
            p.setFont(_font("Microsoft YaHei", 8, 0.7))
            p.setPen(SILVER_LO)
            p.drawText(
                QRectF(PAD_X, 276, TOAST_W - PAD_X * 2, 16),
                int(Qt.AlignHCenter | Qt.AlignVCenter),
                _t(
                    "onb_mode_autoselect",
                    seconds=self._countdown_seconds,
                    mode=_t(mode_spec(self.default_mode()).label_key),
                ),
            )

    def _paint_progress(self, painter: QPainter) -> None:
        mode = self._selected_mode or VISION_MODE_COMPATIBILITY
        theme = theme_for_mode(mode)
        accent = QColor(theme.accent)
        if self._progress_message_key == "onb_mode_loading_slow":
            accent = QColor("#d8a94a")
        if self._phase == "failed":
            accent = RED
        track = QRectF(PAD_X + 16, 271, TOAST_W - (PAD_X + 16) * 2, 2)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 24))
        painter.drawRoundedRect(track, 1, 1)
        painter.setBrush(accent)
        painter.drawRoundedRect(QRectF(track.left(), track.top(), track.width() * self._progress / 100.0, 2), 1, 1)
        painter.setFont(_font("Microsoft YaHei", 8, 0.6))
        painter.setPen(accent if self._phase != "complete" else QColor("#c3c8cf"))
        if self._phase == "failed":
            message = self._failure_detail
        elif self._phase == "complete":
            message = _t("onb_mode_ready", mode=_t(mode_spec(mode).label_key))
        else:
            message = _t(self._progress_message_key)
        painter.drawText(
            QRectF(PAD_X, 278, TOAST_W - PAD_X * 2, 17),
            int(Qt.AlignHCenter | Qt.AlignVCenter),
            message,
        )

    def _render_boot_card(self) -> QPixmap:
        pm = render_glass_card(TOAST_W, BOOT_H, self.devicePixelRatioF())
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)

        # 静态文字三段
        p.setFont(_font("Microsoft YaHei", 10, 4.2))
        p.setPen(SILVER_LO)
        p.drawText(QRectF(PAD_X, Y_HEAD, TOAST_W - PAD_X * 2, 14),
                   int(Qt.AlignLeft | Qt.AlignVCenter), _t("onb_caption"))

        p.setFont(_font("Microsoft YaHei", 15, 2.7))
        p.setPen(SILVER_HI)
        p.drawText(QRectF(PAD_X, Y_TITLE, TOAST_W - PAD_X * 2, 22),
                   int(Qt.AlignLeft | Qt.AlignVCenter), _t("onb_title"))

        p.setFont(_font("Microsoft YaHei", 11, 1.3))
        p.setPen(SILVER_LO)
        sub_lines = (_t("onb_body_1"), _t("onb_body_2"))
        line_h = 20
        for i, line in enumerate(sub_lines):
            p.drawText(QRectF(PAD_X, Y_SUB + i * line_h, TOAST_W - PAD_X * 2, line_h),
                       int(Qt.AlignLeft | Qt.AlignVCenter), line)

        p.end()
        return pm

    def _render_mode_card(self) -> QPixmap:
        pm = render_glass_card(TOAST_W, TOAST_H, self.devicePixelRatioF())
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setFont(_font("Microsoft YaHei", 10, 4.2))
        p.setPen(SILVER_LO)
        p.drawText(
            QRectF(PAD_X, 16, TOAST_W - PAD_X * 2, 14),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            _t("onb_caption"),
        )
        p.setFont(_font("Microsoft YaHei", 15, 2.2))
        p.setPen(SILVER_HI)
        p.drawText(
            QRectF(PAD_X, 39, TOAST_W - PAD_X * 2, 22),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            _t("onb_mode_title"),
        )
        p.setFont(_font("Microsoft YaHei", 9, 0.9))
        p.setPen(SILVER_LO)
        p.drawText(
            QRectF(PAD_X, 64, TOAST_W - PAD_X * 2, 16),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            _t("onb_mode_sub"),
        )
        p.end()
        return pm

    def _on_language_changed(self) -> None:
        """全局语言变更回调：刷新状态文本 + 让卡片缓存失效，下次 paint 重绘。"""
        # 状态文本：如果已经拨开过用 on 状态，否则 off 状态
        self._state_text = _t("onb_state_on") if self._booted else _t("onb_state_off")
        # 卡片缓存失效：下次 paintEvent 会重新 _render_card，画上新语言的静态文字
        self._boot_card = None
        self._mode_card = None
        self.switch.setAccessibleName(_t("onb_accessible_name"))
        self.update()


def main() -> int:
    """独立预览入口：python onboarding_toast.py（不接摄像头、不接托盘）。"""
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    from vision_modes import detect_mode_availability

    toast = OnboardingToast(detect_mode_availability())
    toast.mode_selected.connect(lambda mode: QTimer.singleShot(900, lambda: toast.complete_mode(mode)))
    toast.finished.connect(app.quit)
    toast.show_bottom_right()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
