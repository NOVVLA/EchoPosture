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
    QParallelAnimationGroup,
    QPoint,
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
    QPixmap,
    QRadialGradient,
)
from PyQt5.QtSvg import QGraphicsSvgItem, QSvgRenderer
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsItem,
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
UI_SCALE = 1.17
WINDOW_W = round(880 * UI_SCALE)
WINDOW_H = round(600 * UI_SCALE)


def _scaled(value: float) -> int:
    return round(value * UI_SCALE)

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
# 眼睛（纯装饰，始终闭眼，不可点击）
# 与 ui/onboarding.html 的主 UI 状态一致：监测启停由右下角弹窗/托盘
# 浮窗的滑条开关负责，这里只保留温和的闭眼形象与脉冲提示。
# ============================================================
class EyeItem(QGraphicsObject):
    def __init__(self) -> None:
        super().__init__()
        self._eye_open = 0.0    # 常闭：保留属性但不再有任何路径把它抬起
        self._pulse = 0.0       # 红色提示脉冲 0..1（手绘，不用 graphics effect）
        self.setOpacity(0.0)  # 入场前隐藏
        self._pulse_anim: Optional[QPropertyAnimation] = None
        # 不接受鼠标与悬停：装饰元素，点击穿透
        self.setAcceptedMouseButtons(Qt.NoButton)

    # ---- 动画属性：睁眼程度 0(闭)..1(睁) ----
    def _get_eye_open(self) -> float:
        return self._eye_open

    def _set_eye_open(self, value: float) -> None:
        self._eye_open = value
        self.update()

    eyeOpen = pyqtProperty(float, _get_eye_open, _set_eye_open)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = value
        self.update()

    pulseGlow = pyqtProperty(float, _get_pulse, _set_pulse)

    def boundingRect(self) -> QRectF:
        return QRectF(-78, -78, 156, 156)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addEllipse(QRectF(-50, -34, 100, 68))
        return path

    def pulse(self) -> None:
        """监测未开启时点击椎骨的柔性提示：眼睛红色脉冲一下（手绘光环）。"""
        anim = QPropertyAnimation(self, b"pulseGlow", self)
        anim.setDuration(700)
        anim.setStartValue(0.0)
        anim.setKeyValueAt(0.5, 1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)
        self._pulse_anim = anim

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        t = self._eye_open

        # 红色提示脉冲（手绘外光环，替代原 drop-shadow）
        if self._pulse > 0.001:
            pr = 50 + 18 * self._pulse
            pg = QRadialGradient(QPointF(0, 0), pr)
            a = int(200 * self._pulse)
            pg.setColorAt(0.55, QColor(255, 47, 67, 0))
            pg.setColorAt(0.85, QColor(255, 47, 67, a))
            pg.setColorAt(1.0, QColor(255, 47, 67, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(pg))
            painter.drawEllipse(QPointF(0, 0), pr, pr)

        # 柔光 halo（睁眼淡入、放大；常闭状态下不会触发）
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

        self._glow = 0.0        # 红色辉光呼吸 0..1（手绘，不用 graphics effect）
        self._breathe: Optional[QPropertyAnimation] = None

        verb = {"toggle": "点击切换", "action": "点击触发"}.get(spec.kind, "即将开放")
        self.setToolTip(f"{spec.cn}（{spec.name}） — {verb}")

    # ---- 动画属性 ----
    def _get_on(self) -> float:
        return self._on

    def _set_on(self, value: float) -> None:
        self._on = value
        self.update()

    on = pyqtProperty(float, _get_on, _set_on)

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = value
        self.update()

    glow = pyqtProperty(float, _get_glow, _set_glow)

    def _get_flash(self) -> float:
        return self._flash

    def _set_flash(self, value: float) -> None:
        self._flash = value
        self.update()

    flash = pyqtProperty(float, _get_flash, _set_flash)

    def boundingRect(self) -> QRectF:
        # 含左侧引线/标签 + 点击柔光环 + 呼吸辉光
        return QRectF(-360, -95, 440, 190)

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
        self._update_glow(active and self._enabled_visual)

    def set_enabled_visual(self, enabled: bool) -> None:
        """眼睛闭合时椎骨变灰不可点（仅视觉，不改后端开关值）。"""
        if enabled == self._enabled_visual:
            return  # 脏检查：状态没变就不重绘
        self._enabled_visual = enabled
        self.setOpacity(1.0 if enabled else 0.32)
        if not enabled:
            self._update_glow(False)
        elif self._on > 0.5:
            self._update_glow(True)
        self.update()

    def do_flash(self) -> None:
        anim = QPropertyAnimation(self, b"flash", self)
        anim.setDuration(700)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QPropertyAnimation.DeleteWhenStopped)

    def _update_glow(self, active: bool) -> None:
        """on 时启动手绘红色辉光呼吸（仅 self.update()，无 graphics effect）。"""
        if self._breathe is not None:
            self._breathe.stop()
            self._breathe = None
        if active:
            anim = QPropertyAnimation(self, b"glow", self)
            anim.setDuration(3200)
            anim.setStartValue(0.35)
            anim.setKeyValueAt(0.5, 1.0)
            anim.setEndValue(0.35)
            anim.setLoopCount(-1)
            anim.start()
            self._breathe = anim
        else:
            self._set_glow(0.0)

    def hoverEnterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:
        self._hover = False
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
        on = self._on

        # 红色呼吸辉光（手绘，替代 drop-shadow）——画在本体下方
        if on > 0.01 and self._glow > 0.01:
            gr = 54 + 16 * self._glow
            a = int(130 * self._glow * on)
            gg = QRadialGradient(QPointF(0, 0), gr)
            gg.setColorAt(0.45, QColor(255, 47, 67, 0))
            gg.setColorAt(0.78, QColor(255, 47, 67, a))
            gg.setColorAt(1.0, QColor(255, 47, 67, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(gg))
            painter.drawEllipse(QPointF(0, 0), gr, gr)
        # hover 白色微光（仅未点亮时）
        elif self._hover and on < 0.5:
            hr = 50
            hg = QRadialGradient(QPointF(0, 0), hr)
            hg.setColorAt(0.5, QColor(255, 255, 255, 0))
            hg.setColorAt(0.82, QColor(255, 255, 255, 55))
            hg.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(hg))
            painter.drawEllipse(QPointF(0, 0), hr, hr)

        # 点击柔光环（半径已收敛到 boundingRect 内）
        if self._flash < 0.999:
            t = self._flash
            r = 46 * (0.5 + 1.7 * t)
            opacity = 0.8 * (1.0 - t)
            grad = QRadialGradient(QPointF(0, 0), r)
            grad.setColorAt(0.0, QColor(255, 120, 135, int(0.9 * 255 * opacity)))
            grad.setColorAt(1.0, QColor(255, 47, 67, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(0, 0), r, r)

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

        self._paint_label(painter, on)

    def _paint_label(self, painter: QPainter, on: float) -> None:
        """常驻引线 + 中文功能名（主）+ 英文（副）。hover/点亮时提亮。"""
        placeholder = not self.spec.enabled
        # 基础低调，hover/点亮提亮
        if on > 0.01:
            base_alpha = 1.0
            text_color = QColor(RED_SOFT)
        elif self._hover:
            base_alpha = 1.0
            text_color = QColor(SILVER_HI)
        else:
            base_alpha = 0.4 if placeholder else 0.62
            text_color = QColor(SILVER_LO)

        line_color = QColor(text_color)
        line_color.setAlphaF(base_alpha * 0.7)
        pen = QPen(line_color, 0.75)
        pen.setDashPattern([1, 5])
        painter.setPen(pen)
        painter.drawLine(QPointF(-78, 0), QPointF(-150, 0))

        # 中文主名
        cn_color = QColor(text_color)
        cn_color.setAlphaF(base_alpha)
        cn = self.spec.cn + ("（即将开放）" if placeholder else "")
        cn_font = QFont("Microsoft YaHei", 10)
        cn_font.setWeight(QFont.Normal)
        painter.setFont(cn_font)
        painter.setPen(cn_color)
        painter.drawText(QRectF(-360, -16, 200, 16),
                         int(Qt.AlignRight | Qt.AlignVCenter), cn)

        # 英文副名（更小更暗）
        en_color = QColor(text_color)
        en_color.setAlphaF(base_alpha * 0.72)
        en_font = QFont("Helvetica Neue", 7)
        en_font.setLetterSpacing(QFont.AbsoluteSpacing, 2.0)
        en_font.setWeight(QFont.Light)
        painter.setFont(en_font)
        painter.setPen(en_color)
        painter.drawText(QRectF(-360, 1, 200, 14),
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
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setFrameShape(QGraphicsView.NoFrame)
        self.setStyleSheet("background:#0c0d0f;")
        # 性能：只重绘变化 item 的包围盒（脏区最小化）
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        # 动画期间跳过冗余的 painter 状态保存/抗锯齿边距调整，降低每帧开销
        self.setOptimizationFlag(QGraphicsView.DontSavePainterState, True)
        self.setOptimizationFlag(QGraphicsView.DontAdjustForAntialiasing, True)

        self._bg_pixmap: Optional[QPixmap] = None
        self.drag_bar: Optional["DragBar"] = None
        self.side_panel: Optional["SidePanel"] = None

        # 左下状态读出 + 右下提示（叠加在视图上，保持清晰、不随场景缩放）
        self.readout_title = self._mk_label("SYSTEM", 8, SILVER_LO, 4.2)
        self.readout_state = self._mk_label("监测已暂停 · STANDBY", 11, SILVER_LO, 2.2)
        self.readout_mods = self._mk_label("", 8, SILVER_LO, 1.0)
        self.readout_mods.setTextFormat(Qt.RichText)
        self.readout_mods.setWordWrap(False)
        self.hint = self._mk_label("监测开关在托盘浮窗 · 点击椎骨切换功能", 8, SILVER_LO, 2.6)
        self.hint.setAlignment(Qt.AlignRight)

    def _mk_label(self, text: str, pt: int, color: QColor, spacing: float) -> QLabel:
        # 浮层挂在 viewport 上，确保始终显示在场景渲染之上
        lab = QLabel(text, self.viewport())
        font = QFont("Helvetica Neue", _scaled(pt))
        font.setLetterSpacing(QFont.AbsoluteSpacing, spacing * UI_SCALE)
        font.setWeight(QFont.Light)
        lab.setFont(font)
        lab.setStyleSheet(f"color:{color.name()}; background:transparent;")
        lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        return lab

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._render_background()
        self._place_overlays()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self.scene() is not None:
            self.fitInView(self.scene().sceneRect(), Qt.KeepAspectRatio)
        self._render_background()
        self._place_overlays()

    def attach_overlays(self, drag_bar: "DragBar", side_panel: "SidePanel") -> None:
        self.drag_bar = drag_bar
        self.side_panel = side_panel
        self._place_overlays()

    def _place_overlays(self) -> None:
        vp = self.viewport().rect()
        w, h = vp.width(), vp.height()

        # 顶部拖动条（全宽，透明）
        if self.drag_bar is not None:
            self.drag_bar.setGeometry(0, 0, w, _scaled(32))

        # 右侧控制栏浮层（垂直居中，贴右）
        side_left = w
        if self.side_panel is not None:
            sw = self.side_panel.width()
            sh = self.side_panel.sizeHint().height()
            margin = _scaled(18)
            x = w - sw - margin
            y = max(_scaled(44), (h - sh) // 2)
            self.side_panel.setGeometry(x, y, sw, sh)
            side_left = x

        # 左下状态读出
        self.readout_title.adjustSize()
        self.readout_state.adjustSize()
        self.readout_mods.adjustSize()
        self.readout_title.move(_scaled(20), h - _scaled(20) - _scaled(18) - _scaled(8) - self.readout_mods.height()
                                - self.readout_state.height() - self.readout_title.height())
        self.readout_state.move(_scaled(20), self.readout_title.y() + self.readout_title.height() + _scaled(6))
        self.readout_mods.move(_scaled(20), self.readout_state.y() + self.readout_state.height() + _scaled(8))

        # 右下提示（避让右侧控制栏）
        self.hint.adjustSize()
        self.hint.move(side_left - self.hint.width() - _scaled(20), h - self.hint.height() - _scaled(14))

    def _render_background(self) -> None:
        """把“深邃亮光银”径向渐变 + 暗角预渲染成一张 pixmap，仅尺寸变化时重建。"""
        vp = self.viewport().rect()
        w, h = vp.width(), vp.height()
        if w <= 0 or h <= 0:
            return
        pm = QPixmap(w, h)
        p = QPainter(pm)
        radius = 1.3 * max(w, h)
        grad = QRadialGradient(QPointF(0.32 * w, 0.18 * h), radius)
        grad.setColorAt(0.0, QColor("#4a4f56"))
        grad.setColorAt(0.28, QColor("#30343a"))
        grad.setColorAt(0.60, QColor("#1c1f23"))
        grad.setColorAt(0.86, QColor("#101113"))
        grad.setColorAt(1.0, QColor("#08090a"))
        p.fillRect(vp, QBrush(grad))
        vig = QRadialGradient(QPointF(0.5 * w, 0.45 * h), 0.72 * max(w, h))
        vig.setColorAt(0.0, QColor(0, 0, 0, 0))
        vig.setColorAt(0.72, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 140))
        p.fillRect(vp, QBrush(vig))
        p.end()
        self._bg_pixmap = pm

    def drawBackground(self, painter: QPainter, rect) -> None:
        # 只做一次 blit（缓存的 pixmap），不再每帧重算渐变
        if self._bg_pixmap is None:
            self._render_background()
        painter.save()
        painter.resetTransform()
        if self._bg_pixmap is not None:
            painter.drawPixmap(0, 0, self._bg_pixmap)
        painter.restore()


# ============================================================
# 顶部拖动条（无边框窗口的自定义标题栏）
# ============================================================
class DragBar(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent;")
        self._drag_offset = None

        self.title = QLabel("ECHOPOSTURE", self)
        f = QFont("Helvetica Neue", _scaled(8))
        f.setLetterSpacing(QFont.AbsoluteSpacing, 4.0 * UI_SCALE)
        f.setWeight(QFont.Light)
        self.title.setFont(f)
        self.title.setStyleSheet("color:#7d838c; background:transparent;")

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setFixedSize(_scaled(26), _scaled(24))
        self.close_btn.setStyleSheet(
            f"QPushButton{{color:#7d838c; background:transparent; border:none; font-size:{_scaled(14)}px;}}"
            "QPushButton:hover{color:#ff3145;}"
        )
        self.close_btn.clicked.connect(lambda: self.window().hide())

    def resizeEvent(self, event) -> None:
        self.title.adjustSize()
        self.title.move(_scaled(22), (self.height() - self.title.height()) // 2)
        self.close_btn.move(self.width() - self.close_btn.width() - _scaled(12),
                            (self.height() - self.close_btn.height()) // 2)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPos() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and (event.buttons() & Qt.LeftButton):
            self.window().move(event.globalPos() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        event.accept()


# ============================================================
# 侧边栏（迁移自旧 StatusPanel）
# ============================================================
class SidePanel(QWidget):
    def __init__(self, window: "PostureConsoleWindow", parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.window_ref = window
        # 磨砂玻璃浮层，叠在主体右侧的渐变背景之上，与艺术区同一主题
        self.setObjectName("sideCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(_scaled(204))
        self.setStyleSheet(
            """
            #sideCard {
                background: rgba(255,255,255,0.045);
                border: 1px solid rgba(255,255,255,0.09);
                border-radius: 12px;
            }
            QLabel { color: #c3c8cf; background: transparent; border: none; }
            QLabel#sideTitle { color: #7d838c; }
            QPushButton {
                color: #ff6473; background: transparent;
                border: 1px solid rgba(255,100,115,0.55);
                padding: 7px; border-radius: 6px;
            }
            QPushButton:hover { background: rgba(255,47,67,0.18); color: #ffffff; }
            QSlider::groove:horizontal { height: 4px; background: transparent; }
            QSlider::sub-page:horizontal { height: 4px; background: #ff3145; border-radius: 2px; }
            QSlider::add-page:horizontal { height: 4px; background: #3a3f47; border-radius: 2px; }
            QSlider::handle:horizontal {
                width: 12px; margin: -5px 0; border-radius: 6px; background: #e8ebef;
            }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(_scaled(18), _scaled(16), _scaled(18), _scaled(16))
        layout.setSpacing(_scaled(8))
        self._content_layout = layout

        self.title_label = QLabel("CONTROL · 调节")
        self.title_label.setObjectName("sideTitle")
        title_font = QFont("Helvetica Neue", _scaled(8))
        title_font.setLetterSpacing(QFont.AbsoluteSpacing, 3.0 * UI_SCALE)
        title_font.setWeight(QFont.Light)
        self.title_label.setFont(title_font)
        layout.addWidget(self.title_label)
        layout.addSpacing(_scaled(4))

        self.status_label = QLabel()
        self.dim_label = QLabel()
        self.blur_label = QLabel()
        for lab in (self.status_label, self.dim_label, self.blur_label):
            lab.setFont(QFont("Microsoft YaHei", _scaled(10)))
            layout.addWidget(lab)

        layout.addSpacing(_scaled(6))
        self.max_dim_label = QLabel()
        self.max_dim_label.setFont(QFont("Microsoft YaHei", _scaled(9)))
        layout.addWidget(self.max_dim_label)
        self.max_dim_slider = QSlider(Qt.Horizontal)
        self.max_dim_slider.setRange(0, 85)
        self.max_dim_slider.setMinimumHeight(_scaled(22))
        layout.addWidget(self.max_dim_slider)

        self.blur_scale_label = QLabel()
        self.blur_scale_label.setFont(QFont("Microsoft YaHei", _scaled(9)))
        layout.addWidget(self.blur_scale_label)
        self.blur_scale_slider = QSlider(Qt.Horizontal)
        self.blur_scale_slider.setRange(0, 100)
        self.blur_scale_slider.setMinimumHeight(_scaled(22))
        layout.addWidget(self.blur_scale_slider)

        layout.addSpacing(_scaled(8))
        self.max_effect_button = QPushButton("立即测试最深效果")
        self.max_effect_button.setFont(QFont("Microsoft YaHei", _scaled(9)))
        self.max_effect_button.setMinimumHeight(_scaled(32))
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
        # 脏检查缓存：仅在文本变化时才 setText + 重新定位叠加层
        self._last_state_text: Optional[str] = None
        self._last_mods_html: Optional[str] = None

        self.setWindowTitle("EchoPosture")
        self.setWindowFlags(
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        # 占屏幕的黄金分割（按可用高度的 0.618 取高，保持 880:600 比例）并居中
        self._entrance_group: Optional[QParallelAnimationGroup] = None
        w, h = self._golden_size()
        self.resize(w, h)
        self._center_on_screen()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scene = ConsoleScene()
        self.view = ArtView(self.scene)
        root.addWidget(self.view, 1)  # 艺术区充满整窗

        # 控制栏与拖动条作为视图浮层（挂在 viewport 上），坐在同一渐变背景之上
        self.drag_bar = DragBar(self.view.viewport())
        self.side = SidePanel(self, parent=self.view.viewport())

        self._build_scene()
        self._wire_side_panel()
        self.view.attach_overlays(self.drag_bar, self.side)

        # 250ms 刷新：从 monitor 拉状态，同步眼睛/椎骨/读出/侧栏
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(250)

        self._run_entrance()
        self.refresh()

    # ---- 窗口几何：黄金分割 + 居中 ----
    def _golden_size(self) -> tuple:
        screen = QApplication.primaryScreen()
        if screen is None:
            return WINDOW_W, WINDOW_H
        avail = screen.availableGeometry()
        h = round(avail.height() * 0.618)
        w = round(h * WINDOW_W / WINDOW_H)
        if w > avail.width() * 0.618:
            w = round(avail.width() * 0.618)
            h = round(w * WINDOW_H / WINDOW_W)
        return w, h

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        self.move(
            avail.x() + (avail.width() - self.width()) // 2,
            avail.y() + (avail.height() - self.height()) // 2,
        )

    # ---- 显示/隐藏：隐藏即休眠（停刷新与呼吸动画，省 CPU），显示时恢复 ----
    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.refresh_timer.isActive():
            self.refresh_timer.start(250)
        self.refresh()
        for item in self.vertebrae:
            if item.on > 0.5 and item.spec.enabled:
                item._update_glow(True)
        self._play_window_entrance()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.refresh_timer.stop()
        for item in self.vertebrae:
            item._update_glow(False)

    def _play_window_entrance(self) -> None:
        if (self._entrance_group is not None
                and self._entrance_group.state() == QParallelAnimationGroup.Running):
            return
        end_pos = self.pos()
        self.setWindowOpacity(0.0)
        self.move(end_pos + QPoint(0, 14))

        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(420)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        rise = QPropertyAnimation(self, b"pos")
        rise.setDuration(420)
        rise.setStartValue(end_pos + QPoint(0, 14))
        rise.setEndValue(end_pos)
        rise.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(rise)
        group.start()
        self._entrance_group = group

    # ---- 构建场景 ----
    def _build_scene(self) -> None:
        renderer = QSvgRenderer(QByteArray(_BLUEPRINT_SVG.encode("utf-8")), self)
        self.blueprint = QGraphicsSvgItem()
        self.blueprint.setSharedRenderer(renderer)
        self.blueprint.setPos(0, 0)
        self.blueprint.setOpacity(0.0)
        self.blueprint.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.scene.addItem(self.blueprint)

        # 文字标签 OCULI / VERTEBRA + 引线
        self._add_label_text("OCULI", 300, 340, 16, SILVER_HI, 13.0, Qt.AlignRight)
        self._add_tick_line(452, 332, 612, 332)
        vert_letters = list("VERTEBRA")
        for i, ch in enumerate(vert_letters):
            self._add_label_text(ch, 360, 560 + i * 70, 16, SILVER_HI, 0.0, Qt.AlignLeft)

        self.eye = EyeItem()
        self.eye.setPos(726, 332)
        self.scene.addItem(self.eye)
        # 眼下融入的微型项目名（取自 onboarding.html 的 #eyeword）
        self._add_label_text("ECHOPOSTURE", 726, 400, 7, SILVER_LO, 4.4,
                             Qt.AlignHCenter)

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
        item.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        br = item.boundingRect()
        if align == Qt.AlignRight:
            item.setPos(x - br.width(), y - br.height() / 2)
        elif align == Qt.AlignHCenter:
            item.setPos(x - br.width() / 2, y - br.height() / 2)
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
        line.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
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
        self._set_state_text(text)

    def _set_state_text(self, text: str) -> None:
        if text == self._last_state_text:
            return
        self._last_state_text = text
        self.view.readout_state.setText(text)
        self.view._place_overlays()

    def _build_mods_html(self, monitoring: bool) -> str:
        """左下功能清单：● 红=已启用 / ○ 灰=未启用 / 占位灰显。"""
        rows = []
        for spec in self.registry:
            active = monitoring and spec.kind == "toggle" and self._is_active(spec)
            if active:
                marker, color = "●", RED_SOFT.name()
                name_color = RED_SOFT.name()
            elif not spec.enabled:
                marker, color = "○", "#5a5f66"
                name_color = "#5a5f66"
            else:
                marker, color = "○", SILVER_LO.name()
                name_color = SILVER.name() if monitoring else SILVER_LO.name()
            suffix = " <span style='color:#5a5f66'>· 即将开放</span>" if not spec.enabled else ""
            rows.append(
                f"<span style='color:{color}'>{marker}</span> "
                f"<span style='color:{name_color}'>{spec.cn}</span>{suffix}"
            )
        return "<br>".join(rows)

    # ---- 250ms 刷新：单向从后端同步到 UI（带脏检查） ----
    def refresh(self) -> None:
        monitoring = self.monitor.is_monitoring()

        # 眼睛是纯装饰（常闭），监测启停由托盘浮窗的滑条开关负责

        # 椎骨：可点性 + 点亮态（set_enabled_visual / set_active 内部均有脏守卫）
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

        # 侧栏读出（QLabel.setText 对相同文本会自动 no-op）
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

        # 左下状态行（仅变化时更新）
        if monitoring:
            state_text = (f"监测中 · {active_count} 项功能已启用"
                          if active_count > 0 else "监测中 · 等待启用功能")
        else:
            state_text = "监测已暂停 · STANDBY"
        self._set_state_text(state_text)

        # 左下功能清单（仅变化时更新）
        mods_html = self._build_mods_html(monitoring)
        if mods_html != self._last_mods_html:
            self._last_mods_html = mods_html
            self.view.readout_mods.setText(mods_html)
            self.view._place_overlays()

    def closeEvent(self, event) -> None:
        self.refresh_timer.stop()
        super().closeEvent(event)
