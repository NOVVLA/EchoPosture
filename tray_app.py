"""
EchoPosture tray runtime.

This is the production-style entry point: no debug window, just a tray icon,
startup calibration, camera monitoring, and reversible visual intervention.
"""

from __future__ import annotations

import argparse
import signal
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
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
from onboarding_toast import OnboardingToast
from posture_console import PostureConsoleWindow
from tray_flyout import TrayFlyout
from vision_test import (
    CameraBlackFrameError,
    CameraPermissionError,
    HighPrecisionPostureAnalyzer,
    PostureDecision,
    VisionEngine,
    VisionSample,
)


class StartupCalibrationDialog(QDialog):
    def __init__(self, seconds: int = 5) -> None:
        super().__init__()
        self.remaining_seconds = seconds
        self.setWindowTitle("EchoPosture")
        self.setWindowFlags(
            Qt.Dialog
            | Qt.CustomizeWindowHint
            | Qt.WindowTitleHint
            | Qt.WindowStaysOnTopHint
        )
        self.setFixedSize(620, 280)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 30, 34, 28)
        layout.setSpacing(16)

        title = QLabel("请立即坐直，并保持舒适姿态")
        title.setAlignment(Qt.AlignCenter)
        title.setWordWrap(True)
        title.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))

        body = QLabel("EchoPosture 将在倒计时结束后自动使用摄像头校准当前姿势。")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        body.setFont(QFont("Microsoft YaHei", 12))

        self.countdown_label = QLabel("")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setFont(QFont("Segoe UI", 48, QFont.Bold))

        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
        layout.addWidget(self.countdown_label)
        self._refresh()
        self.setStyleSheet(
            """
            QDialog {
                background: #f7f9fc;
                border: 1px solid #d8e0ea;
            }
            QLabel { color: #172033; }
            """
        )

    def step(self) -> bool:
        self.remaining_seconds -= 1
        self._refresh()
        return self.remaining_seconds <= 0

    def _refresh(self) -> None:
        self.countdown_label.setText(f"{max(self.remaining_seconds, 0)}")


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

        self.max_effect_button = QPushButton("立即测试最深效果")
        self.max_effect_button.clicked.connect(self.monitor.trigger_max_visual_effect)
        layout.addWidget(self.max_effect_button)

        layout.addStretch(1)
        self.setStyleSheet(
            """
            QWidget { background: #f7f9fc; border: 1px solid #d8e0ea; }
            QLabel { color: #172033; border: none; }
            """
        )

        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh)
        self.refresh_timer.start(250)
        self.refresh()

    def refresh(self) -> None:
        decision = self.monitor.last_decision
        status = decision.status if decision is not None else "WAITING"
        dim = round(self.monitor.overlay.dim_level * 100)
        blur = round(self.monitor.overlay.blur_level * 100)
        self.status_label.setText(f"当前状态：{status}")
        self.dim_label.setText(f"压暗程度：{dim}%")
        self.blur_label.setText(f"模糊程度：{blur}%")
        self._refresh_control_labels()

    def _visual_config_changed(self) -> None:
        self.monitor.overlay.set_visual_config(
            self.max_dim_slider.value() / 100.0,
            self.blur_scale_slider.value() / 100.0,
        )
        self._refresh_control_labels()

    def _refresh_control_labels(self) -> None:
        self.max_dim_label.setText(f"最深压暗：{self.max_dim_slider.value()}%")
        self.blur_scale_label.setText(f"模糊强度：{self.blur_scale_slider.value()}%")


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
    ) -> None:
        self.app = app
        self.calibrated_distance_cm = calibrated_distance_cm
        self.engine = VisionEngine(camera_id=camera_id, width=width, height=height)
        self.analyzer = HighPrecisionPostureAnalyzer(
            auto_calibrate=False,
            calibrated_distance_cm=calibrated_distance_cm,
        )
        self._shown_warning_keys: set[str] = set()
        self.overlay = GpuBlurOverlayController(enabled=gpu_blur_enabled)
        self.overlay.screen_capture_warning.connect(self._show_screen_capture_warning)
        self.last_decision: Optional[PostureDecision] = None
        self.last_calibration_sample: Optional[VisionSample] = None
        self.calibration_samples: List[VisionSample] = []
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

        self.timer = QTimer(self.app)
        self.timer.timeout.connect(self._tick)
        self.timer.setInterval(max(1, int(1000 / max(fps, 1.0))))

        self.calibration_timer = QTimer(self.app)
        self.calibration_timer.timeout.connect(self._capture_calibration_sample)
        self.calibration_timer.setInterval(180)

        self.countdown_timer = QTimer(self.app)
        self.countdown_timer.timeout.connect(self._countdown_step)
        self.countdown_timer.setInterval(1000)

    def start(self, show_calibration: bool = True) -> None:
        try:
            self.engine.start()
        except CameraPermissionError as exc:
            self._show_camera_permission_warning(str(exc))
            raise
        self.engine.set_capture_fps(72.0)
        self.tray.show()
        self._show_pending_screen_capture_warning()
        if show_calibration:
            self._start_onboarding_prompt()
        else:
            self.run_startup_self_test()

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.timer.stop()
        self.calibration_timer.stop()
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
        self.engine.close()
        self.tray.hide()
        self.app.quit()

    def run_startup_self_test(self) -> bool:
        if not self._calibrate_from_camera():
            return False
        self._start_monitoring()
        self._tick()
        return self._calibrated

    def recalibrate_now(self) -> None:
        if self._stopping:
            return

        was_monitoring = self.timer.isActive()
        self.timer.stop()
        self.calibration_timer.stop()
        self.countdown_timer.stop()
        if self.calibration_dialog is not None:
            self.calibration_dialog.close()
            self.calibration_dialog = None

        self.calibration_samples.clear()
        self.last_calibration_sample = None
        for _ in range(18):
            self._capture_calibration_sample()
            if self._stopping:
                return

        if self._calibrate_from_camera():
            self._intervention_candidate_started_at = None
            self._manual_effect_until = None
            self.overlay.force_clear()
            if self._monitoring_started or was_monitoring:
                self.timer.start()
            else:
                self._start_monitoring()
            self.tray.showMessage(
                "EchoPosture",
                "已按当前姿势重新校准。",
                QSystemTrayIcon.Information,
                2200,
            )
            return

        if was_monitoring:
            self.timer.start()
        self.tray.showMessage(
            "EchoPosture",
            "重新校准失败：没有识别到可用姿态。",
            QSystemTrayIcon.Warning,
            4000,
        )

    def _tick(self) -> None:
        try:
            sample = self.engine.read_sample()
            decision = self.analyzer.evaluate(sample)
        except (CameraPermissionError, CameraBlackFrameError) as exc:
            self._handle_camera_failure(exc)
            return
        except Exception as exc:
            self.tray.showMessage(
                "EchoPosture",
                f"监测已停止：{exc}",
                QSystemTrayIcon.Warning,
                5000,
            )
            self.stop()
            return

        self.last_decision = decision
        self.overlay.set_warning_active(self._manual_effect_active() or self._should_intervene(decision))

    def trigger_max_visual_effect(self) -> None:
        self._manual_effect_until = datetime.now() + timedelta(seconds=8)
        self.overlay.trigger_max_effect()
        self.tray.showMessage(
            "EchoPosture",
            "已触发 8 秒最深压暗和模糊。",
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
        self.calibration_timer.start()
        self.countdown_timer.start()

    def _countdown_step(self) -> None:
        if self.calibration_dialog is None:
            return
        done = self.calibration_dialog.step()
        if not done:
            return

        self.countdown_timer.stop()
        self.calibration_timer.stop()
        self.calibration_dialog.close()
        self.calibration_dialog = None

        if self._calibrate_from_camera():
            self.tray.showMessage(
                "EchoPosture",
                "校准完成，姿态监测已开始。",
                QSystemTrayIcon.Information,
                2200,
            )
            self._start_monitoring()
            return

        if self._stopping:
            return

        self.tray.showMessage(
            "EchoPosture",
            "校准失败：没有识别到可用姿态。请重新启动并坐直。",
            QSystemTrayIcon.Warning,
            5000,
        )
        self.stop()

    def _capture_calibration_sample(self) -> None:
        try:
            sample = self.engine.read_sample()
        except (CameraPermissionError, CameraBlackFrameError) as exc:
            self._handle_camera_failure(exc)
            return
        except Exception:
            return
        if (
            sample.interpupillary_px is not None
            or sample.signed_shoulder_diff_px is not None
            or sample.trunk_lean_deg is not None
        ):
            self.last_calibration_sample = sample
            self.calibration_samples.append(sample)
            if len(self.calibration_samples) > 60:
                self.calibration_samples = self.calibration_samples[-60:]

    def _calibrate_from_camera(self) -> bool:
        if not self.calibration_samples:
            for _ in range(8):
                self._capture_calibration_sample()
                if self.calibration_samples:
                    break
        sample = self._average_calibration_sample()
        if sample is None:
            return False

        self._calibrated = self.analyzer.set_baseline_from_sample(
            sample,
            self.calibrated_distance_cm,
        )
        return self._calibrated

    def _average_calibration_sample(self) -> Optional[VisionSample]:
        samples = self.calibration_samples
        if not samples:
            return self.last_calibration_sample

        def avg(name: str) -> Optional[float]:
            values = [getattr(sample, name) for sample in samples]
            usable = [value for value in values if value is not None]
            if not usable:
                return None
            return sum(usable) / len(usable)

        base = samples[-1]
        return replace(
            base,
            timestamp=datetime.now(),
            interpupillary_px=avg("interpupillary_px"),
            shoulder_diff_px=avg("shoulder_diff_px"),
            signed_shoulder_diff_px=avg("signed_shoulder_diff_px"),
            shoulder_width_px=avg("shoulder_width_px"),
            trunk_lean_deg=avg("trunk_lean_deg"),
            head_turn_ratio=avg("head_turn_ratio"),
            torso_height_px=avg("torso_height_px"),
            face_detected=any(sample.face_detected for sample in samples),
            pose_detected=any(sample.pose_detected for sample in samples),
        )

    def _start_monitoring(self) -> None:
        if self._monitoring_started:
            return
        self._monitoring_started = True
        self.timer.start()

    def is_monitoring(self) -> bool:
        """监测主循环是否正在运行。"""
        return self.timer.isActive()

    def pause_monitoring(self) -> None:
        """暂停监测并清理覆盖层，避免压暗/模糊残留。"""
        if self._stopping:
            return
        self.timer.stop()
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
            self.timer.start()

    def _handle_camera_failure(self, exc: Exception) -> None:
        if isinstance(exc, CameraPermissionError):
            self._show_camera_permission_warning(str(exc))
        elif isinstance(exc, CameraBlackFrameError):
            self._show_camera_black_frame_warning(str(exc))
        self.stop()

    def _show_camera_permission_warning(self, detail: str) -> None:
        self._show_warning_once(
            "camera_permission",
            "摄像头权限不可用",
            "EchoPosture 无法打开摄像头。\n\n"
            "请在 Windows 设置 > 隐私和安全性 > 摄像头 中允许桌面应用访问摄像头，"
            "确认没有其他程序独占摄像头，然后重新启动 EchoPosture。\n\n"
            f"详细信息：{detail}",
        )

    def _show_camera_black_frame_warning(self, detail: str) -> None:
        self._show_warning_once(
            "camera_black_frame",
            "摄像头画面不可用",
            "EchoPosture 已取得摄像头访问权限，但摄像头输出是全黑或几乎全黑，"
            "当前无法看清姿态。\n\n"
            "请检查镜头遮挡、隐私挡片、驱动禁用、虚拟摄像头输出或环境光线，然后重新启动监测。\n\n"
            f"详细信息：{detail}",
        )

    def _show_screen_capture_warning(self, detail: str) -> None:
        self._show_warning_once(
            "screen_capture_permission",
            "屏幕捕获权限受限",
            "EchoPosture 无法读取桌面画面用于 GPU 模糊，已切换到基础压暗 fallback。\n\n"
            "请检查屏幕捕获权限、显卡/远程桌面限制或安全软件拦截。\n\n"
            f"详细信息：{detail}",
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
                f"托盘浮窗打开失败，监测仍在运行：{exc}",
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
                f"控制台窗口打开失败，监测仍在运行：{exc}",
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
