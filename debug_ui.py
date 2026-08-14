"""
EchoPosture visual debug UI.

Left: live camera view.
Right: human-readable MediaPipe metrics, posture state, and manual calibration.
"""

from __future__ import annotations

import argparse
import ctypes
import math
import os
import sys
import time
from dataclasses import replace
from datetime import datetime
from typing import Callable, Dict, Optional, Sequence

import cv2

from windows_runtime_paths import RuntimePathBridgeError, preload_package_dll


try:
    preload_package_dll("torch", "c10.dll")
except RuntimePathBridgeError:
    # Compatibility mode remains usable; Standard mode reports the dependency
    # failure if the user selects it.
    pass

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
from PyQt5.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QCheckBox,
    QComboBox,
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
    format_calibration_profile,
    format_value,
)
from vision_backend import CompatibilityBackend, PersonObservation, PostureFeatureExtractor
from face_embedding import FaceEmbeddingPipeline, FaceEmbeddingUnavailable
from face_observation_enhancer import (
    FaceObservationEnhancer,
    face_enhanced_backend_factories,
)
from identity_model_adapters import VIT_KPRPE_WEBFACE4M
from identity_model_process import create_identity_model_adapter
from identity_verifier import (
    FaceObservation,
    IdentityVerifier,
    IDENTITY_CONFIRMED,
    IDENTITY_MISMATCH,
    TRIGGER_EXPLICIT,
    TRIGGER_HEARTBEAT,
    TRIGGER_REACQUIRED,
)
from vision_tracking import TargetManager, TargetUpdate
from vision_modes import (
    VISION_MODE_COMPATIBILITY,
    VISION_MODE_SPECS,
    VISION_MODE_STANDARD,
    backend_name,
    mode_spec,
)
from posture_science import (
    CALIBRATION_CONTAMINATION_REASONS,
    CalibrationAccumulator,
    CalibrationPlan,
    CalibrationProfile,
    PREFERRED,
    RELAXED,
    TRANSITION,
    calibration_measurement_values,
    calibration_rejection_reason,
    projected_axis_values,
)

from i18n import _t, add_listener, remove_listener


# 状态码 → 翻译键名（运行时用 _t() 取本地化文本）
STATUS_TEXT: Dict[str, str] = {
    "GOOD": "status.GOOD",
    "GOOD_PART": "status.GOOD_PART",
    "MOVING": "status.MOVING",
    "ADJUSTING": "status.ADJUSTING",
    "OBSERVING": "status.OBSERVING",
    "WATCH": "status.WATCH",
    "BAD": "status.BAD",
    "CRITICAL": "status.CRITICAL",
    "AWAY": "status.AWAY",
    "MULTI_USER": "status.MULTI_USER",
    "ACQUIRING": "status.ACQUIRING",
    "TARGET_LOCKED": "status.TARGET_LOCKED",
    "MULTI_PRESENT": "status.MULTI_PRESENT",
    "TARGET_OCCLUDED": "status.TARGET_OCCLUDED",
    "TARGET_REACQUIRING": "status.TARGET_REACQUIRING",
    "IDENTITY_UNCERTAIN": "status.IDENTITY_UNCERTAIN",
    "TARGET_AMBIGUOUS": "status.TARGET_AMBIGUOUS",
    "PROFILE_MISMATCH": "status.PROFILE_MISMATCH",
    "UNKNOWN": "status.UNKNOWN",
    "CALIBRATING": "status.CALIBRATING",
    "NEEDS_CALIB": "status.NEEDS_CALIB",
}

# 原因码 → 翻译键名（运行时用 _t() 取本地化文本）
REASON_TEXT: Dict[str, str] = {
    "press_calibrate": "reason.press_calibrate",
    "within_baseline": "reason.within_baseline",
    "too_close": "reason.too_close",
    "shoulder_tilt": "reason.shoulder_tilt",
    "missing_face_or_pose": "reason.missing_face_or_pose",
    "no_usable_metrics": "reason.no_usable_metrics",
    "face_within_baseline": "reason.face_within_baseline",
    "shoulder_within_baseline": "reason.shoulder_within_baseline",
    "within_scientific_limits": "reason.within_scientific_limits",
    "distance_calibration": "reason.distance_calibration",
    "distance_unreliable_head_turn": "reason.distance_unreliable_head_turn",
    "head_turn": "reason.head_turn",
    "head_not_facing_camera": "reason.head_not_facing_camera",
    "head_turn_eye_width_ratio": "reason.head_turn_eye_width_ratio",
    "head_turn_ratio_delta": "reason.head_turn_ratio_delta",
    "multiple_faces_detected": "reason.multiple_faces_detected",
    "user_away_s": "reason.user_away_s",
    "user_missing_observing_s": "reason.user_missing_observing_s",
    "profile_check_waiting": "reason.profile_check_waiting",
    "distance_too_close": "reason.distance_too_close",
    "distance_near": "reason.distance_near",
    "distance_too_far": "reason.distance_too_far",
    "distance_far": "reason.distance_far",
    "shoulder_asymmetry": "reason.shoulder_asymmetry",
    "shoulder_width": "reason.shoulder_width",
    "shoulder_width_narrow": "reason.shoulder_width_narrow",
    "trunk_lean": "reason.trunk_lean",
    "sustained_risk_s": "reason.sustained_risk_s",
    "smoothed_risk_score": "reason.smoothed_risk_score",
    "risk_score": "reason.risk_score",
    "risk_observing": "reason.risk_observing",
    "target_not_locked": "reason.target_not_locked",
    "target_observed": "reason.target_observed",
    "target_occluded": "reason.target_occluded",
    "target_reacquiring": "reason.target_reacquiring",
    "target_missing_observing_s": "reason.target_missing_observing_s",
    "target_missing_candidate_present": "reason.target_missing_candidate_present",
    "target_missing_s": "reason.target_missing_s",
    "target_away_s": "reason.target_away_s",
    "ambiguous_face_body_association": "reason.ambiguous_face_body_association",
    "target_face_body_association_ambiguous": "reason.target_face_body_association_ambiguous",
    "target_geometry_association_ambiguous": "reason.target_geometry_association_ambiguous",
    "association_budget_exceeded": "reason.association_budget_exceeded",
    "reacquired_candidate_needs_identity_confirmation": "reason.reacquired_candidate_needs_identity_confirmation",
    "reacquired_candidate_identity_mismatch": "reason.reacquired_candidate_identity_mismatch",
    "other_track_present": "reason.other_track_present",
    "multi_present_observing": "reason.multi_present_observing",
    "multi_exit_stabilizing_s": "reason.multi_exit_stabilizing_s",
    "target_presence_check_disabled": "reason.target_presence_check_disabled",
    "dual_anchor_calibration_required": "reason.dual_anchor_calibration_required",
    "dual_anchor_calibration_collecting": "reason.dual_anchor_calibration_collecting",
    "activity_moving_exposure_paused": "reason.activity_moving_exposure_paused",
    "posture_adjustment_exposure_paused": "reason.posture_adjustment_exposure_paused",
    "minor_posture_variation": "reason.minor_posture_variation",
    "camera_drift_recalibration_required": "reason.camera_drift_recalibration_required",
    "camera_scale_jump_measurement_abstained": "reason.camera_scale_jump_measurement_abstained",
    "camera_roll_measurement_abstained": "reason.camera_roll_measurement_abstained",
    "head_turn_measurement_abstained": "reason.head_turn_measurement_abstained",
    "sustained_head_direction": "reason.sustained_head_direction",
    "head_direction_quality_low": "reason.head_direction_quality_low",
    "head_direction_delta": "reason.head_direction_delta",
    "shared_shoulder_scale_measurement_abstained": "reason.shared_shoulder_scale_measurement_abstained",
    "posture_features_unavailable": "reason.posture_features_unavailable",
    "posture_evidence_inconclusive": "reason.posture_evidence_inconclusive",
    "post_calibration_normal_range_validation": "reason.post_calibration_normal_range_validation",
    "post_calibration_normal_range_validated": "reason.post_calibration_normal_range_validated",
    "measurement_quality_low": "reason.measurement_quality_low",
    "within_personal_posture_range": "reason.within_personal_posture_range",
    "posture_deviation": "reason.posture_deviation",
    "exposure_seconds": "reason.exposure_seconds",
    "static_hold_seconds": "reason.static_hold_seconds",
    "static_hold_bonus": "reason.static_hold_bonus",
    "confidence": "reason.confidence",
}


def _create_standard_pose_backend(**kwargs):
    """Keep the optional Standard backend out of Compatibility-only startup."""

    from standard_pose_backend import StandardPoseBackend

    return StandardPoseBackend(**kwargs)


class PostureInterventionOverlay(QWidget):
    MAX_DIM_ALPHA = 0.32
    LIVE_BLUR_SUPPORTED = True
    RAMP_UP_SECONDS = 45.0
    RAMP_DOWN_SECONDS = 0.3
    TICK_MS = 80

    def __init__(self) -> None:
        super().__init__()
        self._target_level = 0.0
        self._level = 0.0
        self._max_dim_alpha = self.MAX_DIM_ALPHA
        self._blur_scale = 1.0
        self._layer_opacity = 1.0
        self._last_tick = time.perf_counter()
        self._live_blur_enabled = False

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
            if not self.isVisible():
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
        if not self.isVisible():
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

        rect = screens[0].geometry()
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        self.setGeometry(rect)

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
        target_panel: bool = True,
        backend_factory: Optional[Callable[[], object]] = None,
        backend_factories: Optional[Dict[str, Callable[[], object]]] = None,
        initial_vision_mode: str = VISION_MODE_COMPATIBILITY,
        standard_model_path: Optional[str] = None,
        identity_model=None,
        identity_verifier: Optional[IdentityVerifier] = None,
        identity_embedding_pipeline: Optional[FaceEmbeddingPipeline] = None,
        face_enhancer_factory: Callable[[], FaceObservationEnhancer] = FaceObservationEnhancer,
    ) -> None:
        super().__init__()
        self.setWindowTitle("EchoPosture Debug Monitor")
        self.resize(1020, 700)

        compatibility_factory = backend_factory or (
            lambda: CompatibilityBackend(
                lambda: VisionEngine(camera_id=camera_id, width=width, height=height)
            )
        )
        raw_backend_factories = dict(backend_factories or {})
        raw_backend_factories.setdefault(VISION_MODE_COMPATIBILITY, compatibility_factory)
        # A caller that injects a compatibility backend (the offscreen tests
        # and diagnostic embedders) must also opt in to any injected Standard
        # backend. The normal Debug UI path registers the real local model.
        if backend_factory is None:
            raw_backend_factories.setdefault(
                VISION_MODE_STANDARD,
                lambda: _create_standard_pose_backend(
                    camera_id=camera_id,
                    width=width,
                    height=height,
                    capture_fps=fps,
                    model_path=standard_model_path,
                ),
            )
        self._backend_factories = face_enhanced_backend_factories(
            raw_backend_factories,
            enhancer_factory=face_enhancer_factory,
        )
        if initial_vision_mode not in self._backend_factories:
            initial_vision_mode = VISION_MODE_COMPATIBILITY
        self.vision_mode = initial_vision_mode
        self.engine = self._backend_factories[self.vision_mode]()
        self.target_manager = TargetManager() if target_panel else None
        self.analyzer = PostureAnalyzer(auto_calibrate=False)
        self.current_sample: Optional[VisionSample] = None
        self.current_raw_sample: Optional[VisionSample] = None
        self.current_target_update: Optional[TargetUpdate] = None
        self._current_observations: tuple[PersonObservation, ...] = ()
        self._last_frame_error_detail: Optional[str] = None
        self.normal_fps = fps
        self.high_performance_fps = 72.0
        self.high_precision_enabled = False
        self.calibration_plan = CalibrationPlan()
        self._dual_calibration_accumulator: Optional[CalibrationAccumulator] = None
        self._dual_calibration_last_rejection: Optional[str] = None
        self._scientific_profile: Optional[CalibrationProfile] = None
        self._calibration_message_key = "debug_calib_init"
        self._calibration_message_kwargs: dict[str, object] = {}
        self.identity_model = identity_model
        self.identity_verifier = identity_verifier
        self.identity_embedding_pipeline = identity_embedding_pipeline
        self.identity_model_error: Optional[str] = None
        self._identity_verifier_owned = False
        self._identity_pipeline_owned = False
        self._identity_embedding_future = None
        self._identity_embedding_context: Optional[tuple[int, str, str, Optional[int]]] = None
        self._identity_future = None
        self._identity_future_context: Optional[tuple[int, Optional[int]]] = None
        self._identity_enrollment_samples: list[FaceObservation] = []
        self._identity_enrollment_active = False
        self._identity_generation = 0
        self._last_identity_embedding_at: dict[tuple[str, Optional[int]], float] = {}
        self._identity_model_owned = False
        if (
            backend_factory is None
            or identity_model is not None
            or identity_verifier is not None
            or identity_embedding_pipeline is not None
        ):
            self._prepare_identity_components()
        self.intervention_overlay = (
            PostureInterventionOverlay() if intervention_enabled else None
        )

        self.video_label = QLabel("Camera starting...")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        self.video_label.setStyleSheet("background: #111; color: #ccc;")
        self.calibration_camera_prompt = QLabel(self.video_label)
        self.calibration_camera_prompt.setObjectName("calibrationCameraPrompt")
        self.calibration_camera_prompt.setAlignment(Qt.AlignCenter)
        self.calibration_camera_prompt.setWordWrap(True)
        self.calibration_camera_prompt.hide()
        self.calibration_camera_prompt_timer = QTimer(self)
        self.calibration_camera_prompt_timer.setSingleShot(True)
        self.calibration_camera_prompt_timer.timeout.connect(
            self.calibration_camera_prompt.hide
        )
        self.calibration_camera_stage_banner = QLabel(self.video_label)
        self.calibration_camera_stage_banner.setObjectName("calibrationCameraStageBanner")
        self.calibration_camera_stage_banner.setAlignment(Qt.AlignCenter)
        self.calibration_camera_stage_banner.setWordWrap(True)
        self.calibration_camera_stage_banner.hide()
        self.calibration_phase_rail = QFrame(self.video_label)
        self.calibration_phase_rail.setObjectName("calibrationPhaseRail")
        rail_layout = QHBoxLayout(self.calibration_phase_rail)
        # Keep enough vertical room for CJK glyphs. Large stylesheet padding
        # can otherwise leave only a few pixels of the label's contents rect
        # at the fixed camera-overlay height and visibly crop the stage text.
        rail_layout.setContentsMargins(12, 5, 12, 5)
        rail_layout.setSpacing(8)
        self.calibration_phase_preferred = QLabel()
        self.calibration_phase_preferred.setObjectName("calibrationPhasePreferred")
        self.calibration_phase_transition = QLabel("→")
        self.calibration_phase_transition.setObjectName("calibrationPhaseTransition")
        self.calibration_phase_relaxed = QLabel()
        self.calibration_phase_relaxed.setObjectName("calibrationPhaseRelaxed")
        for label in (
            self.calibration_phase_preferred,
            self.calibration_phase_transition,
            self.calibration_phase_relaxed,
        ):
            label.setAlignment(Qt.AlignCenter)
        rail_layout.addWidget(self.calibration_phase_preferred, 1)
        rail_layout.addWidget(self.calibration_phase_transition, 0)
        rail_layout.addWidget(self.calibration_phase_relaxed, 1)
        self.calibration_phase_rail.hide()

        self.status_label = QLabel(_t("debug_status_init"))
        self.status_label.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        self.status_label.setAlignment(Qt.AlignCenter)

        self.reason_label = QLabel(_t("debug_reason_init"))
        self.reason_label.setWordWrap(True)
        self.reason_label.setAlignment(Qt.AlignCenter)

        self.face_label = QLabel("--")
        self.shoulder_label = QLabel("--")
        self.distance_label = QLabel("--")
        self.trunk_label = QLabel("--")
        self.projected_trunk_axis_label = QLabel("--")
        self.projected_head_trunk_label = QLabel("--")
        self.risk_label = QLabel("--")
        self.baseline_label = QLabel("--")
        self.baseline_label.setWordWrap(True)
        self.calibration_label = QLabel(_t("debug_calib_init"))
        self.calibration_label.setWordWrap(True)
        self.calibration_stage_card = QFrame()
        self.calibration_stage_card.setObjectName("calibrationStageCard")
        stage_layout = QVBoxLayout(self.calibration_stage_card)
        stage_layout.setContentsMargins(18, 14, 18, 14)
        stage_layout.setSpacing(8)
        stage_heading = QHBoxLayout()
        stage_heading.setSpacing(14)
        self.calibration_stage_badge = QLabel()
        self.calibration_stage_badge.setObjectName("calibrationStageBadge")
        self.calibration_stage_badge.setAlignment(Qt.AlignCenter)
        self.calibration_stage_badge.setMinimumSize(92, 62)
        self.calibration_stage_title = QLabel()
        self.calibration_stage_title.setObjectName("calibrationStageTitle")
        self.calibration_stage_title.setFont(QFont("Microsoft YaHei", 21, QFont.Bold))
        self.calibration_stage_title.setWordWrap(True)
        stage_heading.addWidget(self.calibration_stage_badge, 0, Qt.AlignVCenter)
        stage_heading.addWidget(self.calibration_stage_title, 1)
        self.calibration_stage_detail = QLabel()
        self.calibration_stage_detail.setObjectName("calibrationStageDetail")
        self.calibration_stage_detail.setWordWrap(True)
        self.calibration_stage_progress = QProgressBar()
        self.calibration_stage_progress.setObjectName("calibrationStageProgress")
        self.calibration_stage_progress.setTextVisible(False)
        self.calibration_stage_progress.setRange(0, 100)
        self.calibration_stage_progress.setFixedHeight(12)
        self.calibration_stage_card.setMinimumHeight(154)
        stage_layout.addLayout(stage_heading)
        stage_layout.addWidget(self.calibration_stage_detail)
        stage_layout.addWidget(self.calibration_stage_progress)
        self._calibration_visual_phase = "idle"
        self._set_calibration_stage_visual("idle")

        self.target_state_label = QLabel("--")
        self.target_track_label = QLabel("--")
        self.target_count_label = QLabel("--")
        self.target_score_label = QLabel("--")
        self.target_motion_label = QLabel("--")
        self.target_activity_label = QLabel("--")
        self.target_reason_label = QLabel("--")
        self.target_reason_label.setWordWrap(True)

        self.vision_mode_label = QLabel(_t("debug_vision_mode"))
        self.vision_mode_combo = QComboBox()
        for spec in VISION_MODE_SPECS:
            self.vision_mode_combo.addItem(_t(spec.label_key), spec.mode)
        self.vision_mode_combo.setCurrentIndex(self._vision_mode_index(self.vision_mode))
        self.vision_mode_combo.currentIndexChanged.connect(self._switch_vision_mode)
        self.vision_mode_combo.activated.connect(self._activate_vision_mode)
        self.vision_backend_label = QLabel()
        self.vision_backend_label.setWordWrap(True)
        self._vision_backend_notice_key: Optional[str] = None
        self._vision_backend_notice_kwargs: dict[str, str] = {}
        self._set_vision_backend_status()

        self.calibrate_button = QPushButton(_t("debug_dual_calibrate_btn"))
        self.calibrate_button.clicked.connect(self.toggle_dual_anchor_calibration)
        self.legacy_calibrate_button = QPushButton(_t("debug_calibrate_btn"))
        self.legacy_calibrate_button.setObjectName("legacyCalibrationButton")
        self.legacy_calibrate_button.clicked.connect(self.calibrate_current_sample)
        self.precision_checkbox = QCheckBox(_t("debug_precision_cb"))
        self.precision_checkbox.toggled.connect(self.toggle_high_precision)
        self.distance_input = QDoubleSpinBox()
        self.distance_input.setRange(35.0, 150.0)
        self.distance_input.setDecimals(0)
        self.distance_input.setSingleStep(5.0)
        self.distance_input.setValue(60.0)
        self.distance_input.setSuffix(" cm")
        self.distance_input.setEnabled(False)
        self.distance_input.valueChanged.connect(self.update_reference_distance)
        self.performance_checkbox = QCheckBox(_t("debug_performance_cb"))
        self.performance_checkbox.toggled.connect(self.toggle_high_performance)

        # 监听全局语言变更：刷新静态 UI 文本
        add_listener(self._on_language_changed)

        self._build_layout()
        self._apply_style()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(self._interval_ms(self.normal_fps))
        self.dual_calibration_timer = QTimer(self)
        self.dual_calibration_timer.setSingleShot(True)
        self.dual_calibration_timer.timeout.connect(self._advance_dual_anchor_calibration)

        self.engine.start()
        self._refresh_runtime_backend_status()
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

        title = QLabel(_t("debug_panel_title"))
        title.setFont(QFont("Microsoft YaHei", 18, QFont.Bold))

        metric_grid = QGridLayout()
        metric_grid.setHorizontalSpacing(10)
        metric_grid.setVerticalSpacing(8)
        self.face_metric_label = QLabel(_t("debug_metric_face"))
        metric_grid.addWidget(self.face_metric_label, 0, 0)
        metric_grid.addWidget(self.face_label, 0, 1)
        self.shoulder_metric_label = QLabel(_t("debug_metric_shoulder"))
        metric_grid.addWidget(self.shoulder_metric_label, 1, 0)
        metric_grid.addWidget(self.shoulder_label, 1, 1)
        self.distance_metric_label = QLabel(_t("debug_metric_distance"))
        metric_grid.addWidget(self.distance_metric_label, 2, 0)
        metric_grid.addWidget(self.distance_label, 2, 1)
        self.trunk_metric_label = QLabel(_t("debug_metric_trunk"))
        metric_grid.addWidget(self.trunk_metric_label, 3, 0)
        metric_grid.addWidget(self.trunk_label, 3, 1)
        self.projected_trunk_axis_metric_label = QLabel(_t("debug_metric_projected_trunk_axis"))
        metric_grid.addWidget(self.projected_trunk_axis_metric_label, 4, 0)
        metric_grid.addWidget(self.projected_trunk_axis_label, 4, 1)
        self.projected_head_trunk_metric_label = QLabel(_t("debug_metric_projected_head_trunk"))
        metric_grid.addWidget(self.projected_head_trunk_metric_label, 5, 0)
        metric_grid.addWidget(self.projected_head_trunk_label, 5, 1)
        self.risk_metric_label = QLabel(_t("debug_metric_risk"))
        metric_grid.addWidget(self.risk_metric_label, 6, 0)
        metric_grid.addWidget(self.risk_label, 6, 1)
        self.baseline_metric_label = QLabel(_t("debug_metric_baseline"))
        metric_grid.addWidget(self.baseline_metric_label, 7, 0)
        metric_grid.addWidget(self.baseline_label, 7, 1)

        target_title = QLabel(_t("debug_target_title"))
        target_title.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))
        target_grid = QGridLayout()
        target_grid.setHorizontalSpacing(10)
        target_grid.setVerticalSpacing(6)
        self.target_state_metric_label = QLabel(_t("debug_target_state"))
        target_grid.addWidget(self.target_state_metric_label, 0, 0)
        target_grid.addWidget(self.target_state_label, 0, 1)
        self.target_track_metric_label = QLabel(_t("debug_target_track"))
        target_grid.addWidget(self.target_track_metric_label, 1, 0)
        target_grid.addWidget(self.target_track_label, 1, 1)
        self.target_count_metric_label = QLabel(_t("debug_target_count"))
        target_grid.addWidget(self.target_count_metric_label, 2, 0)
        target_grid.addWidget(self.target_count_label, 2, 1)
        self.target_score_metric_label = QLabel(_t("debug_target_score"))
        target_grid.addWidget(self.target_score_metric_label, 3, 0)
        target_grid.addWidget(self.target_score_label, 3, 1)
        self.target_motion_metric_label = QLabel(_t("debug_target_motion"))
        target_grid.addWidget(self.target_motion_metric_label, 4, 0)
        target_grid.addWidget(self.target_motion_label, 4, 1)
        self.target_activity_metric_label = QLabel(_t("debug_target_activity"))
        target_grid.addWidget(self.target_activity_metric_label, 5, 0)
        target_grid.addWidget(self.target_activity_label, 5, 1)
        self.target_reason_metric_label = QLabel(_t("debug_target_reason"))
        target_grid.addWidget(self.target_reason_metric_label, 6, 0, Qt.AlignTop)
        target_grid.addWidget(self.target_reason_label, 6, 1)

        panel_layout.addWidget(title)
        panel_layout.addWidget(self.status_label)
        panel_layout.addWidget(self.reason_label)
        panel_layout.addSpacing(8)
        panel_layout.addLayout(metric_grid)
        panel_layout.addSpacing(8)
        panel_layout.addWidget(target_title)
        panel_layout.addLayout(target_grid)
        panel_layout.addWidget(self.calibration_label)
        panel_layout.addWidget(self.vision_mode_label)
        panel_layout.addWidget(self.vision_mode_combo)
        panel_layout.addWidget(self.vision_backend_label)
        panel_layout.addWidget(self.precision_checkbox)
        panel_layout.addWidget(self.distance_input)
        panel_layout.addWidget(self.performance_checkbox)
        panel_layout.addStretch(1)
        panel_layout.addWidget(self.calibrate_button)
        panel_layout.addWidget(self.legacy_calibrate_button)
        self.title_label = title
        self.target_title_label = target_title

        camera_layout = QVBoxLayout()
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_layout.setSpacing(10)
        camera_layout.addWidget(self.calibration_stage_card)
        camera_layout.addWidget(self.video_label, 1)
        layout.addLayout(camera_layout, 1)
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
            QPushButton#legacyCalibrationButton {
                background: #687384;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton#legacyCalibrationButton:hover { background: #4f5968; }
            QFrame#calibrationStageCard {
                border: 2px solid #94a3b8;
                border-radius: 8px;
                background: #f8fafc;
            }
            QLabel#calibrationStageBadge {
                border-radius: 6px;
                color: white;
                font-size: 24px;
                font-weight: 800;
            }
            QLabel#calibrationStageTitle { font-size: 21px; font-weight: 800; }
            QLabel#calibrationStageDetail { font-size: 15px; font-weight: 600; }
            QProgressBar#calibrationStageProgress {
                border: none;
                border-radius: 4px;
                background: rgba(255, 255, 255, 0.55);
            }
            QComboBox {
                border: 1px solid #9aa6b2;
                border-radius: 5px;
                padding: 7px 9px;
                background: white;
                color: #1f2933;
            }
            """
        )

    def _vision_mode_index(self, mode: str) -> int:
        for index in range(self.vision_mode_combo.count()):
            if self.vision_mode_combo.itemData(index) == mode:
                return index
        return 0

    def _render_vision_backend_status(self) -> None:
        current = _t(
            "debug_vision_backend",
            mode=_t(mode_spec(self.vision_mode).label_key),
            backend=backend_name(self.engine),
        )
        if self._vision_backend_notice_key is None:
            self.vision_backend_label.setText(current)
            return
        notice = _t(
            self._vision_backend_notice_key,
            **self._vision_backend_notice_kwargs,
        )
        self.vision_backend_label.setText(
            _t("debug_vision_backend_notice", current=current, notice=notice)
        )

    def _set_vision_backend_status(
        self,
        reason_key: Optional[str] = None,
        **reason_kwargs: str,
    ) -> None:
        self._vision_backend_notice_key = reason_key
        self._vision_backend_notice_kwargs = reason_kwargs
        self._render_vision_backend_status()

    def _refresh_runtime_backend_status(self) -> None:
        if self.identity_model_error is not None:
            self._set_vision_backend_status(
                "vision_identity_model_unavailable",
                detail=self.identity_model_error,
            )
            return
        notice = getattr(self.engine, "diagnostic_notice", None)
        if notice is None:
            self._set_vision_backend_status()
            return
        reason_key, reason_kwargs = notice
        self._set_vision_backend_status(reason_key, **reason_kwargs)

    def _prepare_identity_components(self) -> None:
        if self.identity_verifier is not None and self.identity_embedding_pipeline is not None:
            return
        model = self.identity_model
        created_model = model is None
        try:
            if model is None:
                model = create_identity_model_adapter(VIT_KPRPE_WEBFACE4M)
                self.identity_model = model
            self._identity_model_owned = created_model
            if not getattr(model, "loaded", True):
                model.load()
        except Exception as exc:
            self.identity_model_error = f"{type(exc).__name__}: {exc}"
            return
        if self.identity_verifier is None:
            self.identity_verifier = IdentityVerifier(model)
            self._identity_verifier_owned = True
        if self.identity_embedding_pipeline is None:
            self.identity_embedding_pipeline = FaceEmbeddingPipeline(model)
            self._identity_pipeline_owned = True

    def _reset_identity_session(self, *, enroll: bool = False) -> None:
        self._identity_generation += 1
        self._identity_enrollment_samples = []
        self._identity_enrollment_active = enroll and self.identity_verifier is not None
        self._last_identity_embedding_at.clear()
        for future in (self._identity_embedding_future, self._identity_future):
            if future is not None:
                future.cancel()
        self._identity_embedding_future = None
        self._identity_embedding_context = None
        self._identity_future = None
        self._identity_future_context = None
        if self.identity_verifier is not None:
            self.identity_verifier.clear_template()

    @staticmethod
    def _timestamp_seconds(value) -> float:
        return value.timestamp() if isinstance(value, datetime) else float(value)

    def _schedule_identity(
        self,
        frame,
        observations: Sequence[PersonObservation],
        target_update: Optional[TargetUpdate],
    ) -> None:
        verifier = self.identity_verifier
        pipeline = self.identity_embedding_pipeline
        if verifier is None or pipeline is None or target_update is None:
            return
        observation = (
            target_update.identity_candidate_observation
            or target_update.target_observation
        )
        track_id = (
            target_update.identity_candidate_track_id
            if target_update.identity_candidate_observation is not None
            else target_update.target_track_id
        )
        if observation is None and self._identity_enrollment_active:
            eligible = tuple(
                candidate
                for candidate in observations
                if not candidate.association_ambiguous
                and candidate.face_bbox_xyxy is not None
                and len(candidate.face_landmarks or ()) >= 3
            )
            observation = eligible[0] if len(eligible) == 1 else None
        if (
            observation is None
            or observation.face_bbox_xyxy is None
            or observation.association_ambiguous
            or self._identity_embedding_future is not None
        ):
            return
        if self._identity_enrollment_active:
            kind = "enroll"
            trigger = TRIGGER_EXPLICIT
            interval = 0.0
        else:
            kind = "verify"
            trigger = (
                TRIGGER_REACQUIRED
                if target_update.state == "IDENTITY_UNCERTAIN"
                else TRIGGER_HEARTBEAT
            )
            interval = (
                verifier.config.min_event_interval_seconds
                if trigger == TRIGGER_REACQUIRED
                else verifier.config.heartbeat_seconds
            )
        key = (trigger, track_id)
        now = self._timestamp_seconds(observation.timestamp)
        previous = self._last_identity_embedding_at.get(key)
        if previous is not None and now - previous < interval:
            return
        try:
            self._identity_embedding_future = pipeline.request(frame, observation)
        except (FaceEmbeddingUnavailable, RuntimeError, ValueError):
            return
        self._last_identity_embedding_at[key] = now
        self._identity_embedding_context = (
            self._identity_generation,
            kind,
            trigger,
            track_id,
        )

    def _apply_identity_results(self) -> None:
        embedding_future = self._identity_embedding_future
        if embedding_future is not None and embedding_future.done():
            context = self._identity_embedding_context
            self._identity_embedding_future = None
            self._identity_embedding_context = None
            try:
                observation = embedding_future.result()
            except Exception:
                observation = None
            if observation is not None and context is not None and context[0] == self._identity_generation:
                _generation, kind, trigger, track_id = context
                verifier = self.identity_verifier
                if verifier is not None and kind == "enroll":
                    self._identity_enrollment_samples.append(observation)
                    self._identity_enrollment_samples = self._identity_enrollment_samples[
                        -verifier.config.max_frames:
                    ]
                    if len(self._identity_enrollment_samples) >= verifier.config.min_frames:
                        result = verifier.enroll(self._identity_enrollment_samples)
                        if result.ok:
                            self._identity_enrollment_active = False
                            self._identity_enrollment_samples = []
                elif verifier is not None:
                    future = verifier.request(
                        observation,
                        trigger=trigger,
                        track_id=track_id,
                        force=True,
                    )
                    if future is not None:
                        self._identity_future = future
                        self._identity_future_context = (self._identity_generation, track_id)

        identity_future = self._identity_future
        if identity_future is None or not identity_future.done():
            return
        context = self._identity_future_context
        self._identity_future = None
        self._identity_future_context = None
        if context is None or context[0] != self._identity_generation or self.target_manager is None:
            return
        try:
            result = identity_future.result()
        except Exception:
            self.target_manager.resolve_identity(None, context[1])
            return
        if result.state == IDENTITY_CONFIRMED:
            self.target_manager.resolve_identity(True, context[1])
        elif result.state == IDENTITY_MISMATCH:
            self.target_manager.resolve_identity(False, context[1])
        else:
            self.target_manager.resolve_identity(None, context[1])

    def _switch_vision_mode(self, index: int) -> None:
        requested_mode = self.vision_mode_combo.itemData(index)
        if not requested_mode:
            return
        if requested_mode == self.vision_mode:
            self._refresh_runtime_backend_status()
            self._resume_frame_updates()
            return
        factory = self._backend_factories.get(requested_mode)
        if factory is None:
            spec = mode_spec(requested_mode)
            self._set_vision_backend_status(spec.unavailable_reason_key)
            self.vision_mode_combo.blockSignals(True)
            self.vision_mode_combo.setCurrentIndex(self._vision_mode_index(self.vision_mode))
            self.vision_mode_combo.blockSignals(False)
            self._resume_frame_updates()
            return

        self.timer.stop()
        previous_mode = self.vision_mode
        previous_factory = self._backend_factories[previous_mode]
        self.cancel_dual_anchor_calibration()
        self._reset_identity_session()
        self.engine.close()
        next_engine = None
        try:
            next_engine = factory()
            next_engine.start()
        except Exception as exc:
            if next_engine is not None:
                try:
                    next_engine.close()
                except Exception:
                    pass
            self.engine = previous_factory()
            self.engine.start()
            self._set_vision_backend_status(
                "vision_mode_switch_failed",
                detail=str(exc),
            )
            self.vision_mode_combo.blockSignals(True)
            self.vision_mode_combo.setCurrentIndex(self._vision_mode_index(previous_mode))
            self.vision_mode_combo.blockSignals(False)
            self.timer.start(self._interval_ms(self.normal_fps))
            return

        self.engine = next_engine
        self.vision_mode = requested_mode
        if self.target_manager is not None:
            self.target_manager.reset()
        self.current_sample = None
        self.current_raw_sample = None
        self.current_target_update = None
        self._current_observations = ()
        self._last_frame_error_detail = None
        self._scientific_profile = None
        self.analyzer = HighPrecisionPostureAnalyzer(
            auto_calibrate=False,
            require_dual_anchor=True,
        )
        self._set_calibration_message("debug_calib_init")
        self._set_calibration_stage_visual("idle")
        self._refresh_runtime_backend_status()
        self.timer.start(self._interval_ms(self.normal_fps))

    def _activate_vision_mode(self, index: int) -> None:
        """Clear a stale failed-mode notice when the user reaffirms the live mode."""

        requested_mode = self.vision_mode_combo.itemData(index)
        if requested_mode == self.vision_mode:
            self._refresh_runtime_backend_status()
            self._resume_frame_updates()

    def _resume_frame_updates(self) -> None:
        if not self.timer.isActive():
            self.timer.start(self._interval_ms(self.normal_fps))

    def update_frame(self) -> None:
        try:
            frame, raw_sample = self.engine.read_frame_sample()
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
            detail = str(exc)
            if detail != self._last_frame_error_detail:
                self._last_frame_error_detail = detail
                QMessageBox.critical(self, "Camera error", detail)
            self._resume_frame_updates()
            return

        self._last_frame_error_detail = None
        self._apply_identity_results()
        self.current_raw_sample = raw_sample
        observations = tuple(self.engine.observations_for_last_sample())
        self._current_observations = observations
        target_update = None
        if self.target_manager is not None:
            target_update = self.target_manager.update(
                observations,
                timestamp=raw_sample.timestamp,
            )
        self._schedule_identity(frame, observations, target_update)
        sample = self._sample_for_target(raw_sample, target_update)
        self.current_sample = sample
        self.current_target_update = target_update
        self._collect_dual_anchor_sample(sample)
        # Automatic finalization may lock the target and replace both values;
        # do not overwrite that fresh state with this frame's pre-lock update.
        sample = self.current_sample or sample
        target_update = self.current_target_update
        if self._dual_calibration_accumulator is not None:
            decision = PostureDecision(
                "CALIBRATING",
                "dual_anchor_calibration_collecting",
                False,
                activity_state=sample.activity_state or "UNKNOWN",
            )
        else:
            decision = self.analyzer.evaluate(sample)
        self._show_frame(frame, raw_sample, observations, target_update)
        self._show_metrics(sample, decision)
        if target_update is not None:
            self._show_target_metrics(target_update)
        self._update_intervention(decision)

    def toggle_dual_anchor_calibration(self) -> None:
        if self._dual_calibration_accumulator is None:
            self.start_dual_anchor_calibration()
        else:
            self.cancel_dual_anchor_calibration()

    def start_dual_anchor_calibration(self) -> None:
        """Start the production five-second preferred countdown."""
        self._ensure_scientific_analyzer()
        if self.target_manager is not None:
            self.target_manager.reset()
            self.current_target_update = None
        self._reset_identity_session(enroll=True)
        self._dual_calibration_accumulator = CalibrationAccumulator(self.calibration_plan)
        self._dual_calibration_last_rejection = None
        self.calibrate_button.setText(_t("debug_dual_cancel_btn"))
        self.legacy_calibrate_button.setEnabled(False)
        self.precision_checkbox.setEnabled(False)
        self.dual_calibration_timer.start(
            int(round(self.calibration_plan.preferred_seconds * 1000.0))
        )
        self._set_calibration_stage_visual("preferred")
        self._set_calibration_message("debug_dual_calib_started")

    def _advance_dual_anchor_calibration(self) -> None:
        accumulator = self._dual_calibration_accumulator
        if accumulator is None:
            return
        if accumulator.phase == PREFERRED:
            self.complete_preferred_stage()
        else:
            self.finish_dual_anchor_calibration()

    def complete_preferred_stage(self, timestamp=None) -> None:
        """Close the countdown, announce relaxation, then collect silently."""

        accumulator = self._dual_calibration_accumulator
        if accumulator is None or accumulator.phase != PREFERRED:
            return
        accumulator.begin_transition(timestamp or datetime.now())
        silent_seconds = (
            self.calibration_plan.transition_seconds
            + self.calibration_plan.relaxed_seconds
            + self.calibration_plan.relaxed_max_extension_seconds
        )
        self.dual_calibration_timer.start(int(round(silent_seconds * 1000.0)) + 250)
        self._set_calibration_stage_visual("transition")
        self._set_calibration_message("debug_dual_calib_relax_now")
        self._show_calibration_camera_prompt()

    def cancel_dual_anchor_calibration(self) -> None:
        if self._dual_calibration_accumulator is None:
            return
        self._dual_calibration_accumulator = None
        self._dual_calibration_last_rejection = None
        self.dual_calibration_timer.stop()
        self.calibration_camera_prompt_timer.stop()
        self.calibration_camera_prompt.hide()
        self._reset_identity_session()
        self._restore_calibration_controls()
        self._set_calibration_stage_visual("idle")
        self._set_calibration_message("debug_dual_calib_cancelled")

    def _collect_dual_anchor_sample(self, sample: VisionSample) -> None:
        accumulator = self._dual_calibration_accumulator
        if accumulator is None:
            return

        phase = accumulator.stage_at(sample.timestamp)
        if phase == TRANSITION:
            self._set_calibration_stage_visual("transition")
            counts = accumulator.stage_counts
            self._set_calibration_message(
                "debug_dual_calib_transition",
                preferred=counts.get("preferred", 0),
                relaxed=counts.get("relaxed", 0),
            )
            return

        rejection = calibration_rejection_reason(sample, self.calibration_plan)
        if rejection is not None:
            if rejection in CALIBRATION_CONTAMINATION_REASONS:
                stage = accumulator.reject(sample.timestamp, rejection)
            else:
                stage = accumulator.skip(sample.timestamp, rejection)
            self._dual_calibration_last_rejection = rejection
        else:
            stage = accumulator.add(
                sample.timestamp,
                calibration_measurement_values(sample, self.calibration_plan),
            )
            self._dual_calibration_last_rejection = None

        counts = accumulator.stage_counts
        if stage == RELAXED and accumulator.ready_to_finalize(sample.timestamp):
            self.finish_dual_anchor_calibration()
            return
        if stage == RELAXED and accumulator.relaxed_deadline_reached(sample.timestamp):
            self.finish_dual_anchor_calibration()
            return
        if stage == PREFERRED:
            self._set_calibration_stage_visual("preferred")
            message_key = "debug_dual_calib_preferred"
        elif accumulator.relaxed_target_reached(sample.timestamp):
            self._set_calibration_stage_visual("relaxed")
            message_key = "debug_dual_calib_extending"
        else:
            self._set_calibration_stage_visual("relaxed")
            message_key = "debug_dual_calib_relaxed"
        detail = self._calibration_reason_text(self._dual_calibration_last_rejection)
        self._set_calibration_message(
            message_key,
            preferred=counts.get("preferred", 0),
            relaxed=counts.get("relaxed", 0),
            detail=detail,
        )

    def finish_dual_anchor_calibration(self) -> None:
        accumulator = self._dual_calibration_accumulator
        if accumulator is None:
            return
        self._dual_calibration_accumulator = None
        self.dual_calibration_timer.stop()
        self.calibration_camera_prompt_timer.stop()
        self.calibration_camera_prompt.hide()
        self._restore_calibration_controls()

        try:
            profile = accumulator.finalize()
        except ValueError as exc:
            self._show_dual_calibration_failure(
                self._calibration_failure_text(str(exc)),
                accumulator.stage_counts,
            )
            return

        if self.target_manager is not None and not self.target_manager.lock_calibration_target():
            self._show_dual_calibration_failure(
                _t("debug_target_calib_fail"),
                profile.stage_counts,
            )
            return
        if self.target_manager is not None and self.current_raw_sample is not None:
            self.current_target_update = self.target_manager.update(
                self._current_observations,
                timestamp=self.current_raw_sample.timestamp,
            )
            self.current_sample = self._sample_for_target(
                self.current_raw_sample,
                self.current_target_update,
            )
            self._show_target_metrics(self.current_target_update)

        self._ensure_scientific_analyzer()
        distance_cm = float(self.distance_input.value())
        if not self.analyzer.set_calibration_profile(profile, distance_cm):
            self._show_dual_calibration_failure(
                _t("calib_missing_no_common_posture_features"),
                profile.stage_counts,
            )
            return

        self._scientific_profile = profile
        counts = profile.stage_counts
        self._set_calibration_stage_visual("validating")
        self._set_calibration_message(
            "debug_dual_calib_ok",
            preferred=counts.get("preferred", 0),
            relaxed=counts.get("relaxed", 0),
            quality=profile.calibration_quality,
            features=len(profile.enabled_features),
        )
        self.baseline_label.setText(format_calibration_profile(profile))
        if self.current_sample is not None:
            decision = self.analyzer.evaluate(self.current_sample)
            self._show_metrics(self.current_sample, decision)
            self._update_intervention(decision)

    def calibrate_current_sample(self) -> None:
        """Apply the explicitly legacy one-frame baseline for comparison."""
        if self._dual_calibration_accumulator is not None:
            return
        if self.current_sample is None:
            self._set_calibration_message("debug_calib_no_sample")
            return

        if self.target_manager is not None and not self.target_manager.lock_calibration_target():
            self._set_calibration_message("debug_target_calib_fail")
            return

        self._reset_identity_session(enroll=True)

        if self.target_manager is not None and self.current_raw_sample is not None:
            self.current_target_update = self.target_manager.update(
                self._current_observations,
                timestamp=self.current_raw_sample.timestamp,
            )
            self.current_sample = self._sample_for_target(
                self.current_raw_sample,
                self.current_target_update,
            )

        old_analyzer = self.analyzer
        if self.high_precision_enabled:
            self.analyzer = HighPrecisionPostureAnalyzer(
                auto_calibrate=False,
                calibrated_distance_cm=float(self.distance_input.value()),
                require_dual_anchor=False,
            )
            self._copy_analyzer_toggles(old_analyzer, self.analyzer)
        else:
            self.analyzer = PostureAnalyzer(auto_calibrate=False)
        self._scientific_profile = None
        distance_cm = float(self.distance_input.value()) if self.high_precision_enabled else None
        if not self.analyzer.set_baseline_from_sample(self.current_sample, distance_cm):
            if self.target_manager is not None:
                self.target_manager.reset()
            self._reset_identity_session()
            self._set_calibration_message("debug_calib_fail")
            return

        self._set_calibration_message("debug_calib_ok")
        self.baseline_label.setText(format_baseline(self.analyzer.baseline))
        decision = self.analyzer.evaluate(self.current_sample)
        self._show_metrics(self.current_sample, decision)
        if self.current_target_update is not None:
            self._show_target_metrics(self.current_target_update)
        self._update_intervention(decision)

    def toggle_high_performance(self, enabled: bool) -> None:
        target_fps = self.high_performance_fps if enabled else self.normal_fps
        self.timer.setInterval(self._interval_ms(target_fps))
        self.engine.set_capture_fps(target_fps)

    def toggle_high_precision(self, enabled: bool) -> None:
        if self._dual_calibration_accumulator is not None:
            return
        old_baseline = self.analyzer.baseline
        old_analyzer = self.analyzer
        distance_cm = float(self.distance_input.value())
        self.high_precision_enabled = enabled
        self.distance_input.setEnabled(enabled)
        if enabled:
            self.analyzer = HighPrecisionPostureAnalyzer(
                auto_calibrate=False,
                calibrated_distance_cm=distance_cm,
                require_dual_anchor=True,
                calibration_profile=self._scientific_profile,
            )
            self._copy_analyzer_toggles(old_analyzer, self.analyzer)
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

    def _ensure_scientific_analyzer(self) -> None:
        if (
            isinstance(self.analyzer, HighPrecisionPostureAnalyzer)
            and self.analyzer.require_dual_anchor
        ):
            return
        old_analyzer = self.analyzer
        self.high_precision_enabled = True
        if not self.precision_checkbox.isChecked():
            self.precision_checkbox.setChecked(True)
        self.distance_input.setEnabled(True)
        self.analyzer = HighPrecisionPostureAnalyzer(
            auto_calibrate=False,
            calibrated_distance_cm=float(self.distance_input.value()),
            require_dual_anchor=True,
            calibration_profile=self._scientific_profile,
        )
        self._copy_analyzer_toggles(old_analyzer, self.analyzer)

    @staticmethod
    def _copy_analyzer_toggles(source, target) -> None:
        for name in (
            "precision_enabled",
            "presence_check_enabled",
            "identity_check_enabled",
        ):
            if hasattr(source, name) and hasattr(target, name):
                setattr(target, name, getattr(source, name))

    def _restore_calibration_controls(self) -> None:
        self.calibrate_button.setText(_t("debug_dual_calibrate_btn"))
        self.legacy_calibrate_button.setEnabled(True)
        self.precision_checkbox.setEnabled(True)

    def _set_calibration_message(self, key: str, **kwargs: object) -> None:
        self._calibration_message_key = key
        self._calibration_message_kwargs = kwargs
        self.calibration_label.setText(_t(key, **kwargs))

    def _show_dual_calibration_failure(
        self,
        detail: str,
        counts: dict[str, int],
    ) -> None:
        """Show the actionable failure on both the status line and red card."""

        preferred = counts.get(PREFERRED, 0)
        relaxed = counts.get(RELAXED, 0)
        minimum = self.calibration_plan.min_samples_per_stage
        self._set_calibration_stage_visual("failed")
        self.calibration_stage_detail.setText(
            _t(
                "debug_stage_failed_reason",
                detail=detail,
                preferred=preferred,
                relaxed=relaxed,
                minimum=minimum,
            )
        )
        self._set_calibration_message("debug_dual_calib_failed", detail=detail)

    def _calibration_stage_seconds_remaining(self, phase: str) -> Optional[int]:
        accumulator = self._dual_calibration_accumulator
        if accumulator is None or self.current_sample is None:
            return None
        if phase == "preferred":
            if accumulator.started_at is None or not isinstance(
                accumulator.started_at, datetime
            ):
                return int(math.ceil(self.calibration_plan.preferred_seconds))
            if not isinstance(self.current_sample.timestamp, datetime):
                return int(math.ceil(self.calibration_plan.preferred_seconds))
            elapsed = max(
                0.0,
                (self.current_sample.timestamp - accumulator.started_at).total_seconds(),
            )
            return max(0, int(math.ceil(self.calibration_plan.preferred_seconds - elapsed)))
        # Relaxed collection is deliberately silent. The persistent stage
        # banner explains that measurement is running without presenting a
        # second countdown users might mistake for another action.
        if phase == "relaxed":
            return None
        return None

    def _set_calibration_stage_visual(self, phase: str) -> None:
        """Make every two-anchor phase visibly distinct in the debug UI."""

        visual = {
            "idle": (
                "debug_stage_idle_title",
                "debug_stage_idle_detail",
                "#f8fafc",
                "#64748b",
                "debug_stage_badge_idle",
                0,
                "#172033",
            ),
            "preferred": (
                "debug_stage_preferred_title",
                "debug_stage_preferred_detail",
                "#17633a",
                "#0d3d24",
                "debug_stage_badge_preferred",
                20,
                "white",
            ),
            "transition": (
                "debug_stage_transition_title",
                "debug_stage_transition_detail",
                "#9a4f00",
                "#5f3000",
                "debug_stage_badge_transition",
                50,
                "white",
            ),
            "relaxed": (
                "debug_stage_relaxed_title",
                "debug_stage_relaxed_detail",
                "#6d35ad",
                "#3f1c68",
                "debug_stage_badge_relaxed",
                80,
                "white",
            ),
            "validating": (
                "debug_stage_validating_title",
                "debug_stage_validating_detail",
                "#145da0",
                "#0b355d",
                "debug_stage_badge_validating",
                90,
                "white",
            ),
            "active": (
                "debug_stage_active_title",
                "debug_stage_active_detail",
                "#145da0",
                "#0b355d",
                "debug_stage_badge_active",
                100,
                "white",
            ),
            "failed": (
                "debug_stage_failed_title",
                "debug_stage_failed_detail",
                "#a12d25",
                "#631b17",
                "debug_stage_badge_failed",
                0,
                "white",
            ),
        }
        (
            title_key,
            detail_key,
            background,
            border,
            badge_key,
            progress,
            text_color,
        ) = visual.get(phase, visual["idle"])
        self._calibration_visual_phase = phase
        self.calibration_stage_card.setProperty("calibrationPhase", phase)
        self.calibration_stage_card.setAccessibleName(f"calibration-stage-{phase}")
        self.calibration_stage_badge.setText(_t(badge_key))
        self.calibration_stage_progress.setValue(progress)
        if phase == "relaxed":
            self.calibration_stage_progress.setRange(0, 0)
        else:
            self.calibration_stage_progress.setRange(0, 100)
        title = _t(title_key)
        remaining = self._calibration_stage_seconds_remaining(phase)
        if remaining is not None:
            title = f"{title} · {remaining}s"
        self.calibration_stage_title.setText(title)
        self.calibration_stage_detail.setText(_t(detail_key))
        self.calibration_stage_card.setStyleSheet(
            "QFrame#calibrationStageCard {"
            f"background: {background}; border: 4px solid {border}; border-radius: 8px;"
            f"}} QLabel {{ background: transparent; color: {text_color}; }}"
            f" QLabel#calibrationStageBadge {{ background: {border}; }}"
            f" QProgressBar#calibrationStageProgress::chunk {{ background: {border}; }}"
        )
        self._set_calibration_camera_stage_banner(phase)

    def _set_calibration_camera_stage_banner(self, phase: str) -> None:
        visual = {
            "preferred": (
                "debug_stage_camera_preferred_banner",
                "rgba(13, 92, 52, 238)",
                "#86efac",
            ),
            "transition": (
                "debug_stage_camera_transition_banner",
                "rgba(154, 79, 0, 238)",
                "#fed7aa",
            ),
            "relaxed": (
                "debug_stage_camera_relaxed_banner",
                "rgba(91, 33, 182, 238)",
                "#ddd6fe",
            ),
        }
        config = visual.get(phase)
        if config is None:
            self.calibration_camera_stage_banner.hide()
            self.calibration_phase_rail.hide()
            self.video_label.setStyleSheet("background: #111; color: #ccc;")
            return
        text_key, background, border = config
        (
            first_text,
            second_text,
            first_background,
            second_background,
        ) = {
            "preferred": (
                _t("debug_stage_rail_preferred_active"),
                _t("debug_stage_rail_relaxed_next"),
                "#16a34a",
                "rgba(15, 23, 42, 225)",
            ),
            "transition": (
                _t("debug_stage_rail_preferred_done"),
                _t("debug_stage_rail_relaxed_now"),
                "#475569",
                "#7c3aed",
            ),
            "relaxed": (
                _t("debug_stage_rail_preferred_done"),
                _t("debug_stage_rail_relaxed_active"),
                "#475569",
                "#7c3aed",
            ),
        }[phase]
        self.calibration_camera_stage_banner.setText(_t(text_key))
        self.calibration_camera_stage_banner.setStyleSheet(
            "QLabel#calibrationCameraStageBanner {"
            f"background: {background}; color: white; border: 6px solid {border};"
            "border-radius: 8px; font-size: 30px; font-weight: 800; padding: 18px;"
            "}"
        )
        self.calibration_phase_preferred.setText(first_text)
        self.calibration_phase_relaxed.setText(second_text)
        self.calibration_phase_rail.setStyleSheet(
            "QFrame#calibrationPhaseRail {"
            "background: rgba(2, 6, 23, 235); border: 3px solid white; border-radius: 10px;"
            "} QLabel { color: white; font-size: 20px; font-weight: 800; padding: 4px 14px;"
            " border-radius: 7px; }"
            f" QLabel#calibrationPhasePreferred {{ background: {first_background}; }}"
            " QLabel#calibrationPhaseTransition { background: transparent; font-size: 28px; padding: 0; }"
            f" QLabel#calibrationPhaseRelaxed {{ background: {second_background}; }}"
        )
        video_border = {
            "preferred": "#22c55e",
            "transition": "#f59e0b",
            "relaxed": "#8b5cf6",
        }[phase]
        self.video_label.setStyleSheet(
            f"background: #111; color: #ccc; border: 12px solid {video_border};"
        )
        self._position_calibration_camera_overlays()
        self.calibration_camera_stage_banner.show()
        self.calibration_camera_stage_banner.raise_()
        self.calibration_phase_rail.show()
        self.calibration_phase_rail.raise_()

    def _show_calibration_camera_prompt(self) -> None:
        self.calibration_camera_prompt.setText(_t("debug_stage_camera_relax_prompt"))
        self.calibration_camera_prompt.setStyleSheet(
            "QLabel#calibrationCameraPrompt {"
            "background: rgba(146, 64, 14, 235); color: white;"
            "border: 4px solid white; border-radius: 8px;"
            "font-size: 30px; font-weight: 800; padding: 20px;"
            "}"
        )
        self._position_calibration_camera_overlays()
        self.calibration_camera_prompt.show()
        self.calibration_camera_prompt.raise_()
        duration_ms = max(1000, int(round(self.calibration_plan.transition_seconds * 1000.0)))
        self.calibration_camera_prompt_timer.start(duration_ms)

    def _position_calibration_camera_overlays(self) -> None:
        # The camera banner is intentionally nearly full-width: the active
        # anchor must be unambiguous even when the operator is looking only at
        # the video preview rather than the controls above it.
        banner_width = max(420, self.video_label.width() - 24)
        banner_height = 214
        banner_left = max(0, (self.video_label.width() - banner_width) // 2)
        self.calibration_camera_stage_banner.setGeometry(
            banner_left,
            8,
            banner_width,
            banner_height,
        )
        rail_width = max(420, self.video_label.width() - 48)
        rail_height = 76
        rail_left = max(0, (self.video_label.width() - rail_width) // 2)
        rail_top = max(0, self.video_label.height() - rail_height - 14)
        self.calibration_phase_rail.setGeometry(
            rail_left,
            rail_top,
            rail_width,
            rail_height,
        )
        width = min(max(360, self.video_label.width() - 80), 680)
        height = 150
        left = max(0, (self.video_label.width() - width) // 2)
        top = max(0, (self.video_label.height() - height) // 2)
        self.calibration_camera_prompt.setGeometry(left, top, width, height)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_calibration_camera_overlays()

    @staticmethod
    def _calibration_reason_text(reason: Optional[str]) -> str:
        if reason is None:
            return _t("debug_dual_calib_accepting")
        key = f"calib_missing_{reason}"
        translated = _t(key)
        return translated if translated != key else reason

    def _calibration_failure_text(self, failure: str) -> str:
        parts = [part for part in failure.split(",") if part]
        if not parts:
            return _t("calib_missing_unknown")
        return "；".join(self._calibration_reason_text(part) for part in parts)

    def _show_frame(
        self,
        frame,
        sample: VisionSample,
        observations: Sequence[PersonObservation] = (),
        target_update: Optional[TargetUpdate] = None,
    ) -> None:
        annotated = frame.copy()
        if self.vision_mode == VISION_MODE_STANDARD:
            self._draw_person_boxes(annotated, observations, target_update)
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

    @staticmethod
    def _draw_person_boxes(
        frame,
        observations: Sequence[PersonObservation],
        target_update: Optional[TargetUpdate],
    ) -> None:
        height, width = frame.shape[:2]
        visible_tracks = (
            tuple(
                (track.track_id, track.observation)
                for track in target_update.tracks
                if track.missed_frames == 0
            )
            if target_update is not None
            else ()
        )
        boxes = visible_tracks or tuple(
            (index, observation)
            for index, observation in enumerate(observations, start=1)
        )
        for track_id, observation in boxes:
            values = observation.bbox_xyxy
            if len(values) != 4 or not all(math.isfinite(value) for value in values):
                continue
            left = max(0, min(width - 1, int(round(values[0]))))
            top = max(0, min(height - 1, int(round(values[1]))))
            right = max(0, min(width - 1, int(round(values[2]))))
            bottom = max(0, min(height - 1, int(round(values[3]))))
            if right <= left or bottom <= top:
                continue
            is_target = (
                target_update is not None
                and target_update.target_track_id == track_id
            )
            color = (80, 220, 80) if is_target else (0, 200, 255)
            thickness = 3 if is_target else 2
            cv2.rectangle(
                frame,
                (left, top),
                (right, bottom),
                color,
                thickness,
                cv2.LINE_AA,
            )
            label = f"TARGET #{track_id}" if is_target else f"PERSON #{track_id}"
            label_y = max(18, top - 7)
            cv2.putText(
                frame,
                label,
                (left, label_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                color,
                2,
                cv2.LINE_AA,
            )
            face_values = observation.face_bbox_xyxy
            if (
                face_values is None
                or len(face_values) != 4
                or not all(math.isfinite(value) for value in face_values)
            ):
                continue
            face_left = max(0, min(width - 1, int(round(face_values[0]))))
            face_top = max(0, min(height - 1, int(round(face_values[1]))))
            face_right = max(0, min(width - 1, int(round(face_values[2]))))
            face_bottom = max(0, min(height - 1, int(round(face_values[3]))))
            if face_right <= face_left or face_bottom <= face_top:
                continue
            cv2.rectangle(
                frame,
                (face_left, face_top),
                (face_right, face_bottom),
                (255, 180, 70),
                2,
                cv2.LINE_AA,
            )

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

        for ear in (sample.left_ear_point, sample.right_ear_point):
            ear_point = self._point(ear)
            if ear_point:
                cv2.circle(frame, ear_point, 4, neck_color, -1, cv2.LINE_AA)

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
        if (
            self._dual_calibration_accumulator is None
            and self._calibration_visual_phase == "validating"
            and decision.reason == "post_calibration_normal_range_validated"
        ):
            self._set_calibration_stage_visual("active")
            self._set_calibration_message("debug_dual_calib_active")
        self.status_label.setText(_t(STATUS_TEXT.get(decision.status, decision.status)))
        self.reason_label.setText(self._human_reason(decision.reason))
        self.status_label.setStyleSheet(self._status_style(decision.status))

        face_text = (
            _t("debug_face_suffix", v=format_value(sample.interpupillary_px))
            if sample.face_required_for_calibration
            else _t("debug_face_not_used_standard")
        )
        shoulder_text = _t("debug_shoulder_suffix", v=format_value(sample.shoulder_diff_px))
        estimated_distance = None
        if isinstance(self.analyzer, HighPrecisionPostureAnalyzer):
            estimated_distance = self.analyzer.estimated_distance_cm(sample)
        distance_text = format_value(estimated_distance, "cm")
        trunk_text = format_value(sample.trunk_lean_deg, "deg")
        projected_axes = projected_axis_values(sample)
        projected_trunk_text = format_value(
            projected_axes.get("projected_trunk_axis_deg"),
            "deg",
        )
        projected_head_trunk_text = format_value(
            projected_axes.get("projected_head_trunk_angle_deg"),
            "deg",
        )
        if decision.calibration_quality > 0.0:
            risk_text = (
                f"{decision.posture_deviation:.2f} / "
                f"{decision.risk_score / 100.0:.2f} / "
                f"{decision.exposure_seconds:.1f}s / {decision.confidence:.2f}"
            )
            if decision.static_hold_seconds > 0.0 or decision.static_hold_bonus > 0.0:
                risk_text += (
                    f" / {_t('reason.static_hold_seconds')}="
                    f"{decision.static_hold_seconds:.1f}s"
                    f" / {_t('reason.static_hold_bonus')}={decision.static_hold_bonus:.2f}"
                )
        else:
            risk_text = (
                f"{decision.risk_score:.0f} / {decision.sustained_seconds:.1f}s"
                if decision.risk_score
                else "--"
            )
        self.face_label.setText(face_text)
        self.shoulder_label.setText(shoulder_text)
        self.distance_label.setText(distance_text)
        self.trunk_label.setText(trunk_text)
        self.projected_trunk_axis_label.setText(projected_trunk_text)
        self.projected_head_trunk_label.setText(projected_head_trunk_text)
        self.target_motion_label.setText(
            "--" if sample.target_motion is None else f"{sample.target_motion:.3f} /s"
        )
        activity_key = f"debug_activity_{sample.activity_state or 'UNKNOWN'}"
        self.target_activity_label.setText(_t(activity_key))
        self.risk_label.setText(risk_text)
        profile = getattr(self.analyzer, "calibration_profile", None)
        self.baseline_label.setText(
            format_calibration_profile(profile)
            if profile is not None
            else format_baseline(self.analyzer.baseline)
        )

    @staticmethod
    def _sample_for_target(
        raw_sample: VisionSample,
        target_update: Optional[TargetUpdate],
    ) -> VisionSample:
        if target_update is None:
            return raw_sample
        sample = raw_sample
        if target_update.target_observation is not None:
            sample = PostureFeatureExtractor.to_sample(target_update.target_observation)
        return replace(
            sample,
            target_track_id=target_update.target_track_id,
            target_state=target_update.state,
            target_observed=target_update.target_observation is not None,
            person_count=target_update.person_count,
            target_reason=target_update.reason,
            target_motion=target_update.target_motion,
            activity_state=target_update.activity_state,
        )

    def _show_target_metrics(self, update: TargetUpdate) -> None:
        state = _t(STATUS_TEXT.get(update.state, update.state))
        self.target_state_label.setText(state)
        self.target_track_label.setText(
            str(update.target_track_id) if update.target_track_id is not None else "--"
        )
        self.target_count_label.setText(str(update.person_count))
        target_track = next(
            (track for track in update.tracks if track.track_id == update.target_track_id),
            None,
        )
        score = target_track.target_match_score if target_track is not None else None
        self.target_score_label.setText("--" if score is None else f"{score:.2f}")
        self.target_reason_label.setText(self._human_reason(update.reason))

    def _update_intervention(self, decision: PostureDecision) -> None:
        if self.intervention_overlay is None:
            return

        self.intervention_overlay.set_warning_active(
            decision.status in {"BAD", "CRITICAL"}
        )

    def _show_camera_permission_warning(self, detail: str) -> None:
        self._show_warning_dialog(
            _t("warn_camera_perm_title"),
            _t("warn_camera_perm_body", detail=detail),
        )

    def _show_camera_black_frame_warning(self, detail: str) -> None:
        self._show_warning_dialog(
            _t("warn_camera_black_title"),
            _t("warn_camera_black_body", detail=detail),
        )

    def _show_warning_dialog(self, title: str, message: str) -> None:
        box = QMessageBox(QMessageBox.Warning, title, message, QMessageBox.Ok, self)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.exec_()

    def _on_language_changed(self) -> None:
        """语言变更回调：刷新所有静态 UI 文本。

        动态标签（status_label / reason_label / face_label 等）由 update_frame
        周期刷新，会自动用新语言；这里只刷一次性的静态控件。
        """
        self.title_label.setText(_t("debug_panel_title"))
        self.status_label.setText(_t("debug_status_init"))
        self.reason_label.setText(_t("debug_reason_init"))
        self.calibration_label.setText(
            _t(self._calibration_message_key, **self._calibration_message_kwargs)
        )
        self.calibrate_button.setText(
            _t(
                "debug_dual_cancel_btn"
                if self._dual_calibration_accumulator is not None
                else "debug_dual_calibrate_btn"
            )
        )
        self.legacy_calibrate_button.setText(_t("debug_calibrate_btn"))
        if not self.calibration_camera_prompt.isHidden():
            self.calibration_camera_prompt.setText(_t("debug_stage_camera_relax_prompt"))
        self._set_calibration_stage_visual(self._calibration_visual_phase)
        self.precision_checkbox.setText(_t("debug_precision_cb"))
        self.performance_checkbox.setText(_t("debug_performance_cb"))
        self.vision_mode_label.setText(_t("debug_vision_mode"))
        for index, spec in enumerate(VISION_MODE_SPECS):
            self.vision_mode_combo.setItemText(index, _t(spec.label_key))
        self._render_vision_backend_status()
        self.face_metric_label.setText(_t("debug_metric_face"))
        self.shoulder_metric_label.setText(_t("debug_metric_shoulder"))
        self.distance_metric_label.setText(_t("debug_metric_distance"))
        self.trunk_metric_label.setText(_t("debug_metric_trunk"))
        self.projected_trunk_axis_metric_label.setText(_t("debug_metric_projected_trunk_axis"))
        self.projected_head_trunk_metric_label.setText(_t("debug_metric_projected_head_trunk"))
        self.risk_metric_label.setText(_t("debug_metric_risk"))
        self.baseline_metric_label.setText(_t("debug_metric_baseline"))
        self.target_title_label.setText(_t("debug_target_title"))
        self.target_state_metric_label.setText(_t("debug_target_state"))
        self.target_track_metric_label.setText(_t("debug_target_track"))
        self.target_count_metric_label.setText(_t("debug_target_count"))
        self.target_score_metric_label.setText(_t("debug_target_score"))
        self.target_motion_metric_label.setText(_t("debug_target_motion"))
        self.target_activity_metric_label.setText(_t("debug_target_activity"))
        self.target_reason_metric_label.setText(_t("debug_target_reason"))

    def _human_reason(self, reason: str) -> str:
        if not reason:
            return "--"

        # 用 reason key 直接替换为本地化文本（_t 自动按当前语言返回）
        translated = reason
        for key, tkey in REASON_TEXT.items():
            translated = translated.replace(key, _t(tkey))
        translated = translated.replace("missing=", _t("reason_frag.missing"))
        translated = translated.replace("face", _t("reason_frag.face"))
        translated = translated.replace("shoulder", _t("reason_frag.shoulder"))
        translated = translated.replace("trunk", _t("reason_frag.trunk"))
        translated = translated.replace("distance", _t("reason_frag.distance"))
        translated = translated.replace("baseline", _t("reason_frag.baseline"))
        translated = translated.replace("+", " / ")
        translated = translated.replace(",", "，")
        translated = translated.replace(";", "；")
        return translated

    @staticmethod
    def _status_style(status: str) -> str:
        if status in {"BAD", "CRITICAL"}:
            return "color: #b42318;"
        if status in {
            "AWAY",
            "MULTI_USER",
            "MULTI_PRESENT",
            "TARGET_OCCLUDED",
            "TARGET_REACQUIRING",
            "IDENTITY_UNCERTAIN",
            "TARGET_AMBIGUOUS",
            "PROFILE_MISMATCH",
        }:
            return "color: #6b7280;"
        if status == "WATCH":
            return "color: #b7791f;"
        if status == "MOVING":
            return "color: #2563eb;"
        if status == "ADJUSTING":
            return "color: #0f766e;"
        if status == "OBSERVING":
            return "color: #6d28d9;"
        if status in {"GOOD", "GOOD_PART"}:
            return "color: #157347;"
        return "color: #6b7280;"

    def closeEvent(self, event) -> None:
        remove_listener(self._on_language_changed)
        self.timer.stop()
        self.dual_calibration_timer.stop()
        self._reset_identity_session()
        if self.intervention_overlay is not None:
            self.intervention_overlay.force_clear()
            self.intervention_overlay.close()
        self.engine.close()
        if self._identity_pipeline_owned and self.identity_embedding_pipeline is not None:
            self.identity_embedding_pipeline.close()
            self.identity_embedding_pipeline = None
        if self._identity_verifier_owned and self.identity_verifier is not None:
            self.identity_verifier.close()
            self.identity_verifier = None
        if self._identity_model_owned and self.identity_model is not None:
            self.identity_model.close()
            self.identity_model = None
        super().closeEvent(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPosture visual debug UI.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--fps", type=float, default=4.0, help="Detection frequency. Default: 4")
    parser.add_argument("--width", type=int, default=640, help="Capture width. Default: 640")
    parser.add_argument("--height", type=int, default=480, help="Capture height. Default: 480")
    parser.add_argument(
        "--standard-model",
        default=None,
        help=(
            "Local yolo26n-pose.pt path for Debug UI standard mode. "
            "Automatic downloads are disabled."
        ),
    )
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
    parser.add_argument(
        "--target-panel",
        dest="target_panel",
        action="store_true",
        default=True,
        help="Show live P3/P4 target tracking details (default).",
    )
    parser.add_argument(
        "--no-target-panel",
        dest="target_panel",
        action="store_false",
        help="Use the legacy single-sample debug path for comparison.",
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
            target_panel=args.target_panel,
            standard_model_path=args.standard_model,
        )
    except CameraPermissionError as exc:
        QMessageBox.warning(
            None,
            _t("warn_camera_perm_title"),
            _t("warn_camera_perm_body", detail=exc),
        )
        return 1
    except Exception as exc:
        QMessageBox.critical(None, "Startup error", str(exc))
        return 1

    if args.self_test:
        window.update_frame()
        # Keep the packaged smoke-test contract fast and camera-focused. The
        # interactive UI's primary button runs the full five-second profile;
        # this explicit call exercises the labelled legacy comparison only.
        window.calibrate_current_sample()
        print(f"status={window.status_label.text()}")
        print(f"face={window.face_label.text()}")
        print(f"shoulder={window.shoulder_label.text()}")
        print(f"baseline={window.baseline_label.text()}")
        print(f"calibration={window.calibration_label.text()}")
        print(f"target_state={window.target_state_label.text()}")
        print(f"target_track={window.target_track_label.text()}")
        print(f"target_count={window.target_count_label.text()}")
        print(f"target_score={window.target_score_label.text()}")
        print(f"target_reason={window.target_reason_label.text()}")
        print(f"high_precision={window.precision_checkbox.isChecked()}")
        print(f"high_performance={window.performance_checkbox.isChecked()}")
        print("calibration_mode=legacy-smoke-test")
        window.close()
        return 0

    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
