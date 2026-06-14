"""
EchoPosture visual debug UI.

Left: live camera view.
Right: human-readable MediaPipe metrics, posture state, and manual calibration.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from typing import Dict, Optional

import cv2

QT_PLUGIN_ROOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "runtime",
    "python311",
    "Lib",
    "site-packages",
    "PyQt5",
    "Qt5",
    "plugins",
)
if os.path.isdir(QT_PLUGIN_ROOT):
    os.environ.setdefault("QT_PLUGIN_PATH", QT_PLUGIN_ROOT)
    os.environ.setdefault(
        "QT_QPA_PLATFORM_PLUGIN_PATH",
        os.path.join(QT_PLUGIN_ROOT, "platforms"),
    )

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPixmap, QRegion
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
    QDoubleSpinBox,
    QVBoxLayout,
    QWidget,
)

from vision_test import (
    CameraBlackFrameError,
    CameraPermissionError,
    HighPrecisionPostureAnalyzer,
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
    "WATCH": "观察中",
    "BAD": "需要调整",
    "CRITICAL": "高风险",
    "AWAY": "已离开",
    "MULTI_USER": "多人",
    "PROFILE_MISMATCH": "疑似换人",
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
    "within_scientific_limits": "高精度指标在建议范围内",
    "distance_calibration": "校准距离",
    "distance_unreliable_head_turn": "转头时距离估算不可靠",
    "head_turn": "头部转向",
    "head_not_facing_camera": "头部未正对屏幕",
    "head_turn_eye_width_ratio": "头部转向眼距比例",
    "head_turn_ratio_delta": "头部转向偏移",
    "multiple_faces_detected": "检测到多张脸",
    "user_away_s": "用户离开秒数",
    "user_missing_observing_s": "用户缺失观察秒数",
    "profile_check_waiting": "等待用户轮廓校验",
    "profile_face_shoulder_delta": "脸肩比例变化",
    "profile_torso_shoulder_delta": "躯干肩宽比例变化",
    "distance_too_close": "距离过近",
    "distance_near": "距离偏近",
    "distance_too_far": "距离过远",
    "distance_far": "距离偏远",
    "shoulder_asymmetry": "肩颈不对称",
    "shoulder_width": "肩宽",
    "shoulder_width_narrow": "肩宽明显缩窄",
    "trunk_lean": "躯干倾斜",
    "sustained_risk_s": "持续风险秒数",
    "smoothed_risk_score": "平滑风险评分",
    "risk_score": "风险评分",
    "risk_observing": "风险观察中",
}


class PostureInterventionOverlay(QWidget):
    MAX_DIM_ALPHA = 0.32
    LIVE_BLUR_SUPPORTED = True
    RAMP_UP_SECONDS = 45.0
    RAMP_DOWN_SECONDS = 0.3
    TICK_MS = 80
    MIN_BOTTOM_SAFE_BAND_PX = 96
    MAX_BOTTOM_SAFE_BAND_PX = 180
    INPUT_ESCAPE_BAND_PX = 240

    def __init__(self) -> None:
        super().__init__()
        self._target_level = 0.0
        self._level = 0.0
        self._max_dim_alpha = self.MAX_DIM_ALPHA
        self._blur_scale = 1.0
        self._layer_opacity = 1.0
        self._last_tick = time.perf_counter()
        self._live_blur_enabled = False
        self._input_escape_active = False

        self.setWindowTitle("EchoPosture Intervention Overlay")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )

        self._cover_all_screens()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.TICK_MS)
        self.hide()

    def set_warning_active(self, active: bool) -> None:
        target = 1.0 if active else 0.0
        if target == self._target_level:
            return

        self._target_level = target
        if active:
            self._cover_all_screens()
            self._last_tick = time.perf_counter()
            if not self._cursor_in_input_escape_band() and not self.isVisible():
                self.show()
                self.raise_()
                self._enable_windows_click_through()
        else:
            self._last_tick = time.perf_counter()

    def force_clear(self) -> None:
        self._target_level = 0.0
        self._level = 0.0
        self._set_live_blur(False)
        self.hide()

    def trigger_max_effect(self) -> None:
        self._target_level = 1.0
        self._level = 1.0
        self._cover_all_screens()
        self._last_tick = time.perf_counter()
        if not self._cursor_in_input_escape_band() and not self.isVisible():
            self.show()
            self.raise_()
            self._enable_windows_click_through()
        self._set_live_blur(
            self.LIVE_BLUR_SUPPORTED and self._blur_scale > 0.01,
            self._level * self._blur_scale,
        )
        self.update()

    def paintEvent(self, event) -> None:
        if self._level <= 0.001:
            return

        painter = QPainter(self)
        try:
            target_alpha = 255 * self._max_dim_alpha * self._level
            opacity = self._layer_opacity if self._live_blur_enabled else 1.0
            dim_alpha = int(min(255, target_alpha / max(0.001, opacity)))
            painter.fillRect(self.rect(), QColor(0, 0, 0, dim_alpha))
        finally:
            painter.end()

    def _tick(self) -> None:
        now = time.perf_counter()
        elapsed = max(0.0, now - self._last_tick)
        self._last_tick = now

        if self._target_level > self._level:
            self._level = min(self._target_level, self._level + elapsed / self.RAMP_UP_SECONDS)
        elif self._target_level < self._level:
            self._level = max(self._target_level, self._level - elapsed / self.RAMP_DOWN_SECONDS)

        if self._level <= 0.001 and self._target_level <= 0.001:
            if self.isVisible():
                self.hide()
            self._set_live_blur(False)
            return

        if self._cursor_in_input_escape_band():
            self._input_escape_active = True
            if self.isVisible():
                self.hide()
            self._set_live_blur(False)
            return

        if self._input_escape_active:
            self._input_escape_active = False
            self._cover_all_screens()

        if not self.isVisible():
            self.show()
            self.raise_()
            self._enable_windows_click_through()
        self._set_live_blur(
            self.LIVE_BLUR_SUPPORTED and self._blur_scale > 0.01 and self._level > 0.01,
            self._level * self._blur_scale,
        )
        self.update()

    @property
    def dim_level(self) -> float:
        return min(1.0, max(0.0, self._level))

    @property
    def blur_level(self) -> float:
        if self.LIVE_BLUR_SUPPORTED and self._live_blur_enabled:
            return min(1.0, max(0.0, self.dim_level * self._blur_scale))
        return 0.0

    def set_visual_config(self, max_dim_alpha: float, blur_scale: float) -> None:
        self._max_dim_alpha = min(0.85, max(0.0, float(max_dim_alpha)))
        self._blur_scale = min(1.0, max(0.0, float(blur_scale)))
        if self._blur_scale <= 0.01:
            self._set_live_blur(False)
        elif self._live_blur_enabled:
            self._set_live_blur(True, self._level * self._blur_scale)
        self.update()

    def _cover_all_screens(self) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return

        full_rect = screens[0].geometry()
        for screen in screens[1:]:
            full_rect = full_rect.united(screen.geometry())

        work_region = QRegion()
        for screen in screens:
            work_rect = screen.availableGeometry()
            if work_rect.isNull() or work_rect.width() <= 0 or work_rect.height() <= 0:
                work_rect = screen.geometry()
            bottom_safe_band = min(
                self.MAX_BOTTOM_SAFE_BAND_PX,
                max(self.MIN_BOTTOM_SAFE_BAND_PX, screen.geometry().height() // 12),
            )
            safe_bottom = screen.geometry().bottom() + 1 - bottom_safe_band
            if work_rect.bottom() + 1 > safe_bottom and safe_bottom > work_rect.top() + 240:
                work_rect.setBottom(safe_bottom - 1)
            work_region = work_region.united(QRegion(work_rect.translated(-full_rect.topLeft())))

        self.setGeometry(full_rect)
        self.setMask(work_region)

    def _cursor_in_input_escape_band(self) -> bool:
        cursor_pos = QCursor.pos()
        for screen in QGuiApplication.screens():
            rect = screen.geometry()
            if rect.contains(cursor_pos):
                return cursor_pos.y() >= rect.bottom() + 1 - self.INPUT_ESCAPE_BAND_PX
        return False

    def _enable_windows_click_through(self) -> None:
        if sys.platform != "win32":
            return

        hwnd = int(self.winId())
        user32 = ctypes.windll.user32

        gwl_exstyle = -20
        ws_ex_layered = 0x00080000
        ws_ex_transparent = 0x00000020
        ws_ex_toolwindow = 0x00000080

        style = user32.GetWindowLongW(hwnd, gwl_exstyle)
        style |= ws_ex_layered | ws_ex_transparent | ws_ex_toolwindow
        user32.SetWindowLongW(hwnd, gwl_exstyle, style)
        user32.EnableWindow(hwnd, False)

    def _set_live_blur(self, enabled: bool, blur_mix: float = 0.0) -> None:
        if sys.platform != "win32":
            return

        hwnd = int(self.winId())
        blur_mix = min(1.0, max(0.0, float(blur_mix))) if enabled else 0.0
        target_dim = min(1.0, max(0.0, self._max_dim_alpha * self._level))
        layer_opacity = max(blur_mix, target_dim) if enabled else 1.0
        layer_alpha = int(min(255, max(0, round(255 * layer_opacity))))

        try:
            ctypes.windll.user32.SetLayeredWindowAttributes(hwnd, 0, layer_alpha, 0x00000002)
            self._layer_opacity = layer_opacity
        except Exception:
            self._layer_opacity = 1.0

        if enabled == self._live_blur_enabled:
            return

        class AccentPolicy(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_int),
                ("AnimationId", ctypes.c_int),
            ]

        class WindowCompositionAttributeData(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.c_void_p),
                ("SizeOfData", ctypes.c_size_t),
            ]

        accent_disabled = 0
        accent_blur_behind = 3
        wca_accent_policy = 19
        accent = AccentPolicy()
        accent.AccentState = accent_blur_behind if enabled else accent_disabled
        accent.AccentFlags = 0
        accent.GradientColor = 0
        accent.AnimationId = 0
        data = WindowCompositionAttributeData()
        data.Attribute = wca_accent_policy
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        try:
            result = ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
            self._live_blur_enabled = bool(result) if enabled else False
        except Exception:
            self._live_blur_enabled = False


class DebugWindow(QMainWindow):
    def __init__(
        self,
        camera_id: int,
        fps: float,
        width: int,
        height: int,
        intervention_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("EchoPosture Debug Monitor")
        self.resize(980, 580)

        self.engine = VisionEngine(camera_id=camera_id, width=width, height=height)
        self.analyzer = PostureAnalyzer(auto_calibrate=False)
        self.current_sample: Optional[VisionSample] = None
        self.normal_fps = fps
        self.high_performance_fps = 72.0
        self.high_precision_enabled = False
        self.intervention_overlay = (
            PostureInterventionOverlay() if intervention_enabled else None
        )

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
        self.distance_label = QLabel("--")
        self.trunk_label = QLabel("--")
        self.risk_label = QLabel("--")
        self.baseline_label = QLabel("--")
        self.calibration_label = QLabel("未校准")
        self.calibration_label.setWordWrap(True)

        self.calibrate_button = QPushButton("校准当前姿势")
        self.calibrate_button.clicked.connect(self.calibrate_current_sample)
        self.precision_checkbox = QCheckBox("高精度模式（需要输入校准距离）")
        self.precision_checkbox.toggled.connect(self.toggle_high_precision)
        self.distance_input = QDoubleSpinBox()
        self.distance_input.setRange(35.0, 150.0)
        self.distance_input.setDecimals(0)
        self.distance_input.setSingleStep(5.0)
        self.distance_input.setValue(60.0)
        self.distance_input.setSuffix(" cm")
        self.distance_input.setEnabled(False)
        self.distance_input.valueChanged.connect(self.update_reference_distance)
        self.performance_checkbox = QCheckBox("高性能模式（72帧捕捉用于高流畅度）")
        self.performance_checkbox.toggled.connect(self.toggle_high_performance)

        self._build_layout()
        self._apply_style()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(self._interval_ms(self.normal_fps))

        self.engine.start()
        self.precision_checkbox.setChecked(True)
        self.performance_checkbox.setChecked(True)

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
        metric_grid.addWidget(QLabel("估算距离"), 2, 0)
        metric_grid.addWidget(self.distance_label, 2, 1)
        metric_grid.addWidget(QLabel("躯干倾斜"), 3, 0)
        metric_grid.addWidget(self.trunk_label, 3, 1)
        metric_grid.addWidget(QLabel("风险评分"), 4, 0)
        metric_grid.addWidget(self.risk_label, 4, 1)
        metric_grid.addWidget(QLabel("当前基准"), 5, 0)
        metric_grid.addWidget(self.baseline_label, 5, 1)

        panel_layout.addWidget(title)
        panel_layout.addWidget(self.status_label)
        panel_layout.addWidget(self.reason_label)
        panel_layout.addSpacing(8)
        panel_layout.addLayout(metric_grid)
        panel_layout.addWidget(self.calibration_label)
        panel_layout.addWidget(self.precision_checkbox)
        panel_layout.addWidget(self.distance_input)
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
        except CameraPermissionError as exc:
            self.timer.stop()
            self._show_camera_permission_warning(str(exc))
            return
        except CameraBlackFrameError as exc:
            self.timer.stop()
            self._show_camera_black_frame_warning(str(exc))
            return
        except Exception as exc:
            self.timer.stop()
            QMessageBox.critical(self, "Camera error", str(exc))
            return

        self.current_sample = sample
        decision = self.analyzer.evaluate(sample)
        self._show_frame(frame, sample)
        self._show_metrics(sample, decision)
        self._update_intervention(decision)

    def calibrate_current_sample(self) -> None:
        if self.current_sample is None:
            self.calibration_label.setText("还没有摄像头样本")
            return

        distance_cm = float(self.distance_input.value()) if self.high_precision_enabled else None
        if not self.analyzer.set_baseline_from_sample(self.current_sample, distance_cm):
            self.calibration_label.setText("校准失败：没有识别到脸部或肩膀")
            return

        self.calibration_label.setText("已校准：当前姿势已作为健康基准")
        self.baseline_label.setText(format_baseline(self.analyzer.baseline))
        decision = self.analyzer.evaluate(self.current_sample)
        self._show_metrics(self.current_sample, decision)
        self._update_intervention(decision)

    def toggle_high_performance(self, enabled: bool) -> None:
        target_fps = self.high_performance_fps if enabled else self.normal_fps
        self.timer.setInterval(self._interval_ms(target_fps))
        self.engine.set_capture_fps(target_fps)

    def toggle_high_precision(self, enabled: bool) -> None:
        old_baseline = self.analyzer.baseline
        distance_cm = float(self.distance_input.value())
        self.high_precision_enabled = enabled
        self.distance_input.setEnabled(enabled)
        if enabled:
            self.analyzer = HighPrecisionPostureAnalyzer(
                auto_calibrate=False,
                baseline=old_baseline,
                calibrated_distance_cm=distance_cm,
            )
            self.analyzer.set_calibrated_distance_cm(distance_cm)
        else:
            self.analyzer = PostureAnalyzer(auto_calibrate=False, baseline=old_baseline)
        if self.current_sample is not None:
            decision = self.analyzer.evaluate(self.current_sample)
            self._show_metrics(self.current_sample, decision)

    def update_reference_distance(self, value: float) -> None:
        if isinstance(self.analyzer, HighPrecisionPostureAnalyzer):
            self.analyzer.set_calibrated_distance_cm(float(value))
            if self.current_sample is not None:
                decision = self.analyzer.evaluate(self.current_sample)
                self._show_metrics(self.current_sample, decision)

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
        trunk_color = (255, 180, 80)

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

        face_nose = self._point(sample.face_nose_point)
        if face_nose:
            cv2.circle(frame, face_nose, 4, eye_color, -1, cv2.LINE_AA)

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

        left_hip = self._point(sample.left_hip_point)
        right_hip = self._point(sample.right_hip_point)
        hip_center = self._point(sample.hip_center)
        if left_hip and right_hip:
            cv2.line(frame, left_hip, right_hip, trunk_color, 2, cv2.LINE_AA)
            cv2.circle(frame, left_hip, 5, trunk_color, -1, cv2.LINE_AA)
            cv2.circle(frame, right_hip, 5, trunk_color, -1, cv2.LINE_AA)

        if shoulder_center and hip_center:
            cv2.circle(frame, hip_center, 5, trunk_color, -1, cv2.LINE_AA)
            cv2.line(frame, shoulder_center, hip_center, trunk_color, 2, cv2.LINE_AA)

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
        estimated_distance = None
        if isinstance(self.analyzer, HighPrecisionPostureAnalyzer):
            estimated_distance = self.analyzer.estimated_distance_cm(sample)
        distance_text = format_value(estimated_distance, "cm")
        trunk_text = format_value(sample.trunk_lean_deg, "deg")
        risk_text = (
            f"{decision.risk_score:.0f} / {decision.sustained_seconds:.1f}s"
            if decision.risk_score
            else "--"
        )
        self.face_label.setText(face_text)
        self.shoulder_label.setText(shoulder_text)
        self.distance_label.setText(distance_text)
        self.trunk_label.setText(trunk_text)
        self.risk_label.setText(risk_text)
        self.baseline_label.setText(format_baseline(self.analyzer.baseline))

    def _update_intervention(self, decision: PostureDecision) -> None:
        if self.intervention_overlay is None:
            return

        self.intervention_overlay.set_warning_active(
            decision.status in {"BAD", "CRITICAL"}
        )

    def _show_camera_permission_warning(self, detail: str) -> None:
        self._show_warning_dialog(
            "摄像头权限不可用",
            "EchoPosture 无法打开摄像头。\n\n"
            "请在 Windows 设置 > 隐私和安全性 > 摄像头 中允许桌面应用访问摄像头，"
            "确认没有其他程序独占摄像头，然后重新启动 EchoPosture。\n\n"
            f"详细信息：{detail}",
        )

    def _show_camera_black_frame_warning(self, detail: str) -> None:
        self._show_warning_dialog(
            "摄像头画面不可用",
            "EchoPosture 已取得摄像头访问权限，但摄像头输出是全黑或几乎全黑，"
            "当前无法看清姿态。\n\n"
            "请检查镜头遮挡、隐私挡片、驱动禁用、虚拟摄像头输出或环境光线，然后重新启动监测。\n\n"
            f"详细信息：{detail}",
        )

    def _show_warning_dialog(self, title: str, message: str) -> None:
        box = QMessageBox(QMessageBox.Warning, title, message, QMessageBox.Ok, self)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.exec_()

    def _human_reason(self, reason: str) -> str:
        if not reason:
            return "--"

        translated = reason
        for key, text in REASON_TEXT.items():
            translated = translated.replace(key, text)
        translated = translated.replace("missing=", "缺失：")
        translated = translated.replace("face", "脸部")
        translated = translated.replace("shoulder", "肩膀")
        translated = translated.replace("trunk", "躯干")
        translated = translated.replace("distance", "距离")
        translated = translated.replace("baseline", "基准")
        translated = translated.replace("+", " / ")
        translated = translated.replace(",", "，")
        translated = translated.replace(";", "；")
        return translated

    @staticmethod
    def _status_style(status: str) -> str:
        if status in {"BAD", "CRITICAL"}:
            return "color: #b42318;"
        if status in {"AWAY", "MULTI_USER", "PROFILE_MISMATCH"}:
            return "color: #6b7280;"
        if status == "WATCH":
            return "color: #b7791f;"
        if status in {"GOOD", "GOOD_PART"}:
            return "color: #157347;"
        return "color: #6b7280;"

    def closeEvent(self, event) -> None:
        self.timer.stop()
        if self.intervention_overlay is not None:
            self.intervention_overlay.force_clear()
            self.intervention_overlay.close()
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
    parser.add_argument(
        "--disable-intervention",
        action="store_true",
        help="Disable gradual dimming and blur intervention overlay.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication(sys.argv)
    try:
        window = DebugWindow(
            args.camera,
            args.fps,
            args.width,
            args.height,
            intervention_enabled=not args.self_test and not args.disable_intervention,
        )
    except CameraPermissionError as exc:
        QMessageBox.warning(
            None,
            "摄像头权限不可用",
            "EchoPosture 无法打开摄像头。\n\n"
            "请在 Windows 设置 > 隐私和安全性 > 摄像头 中允许桌面应用访问摄像头，"
            "确认没有其他程序独占摄像头，然后重新启动 EchoPosture。\n\n"
            f"详细信息：{exc}",
        )
        return 1
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
        print(f"high_precision={window.precision_checkbox.isChecked()}")
        print(f"high_performance={window.performance_checkbox.isChecked()}")
        window.close()
        return 0

    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
