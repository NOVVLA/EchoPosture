"""
EchoPosture visual debug UI.

Left: live camera view.
Right: human-readable MediaPipe metrics, posture state, and manual calibration.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, Optional

import cv2
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QCheckBox,
    QVBoxLayout,
    QWidget,
)

from vision_test import (
    PostureAnalyzer,
    PostureDecision,
    VisionEngine,
    VisionSample,
    format_baseline,
    format_value,
)


STATUS_TEXT: Dict[str, str] = {
    "GOOD": "正常",
    "GOOD_PART": "部分正常",
    "BAD": "需要调整",
    "UNKNOWN": "未识别",
    "CALIBRATING": "校准中",
    "NEEDS_CALIB": "等待校准",
}

REASON_TEXT: Dict[str, str] = {
    "press_calibrate": "请坐直后点击校准",
    "within_baseline": "与基准姿势接近",
    "too_close": "脸离屏幕过近",
    "shoulder_tilt": "肩膀高度偏差较大",
    "missing_face_or_pose": "脸部或肩膀未识别",
    "no_usable_metrics": "暂时没有可用视觉指标",
    "face_within_baseline": "脸部距离正常",
    "shoulder_within_baseline": "肩膀高度正常",
}


class DebugWindow(QMainWindow):
    def __init__(self, camera_id: int, fps: float, width: int, height: int) -> None:
        super().__init__()
        self.setWindowTitle("EchoPosture Debug Monitor")
        self.resize(980, 580)

        self.engine = VisionEngine(camera_id=camera_id, width=width, height=height)
        self.analyzer = PostureAnalyzer(auto_calibrate=False)
        self.current_sample: Optional[VisionSample] = None
        self.normal_fps = fps
        self.high_performance_fps = 72.0

        self.video_label = QLabel("Camera starting...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setStyleSheet("background: #111; color: #ccc;")

        self.status_label = QLabel("等待校准")
        self.status_label.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)

        self.reason_label = QLabel("请坐直后点击校准")
        self.reason_label.setWordWrap(True)
        self.reason_label.setAlignment(Qt.AlignCenter)

        self.face_label = QLabel("--")
        self.shoulder_label = QLabel("--")
        self.baseline_label = QLabel("--")
        self.calibration_label = QLabel("未校准")
        self.calibration_label.setWordWrap(True)

        self.calibrate_button = QPushButton("校准当前姿势")
        self.calibrate_button.clicked.connect(self.calibrate_current_sample)
        self.performance_checkbox = QCheckBox("高性能模式（72帧捕捉用于高流畅度）")
        self.performance_checkbox.toggled.connect(self.toggle_high_performance)

        self._build_layout()
        self._apply_style()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(self._interval_ms(self.normal_fps))

        self.engine.start()

    def _build_layout(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(14)

        panel = QFrame()
        panel.setFixedWidth(300)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(16, 16, 16, 16)
        panel_layout.setSpacing(12)

        title = QLabel("视觉监听")
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))

        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(10)
        metric_grid.setVerticalSpacing(8)
        metric_grid.addWidget(QLabel("脸部距离"), 0, 0)
        metric_grid.addWidget(self.face_label, 0, 1)
        metric_grid.addWidget(QLabel("肩膀倾斜"), 1, 0)
        metric_grid.addWidget(self.shoulder_label, 1, 1)
        metric_grid.addWidget(QLabel("当前基准"), 2, 0)
        metric_grid.addWidget(self.baseline_label, 2, 1)

        panel_layout.addWidget(title)
        panel_layout.addWidget(self.status_label)
        panel_layout.addWidget(self.reason_label)
        panel_layout.addSpacing(8)
        panel_layout.addLayout(metric_grid)
        panel_layout.addWidget(self.calibration_label)
        panel_layout.addWidget(self.performance_checkbox)
        panel_layout.addStretch(1)
        panel_layout.addWidget(self.calibrate_button)

        layout.addWidget(self.video_label, 1)
        layout.addWidget(panel)
        self.setCentralWidget(root)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f4f5f7; }
            QFrame { background: white; border: 1px solid #d8dde6; border-radius: 6px; }
            QLabel { color: #1f2933; font-size: 13px; }
            QPushButton {
                background: #1f6feb;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 12px;
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton:hover { background: #1557b0; }
            """
        )

    def update_frame(self) -> None:
        try:
            frame, sample = self.engine.read_frame_sample()
        except Exception as exc:
            self.timer.stop()
            QMessageBox.critical(self, "Camera error", str(exc))
            return

        self.current_sample = sample
        decision = self.analyzer.evaluate(sample)
        self._show_frame(frame, sample)
        self._show_metrics(sample, decision)

    def calibrate_current_sample(self) -> None:
        if self.current_sample is None:
            self.calibration_label.setText("还没有摄像头样本")
            return

        if not self.analyzer.set_baseline_from_sample(self.current_sample):
            self.calibration_label.setText("校准失败：没有识别到脸部或肩膀")
            return

        self.calibration_label.setText("已校准：当前姿势已作为健康基准")
        self.baseline_label.setText(format_baseline(self.analyzer.baseline))
        decision = self.analyzer.evaluate(self.current_sample)
        self._show_metrics(self.current_sample, decision)

    def toggle_high_performance(self, enabled: bool) -> None:
        target_fps = self.high_performance_fps if enabled else self.normal_fps
        self.timer.setInterval(self._interval_ms(target_fps))
        self.engine.set_capture_fps(target_fps)

    def _show_frame(self, frame, sample: VisionSample) -> None:
        annotated = frame.copy()
        self._draw_landmarks(annotated, sample)

        rgb = cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)
        height, width, channel_count = rgb.shape
        bytes_per_line = channel_count * width
        image = QImage(
            rgb.data,
            width,
            height,
            bytes_per_line,
            QImage.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image).scaled(
            self.video_label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)

    def _draw_landmarks(self, frame, sample: VisionSample) -> None:
        eye_color = (0, 220, 255)
        shoulder_color = (80, 220, 80)
        neck_color = (255, 120, 220)
        center_color = (0, 180, 255)

        left_eye = self._point(sample.left_eye_center)
        right_eye = self._point(sample.right_eye_center)
        if left_eye and right_eye:
            cv2.line(frame, left_eye, right_eye, eye_color, 2, cv2.LINE_AA)
            cv2.circle(frame, left_eye, 6, eye_color, -1, cv2.LINE_AA)
            cv2.circle(frame, right_eye, 6, eye_color, -1, cv2.LINE_AA)
            cv2.putText(
                frame,
                "eye distance",
                (min(left_eye[0], right_eye[0]), max(20, min(left_eye[1], right_eye[1]) - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                eye_color,
                1,
                cv2.LINE_AA,
            )

        left_shoulder = self._point(sample.left_shoulder_point)
        right_shoulder = self._point(sample.right_shoulder_point)
        shoulder_center = self._point(sample.shoulder_center)
        if left_shoulder and right_shoulder:
            cv2.line(frame, left_shoulder, right_shoulder, shoulder_color, 3, cv2.LINE_AA)
            cv2.circle(frame, left_shoulder, 7, shoulder_color, -1, cv2.LINE_AA)
            cv2.circle(frame, right_shoulder, 7, shoulder_color, -1, cv2.LINE_AA)
            cv2.putText(
                frame,
                "shoulder line",
                (min(left_shoulder[0], right_shoulder[0]), max(20, min(left_shoulder[1], right_shoulder[1]) - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                shoulder_color,
                1,
                cv2.LINE_AA,
            )

        nose = self._point(sample.nose_point)
        if nose:
            cv2.circle(frame, nose, 6, neck_color, -1, cv2.LINE_AA)

        if nose and shoulder_center:
            cv2.circle(frame, shoulder_center, 5, center_color, -1, cv2.LINE_AA)
            cv2.line(frame, nose, shoulder_center, neck_color, 2, cv2.LINE_AA)
            cv2.putText(
                frame,
                "head axis",
                (min(nose[0], shoulder_center[0]) + 8, min(nose[1], shoulder_center[1]) + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                neck_color,
                1,
                cv2.LINE_AA,
            )

    @staticmethod
    def _point(point) -> Optional[tuple]:
        if point is None:
            return None
        return int(round(point[0])), int(round(point[1]))

    @staticmethod
    def _interval_ms(fps: float) -> int:
        return max(1, int(1000 / max(fps, 1.0)))

    def _show_metrics(self, sample: VisionSample, decision: PostureDecision) -> None:
        self.status_label.setText(STATUS_TEXT.get(decision.status, decision.status))
        self.reason_label.setText(self._human_reason(decision.reason))
        self.status_label.setStyleSheet(self._status_style(decision.status))

        face_text = f"{format_value(sample.interpupillary_px)}  越大越近"
        shoulder_text = f"{format_value(sample.shoulder_diff_px)}  越大越歪"
        self.face_label.setText(face_text)
        self.shoulder_label.setText(shoulder_text)
        self.baseline_label.setText(format_baseline(self.analyzer.baseline))

    def _human_reason(self, reason: str) -> str:
        if not reason:
            return "--"

        translated = reason
        for key, text in REASON_TEXT.items():
            translated = translated.replace(key, text)
        translated = translated.replace("missing=", "缺失：")
        translated = translated.replace("face", "脸部")
        translated = translated.replace("shoulder", "肩膀")
        translated = translated.replace("baseline", "基准")
        translated = translated.replace("+", " / ")
        translated = translated.replace(",", "，")
        translated = translated.replace(";", "；")
        return translated

    @staticmethod
    def _status_style(status: str) -> str:
        if status == "BAD":
            return "color: #b42318;"
        if status in {"GOOD", "GOOD_PART"}:
            return "color: #157347;"
        return "color: #6b7280;"

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.engine.close()
        super().closeEvent(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPosture visual debug UI.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--fps", type=float, default=4.0, help="Detection frequency. Default: 4")
    parser.add_argument("--width", type=int, default=640, help="Capture width. Default: 640")
    parser.add_argument("--height", type=int, default=480, help="Capture height. Default: 480")
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Create the debug window offscreen, process one frame, calibrate, and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    try:
        window = DebugWindow(args.camera, args.fps, args.width, args.height)
    except Exception as exc:
        QMessageBox.critical(None, "Startup error", str(exc))
        return 1

    if args.self_test:
        window.update_frame()
        window.calibrate_current_sample()
        print(f"status={window.status_label.text()}")
        print(f"face={window.face_label.text()}")
        print(f"shoulder={window.shoulder_label.text()}")
        print(f"baseline={window.baseline_label.text()}")
        print(f"calibration={window.calibration_label.text()}")
        window.close()
        return 0

    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
