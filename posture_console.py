"""
EchoPosture 控制台窗口。

这是双击托盘图标后打开的非侵入式小 UI，用 PyQt5 原生方式（QGraphicsScene +
QtSvg + 自定义 QGraphicsObject）重建 ui/index.html 的 OCULI / VERTEBRA 观感，
并把它接进真实的监测功能。ui/index.html 是冻结的视觉参考文件，本模块只复用其
几何与配色，不读取也不修改它。

布局：中央艺术区（眼睛总开关 + 7 节脊柱功能开关）+ 右侧可折叠侧栏（迁移自旧的
StatusPanel：状态读出 + 压暗/模糊滑块 + 一键测试按钮）。

功能映射集中在 FEATURE_REGISTRY，扩展只需新增一条配置。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PyQt5.QtCore import (
    QByteArray,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtProperty,
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
    QRadialGradient,
)
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer
from PyQt5.QtWidgets import (
    QGraphicsDropShadowEffect,
    QGraphicsObject,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

# ============================================================
# 配色（取自 ui/index.html 的 :root，仅复用数值，不读取文件）
# ============================================================
SILVER_HI = QColor("#eef1f4")
SILVER = QColor("#c3c8cf")
SILVER_LO = QColor("#7d838c")
LINE = QColor("#d8dde3")
RED = QColor("#ff2f43")
RED_SOFT = QColor("#ff6473")
INK = QColor("#e8ebef")

# 场景坐标系 = ui/index.html 的 viewBox
SCENE_W = 1180.0
SCENE_H = 1380.0

# 椎骨透镜主体 / 顶部高光路径（取自 index.html 的 VERT_PATH / GLOSS_PATH）
_VERT_OUTLINE = [
    (-76, 0), (-52, -32), (52, -32), (76, 0), (52, 32), (-52, 32), (-76, 0)
]
_GLOSS_OUTLINE = [
    (-58, -7), (-38, -22), (38, -22), (58, -7), (38, -14), (-38, -14), (-58, -7)
]

# 静态蓝图层（构造圆 / 头部侧脸线稿 / 主轴），用 QtSvg 渲染。
# 文字标签与引线交给独立的 QGraphics 文本项以便控制字距，不放进这段 SVG。
_BLUEPRINT_SVG = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1180 1380'>
  <g fill='none' stroke-linecap='round'>
    <circle cx='648' cy='335' r='168' stroke='#d8dde3' stroke-opacity='0.35' stroke-width='0.75'/>
    <circle cx='560' cy='640' r='150' stroke='#d8dde3' stroke-opacity='0.35' stroke-width='0.75'/>
    <circle cx='720' cy='820' r='150' stroke='#d8dde3' stroke-opacity='0.35' stroke-width='0.75'/>
    <ellipse cx='612' cy='1060' rx='150' ry='92' stroke='#d8dde3' stroke-opacity='0.35' stroke-width='0.75'/>
    <line x1='640' y1='150' x2='640' y2='1190' stroke='#d8dde3' stroke-width='1'/>
    <line x1='470' y1='335' x2='820' y2='335' stroke='#d8dde3' stroke-opacity='0.35' stroke-width='0.75'/>
    <path d='M 612 196 C 700 168, 800 220, 812 318 C 818 372, 806 404, 786 430
             C 800 446, 802 462, 788 470 C 778 476, 770 472, 766 466
             C 760 488, 742 506, 726 512 C 740 520, 742 540, 728 556
             C 716 570, 702 600, 700 642' stroke='#d8dde3' stroke-width='1'/>
    <path d='M 612 196 C 540 224, 500 300, 512 372 C 520 420, 548 452, 574 470'
          stroke='#d8dde3' stroke-width='1'/>
    <path d='M 786 430 C 792 436, 790 444, 782 446' stroke='#d8dde3' stroke-width='1'/>
  </g>
</svg>"""


def _outline_path(points) -> QPainterPath:
    """把一组点按 index.html 的贝塞尔节奏连成透镜形闭合路径。

    index.html 用 C 命令两两连接，这里用 cubicTo 近似还原同样的胖透镜轮廓。
    """
    path = QPainterPath()
    path.moveTo(points[0][0], points[0][1])
    # 上半弧
    path.cubicTo(points[1][0], points[1][1], points[2][0], points[2][1],
                 points[3][0], points[3][1])
    # 下半弧
    path.cubicTo(points[4][0], points[4][1], points[5][0], points[5][1],
                 points[6][0], points[6][1])
    path.closeSubpath()
    return path


# ============================================================
# 功能映射表
# ============================================================
@dataclass
class FeatureSpec:
    """一节椎骨 = 一个功能。扩展只需在 FEATURE_REGISTRY 追加一条。"""

    id: str
    name: str            # 英文名，例如 "DIMMING"
    cn: str              # 中文名，例如 "压暗干预"
    x: float
    y: float
    rot: float
    kind: str            # "toggle" | "action" | "placeholder"
    apply: Optional[Callable] = None       # toggle: fn(monitor, bool)
    invoke: Optional[Callable] = None      # action: fn(monitor)
    is_active: Optional[Callable] = None   # 回读真实状态: fn(monitor) -> bool
    enabled: bool = True                   # placeholder=False → 仅占位


# 控制台持有的“恢复值”，关闭某开关时归零、重开时恢复。
class _ControlState:
    def __init__(self) -> None:
        self.saved_max_dim = 0.32
        self.saved_blur = 1.0
        self.high_fps = True


def _build_registry(ctrl: "_ControlState") -> List[FeatureSpec]:
    """7 节椎骨。坐标/倾角取自 index.html 的 VERTEBRAE 数组。"""

    def dimming_apply(monitor, on: bool) -> None:
        overlay = monitor.overlay
        if on:
            overlay.set_visual_config(ctrl.saved_max_dim, overlay.blur_scale)
        else:
            if overlay.max_dim_alpha > 0:
                ctrl.saved_max_dim = overlay.max_dim_alpha
            overlay.set_visual_config(0.0, overlay.blur_scale)

    def blur_apply(monitor, on: bool) -> None:
        overlay = monitor.overlay
        if on:
            overlay.set_visual_config(overlay.max_dim_alpha, ctrl.saved_blur)
        else:
            if overlay.blur_scale > 0:
                ctrl.saved_blur = overlay.blur_scale
            overlay.set_visual_config(overlay.max_dim_alpha, 0.0)

    def perf_apply(monitor, on: bool) -> None:
        ctrl.high_fps = on
        monitor.engine.set_capture_fps(72.0 if on else 15.0)

    return [
        FeatureSpec("calib", "CALIBRATION", "启动校准", 596, 486, -12, "action",
                    invoke=lambda m: m.recalibrate_now()),
        FeatureSpec("prec", "PRECISION", "高精度评分", 606, 574, 2, "placeholder",
                    enabled=False),
        FeatureSpec("perf", "PERFORMANCE", "72FPS 采集", 634, 662, 14, "toggle",
                    apply=perf_apply,
                    is_active=lambda m: m.engine.get_capture_fps() >= 60.0),
        FeatureSpec("dim", "DIMMING", "压暗干预", 658, 752, 9, "toggle",
                    apply=dimming_apply,
                    is_active=lambda m: m.overlay.max_dim_alpha > 0),
        FeatureSpec("blur", "BLUR", "GPU 模糊", 648, 844, -7, "toggle",
                    apply=blur_apply,
                    is_active=lambda m: m.overlay.blur_scale > 0),
        FeatureSpec("pres", "PRESENCE", "离开/多人检测", 620, 936, -17, "placeholder",
                    enabled=False),
        FeatureSpec("ident", "IDENTITY", "换人保护", 600, 1026, -11, "placeholder",
                    enabled=False),
    ]


# ============================================================
# 眼睛总开关
# ============================================================
class EyeItem(QGraphicsObject):
    clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self._eye_open = 0.0
        self._hover = False
        self.setAcceptHoverEvents(True)
        self.setOpacity(0.0)  # 入场前隐藏
        self._effect = QGraphicsDropShadowEffect()
        self._effect.setColor(QColor(255, 255, 255, 0))
        self._effect.setOffset(0, 0)
        self._effect.setBlurRadius(0)
        self.setGraphicsEffect(self._effect)
        self._pulse_anim: Optional[QPropertyAnimation] = None

    # ---- 动画属性：睁眼程度 0(闭)..1(睁) ----
    def _get_eye_open(self) -> float:
        return self._eye_open

    def _set_eye_open(self, value: float) -> None:
        self._eye_open = value
        self.update()

    eyeOpen = pyqtProperty(float, _get_eye_open, _set_eye_open)

    def boundingRect(self) -> QRectF:
        return QRectF(-70, -70, 140, 140)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QRectF(-50, -34, 100, 68))
        return path

    def set_open(self, open_: bool) -> None:
        anim = QPropertyAnimation(self, b"eyeOpen", self)
        anim.setDuration(620)
        anim.setStartValue(self._eye_open)
        anim.setEndValue(1.0 if open_ else 0.0)
        anim.setEasingCurve(QEasingCurve.OutBack if open_ else QEasingCurve.InOutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def pulse(self) -> None:
        """监测未开启时点击椎骨的柔性提示：眼睛红色脉冲一下。"""
        self._effect.setColor(QColor(255, 47, 67))
        anim = QPropertyAnimation(self._effect, b"blurRadius", self)
        anim.setDuration(700)
        anim.setStartValue(0)
        anim.setKeyValueAt(0.5, 14)
        anim.setEndValue(0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(self._restore_hover_effect)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._pulse_anim = anim

    def _restore_hover_effect(self) -> None:
        if self._hover:
            self._effect.setColor(QColor(255, 255, 255))
            self._effect.setBlurRadius(6)
        else:
            self._effect.setBlurRadius(0)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self._effect.setColor(QColor(255, 255, 255))
        self._effect.setBlurRadius(6)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        self._effect.setBlurRadius(0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.boundingRect().contains(event.pos()):
            self.clicked.emit()
        event.accept()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        t = self._eye_open

        # 柔光 halo（睁眼淡入、放大）
        if t > 0.001:
            scale = 0.6 + 0.4 * t
            r = 54 * scale
            grad = QRadialGradient(QPointF(0, 0), r)
            grad.setColorAt(0.0, QColor(255, 255, 255, int(0.5 * 255 * 0.9 * t)))
            grad.setColorAt(0.6, QColor(255, 255, 255, int(0.08 * 255 * t)))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(0, 0), r, r)

        # 眼形：纵向压扁 scaleY(0.07..1)
        sy = 0.07 + 0.93 * t
        painter.save()
        painter.scale(1.0, sy)

        almond = QPainterPath()
        almond.moveTo(-46, 0)
        almond.quadTo(0, -27, 46, 0)
        almond.quadTo(0, 27, -46, 0)
        almond.closeSubpath()

        painter.setBrush(QColor("#0e0f12"))
        pen = QPen(LINE, 1.4)
        painter.setPen(pen)
        painter.drawPath(almond)

        # 眼白 + 虹膜（裁剪在眼形内）
        painter.save()
        painter.setClipPath(almond)
        painter.setPen(Qt.NoPen)
        painter.setBrush(SILVER_HI)
        painter.drawRect(QRectF(-46, -28, 92, 56))
        if t > 0.001:
            painter.setOpacity(t)
            iris = QRadialGradient(QPointF(6, -2), 17)
            iris.setColorAt(0.0, QColor("#aeb7c2"))
            iris.setColorAt(0.55, QColor("#5d646e"))
            iris.setColorAt(1.0, QColor("#23272d"))
            painter.setBrush(QBrush(iris))
            painter.drawEllipse(QPointF(6, 0), 17, 17)
            painter.setBrush(QColor("#0c0d0f"))
            painter.drawEllipse(QPointF(6, 0), 7.5, 7.5)
            painter.setBrush(QColor(255, 255, 255, 230))
            painter.drawEllipse(QPointF(1, -5), 3, 3)
            painter.setOpacity(1.0)
        painter.restore()

        # 上睑加深
        lid = QPainterPath()
        lid.moveTo(-46, 0)
        lid.quadTo(0, -27, 46, 0)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(SILVER_HI, 1.8))
        painter.drawPath(lid)
        painter.restore()


# ============================================================
# 椎骨功能开关
# ============================================================
class VertebraItem(QGraphicsObject):
    clicked = pyqtSignal(str)

    def __init__(self, spec: FeatureSpec) -> None:
        super().__init__()
        self.spec = spec
        self._on = 0.0          # 红色点亮程度 0..1
        self._flash = 1.0       # 1=无闪光，点击时 0→1 动画
        self._hover = False
        self._enabled_visual = True
        self.setAcceptHoverEvents(True)
        self.setPos(spec.x, spec.y)
        self.setRotation(spec.rot)
        self.setOpacity(0.0)    # 入场前隐藏

        self._body = _outline_path(_VERT_OUTLINE)
        self._gloss = _outline_path(_GLOSS_OUTLINE)

        self._effect = QGraphicsDropShadowEffect()
        self._effect.setOffset(0, 0)
        self._effect.setColor(QColor(255, 255, 255, 0))
        self._effect.setBlurRadius(0)
        self.setGraphicsEffect(self._effect)
        self._breathe: Optional[QPropertyAnimation] = None

    # ---- 动画属性 ----
    def _get_on(self) -> float:
        return self._on

    def _set_on(self, value: float) -> None:
        self._on = value
        self.update()

    on = pyqtProperty(float, _get_on, _set_on)

    def _get_flash(self) -> float:
        return self._flash

    def _set_flash(self, value: float) -> None:
        self._flash = value
        self.update()

    flash = pyqtProperty(float, _get_flash, _set_flash)

    def boundingRect(self) -> QRectF:
        # 含左侧引线/标签 + 点击柔光环（r≈60）
        return QRectF(-360, -65, 440, 130)

    def shape(self) -> QPainterPath:
        # 命中区仅限透镜本体，避免点到标签
        path = QPainterPath()
        path.addEllipse(QRectF(-80, -36, 160, 72))
        return path

    # ---- 状态控制 ----
    def set_active(self, active: bool, animate: bool = True) -> None:
        target = 1.0 if active else 0.0
        if animate:
            anim = QPropertyAnimation(self, b"on", self)
            anim.setDuration(520)
            anim.setStartValue(self._on)
            anim.setEndValue(target)
            anim.start(QPropertyAnimation.DeleteWhenStopped)
        else:
            self._set_on(target)
        self._update_glow(active)

    def set_enabled_visual(self, enabled: bool) -> None:
        """眼睛闭合时椎骨变灰不可点（仅视觉，不改后端开关值）。"""
        self._enabled_visual = enabled
        self.setOpacity(1.0 if enabled else 0.32)
        if not enabled:
            self._update_glow(False)
        self.update()

    def do_flash(self) -> None:
        anim = QPropertyAnimation(self, b"flash", self)
        anim.setDuration(700)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _update_glow(self, active: bool) -> None:
        if self._breathe is not None:
            self._breathe.stop()
            self._breathe = None
        if active and self._enabled_visual:
            self._effect.setColor(QColor(255, 47, 67))
            anim = QPropertyAnimation(self._effect, b"blurRadius", self)
            anim.setDuration(3200)
            anim.setStartValue(6)
            anim.setKeyValueAt(0.5, 16)
            anim.setEndValue(6)
            anim.setLoopCount(-1)
            anim.start()
            self._breathe = anim
        elif self._hover and self._enabled_visual:
            self._effect.setColor(QColor(255, 255, 255))
            self._effect.setBlurRadius(7)
        else:
            self._effect.setBlurRadius(0)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        if self._on < 0.5:
            self._update_glow(False)
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
        if self._on < 0.5:
            self._update_glow(False)
        self.update()
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self.shape().contains(event.pos()):
            self.clicked.emit(self.spec.id)
        event.accept()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 点击柔光环
        if self._flash < 0.999:
            t = self._flash
            scale = 0.5 + 1.9 * t
            opacity = 0.8 * (1.0 - t)
            r = 60 * scale
            grad = QRadialGradient(QPointF(0, 0), r)
            grad.setColorAt(0.0, QColor(255, 120, 135, int(0.9 * 255 * opacity)))
            grad.setColorAt(1.0, QColor(255, 47, 67, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(0, 0), r, r)

        on = self._on
        # 白瓷态（随点亮淡出）
        white_grad = QLinearGradient(QPointF(-76, -32), QPointF(53.2, 32))
        white_grad.setColorAt(0.0, QColor("#ffffff"))
        white_grad.setColorAt(0.42, QColor("#e7eaee"))
        white_grad.setColorAt(1.0, QColor("#9aa0a8"))
        painter.setOpacity(1.0 - on)
        painter.setBrush(QBrush(white_grad))
        painter.setPen(QPen(QColor(255, 255, 255, 140), 0.75))
        painter.drawPath(self._body)
        # 高光
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 140))
        painter.drawPath(self._gloss)

        # 红色态（随点亮淡入）
        if on > 0.001:
            red_grad = QLinearGradient(QPointF(-76, -32), QPointF(53.2, 32))
            red_grad.setColorAt(0.0, QColor("#ff8a96"))
            red_grad.setColorAt(0.40, QColor("#ff3145"))
            red_grad.setColorAt(1.0, QColor("#b00d1d"))
            painter.setOpacity(on)
            painter.setBrush(QBrush(red_grad))
            painter.setPen(QPen(QColor(255, 120, 135, 180), 0.75))
            painter.drawPath(self._body)
        painter.setOpacity(1.0)

        # 引线 + 标签（hover 或点亮时显示）
        label_alpha = max(1.0 if self._hover else 0.0, on)
        if label_alpha > 0.01 and self._enabled_visual:
            color = QColor(SILVER_LO)
            if on > 0.01:
                color = QColor(RED_SOFT)
            color.setAlphaF(label_alpha)
            pen = QPen(color, 0.75)
            pen.setDashPattern([1, 5])
            painter.setPen(pen)
            painter.drawLine(QPointF(-78, 0), QPointF(-150, 0))

            font = QFont("Helvetica Neue", 7)
            font.setLetterSpacing(QFont.AbsoluteSpacing, 2.8)
            font.setWeight(QFont.Light)
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(QRectF(-360, -9, 200, 18),
                             int(Qt.AlignRight | Qt.AlignVCenter), self.spec.name)


# ============================================================
# 场景与视图
# ============================================================
class ConsoleScene(QGraphicsScene):
    def __init__(self) -> None:
        super().__init__()
        self.setSceneRect(0, 0, SCENE_W, SCENE_H)


class ArtView(QGraphicsView):
    def __init__(self, scene: ConsoleScene) -> None:
        super().__init__(scene)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setStyleSheet("background:#0c0d0f;")

        # 左下状态读出 + 右下提示（叠加在视图上，保持清晰、不随场景缩放）
        self.readout_title = self._mk_label("SYSTEM", 8, SILVER_LO, 4.2)
        self.readout_state = self._mk_label("监测已暂停 · STANDBY", 11, SILVER_LO, 2.2)
        self.readout_mods = self._mk_label("", 8, SILVER_LO, 1.8)
        self.readout_mods.setWordWrap(False)
        self.hint = self._mk_label("点击眼睛启停监测 · 点击椎骨切换功能", 8, SILVER_LO, 2.6)
        self.hint.setAlignment(Qt.AlignRight)

    def _mk_label(self, text: str, pt: int, color: QColor, spacing: float) -> QLabel:
        lab = QLabel(text, self)
        font = QFont("Helvetica Neue", pt)
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        font.setWeight(QFont.Light)
        lab.setFont(font)
        lab.setStyleSheet(f"color:{color.name()}; background:transparent;")
        lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return lab

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._place_overlays()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._place_overlays()

    def _place_overlays(self) -> None:
        w, h = self.width(), self.height()
        self.readout_title.adjustSize()
        self.readout_state.adjustSize()
        self.readout_mods.adjustSize()
        self.readout_title.move(20, h - 20 - 18 - 8 - self.readout_mods.height()
                                - self.readout_state.height() - self.readout_title.height())
        self.readout_state.move(20, self.readout_title.y() + self.readout_title.height() + 6)
        self.readout_mods.move(20, self.readout_state.y() + self.readout_state.height() + 8)
        self.hint.adjustSize()
        self.hint.move(w - self.hint.width() - 16, h - self.hint.height() - 14)

    def drawBackground(self, painter: QPainter, rect) -> None:
        # 在视口坐标系画“深邃亮光银”径向渐变 + 暗角，铺满整个视图
        painter.save()
        painter.resetTransform()
        vp = self.viewport().rect()
        w, h = vp.width(), vp.height()
        radius = 1.3 * max(w, h)
        grad = QRadialGradient(QPointF(0.32 * w, 0.18 * h), radius)
        grad.setColorAt(0.0, QColor("#4a4f56"))
        grad.setColorAt(0.28, QColor("#30343a"))
        grad.setColorAt(0.60, QColor("#1c1f23"))
        grad.setColorAt(0.86, QColor("#101113"))
        grad.setColorAt(1.0, QColor("#08090a"))
        painter.fillRect(vp, QBrush(grad))
        # 暗角
        vig = QRadialGradient(QPointF(0.5 * w, 0.45 * h), 0.72 * max(w, h))
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.72, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 140))
        painter.fillRect(vp, QBrush(vig))
        painter.restore()


# ============================================================
# 侧边栏（迁移自旧 StatusPanel）
# ============================================================
class SidePanel(QWidget):
    def __init__(self, window: "PostureConsoleWindow") -> None:
        super().__init__()
        self.window_ref = window
        self.setFixedWidth(210)
        self.setStyleSheet(
            """
            QWidget { background: rgba(18,20,24,0.92); }
            QLabel { color: #c3c8cf; background: transparent; }
            QPushButton {
                color: #e8ebef; background: #1f6feb; border: none;
                padding: 7px; border-radius: 4px;
            }
            QPushButton:hover { background: #2f7ff6; }
            QSlider::groove:horizontal { height: 4px; background: #3a3f47; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 12px; margin: -5px 0; border-radius: 6px; background: #c3c8cf;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(8)
        self._content_layout = layout

        self.status_label = QLabel()
        self.dim_label = QLabel()
        self.blur_label = QLabel()
        for lab in (self.status_label, self.dim_label, self.blur_label):
            lab.setFont(QFont("Microsoft YaHei", 10))
            layout.addWidget(lab)

        layout.addSpacing(6)
        self.max_dim_label = QLabel()
        self.max_dim_label.setFont(QFont("Microsoft YaHei", 9))
        layout.addWidget(self.max_dim_label)
        self.max_dim_slider = QSlider(Qt.Horizontal)
        self.max_dim_slider.setRange(0, 85)
        layout.addWidget(self.max_dim_slider)

        self.blur_scale_label = QLabel()
        self.blur_scale_label.setFont(QFont("Microsoft YaHei", 9))
        layout.addWidget(self.blur_scale_label)
        self.blur_scale_slider = QSlider(Qt.Horizontal)
        self.blur_scale_slider.setRange(0, 100)
        layout.addWidget(self.blur_scale_slider)

        layout.addSpacing(8)
        self.max_effect_button = QPushButton("立即测试最深效果")
        layout.addWidget(self.max_effect_button)

        layout.addStretch(1)

    def add_control_row(self, widget: QWidget) -> None:
        """扩展点：未来要加控制项时调用，自动插在测试按钮之前。"""
        self._content_layout.insertWidget(self._content_layout.count() - 2, widget)


# ============================================================
# 控制台主窗口
# ============================================================
class PostureConsoleWindow(QWidget):
    def __init__(self, monitor) -> None:
        super().__init__()
        self.monitor = monitor
        self.ctrl = _ControlState()
        self.registry = _build_registry(self.ctrl)
        self._registry_by_id = {spec.id: spec for spec in self.registry}

        self.setWindowTitle("EchoPosture")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.resize(620, 470)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scene = ConsoleScene()
        self.view = ArtView(self.scene)
        root.addWidget(self.view, 1)

        self.side = SidePanel(self)
        root.addWidget(self.side, 0)

        self._build_scene()
        self._wire_side_panel()

        # 250ms 刷新：从 monitor 拉状态，同步眼睛/椎骨/读出/侧栏
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(250)

        self._run_entrance()
        self.refresh()

    # ---- 构建场景 ----
    def _build_scene(self) -> None:
        renderer = QSvgRenderer(QByteArray(_BLUEPRINT_SVG.encode("utf-8")), self)
        self.blueprint = QGraphicsSvgItem()
        self.blueprint.setSharedRenderer(renderer)
        self.blueprint.setPos(0, 0)
        self.blueprint.setOpacity(0.0)
        self.scene.addItem(self.blueprint)

        # 文字标签 OCULI / VERTEBRA + 引线
        self._add_label_text("OCULI", 300, 340, 16, SILVER_HI, 13.0, Qt.AlignRight)
        self._add_tick_line(452, 332, 612, 332)
        vert_letters = list("VERTEBRA")
        for i, ch in enumerate(vert_letters):
            self._add_label_text(ch, 360, 560 + i * 70, 16, SILVER_HI, 0.0, Qt.AlignLeft)

        self.eye = EyeItem()
        self.eye.setPos(726, 332)
        self.eye.clicked.connect(self._on_eye_toggle)
        self.scene.addItem(self.eye)

        self.vertebrae: List[VertebraItem] = []
        for spec in self.registry:
            item = VertebraItem(spec)
            item.clicked.connect(self._on_vertebra_clicked)
            self.scene.addItem(item)
            self.vertebrae.append(item)

    def _add_label_text(self, text, x, y, pt, color, spacing, align) -> None:
        from PyQt5.QtWidgets import QGraphicsTextItem
        item = QGraphicsTextItem(text)
        font = QFont("Helvetica Neue", pt)
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
        font.setWeight(QFont.Light)
        item.setFont(font)
        item.setDefaultTextColor(color)
        item.setOpacity(0.0)
        br = item.boundingRect()
        if align == Qt.AlignRight:
            item.setPos(x - br.width(), y - br.height() / 2)
        else:
            item.setPos(x, y - br.height() / 2)
        self.scene.addItem(item)
        if not hasattr(self, "_label_items"):
            self._label_items = []
        self._label_items.append(item)

    def _add_tick_line(self, x1, y1, x2, y2) -> None:
        from PyQt5.QtWidgets import QGraphicsLineItem
        line = QGraphicsLineItem(x1, y1, x2, y2)
        pen = QPen(LINE, 0.75)
        pen.setColor(QColor(216, 221, 227, int(0.35 * 255)))
        line.setPen(pen)
        line.setOpacity(0.0)
        self.scene.addItem(line)
        if not hasattr(self, "_label_items"):
            self._label_items = []
        self._label_items.append(line)

    def _wire_side_panel(self) -> None:
        overlay = self.monitor.overlay
        self.side.max_dim_slider.setValue(round(overlay.max_dim_alpha * 100))
        self.side.blur_scale_slider.setValue(round(overlay.blur_scale * 100))
        self.side.max_dim_slider.valueChanged.connect(self._on_slider_changed)
        self.side.blur_scale_slider.valueChanged.connect(self._on_slider_changed)
        self.side.max_effect_button.clicked.connect(self.monitor.trigger_max_visual_effect)

    # ---- 入场动画 ----
    def _run_entrance(self) -> None:
        self._anim_keep = []  # 防止动画被回收

        # 用 QVariantAnimation 驱动 setOpacity：对任意 QGraphicsItem 都适用
        # （QGraphicsLineItem 不是 QObject，不能用 QPropertyAnimation 直接驱动）。
        def fade(item, delay, dur=900, target=1.0):
            anim = QVariantAnimation(self)
            anim.setStartValue(0.0)
            anim.setEndValue(float(target))
            anim.setDuration(dur)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(lambda value, it=item: it.setOpacity(float(value)))
            QTimer.singleShot(delay, anim.start)
            self._anim_keep.append(anim)

        fade(self.blueprint, 0, 1200, 0.9)
        for item in getattr(self, "_label_items", []):
            fade(item, 600, 1000, 1.0)
        fade(self.eye, 500, 1000, 1.0)
        # 椎骨错峰入场（淡入；可见性由 refresh 的 enabled 控制）
        for i, item in enumerate(self.vertebrae):
            fade(item, 800 + i * 120, 900, 1.0)

    # ---- 眼睛 = 监测总开关 ----
    def _on_eye_toggle(self) -> None:
        if self.monitor.is_monitoring():
            self.monitor.pause_monitoring()
        else:
            self.monitor.resume_monitoring()
        self.refresh()

    # ---- 椎骨点击统一入口 ----
    def _on_vertebra_clicked(self, feature_id: str) -> None:
        if not self.monitor.is_monitoring():
            self.eye.pulse()
            return
        spec = self._registry_by_id[feature_id]
        item = self._item_for(feature_id)

        if not spec.enabled:
            item.do_flash()
            self._note(f"{spec.name} {spec.cn}：扩展占位，暂不可单独切换")
            return

        if spec.kind == "action":
            if spec.invoke is not None:
                spec.invoke(self.monitor)
            item.do_flash()
        elif spec.kind == "toggle":
            new_state = not self._is_active(spec)
            if spec.apply is not None:
                spec.apply(self.monitor, new_state)
            item.set_active(new_state)
            item.do_flash()
        self.refresh()

    def _on_slider_changed(self) -> None:
        max_dim = self.side.max_dim_slider.value() / 100.0
        blur = self.side.blur_scale_slider.value() / 100.0
        self.monitor.overlay.set_visual_config(max_dim, blur)
        # 记住非零值，便于 DIMMING/BLUR 椎骨重新开启时恢复
        if max_dim > 0:
            self.ctrl.saved_max_dim = max_dim
        if blur > 0:
            self.ctrl.saved_blur = blur
        self.refresh()

    # ---- helpers ----
    def _item_for(self, feature_id: str) -> VertebraItem:
        for item in self.vertebrae:
            if item.spec.id == feature_id:
                return item
        raise KeyError(feature_id)

    def _is_active(self, spec: FeatureSpec) -> bool:
        if spec.is_active is None:
            return False
        try:
            return bool(spec.is_active(self.monitor))
        except Exception:
            return False

    def _note(self, text: str) -> None:
        self.view.readout_state.setText(text)

    # ---- 250ms 刷新：单向从后端同步到 UI ----
    def refresh(self) -> None:
        monitoring = self.monitor.is_monitoring()

        # 眼睛睁闭跟随监测状态
        target_open = 1.0 if monitoring else 0.0
        if abs(self.eye.eyeOpen - target_open) > 0.01:
            self.eye.set_open(monitoring)

        # 椎骨：可点性 + 点亮态
        active_count = 0
        for item in self.vertebrae:
            item.set_enabled_visual(monitoring)
            if monitoring and item.spec.kind == "toggle":
                active = self._is_active(item.spec)
                if active:
                    active_count += 1
                if (item.on > 0.5) != active:
                    item.set_active(active)
            elif not monitoring and item.on > 0.5:
                item.set_active(False)

        # 侧栏读出
        decision = self.monitor.last_decision
        status = decision.status if decision is not None else "WAITING"
        overlay = self.monitor.overlay
        dim = round(overlay.dim_level * 100)
        blur = round(overlay.blur_level * 100)
        self.side.status_label.setText(f"当前状态：{status}")
        self.side.dim_label.setText(f"压暗程度：{dim}%")
        self.side.blur_label.setText(f"模糊程度：{blur}%")
        self.side.max_dim_label.setText(f"最深压暗：{self.side.max_dim_slider.value()}%")
        self.side.blur_scale_label.setText(f"模糊强度：{self.side.blur_scale_slider.value()}%")

        # 左下读出
        if monitoring:
            if active_count > 0:
                self.view.readout_state.setText(f"监测中 · {active_count} 项功能已启用")
            else:
                self.view.readout_state.setText("监测中 · 等待启用功能")
        else:
            self.view.readout_state.setText("监测已暂停 · STANDBY")
        self.view._place_overlays()

    def closeEvent(self, event) -> None:
        self.refresh_timer.stop()
        super().closeEvent(event)
