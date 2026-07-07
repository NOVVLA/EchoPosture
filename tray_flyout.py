"""
EchoPosture 托盘配置浮窗。

右键托盘图标时弹出，替代旧的简陋 QMenu。与开场弹窗（onboarding_toast）
同一视觉语言：深色玻璃卡片 + logo 蓝图衬底 + 右下角定位 + 上浮淡入。

结构自上而下：
- 左上角灰色小齿轮：打开主配置 UI（控制台窗口）。
- 监测开关行：与开场弹窗同款的眼睛滑条开关（双向），点一下暂停/恢复监测。
- 四个操作按钮：立即重新校准 / 立即测试最深效果 / 语言切换 / 退出本程序（标红）。

Qt.Popup 窗口：点击浮窗以外的区域自动关闭。
"""

from __future__ import annotations

from typing import List

from PyQt5.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PyQt5.QtGui import QFont, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from onboarding_toast import (
    RED_SOFT,
    SILVER_LO,
    EyeSlideSwitch,
    _font,
    render_glass_card,
)
from i18n import _t, add_listener, remove_listener, cycle_language, lang_button_text

FLYOUT_W = 300
FLYOUT_MARGIN = 12


class TrayFlyout(QWidget):
    def __init__(self, monitor) -> None:
        super().__init__()
        self.monitor = monitor
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedWidth(FLYOUT_W)

        self._card: QPixmap | None = None
        self._final_pos = QPoint(0, 0)
        self._anims: List = []

        self.setStyleSheet(
            """
            QPushButton {
                color: #c3c8cf; background: rgba(255,255,255,0.04);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 8px; padding: 8px 10px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.10); color: #ffffff; }
            QPushButton#exitBtn { color: #ff6473; border-color: rgba(255,100,115,0.55); }
            QPushButton#exitBtn:hover { background: rgba(255,47,67,0.18); color: #ffffff; }
            QPushButton#gearBtn {
                color: #7d838c; background: transparent; border: none; padding: 0;
            }
            QPushButton#gearBtn:hover { color: #eef1f4; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 46, 20, 18)
        layout.setSpacing(10)

        # 监测开关行（与开场弹窗同款滑条，双向）
        row = QHBoxLayout()
        self.state_label = QLabel()
        self.state_label.setFont(_font("Microsoft YaHei", 10, 3.0))
        row.addWidget(self.state_label)
        row.addStretch(1)
        self.switch = EyeSlideSwitch(self, one_shot=False)
        self.switch.toggled.connect(self._on_switch_toggled)
        row.addWidget(self.switch)
        layout.addLayout(row)
        layout.addSpacing(2)

        btn_font = _font("Microsoft YaHei", 12, 1.0, QFont.Normal)
        self.recalibrate_button = QPushButton(_t("recalibrate"))
        self.max_effect_button = QPushButton(_t("max_effect"))
        self.lang_button = QPushButton(lang_button_text())
        self.exit_button = QPushButton(_t("exit"))
        self.exit_button.setObjectName("exitBtn")
        # 语言切换按钮夹在 max_effect 与 exit 之间：同款样式，无图标，
        # 仅作文本切换，不参与监测/校准/退出等动作。
        for btn in (
            self.recalibrate_button,
            self.max_effect_button,
            self.lang_button,
            self.exit_button,
        ):
            btn.setFont(btn_font)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(34)
            layout.addWidget(btn)
        self.recalibrate_button.clicked.connect(self._on_recalibrate)
        self.max_effect_button.clicked.connect(self._on_max_effect)
        self.lang_button.clicked.connect(self._on_toggle_language)
        self.exit_button.clicked.connect(self._on_exit)

        # 监听全局语言变更：其他入口（如未来加的设置面板）切语言时，浮窗也跟着刷
        add_listener(self._apply_texts)

        # 左上角灰色小齿轮 → 打开主配置 UI
        self.gear_button = QPushButton("⚙", self)
        self.gear_button.setObjectName("gearBtn")
        gear_font = QFont("Segoe UI Symbol")
        gear_font.setPixelSize(16)
        self.gear_button.setFont(gear_font)
        self.gear_button.setFixedSize(26, 26)
        self.gear_button.setCursor(Qt.PointingHandCursor)
        self.gear_button.setToolTip(_t("gear_tooltip"))
        self.gear_button.move(12, 9)
        self.gear_button.clicked.connect(self._on_gear)

        # 齿轮右侧的小标题
        self.caption = QLabel(_t("caption"), self)
        self.caption.setFont(_font("Microsoft YaHei", 10, 4.2))
        self.caption.setStyleSheet(f"color:{SILVER_LO.name()}; background:transparent;")
        self.caption.adjustSize()
        self.caption.move(44, 9 + (26 - self.caption.height()) // 2)

        self.adjustSize()
        self.setFixedSize(self.size())

    # ---- 打开：右下角定位 + 上浮淡入 ----
    def popup_bottom_right(self) -> None:
        self._sync_state()
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.x() + screen.width() - self.width() - FLYOUT_MARGIN
        y = screen.y() + screen.height() - self.height() - FLYOUT_MARGIN
        self._final_pos = QPoint(x, y)

        self.move(x, y + 10)
        self.setWindowOpacity(0.0)
        self.show()

        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity")
        fade.setDuration(240)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.OutCubic)
        rise = QPropertyAnimation(self, b"pos")
        rise.setDuration(240)
        rise.setStartValue(self._final_pos + QPoint(0, 10))
        rise.setEndValue(self._final_pos)
        rise.setEasingCurve(QEasingCurve.OutCubic)
        group.addAnimation(fade)
        group.addAnimation(rise)
        group.start()
        self._anims = [group]

    # ---- 状态同步 ----
    def _sync_state(self) -> None:
        on = self.monitor.is_monitoring()
        self.switch.set_on(on, animate=False)
        self._update_state_label(on)

    def _update_state_label(self, on: bool) -> None:
        if on:
            self.state_label.setText(_t("state_on"))
            color = RED_SOFT.name()
        else:
            self.state_label.setText(_t("state_off"))
            color = SILVER_LO.name()
        self.state_label.setStyleSheet(f"color:{color}; background:transparent;")

    # ---- 交互 ----
    def _on_switch_toggled(self, on: bool) -> None:
        if on:
            self.monitor.resume_monitoring()
        else:
            self.monitor.pause_monitoring()
        self._update_state_label(self.monitor.is_monitoring())

    def _on_gear(self) -> None:
        self.hide()
        self.monitor.open_console()

    def _on_recalibrate(self) -> None:
        # 先让浮窗收起，再开始校准采样（采样会短暂阻塞事件循环）
        self.hide()
        QTimer.singleShot(150, self.monitor.recalibrate_now)

    def _on_max_effect(self) -> None:
        self.hide()
        self.monitor.trigger_max_visual_effect()

    def _on_exit(self) -> None:
        self.hide()
        self.monitor.stop()

    # ---- 语言切换：非侵入式，仅刷新文本，不动图标 / 不动布局 ----
    def _on_toggle_language(self) -> None:
        # 三态循环：zh → en → auto(跟随系统) → zh
        # cycle_language 内部会调 set_language，从而触发 _apply_texts（通过 i18n 监听器列表）
        cycle_language()

    def _apply_texts(self) -> None:
        """切换语言后，把所有可见文本一次性刷新到当前语言。

        - 按钮宽度跟随布局自适应，不会被新文本截断（layout 横向填满 FLYOUT_W）。
        - caption 是绝对定位的 QLabel，重新 adjustSize + 重定位，避免与齿轮重叠。
        - 不重建浮窗、不重画玻璃卡片，保持视觉与原风格完全一致。
        - lang_button 文案由 lang_button_text() 决定，反映当前模式（zh / en / 跟随系统）。
        """
        self.recalibrate_button.setText(_t("recalibrate"))
        self.max_effect_button.setText(_t("max_effect"))
        self.lang_button.setText(lang_button_text())
        self.exit_button.setText(_t("exit"))
        self.gear_button.setToolTip(_t("gear_tooltip"))
        self.caption.setText(_t("caption"))
        self.caption.adjustSize()
        # 与 __init__ 中同一公式，保证 caption 纵向居中于齿轮行不漂移
        self.caption.move(44, 9 + (26 - self.caption.height()) // 2)
        self._update_state_label(self.monitor.is_monitoring())

    # ---- 绘制：玻璃卡片预渲染，paintEvent 只 blit ----
    def paintEvent(self, event) -> None:
        if self._card is None:
            self._card = render_glass_card(
                self.width(), self.height(), self.devicePixelRatioF()
            )
        p = QPainter(self)
        p.drawPixmap(0, 0, self._card)
