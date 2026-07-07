"""
EchoPosture tray runtime.

This is the production-style entry point: no debug window, just a tray icon,
startup calibration, camera monitoring, and reversible visual intervention.
"""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QStyle,
    QSystemTrayIcon,
    QWidget,
    QVBoxLayout,
)

from gpu_blur_overlay import GpuBlurOverlayController
from i18n import _t, add_listener, remove_listener
from onboarding_toast import (
    RED_SOFT,
    SILVER_HI,
    SILVER_LO,
    OnboardingToast,
    _font,
    render_glass_card,
)
from posture_console import PostureConsoleWindow
from tray_flyout import TrayFlyout
from vision_test import (
    CameraBlackFrameError,
    CameraPermissionError,
    HighPrecisionPostureAnalyzer,
    PostureDecision,
    VisionEngine,
)
from vision_worker import (
    CalibrationResult,
    VisionWorker,
    average_calibration_sample,
    sample_is_usable,
)


class _EngineProxy:
    """posture_console 通过 monitor.engine.set/get_capture_fps 调节采集帧率；
    真正的 VisionEngine 活在工作线程内，这里只做转发，调用方零改动。"""

    def __init__(self, worker: VisionWorker) -> None:
        self._worker = worker

    def set_capture_fps(self, fps: float) -> None:
        self._worker.set_capture_fps(fps)

    def get_capture_fps(self) -> float:
        return self._worker.get_capture_fps()


class _CountdownRing(QWidget):
    """自绘倒计时圆环：底环 + 渐变进度弧 + 居中数字。

    与玻璃卡片同一银色语言；进度弧从 12 点顺时针递减，
    颜色由顶部银白渐入底部品牌红，作为校准时的视觉焦点。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(128, 128)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._remaining = 0
        self._total = 1
        self._num_font = QFont("Segoe UI", 44)
        self._num_font.setBold(True)

    def set_values(self, remaining: int, total: int) -> None:
        self._remaining = max(remaining, 0)
        self._total = max(total, 1)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        stroke = 7.0
        inset = stroke / 2.0 + 3.0
        rect = QRectF(inset, inset,
                      self.width() - 2 * inset, self.height() - 2 * inset)

        # 底环（淡白）
        p.setPen(QPen(QColor(255, 255, 255, 28), stroke,
                      Qt.SolidLine, Qt.RoundCap))
        p.setBrush(Qt.NoBrush)
        p.drawArc(rect, 0, 360 * 16)

        # 进度弧（银白 → 品牌红渐变），从 12 点顺时针递减
        frac = max(0.0, min(1.0, self._remaining / self._total))
        if frac > 0.0:
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0.0, SILVER_HI)
            grad.setColorAt(1.0, RED_SOFT)
            pen = QPen(QBrush(grad), stroke, Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, int(-frac * 360 * 16))

        # 居中数字
        p.setPen(SILVER_HI)
        p.setFont(self._num_font)
        p.drawText(self.rect(), int(Qt.AlignCenter), str(self._remaining))
        p.end()


class StartupCalibrationDialog(QDialog):
    """启动校准提示：无边框玻璃卡 + logo 衬底，与开场弹窗、托盘浮窗同一语言。

    对外仍是 seconds → step() → _refresh() 的接口，tray_app 的倒计时逻辑零改动。
    """

    DIALOG_W = 580
    DIALOG_H = 248

    PAD_X = 42                       # 左侧文字外边距
    RING_RIGHT = 30                  # 圆环右外边距
    CAP_TOP = 64                     # 小标题顶
    TITLE_TOP = 90                   # 主标题顶
    BODY_TOP = 142                   # 说明首行顶
    LINE_H = 24                      # 说明行高

    def __init__(self, seconds: int = 5) -> None:
        super().__init__()
        self.remaining_seconds = seconds
        self.total_seconds = max(seconds, 1)
        self._card: Optional[QPixmap] = None
        self._fade: Optional[QPropertyAnimation] = None
        self._shown_once = False

        self.setWindowTitle("EchoPosture")
        self.setWindowFlags(
            Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(self.DIALOG_W, self.DIALOG_H)

        # 倒计时圆环：右侧，垂直居中（动态部分作为子控件自绘，文字画进卡片）
        self.ring = _CountdownRing(self)
        ring_x = self.DIALOG_W - self.RING_RIGHT - self.ring.width()
        ring_y = (self.DIALOG_H - self.ring.height()) // 2
        self.ring.move(ring_x, ring_y)

        # 语言变更时让卡片缓存失效，下次 paintEvent 用新语言重绘
        add_listener(self._on_language_changed)

        self._refresh()
        self._center_on_screen()

    def _on_language_changed(self) -> None:
        self._card = None
        self.update()

    def _center_on_screen(self) -> None:
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._shown_once:
            return
        self._shown_once = True
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(240)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start()
        self._fade = anim

    def paintEvent(self, event) -> None:
        if self._card is None:
            self._card = self._render_card()
        p = QPainter(self)
        p.drawPixmap(0, 0, self._card)
        p.end()

    def _render_card(self) -> QPixmap:
        """玻璃卡 + logo 衬底，并把三段静态文字一次性画进 pixmap（与开场弹窗一致）。"""
        pm = render_glass_card(self.width(), self.height(), self.devicePixelRatioF())
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)

        text_w = self.ring.x() - self.PAD_X - 20  # 文字区右界，给圆环留白

        p.setFont(_font("Microsoft YaHei", 11, 4.2))
        p.setPen(SILVER_LO)
        p.drawText(QRectF(self.PAD_X, self.CAP_TOP, text_w, 16),
                   int(Qt.AlignLeft | Qt.AlignVCenter), _t("sd_caption"))

        p.setFont(_font("Microsoft YaHei", 21, 1.5, QFont.DemiBold))
        p.setPen(SILVER_HI)
        p.drawText(QRectF(self.PAD_X, self.TITLE_TOP, text_w, 32),
                   int(Qt.AlignLeft | Qt.AlignVCenter), _t("sd_title"))

        p.setFont(_font("Microsoft YaHei", 12, 0.8))
        p.setPen(SILVER_LO)
        body_lines = (_t("sd_body_1"), _t("sd_body_2"))
        for i, line in enumerate(body_lines):
            p.drawText(QRectF(self.PAD_X, self.BODY_TOP + i * self.LINE_H,
                              text_w, self.LINE_H),
                       int(Qt.AlignLeft | Qt.AlignVCenter), line)

        p.end()
        return pm

    def step(self) -> bool:
        self.remaining_seconds -= 1
        self._refresh()
        return self.remaining_seconds <= 0

    def _refresh(self) -> None:
        self.ring.set_values(max(self.remaining_seconds, 0), self.total_seconds)


class StatusPanel(QWidget):
    def __init__(self, monitor: "TrayMonitor") -> None:
        super().__init__()
        self.monitor = monitor
        self.setWindowTitle("EchoPosture")
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setFixedSize(320, 285)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.dim_label = QLabel()
        self.blur_label = QLabel()
        self.max_dim_label = QLabel()
        self.blur_scale_label = QLabel()
        for label in (
            self.status_label,
            self.dim_label,
            self.blur_label,
            self.max_dim_label,
            self.blur_scale_label,
        ):
            label.setFont(QFont("Microsoft YaHei", 11))
            layout.addWidget(label)

        self.max_dim_slider = QSlider(Qt.Horizontal)
        self.max_dim_slider.setRange(0, 85)
        self.max_dim_slider.setValue(round(self.monitor.overlay.max_dim_alpha * 100))
        self.max_dim_slider.valueChanged.connect(self._visual_config_changed)
        layout.addWidget(self.max_dim_slider)

        self.blur_scale_slider = QSlider(Qt.Horizontal)
        self.blur_scale_slider.setRange(0, 100)
        self.blur_scale_slider.setValue(round(self.monitor.overlay.blur_scale * 100))
        self.blur_scale_slider.valueChanged.connect(self._visual_config_changed)
        layout.addWidget(self.blur_scale_slider)

        self.max_effect_button = QPushButton(_t("max_effect"))
        self.max_effect_button.clicked.connect(self.monitor.trigger_max_visual_effect)
        layout.addWidget(self.max_effect_button)

        layout.addStretch(1)
        self.setStyleSheet(
            """
            QWidget { background: #f7f9fc; border: 1px solid #d8e0ea; }
            QLabel { color: #172033; border: none; }
            """
        )

        # 语言变更时刷新所有标签文本（按钮文字也跟着切）
        add_listener(self._apply_texts)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(250)
        self.refresh()

    def _apply_texts(self) -> None:
        """语言变更回调：刷新按钮文字。标签由 refresh() 自动用新模板重画。"""
        self.max_effect_button.setText(_t("max_effect"))
        self.refresh()

    def refresh(self) -> None:
        decision = self.monitor.last_decision
        status = decision.status if decision is not None else "WAITING"
        dim = round(self.monitor.overlay.dim_level * 100)
        blur = round(self.monitor.overlay.blur_level * 100)
        self.status_label.setText(_t("sp_status", status=status))
        self.dim_label.setText(_t("sp_dim", dim=dim))
        self.blur_label.setText(_t("sp_blur", blur=blur))
        self._refresh_control_labels()

    def _visual_config_changed(self) -> None:
        self.monitor.overlay.set_visual_config(
            self.max_dim_slider.value() / 100.0,
            self.blur_scale_slider.value() / 100.0,
        )
        self._refresh_control_labels()

    def _refresh_control_labels(self) -> None:
        self.max_dim_label.setText(_t("sp_max_dim", v=self.max_dim_slider.value()))
        self.blur_scale_label.setText(_t("sp_blur_scale", v=self.blur_scale_slider.value()))


class TrayMonitor:
    def __init__(
        self,
        app: QApplication,
        camera_id: int,
        width: int,
        height: int,
        fps: float,
        calibrated_distance_cm: float,
        gpu_blur_enabled: bool = True,
        mock_camera: bool = False,
    ) -> None:
        self.app = app
        self.camera_id = camera_id
        self.capture_width = width
        self.capture_height = height
        self.calibrated_distance_cm = calibrated_distance_cm
        self.mock_camera = mock_camera
        self.analyzer = HighPrecisionPostureAnalyzer(
            auto_calibrate=False,
            calibrated_distance_cm=calibrated_distance_cm,
        )
        # 摄像头 + MediaPipe + 评分全部活在 VisionWorker 工作线程；
        # 主线程只低频取信箱快照，UI 不再被推理阻塞。
        # --mock-camera 时用 MockVisionEngine 替身，跳过真实摄像头
        if mock_camera:
            from mock_vision import MockVisionEngine
            engine_factory = lambda: MockVisionEngine(
                camera_id=camera_id, width=width, height=height
            )
        else:
            engine_factory = lambda: VisionEngine(
                camera_id=camera_id, width=width, height=height
            )
        self.worker = VisionWorker(
            engine_factory=engine_factory,
            analyzer=self.analyzer,
            target_fps=fps,
        )
        self.engine = _EngineProxy(self.worker)
        self._shown_warning_keys: set[str] = set()
        self.overlay = GpuBlurOverlayController(enabled=gpu_blur_enabled)
        self.overlay.screen_capture_warning.connect(self._show_screen_capture_warning)
        self.last_decision: Optional[PostureDecision] = None
        # 进行中的校准请求：(用途 "startup"/"recal", 此前是否在监测)
        self._awaiting_calibration: Optional[tuple] = None
        self._stopping = False
        self._calibrated = False
        self._monitoring_started = False
        self._intervention_candidate_started_at: Optional[datetime] = None
        self._manual_effect_until: Optional[datetime] = None
        self.calibration_dialog: Optional[StartupCalibrationDialog] = None
        self.onboarding_toast: Optional[OnboardingToast] = None
        self.status_panel: Optional[StatusPanel] = None
        self.console: Optional[PostureConsoleWindow] = None

        self.tray = QSystemTrayIcon(self._icon(), self.app)
        self.tray.setToolTip("EchoPosture")
        # 右键不再用 QMenu，改为同主题的玻璃浮窗（TrayFlyout，懒加载）
        self.flyout: Optional[TrayFlyout] = None
        self.tray.activated.connect(self._tray_activated)

        # 10Hz 轻量轮询：消费工作线程信箱（决策快照/错误/校准回执）并驱动
        # overlay。推理已不在主线程，单次 tick <1ms。
        self.timer = QTimer(self.app)
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(100)

        self.countdown_timer = QTimer(self.app)
        self.countdown_timer.timeout.connect(self._countdown_step)
        self.countdown_timer.setInterval(1000)

    def start(self, show_calibration: bool = True) -> None:
        if not show_calibration:
            # --self-test：完全同步的本地路径，不启动工作线程
            self.tray.show()
            self._show_pending_screen_capture_warning()
            self.run_startup_self_test()
            return

        try:
            self.worker.start(timeout=15.0)
        except CameraPermissionError as exc:
            self._show_camera_permission_warning(str(exc))
            raise
        self.tray.show()
        self._show_pending_screen_capture_warning()
        self.timer.start()
        self._start_onboarding_prompt()

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.timer.stop()
        self.countdown_timer.stop()
        if self.onboarding_toast is not None:
            self.onboarding_toast.close()
            self.onboarding_toast = None
        if self.flyout is not None:
            self.flyout.close()
            self.flyout = None
        if self.calibration_dialog is not None:
            self.calibration_dialog.close()
            self.calibration_dialog = None
        if self.status_panel is not None:
            self.status_panel.close()
            self.status_panel = None
        if self.console is not None:
            self.console.close()
            self.console = None
        self.overlay.force_clear()
        self.overlay.close()
        self.worker.stop(join_timeout=2.0)
        self.tray.hide()
        self.app.quit()

    def run_startup_self_test(self) -> bool:
        """--self-test 专用：主线程同步完成 校准→单次评估。

        MediaPipe/摄像头的构造、使用、释放都在本线程内完成，不经工作线程。
        """
        if self.mock_camera:
            from mock_vision import MockVisionEngine
            engine = MockVisionEngine(
                camera_id=self.camera_id,
                width=self.capture_width,
                height=self.capture_height,
            )
        else:
            engine = VisionEngine(
                camera_id=self.camera_id,
                width=self.capture_width,
                height=self.capture_height,
            )
        try:
            try:
                engine.start()
            except CameraPermissionError as exc:
                self._show_camera_permission_warning(str(exc))
                raise
            samples = []
            for _ in range(8):
                try:
                    sample = engine.read_sample()
                except Exception:
                    continue
                if sample_is_usable(sample):
                    samples.append(sample)
                    break
            averaged = average_calibration_sample(samples)
            self._calibrated = averaged is not None and self.analyzer.set_baseline_from_sample(
                averaged, self.calibrated_distance_cm
            )
            if self._calibrated:
                try:
                    self.last_decision = self.analyzer.evaluate(engine.read_sample())
                except Exception:
                    pass
            return self._calibrated
        finally:
            engine.close()

    def recalibrate_now(self) -> None:
        if self._stopping or self._awaiting_calibration is not None:
            return
        # 后台重采 18 帧并定基线；UI 全程不阻塞，结果经 _tick 的回执分支处理
        was_monitoring = self.worker.is_monitoring_active()
        self.worker.begin_calibration_sampling()
        self._awaiting_calibration = ("recal", was_monitoring)
        self.worker.finalize_calibration(self.calibrated_distance_cm, sample_count=18)

    def _tick(self) -> None:
        if self._stopping:
            return

        error = self.worker.take_error()
        if error is not None:
            self._on_worker_error(error)
            return

        result = self.worker.take_calibration_result()
        if result is not None:
            self._on_calibration_result(result)
            if self._stopping:
                return

        if self.worker.is_monitoring_active():
            snapshot = self.worker.latest()
            if snapshot.decision is not None:
                self.last_decision = snapshot.decision
            decision = self.last_decision
            active = self._manual_effect_active() or (
                decision is not None and self._should_intervene(decision)
            )
        else:
            active = self._manual_effect_active()
        self.overlay.set_warning_active(active)

    def _on_worker_error(self, exc: Exception) -> None:
        if isinstance(exc, (CameraPermissionError, CameraBlackFrameError)):
            self._handle_camera_failure(exc)
            return
        self.tray.showMessage(
            "EchoPosture",
            _t("tm_worker_error", exc=exc),
            QSystemTrayIcon.Warning,
            5000,
        )
        self.stop()

    def _on_calibration_result(self, result: CalibrationResult) -> None:
        context = self._awaiting_calibration
        self._awaiting_calibration = None
        if context is None or self._stopping:
            return
        purpose, was_monitoring = context

        if purpose == "startup":
            self._calibrated = result.ok
            if result.ok:
                self.tray.showMessage(
                    "EchoPosture",
                    _t("tm_calib_ok"),
                    QSystemTrayIcon.Information,
                    2200,
                )
                self._start_monitoring()
                return
            self.tray.showMessage(
                "EchoPosture",
                _t("tm_calib_fail_startup"),
                QSystemTrayIcon.Warning,
                5000,
            )
            self.stop()
            return

        # 重新校准
        if result.ok:
            self._calibrated = True
            self._intervention_candidate_started_at = None
            self._manual_effect_until = None
            self.overlay.force_clear()
            if self._monitoring_started or was_monitoring:
                self._monitoring_started = True
                self.worker.resume()
            else:
                self._start_monitoring()
            self.tray.showMessage(
                "EchoPosture",
                _t("tm_recal_ok"),
                QSystemTrayIcon.Information,
                2200,
            )
            return

        if was_monitoring:
            self.worker.resume()
        self.tray.showMessage(
            "EchoPosture",
            _t("tm_recal_fail"),
            QSystemTrayIcon.Warning,
            4000,
        )

    def trigger_max_visual_effect(self) -> None:
        self._manual_effect_until = datetime.now() + timedelta(seconds=8)
        self.overlay.trigger_max_effect()
        self.tray.showMessage(
            "EchoPosture",
            _t("tm_max_effect"),
            QSystemTrayIcon.Information,
            1800,
        )

    def _manual_effect_active(self) -> bool:
        if self._manual_effect_until is None:
            return False
        if datetime.now() < self._manual_effect_until:
            return True
        self._manual_effect_until = None
        return False

    def _start_onboarding_prompt(self) -> None:
        """右下角开场弹窗：用户拨开滑条开关后，弹窗谢幕，再进入校准倒计时。"""
        self.onboarding_toast = OnboardingToast()
        self.onboarding_toast.finished.connect(self._on_onboarding_finished)
        self.onboarding_toast.show_bottom_right()

    def _on_onboarding_finished(self) -> None:
        self.onboarding_toast = None
        if self._stopping:
            return
        self._start_calibration_prompt()

    def _start_calibration_prompt(self) -> None:
        self.calibration_dialog = StartupCalibrationDialog(seconds=5)
        self.calibration_dialog.show()
        self.calibration_dialog.raise_()
        # 倒计时期间工作线程在后台按 180ms 间隔累积校准样本
        self.worker.begin_calibration_sampling()
        self.countdown_timer.start()

    def _countdown_step(self) -> None:
        if self.calibration_dialog is None:
            return
        done = self.calibration_dialog.step()
        if not done:
            return

        self.countdown_timer.stop()
        self.calibration_dialog.close()
        self.calibration_dialog = None

        # 让工作线程平均样本并定基线；结果经 _tick 的回执分支处理
        self._awaiting_calibration = ("startup", False)
        self.worker.finalize_calibration(self.calibrated_distance_cm, sample_count=1)

    def _start_monitoring(self) -> None:
        if self._monitoring_started:
            return
        self._monitoring_started = True
        self.worker.resume()
        if not self.timer.isActive():
            self.timer.start()

    def is_monitoring(self) -> bool:
        """监测主循环（工作线程）是否正在运行。"""
        return self.worker.is_monitoring_active()

    def pause_monitoring(self) -> None:
        """暂停监测并清理覆盖层，避免压暗/模糊残留。"""
        if self._stopping:
            return
        self.worker.pause()
        self._intervention_candidate_started_at = None
        self._manual_effect_until = None
        self.overlay.force_clear()

    def resume_monitoring(self) -> None:
        """恢复监测。若尚未首次启动则走启动流程。"""
        if self._stopping:
            return
        if not self._monitoring_started:
            self._start_monitoring()
        else:
            self.worker.resume()

    def _handle_camera_failure(self, exc: Exception) -> None:
        if isinstance(exc, CameraPermissionError):
            self._show_camera_permission_warning(str(exc))
        elif isinstance(exc, CameraBlackFrameError):
            self._show_camera_black_frame_warning(str(exc))
        self.stop()

    def _show_camera_permission_warning(self, detail: str) -> None:
        self._show_warning_once(
            "camera_permission",
            _t("warn_camera_perm_title"),
            _t("warn_camera_perm_body", detail=detail),
        )

    def _show_camera_black_frame_warning(self, detail: str) -> None:
        self._show_warning_once(
            "camera_black_frame",
            _t("warn_camera_black_title"),
            _t("warn_camera_black_body", detail=detail),
        )

    def _show_screen_capture_warning(self, detail: str) -> None:
        self._show_warning_once(
            "screen_capture_permission",
            _t("warn_screen_capture_title"),
            _t("warn_screen_capture_body", detail=detail),
        )

    def _show_pending_screen_capture_warning(self) -> None:
        reason = self.overlay.screen_capture_warning_reason
        if reason:
            self._show_screen_capture_warning(reason)

    def _show_warning_once(self, key: str, title: str, message: str) -> None:
        if key in self._shown_warning_keys:
            return
        self._shown_warning_keys.add(key)
        box = QMessageBox(QMessageBox.Warning, title, message, QMessageBox.Ok)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.exec_()

    def _should_intervene(self, decision: PostureDecision) -> bool:
        if decision.status not in {"BAD", "CRITICAL"}:
            self._intervention_candidate_started_at = None
            return False
        if decision.risk_score < 45.0 or decision.sustained_seconds < 12.0:
            self._intervention_candidate_started_at = None
            return False

        now = datetime.now()
        if self._intervention_candidate_started_at is None:
            self._intervention_candidate_started_at = now
            return False
        return (now - self._intervention_candidate_started_at).total_seconds() >= 3.0

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._toggle_status_panel()
        elif reason == QSystemTrayIcon.Context:
            self._show_flyout()

    def _show_flyout(self) -> None:
        # 浮窗是非核心 UI：它的任何错误都不能拖垮监测主程序。
        try:
            if self.flyout is None:
                self.flyout = TrayFlyout(self)
            self.flyout.popup_bottom_right()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.flyout = None
            self.tray.showMessage(
                "EchoPosture",
                _t("tm_flyout_open_fail", exc=exc),
                QSystemTrayIcon.Warning,
                4000,
            )

    def _toggle_status_panel(self) -> None:
        if self.console is not None and self.console.isVisible():
            self.console.hide()
            return
        self.open_console()

    def open_console(self) -> None:
        # 控制台是非核心 UI：它的任何错误都不能拖垮监测主程序。
        try:
            if self.console is None:
                self.console = PostureConsoleWindow(self)
            self.console.refresh()
            self.console.show()
            self.console.raise_()
            self.console.activateWindow()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.console = None
            self.tray.showMessage(
                "EchoPosture",
                _t("tm_console_open_fail", exc=exc),
                QSystemTrayIcon.Warning,
                4000,
            )

    def _icon(self) -> QIcon:
        logo_path = Path(__file__).resolve().with_name("logo.png")
        logo_pixmap = QPixmap(str(logo_path))
        if not logo_pixmap.isNull():
            return QIcon(logo_pixmap)

        style_icon = self.app.style().standardIcon(QStyle.SP_ComputerIcon)
        if not style_icon.isNull():
            return style_icon

        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setBrush(QColor(31, 111, 235))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(4, 4, 56, 56, 12, 12)
            painter.setPen(QColor(255, 255, 255))
            painter.setFont(QFont("Arial", 18, QFont.Bold))
            painter.drawText(pixmap.rect(), Qt.AlignCenter, "EP")
        finally:
            painter.end()
        return QIcon(pixmap)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPosture tray monitor.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--width", type=int, default=640, help="Capture width. Default: 640")
    parser.add_argument("--height", type=int, default=480, help="Capture height. Default: 480")
    parser.add_argument(
        "--fps",
        type=float,
        default=72.0,
        help="Monitoring frequency. Default: 72",
    )
    parser.add_argument(
        "--distance-cm",
        type=float,
        default=60.0,
        help="Reference calibration distance. Default: 60",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Open the camera, calibrate once, process one sample, and exit.",
    )
    parser.add_argument(
        "--disable-gpu-blur",
        action="store_true",
        help="Use the PyQt dimming overlay fallback instead of BlurOverlayHost.exe.",
    )
    parser.add_argument(
        "--mock-camera",
        action="store_true",
        help="Use a fake in-memory camera (MockVisionEngine) instead of real hardware. "
        "Useful for UI/i18n testing when no camera is available.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    # 高 DPI 感知：必须在 QApplication 构造前设置，否则 Windows 缩放下窗口被
    # 位图拉伸，文字发虚、动画也更卡。开启后按真实像素渲染，文字锐利、动画顺滑。
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    monitor = TrayMonitor(
        app=app,
        camera_id=args.camera,
        width=args.width,
        height=args.height,
        fps=args.fps,
        calibrated_distance_cm=args.distance_cm,
        gpu_blur_enabled=not args.disable_gpu_blur,
        mock_camera=args.mock_camera,
    )
    signal.signal(signal.SIGINT, lambda *_args: monitor.stop())

    try:
        monitor.start(show_calibration=not args.self_test)
        if args.self_test:
            status = monitor.last_decision.status if monitor.last_decision else "NONE"
            print(f"tray_status={status}")
            print(f"tray_icon_visible={monitor.tray.isVisible()}")
            print(f"startup_calibrated={monitor._calibrated}")
            print(f"baseline={monitor.analyzer.baseline is not None}")
            monitor.stop()
            return 0 if monitor._calibrated else 1
        return app.exec_()
    except Exception as exc:
        monitor.stop()
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
