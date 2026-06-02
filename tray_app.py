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
from datetime import datetime
from typing import List, Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QLabel,
    QMenu,
    QStyle,
    QSystemTrayIcon,
    QWidget,
    QVBoxLayout,
)

from gpu_blur_overlay import GpuBlurOverlayController
from vision_test import (
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
        self.setFixedSize(260, 150)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        self.status_label = QLabel()
        self.dim_label = QLabel()
        self.blur_label = QLabel()
        for label in (self.status_label, self.dim_label, self.blur_label):
            label.setFont(QFont("Microsoft YaHei", 11))
            layout.addWidget(label)
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
        self.overlay = GpuBlurOverlayController(enabled=gpu_blur_enabled)
        self.last_decision: Optional[PostureDecision] = None
        self.last_calibration_sample: Optional[VisionSample] = None
        self.calibration_samples: List[VisionSample] = []
        self._stopping = False
        self._calibrated = False
        self._monitoring_started = False
        self._intervention_candidate_started_at: Optional[datetime] = None
        self.calibration_dialog: Optional[StartupCalibrationDialog] = None
        self.status_panel: Optional[StatusPanel] = None

        self.tray = QSystemTrayIcon(self._icon(), self.app)
        self.tray.setToolTip("EchoPosture")
        self.menu = QMenu()
        self.stop_action = QAction("停止", self.menu)
        self.stop_action.triggered.connect(self.stop)
        self.menu.addAction(self.stop_action)
        self.tray.setContextMenu(self.menu)
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
        self.engine.start()
        self.engine.set_capture_fps(72.0)
        self.tray.show()
        if show_calibration:
            self._start_calibration_prompt()
        else:
            self.run_startup_self_test()

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self.timer.stop()
        self.calibration_timer.stop()
        self.countdown_timer.stop()
        if self.calibration_dialog is not None:
            self.calibration_dialog.close()
            self.calibration_dialog = None
        if self.status_panel is not None:
            self.status_panel.close()
            self.status_panel = None
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

    def _tick(self) -> None:
        try:
            sample = self.engine.read_sample()
            decision = self.analyzer.evaluate(sample)
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
        self.overlay.set_warning_active(self._should_intervene(decision))

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

    def _toggle_status_panel(self) -> None:
        if self.status_panel is None:
            self.status_panel = StatusPanel(self)
        if self.status_panel.isVisible():
            self.status_panel.hide()
            return
        self.status_panel.refresh()
        self.status_panel.show()
        self.status_panel.raise_()
        self.status_panel.activateWindow()

    def _icon(self) -> QIcon:
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
