"""
EchoPosture - Step 1 vision sensing and posture decision test.

This script silently reads the webcam and prints:
1. Interpupillary pixel distance from MediaPipe Face Mesh iris landmarks.
2. Shoulder height difference from MediaPipe Pose landmarks.
3. A minimal GOOD/BAD/UNKNOWN posture decision after calibration.

No camera preview window is opened. Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

import cv2
import mediapipe as mp

from posture_science import (
    CalibrationProfile,
    ExposureAccumulator,
    PosturePolicy,
    aggregate_sample_quality,
    measurement_values,
    runtime_measurement_values,
    score_posture_deviation,
    shared_scale_measurement_unstable,
)


Point = Tuple[float, float]


class CameraPermissionError(RuntimeError):
    """Raised when the camera cannot be opened by the OS or privacy policy."""


class CameraBlackFrameError(RuntimeError):
    """Raised when the camera opens but returns unusably dark frames."""


LEFT_IRIS = (468, 469, 470, 471, 472)
RIGHT_IRIS = (473, 474, 475, 476, 477)
FACE_NOSE = 1
NOSE = 0
LEFT_EAR = 7
RIGHT_EAR = 8
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12
LEFT_HIP = 23
RIGHT_HIP = 24


@dataclass(frozen=True)
class VisionSample:
    timestamp: datetime
    interpupillary_px: Optional[float]
    shoulder_diff_px: Optional[float]
    signed_shoulder_diff_px: Optional[float]
    shoulder_width_px: Optional[float]
    trunk_lean_deg: Optional[float]
    face_detected: bool
    pose_detected: bool
    face_count: int = 0
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    left_eye_center: Optional[Point] = None
    right_eye_center: Optional[Point] = None
    nose_point: Optional[Point] = None
    left_shoulder_point: Optional[Point] = None
    right_shoulder_point: Optional[Point] = None
    shoulder_center: Optional[Point] = None
    left_hip_point: Optional[Point] = None
    right_hip_point: Optional[Point] = None
    hip_center: Optional[Point] = None
    face_nose_point: Optional[Point] = None
    head_turn_ratio: Optional[float] = None
    torso_height_px: Optional[float] = None
    left_ear_point: Optional[Point] = None
    right_ear_point: Optional[Point] = None
    face_quality: Optional[float] = None
    pose_quality: Optional[float] = None
    nose_confidence: Optional[float] = None
    left_ear_confidence: Optional[float] = None
    right_ear_confidence: Optional[float] = None
    left_shoulder_confidence: Optional[float] = None
    right_shoulder_confidence: Optional[float] = None
    left_hip_confidence: Optional[float] = None
    right_hip_confidence: Optional[float] = None
    target_motion: Optional[float] = None
    activity_state: Optional[str] = None
    camera_drift: bool = False
    target_track_id: Optional[int] = None
    target_state: Optional[str] = None
    target_observed: Optional[bool] = None
    person_count: Optional[int] = None
    target_reason: Optional[str] = None


def calibration_sample_missing_fields(sample: VisionSample) -> tuple[str, ...]:
    """Return completeness conditions missing from one calibration sample."""
    missing: list[str] = []
    if (
        sample.face_count != 1
        or (sample.person_count is not None and sample.person_count != 1)
        or sample.target_state in {"MULTI_PRESENT", "TARGET_AMBIGUOUS"}
    ):
        missing.append("single_person")
    if not sample.face_detected:
        missing.append("face_detected")
    if not sample.pose_detected:
        missing.append("pose_detected")
    for field in (
        "interpupillary_px",
        "signed_shoulder_diff_px",
        "shoulder_width_px",
        "trunk_lean_deg",
    ):
        if getattr(sample, field) is None:
            missing.append(field)
    if sample.face_quality is not None and sample.face_quality < 0.65:
        missing.append("face_quality_low")
    if sample.pose_quality is not None and sample.pose_quality < 0.65:
        missing.append("pose_quality_low")
    if sample.target_motion is not None and sample.target_motion > 0.20:
        missing.append("target_moving")
    return tuple(missing)


def calibration_sample_is_complete(sample: VisionSample) -> bool:
    """Return whether a sample is safe to use for a posture baseline.

    Requiring all core metrics from one observation prevents combining face
    and pose data from different people or unrelated moments.
    """
    return not calibration_sample_missing_fields(sample)


@dataclass(frozen=True)
class PostureDecision:
    status: str
    reason: str
    calibrated: bool
    risk_score: float = 0.0
    sustained_seconds: float = 0.0
    environment_state: Optional[str] = None
    target_track_id: Optional[int] = None
    posture_deviation: float = 0.0
    exposure_seconds: float = 0.0
    confidence: float = 0.0
    calibration_quality: float = 0.0
    activity_state: str = "UNKNOWN"


@dataclass(frozen=True)
class PostureBaseline:
    interpupillary_px: Optional[float] = None
    signed_shoulder_diff_px: Optional[float] = None
    shoulder_width_px: Optional[float] = None
    trunk_lean_deg: Optional[float] = None
    head_turn_ratio: Optional[float] = None
    face_shoulder_ratio: Optional[float] = None
    torso_shoulder_ratio: Optional[float] = None
    calibrated_distance_cm: Optional[float] = None


class PostureAnalyzer:
    def __init__(
        self,
        calibration_samples: int = 8,
        too_close_ratio: float = 1.25,
        shoulder_threshold_px: float = 28.0,
        baseline: Optional[PostureBaseline] = None,
        auto_calibrate: bool = True,
        calibrated_distance_cm: Optional[float] = None,
    ) -> None:
        self.calibration_samples = max(1, calibration_samples)
        self.too_close_ratio = too_close_ratio
        self.shoulder_threshold_px = shoulder_threshold_px
        self.baseline = baseline
        self.auto_calibrate = auto_calibrate
        self.calibrated_distance_cm = calibrated_distance_cm
        self._pupil_calibration_values: List[float] = []
        self._shoulder_calibration_values: List[float] = []
        self._shoulder_width_calibration_values: List[float] = []
        self._trunk_calibration_values: List[float] = []

    @property
    def calibrated(self) -> bool:
        return self.baseline is not None and (
            self.baseline.interpupillary_px is not None
            or self.baseline.signed_shoulder_diff_px is not None
        )

    def evaluate(self, sample: VisionSample) -> PostureDecision:
        if self.auto_calibrate and calibration_sample_is_complete(sample):
            self._update_baseline(sample)
        if self.baseline is None:
            if not self.auto_calibrate:
                return PostureDecision("NEEDS_CALIB", "press_calibrate", False)
            return PostureDecision("UNKNOWN", "no_usable_metrics", False)

        active_metrics = []
        missing_metrics = []
        reasons = []

        if self.baseline.interpupillary_px is None:
            missing_metrics.append("face_baseline")
        elif sample.interpupillary_px is None:
            missing_metrics.append("face")
        else:
            active_metrics.append("face")
            too_close_limit = self.baseline.interpupillary_px * self.too_close_ratio
            if sample.interpupillary_px > too_close_limit:
                reasons.append("too_close")

        if self.baseline.signed_shoulder_diff_px is None:
            missing_metrics.append("shoulder_baseline")
        elif sample.signed_shoulder_diff_px is None:
            missing_metrics.append("shoulder")
        else:
            active_metrics.append("shoulder")
            shoulder_delta = abs(
                sample.signed_shoulder_diff_px - self.baseline.signed_shoulder_diff_px
            )
            if shoulder_delta > self.shoulder_threshold_px:
                reasons.append("shoulder_tilt")

        if not active_metrics:
            calibration_status = self._calibration_status()
            if calibration_status:
                return PostureDecision("CALIBRATING", calibration_status, False)
            return PostureDecision("UNKNOWN", ",".join(missing_metrics), self.calibrated)

        if reasons:
            return PostureDecision("BAD", ",".join(reasons), self.calibrated)

        if missing_metrics:
            return PostureDecision(
                "GOOD_PART",
                f"{'+'.join(active_metrics)}_within_baseline;"
                f"missing={'+'.join(missing_metrics)}",
                self.calibrated,
            )
        return PostureDecision("GOOD", "within_baseline", self.calibrated)

    def set_calibrated_distance_cm(self, distance_cm: Optional[float]) -> None:
        self.calibrated_distance_cm = distance_cm
        if self.baseline is not None:
            self.baseline = PostureBaseline(
                interpupillary_px=self.baseline.interpupillary_px,
                signed_shoulder_diff_px=self.baseline.signed_shoulder_diff_px,
                shoulder_width_px=self.baseline.shoulder_width_px,
                trunk_lean_deg=self.baseline.trunk_lean_deg,
                head_turn_ratio=self.baseline.head_turn_ratio,
                face_shoulder_ratio=self.baseline.face_shoulder_ratio,
                torso_shoulder_ratio=self.baseline.torso_shoulder_ratio,
                calibrated_distance_cm=distance_cm,
            )

    def set_baseline_from_sample(
        self,
        sample: VisionSample,
        calibrated_distance_cm: Optional[float] = None,
    ) -> bool:
        if (
            sample.interpupillary_px is None
            and sample.signed_shoulder_diff_px is None
            and sample.trunk_lean_deg is None
        ):
            return False

        distance_cm = (
            calibrated_distance_cm
            if calibrated_distance_cm is not None
            else self.calibrated_distance_cm
        )
        face_shoulder_ratio, torso_shoulder_ratio = self._profile_ratios(sample)
        self.baseline = PostureBaseline(
            interpupillary_px=sample.interpupillary_px,
            signed_shoulder_diff_px=sample.signed_shoulder_diff_px,
            shoulder_width_px=sample.shoulder_width_px,
            trunk_lean_deg=sample.trunk_lean_deg,
            head_turn_ratio=sample.head_turn_ratio,
            face_shoulder_ratio=face_shoulder_ratio,
            torso_shoulder_ratio=torso_shoulder_ratio,
            calibrated_distance_cm=distance_cm,
        )
        self._pupil_calibration_values.clear()
        self._shoulder_calibration_values.clear()
        self._shoulder_width_calibration_values.clear()
        self._trunk_calibration_values.clear()
        return True

    def reset_baseline(self) -> None:
        self.baseline = None
        self._pupil_calibration_values.clear()
        self._shoulder_calibration_values.clear()
        self._shoulder_width_calibration_values.clear()
        self._trunk_calibration_values.clear()

    def _update_baseline(self, sample: VisionSample) -> None:
        pupil_baseline = self.baseline.interpupillary_px if self.baseline else None
        shoulder_baseline = self.baseline.signed_shoulder_diff_px if self.baseline else None
        shoulder_width_baseline = self.baseline.shoulder_width_px if self.baseline else None
        trunk_baseline = self.baseline.trunk_lean_deg if self.baseline else None
        head_turn_baseline = self.baseline.head_turn_ratio if self.baseline else None
        face_shoulder_baseline = self.baseline.face_shoulder_ratio if self.baseline else None
        torso_shoulder_baseline = self.baseline.torso_shoulder_ratio if self.baseline else None

        if pupil_baseline is None and sample.interpupillary_px is not None:
            self._pupil_calibration_values.append(sample.interpupillary_px)
            if len(self._pupil_calibration_values) >= self.calibration_samples:
                pupil_baseline = sum(self._pupil_calibration_values) / len(
                    self._pupil_calibration_values
                )

        if shoulder_baseline is None and sample.signed_shoulder_diff_px is not None:
            self._shoulder_calibration_values.append(sample.signed_shoulder_diff_px)
            if len(self._shoulder_calibration_values) >= self.calibration_samples:
                shoulder_baseline = sum(self._shoulder_calibration_values) / len(
                    self._shoulder_calibration_values
                )

        if shoulder_width_baseline is None and sample.shoulder_width_px is not None:
            self._shoulder_width_calibration_values.append(sample.shoulder_width_px)
            if len(self._shoulder_width_calibration_values) >= self.calibration_samples:
                shoulder_width_baseline = sum(self._shoulder_width_calibration_values) / len(
                    self._shoulder_width_calibration_values
                )

        if trunk_baseline is None and sample.trunk_lean_deg is not None:
            self._trunk_calibration_values.append(sample.trunk_lean_deg)
            if len(self._trunk_calibration_values) >= self.calibration_samples:
                trunk_baseline = sum(self._trunk_calibration_values) / len(
                    self._trunk_calibration_values
                )

        if head_turn_baseline is None and sample.head_turn_ratio is not None:
            head_turn_baseline = sample.head_turn_ratio

        face_shoulder_ratio, torso_shoulder_ratio = self._profile_ratios(sample)
        if face_shoulder_baseline is None:
            face_shoulder_baseline = face_shoulder_ratio
        if torso_shoulder_baseline is None:
            torso_shoulder_baseline = torso_shoulder_ratio

        if (
            pupil_baseline is not None
            or shoulder_baseline is not None
            or trunk_baseline is not None
        ):
            self.baseline = PostureBaseline(
                interpupillary_px=pupil_baseline,
                signed_shoulder_diff_px=shoulder_baseline,
                shoulder_width_px=shoulder_width_baseline,
                trunk_lean_deg=trunk_baseline,
                head_turn_ratio=head_turn_baseline,
                face_shoulder_ratio=face_shoulder_baseline,
                torso_shoulder_ratio=torso_shoulder_baseline,
                calibrated_distance_cm=self.calibrated_distance_cm,
            )

    def _calibration_status(self) -> str:
        parts = []
        if self.baseline is None or self.baseline.interpupillary_px is None:
            parts.append(
                f"face={len(self._pupil_calibration_values)}/{self.calibration_samples}"
            )
        if self.baseline is None or self.baseline.signed_shoulder_diff_px is None:
            parts.append(
                f"shoulder={len(self._shoulder_calibration_values)}/{self.calibration_samples}"
            )
        return ",".join(parts)

    @staticmethod
    def _profile_ratios(sample: VisionSample) -> Tuple[Optional[float], Optional[float]]:
        face_shoulder_ratio = None
        torso_shoulder_ratio = None
        if sample.shoulder_width_px is not None and sample.shoulder_width_px > 0:
            if sample.interpupillary_px is not None:
                face_shoulder_ratio = sample.interpupillary_px / sample.shoulder_width_px
            if sample.torso_height_px is not None:
                torso_shoulder_ratio = sample.torso_height_px / sample.shoulder_width_px
        return face_shoulder_ratio, torso_shoulder_ratio


class HighPrecisionPostureAnalyzer(PostureAnalyzer):
    def __init__(
        self,
        calibration_samples: int = 8,
        baseline: Optional[PostureBaseline] = None,
        auto_calibrate: bool = True,
        calibrated_distance_cm: Optional[float] = None,
        bad_sustain_seconds: float = 8.0,
        critical_sustain_seconds: float = 30.0,
        risk_clear_seconds: float = 4.0,
        away_grace_seconds: float = 2.0,
        multi_present_confirm_seconds: float = 0.3,
        require_dual_anchor: bool = False,
        calibration_profile: Optional[CalibrationProfile] = None,
        posture_policy: Optional[PosturePolicy] = None,
    ) -> None:
        super().__init__(
            calibration_samples=calibration_samples,
            baseline=baseline,
            auto_calibrate=auto_calibrate,
            calibrated_distance_cm=calibrated_distance_cm,
        )
        self.bad_sustain_seconds = bad_sustain_seconds
        self.critical_sustain_seconds = critical_sustain_seconds
        self.risk_clear_seconds = risk_clear_seconds
        self.risk_start_score = 35.0
        self.away_grace_seconds = away_grace_seconds
        self.multi_present_confirm_seconds = max(0.0, multi_present_confirm_seconds)
        self.require_dual_anchor = require_dual_anchor
        self.calibration_profile: Optional[CalibrationProfile] = None
        self.posture_policy = posture_policy or PosturePolicy()
        self.exposure_accumulator = ExposureAccumulator(self.posture_policy)
        self.legacy_calibration_used = False
        self._camera_drifted = False
        self._post_calibration_validation_required = False
        self._post_calibration_validation_started_at: Optional[datetime] = None
        # 运行时功能开关（UI 主线程写、工作线程读；GIL 下 bool 读写原子，
        # evaluate 每帧读取一次即可生效）。默认全开，与历史行为一致。
        self.precision_enabled = True        # False → 回退到基础阈值判定
        self.presence_check_enabled = True   # False → 不产出 AWAY/MULTI_USER
        self.identity_check_enabled = True   # False → 不做换人比对
        self._risk_started_at: Optional[datetime] = None
        self._last_risky_at: Optional[datetime] = None
        self._smoothed_score = 0.0
        self._away_started_at: Optional[datetime] = None
        self._multi_started_at: Optional[datetime] = None
        self._requires_profile_check = False
        if calibration_profile is not None:
            self.set_calibration_profile(calibration_profile, calibrated_distance_cm)

    @property
    def calibrated(self) -> bool:
        if self.calibration_profile is not None:
            return self.calibration_profile.scientific_ready
        return super().calibrated

    def set_baseline_from_sample(
        self,
        sample: VisionSample,
        calibrated_distance_cm: Optional[float] = None,
        legacy_debug: bool = False,
    ) -> bool:
        """Set a legacy single-sample baseline for explicit debug/self-test use.

        Production constructs this analyzer with ``require_dual_anchor=True``;
        that path refuses this compatibility entry point.
        """
        if self.require_dual_anchor and not legacy_debug:
            return False
        ok = super().set_baseline_from_sample(sample, calibrated_distance_cm)
        self.legacy_calibration_used = ok
        return ok

    def set_calibration_profile(
        self,
        profile: CalibrationProfile,
        calibrated_distance_cm: Optional[float] = None,
    ) -> bool:
        if not profile.scientific_ready:
            return False

        def mean(name: str) -> Optional[float]:
            stats = profile.preferred.get(name)
            return stats.mean if stats is not None else None

        self.calibration_profile = profile
        self.baseline = PostureBaseline(
            interpupillary_px=mean("interpupillary_px"),
            signed_shoulder_diff_px=mean("signed_shoulder_diff_px"),
            shoulder_width_px=mean("shoulder_width_px"),
            trunk_lean_deg=mean("trunk_lean_deg"),
            head_turn_ratio=mean("head_turn_ratio"),
            face_shoulder_ratio=mean("face_shoulder_ratio"),
            torso_shoulder_ratio=mean("torso_shoulder_ratio"),
            calibrated_distance_cm=(
                calibrated_distance_cm
                if calibrated_distance_cm is not None
                else self.calibrated_distance_cm
            ),
        )
        self.calibrated_distance_cm = self.baseline.calibrated_distance_cm
        self.legacy_calibration_used = False
        self._camera_drifted = False
        self.exposure_accumulator.reset()
        self._reset_risk_state()
        self._post_calibration_validation_required = True
        self._post_calibration_validation_started_at = None
        return True

    def reset_baseline(self) -> None:
        super().reset_baseline()
        self.calibration_profile = None
        self.legacy_calibration_used = False
        self._camera_drifted = False
        self.exposure_accumulator.reset()
        self._post_calibration_validation_required = False
        self._post_calibration_validation_started_at = None

    def evaluate(self, sample: VisionSample) -> PostureDecision:
        if not self.precision_enabled:
            return self._basic_mode_evaluate(sample)

        if self.calibration_profile is not None:
            return self._scientific_mode_evaluate(sample)
        if self.require_dual_anchor:
            return PostureDecision(
                "NEEDS_CALIB",
                "dual_anchor_calibration_required",
                False,
                calibration_quality=0.0,
                activity_state=sample.activity_state or "UNKNOWN",
            )

        if self.auto_calibrate and calibration_sample_is_complete(sample):
            self._update_baseline(sample)
        if self.baseline is None:
            if not self.auto_calibrate:
                return PostureDecision("NEEDS_CALIB", "press_calibrate", False)
            return PostureDecision("UNKNOWN", "no_usable_metrics", False)

        suppressed = self._suppressed_presence_decision(sample)
        if suppressed is not None:
            return suppressed

        active_metrics: List[str] = []
        missing_metrics: List[str] = []
        reasons: List[str] = []

        head_turn_score = self._head_turn_score(sample, active_metrics, missing_metrics, reasons)
        distance_score = self._distance_score(sample, active_metrics, missing_metrics, reasons)
        shoulder_width_score = self._shoulder_width_score(
            sample, active_metrics, missing_metrics, reasons
        )
        shoulder_score = self._shoulder_asymmetry_score(
            sample, active_metrics, missing_metrics, reasons
        )
        trunk_score = self._trunk_lean_score(sample, active_metrics, missing_metrics, reasons)

        if not active_metrics:
            return PostureDecision("UNKNOWN", ",".join(missing_metrics), self.calibrated)

        instant_score = min(
            100.0,
            head_turn_score
            + distance_score
            + shoulder_width_score
            + shoulder_score
            + trunk_score,
        )
        smoothed_score = self._smooth_risk_score(instant_score)
        sustained_seconds = self._update_sustained_risk(
            sample,
            instant_score,
            smoothed_score,
        )
        duration_score = self._duration_score(sustained_seconds)
        final_score = min(100.0, max(instant_score, smoothed_score) + duration_score)

        if sustained_seconds > 0:
            reasons.append(f"sustained_risk_s={sustained_seconds:.1f}")
        reasons.append(f"smoothed_risk_score={smoothed_score:.0f}")
        reasons.append(f"risk_score={final_score:.0f}")

        if instant_score < 30.0 and smoothed_score < 30.0 and sustained_seconds == 0.0:
            return PostureDecision("GOOD", "within_scientific_limits", True, final_score, 0.0)
        if sustained_seconds >= self.critical_sustain_seconds and final_score >= 55.0:
            return PostureDecision("CRITICAL", ",".join(reasons), True, final_score, sustained_seconds)
        if sustained_seconds >= self.bad_sustain_seconds and final_score >= self.risk_start_score:
            return PostureDecision("BAD", ",".join(reasons), True, final_score, sustained_seconds)
        reasons.append("risk_observing")
        return PostureDecision("WATCH", ",".join(reasons), True, final_score, sustained_seconds)

    def _scientific_mode_evaluate(self, sample: VisionSample) -> PostureDecision:
        profile = self.calibration_profile
        assert profile is not None

        activity_state = sample.activity_state or "UNKNOWN"
        if sample.target_motion is not None:
            activity_state = (
                "MOVING"
                if sample.target_motion > self.posture_policy.moving_threshold
                else "STATIC"
            )

        suppressed = self._suppressed_presence_decision(sample)
        if suppressed is not None:
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                suppressed.status,
                suppressed.reason,
                True,
                risk_score=0.0,
                sustained_seconds=exposure.exposure_seconds,
                environment_state=sample.target_state,
                target_track_id=sample.target_track_id,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=0.0,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if activity_state == "MOVING":
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "activity_moving_exposure_paused",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=aggregate_sample_quality(sample),
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if sample.camera_drift:
            self._camera_drifted = True
        if self._camera_drifted:
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "camera_drift_recalibration_required",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=0.0,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if self._camera_scale_jump(sample, profile):
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "camera_scale_jump_measurement_abstained",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=0.0,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        values = runtime_measurement_values(sample)
        score = score_posture_deviation(values, profile, self.posture_policy)
        scored_features = tuple(item.feature for item in score.features)
        quality = aggregate_sample_quality(sample, scored_features)
        confidence = max(0.0, min(1.0, quality * score.coverage))

        # Head orientation is a measurement-validity gate, not posture
        # evidence.  Use only the normalized nose/eye ratio here.  Raw
        # interpupillary pixels change with camera distance and must never
        # turn a fixed posture into a head-turn warning.
        head_turned = False
        preferred_head_turn = profile.preferred.get("head_turn_ratio")
        if sample.head_turn_ratio is not None and preferred_head_turn is not None:
            head_turned = abs(sample.head_turn_ratio - preferred_head_turn.mean) > 0.25

        if head_turned:
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "head_turn_measurement_abstained",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=confidence,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if shared_scale_measurement_unstable(
            values,
            profile,
            self.posture_policy,
            score,
        ):
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "shared_shoulder_scale_measurement_abstained",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=0.0,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if not score.features:
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "posture_features_unavailable",
                True,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=0.0,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if confidence < self.posture_policy.quality_floor:
            self._reset_post_calibration_validation_window()
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                f"measurement_quality_low={confidence:.2f}",
                True,
                risk_score=score.deviation * 100.0,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=score.deviation,
                exposure_seconds=exposure.exposure_seconds,
                confidence=confidence,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if self._post_calibration_validation_required:
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            within_normal_band = score.raw_deviation <= 1e-9
            if within_normal_band:
                if self._post_calibration_validation_started_at is None:
                    self._post_calibration_validation_started_at = sample.timestamp
                stable_seconds = max(
                    0.0,
                    (
                        sample.timestamp - self._post_calibration_validation_started_at
                    ).total_seconds(),
                )
                if stable_seconds >= self.posture_policy.post_calibration_validation_seconds:
                    self._post_calibration_validation_required = False
                    self._post_calibration_validation_started_at = None
                    self.exposure_accumulator.reset()
                    self.exposure_accumulator.pause(sample.timestamp)
                    return PostureDecision(
                        "GOOD",
                        "post_calibration_normal_range_validated",
                        True,
                        posture_deviation=0.0,
                        exposure_seconds=0.0,
                        confidence=confidence,
                        calibration_quality=profile.calibration_quality,
                        activity_state=activity_state,
                    )
            else:
                self._post_calibration_validation_started_at = None
            return PostureDecision(
                "UNKNOWN",
                "post_calibration_normal_range_validation",
                True,
                risk_score=score.raw_deviation * 100.0,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=confidence,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        if score.raw_deviation > 0.0 and not score.corroborated:
            # One drifting ratio/angle is diagnostic evidence, not enough
            # independent posture evidence to enter WATCH or accumulate
            # exposure. Abstain for this frame and make that uncertainty
            # visible to callers instead of silently converting it to GOOD.
            exposure = self.exposure_accumulator.pause(sample.timestamp)
            return PostureDecision(
                "UNKNOWN",
                "posture_evidence_inconclusive",
                True,
                risk_score=score.raw_deviation * 100.0,
                sustained_seconds=exposure.exposure_seconds,
                posture_deviation=0.0,
                exposure_seconds=exposure.exposure_seconds,
                confidence=confidence,
                calibration_quality=profile.calibration_quality,
                activity_state=activity_state,
            )

        exposure = self.exposure_accumulator.update(sample.timestamp, score.deviation)
        reasons = [
            f"posture_deviation={score.deviation:.2f}",
            f"exposure_seconds={exposure.exposure_seconds:.1f}",
            f"confidence={confidence:.2f}",
        ]
        if score.features:
            primary = max(score.features, key=lambda item: item.deviation)
            reasons.append(f"primary_feature={primary.feature}:{primary.deviation:.2f}")

        estimated_distance = self.estimated_distance_cm(sample)
        if estimated_distance is not None and estimated_distance < 40.0:
            reasons.append(f"distance_environment_near_cm={estimated_distance:.0f}")
        elif estimated_distance is not None and estimated_distance > 120.0:
            reasons.append(f"distance_environment_far_cm={estimated_distance:.0f}")

        if (
            exposure.exposure_seconds >= self.posture_policy.critical_exposure_seconds
            and score.deviation >= self.posture_policy.severe_deviation
        ):
            status = "CRITICAL"
        elif (
            exposure.exposure_seconds >= self.posture_policy.alert_exposure_seconds
            and exposure.alert_active
        ):
            status = "BAD"
        elif exposure.watch_active:
            status = "WATCH"
        else:
            status = "GOOD"
            reasons = ["within_personal_posture_range"]

        return PostureDecision(
            status,
            ",".join(reasons),
            True,
            risk_score=score.deviation * 100.0,
            sustained_seconds=exposure.exposure_seconds,
            posture_deviation=score.deviation,
            exposure_seconds=exposure.exposure_seconds,
            confidence=confidence,
            calibration_quality=profile.calibration_quality,
            activity_state=activity_state,
        )

    def _reset_post_calibration_validation_window(self) -> None:
        if self._post_calibration_validation_required:
            self._post_calibration_validation_started_at = None

    def _basic_mode_evaluate(self, sample: VisionSample) -> PostureDecision:
        """PRECISION 关闭时的回退：沿用基础阈值判定（PostureAnalyzer），
        但保留在场/换人门控，并把 BAD 折算成 risk_score/sustained_seconds，
        保证托盘的干预链路（risk>=45 且 sustained>=12s）仍然工作。"""
        if self.baseline is not None:
            suppressed = self._suppressed_presence_decision(sample)
            if suppressed is not None:
                return suppressed

        decision = super().evaluate(sample)
        if decision.status not in {"GOOD", "GOOD_PART", "BAD"}:
            return decision
        instant_score = 60.0 if decision.status == "BAD" else 0.0
        smoothed_score = self._smooth_risk_score(instant_score)
        sustained_seconds = self._update_sustained_risk(
            sample, instant_score, smoothed_score
        )
        return PostureDecision(
            decision.status,
            decision.reason,
            decision.calibrated,
            instant_score,
            sustained_seconds,
        )

    def estimated_distance_cm(self, sample: VisionSample) -> Optional[float]:
        if (
            self.baseline is None
            or self.baseline.interpupillary_px is None
            or self.baseline.calibrated_distance_cm is None
            or sample.interpupillary_px is None
            or sample.interpupillary_px <= 0
        ):
            return None
        return (
            self.baseline.calibrated_distance_cm
            * self.baseline.interpupillary_px
            / sample.interpupillary_px
        )

    def _suppressed_presence_decision(
        self,
        sample: VisionSample,
    ) -> Optional[PostureDecision]:
        if sample.target_state is not None:
            return self._tracked_presence_decision(sample)

        # 离开/换人的内部状态始终跟踪（两项功能互相独立），
        # presence_check_enabled 只决定是否产出 AWAY/MULTI_USER 抑制决策。
        if sample.face_count > 1:
            self._requires_profile_check = True
            self._away_started_at = None
            if self.presence_check_enabled:
                # The timestamp is based on capture timestamps, so the
                # confirmation window is time-based rather than frame-based.
                if self._multi_started_at is None:
                    self._multi_started_at = sample.timestamp
                multi_seconds = max(
                    0.0,
                    (sample.timestamp - self._multi_started_at).total_seconds(),
                )
                self._reset_risk_state()
                if multi_seconds < self.multi_present_confirm_seconds:
                    return PostureDecision(
                        "UNKNOWN",
                        f"multi_user_observing_s={multi_seconds:.1f}",
                        True,
                    )
                return PostureDecision("MULTI_USER", "multiple_faces_detected", True)
            self._multi_started_at = None
        elif not sample.face_detected and not sample.pose_detected:
            self._multi_started_at = None
            if self._away_started_at is None:
                self._away_started_at = sample.timestamp
            away_seconds = max(
                0.0,
                (sample.timestamp - self._away_started_at).total_seconds(),
            )
            self._requires_profile_check = True
            if self.presence_check_enabled:
                self._reset_risk_state()
                if away_seconds >= self.away_grace_seconds:
                    return PostureDecision("AWAY", f"user_away_s={away_seconds:.1f}", True)
                return PostureDecision(
                    "UNKNOWN", f"user_missing_observing_s={away_seconds:.1f}", True
                )
            # 关闭在场检测时不抑制：无指标样本会在后续评分中自然得到 UNKNOWN
            return None
        else:
            self._multi_started_at = None
            self._away_started_at = None

        # 换人比对只在画面回到单人时进行：多人帧的“第一张脸”归属不可靠
        if self._requires_profile_check and sample.face_count <= 1:
            if not self.identity_check_enabled:
                self._requires_profile_check = False
                return None
            profile_decision = self._profile_check_decision(sample)
            if profile_decision is not None:
                self._reset_risk_state()
                return profile_decision
            self._requires_profile_check = False
        return None

    def _tracked_presence_decision(self, sample: VisionSample) -> Optional[PostureDecision]:
        state = sample.target_state
        if state in {"TARGET_LOCKED", "MULTI_PRESENT"} and sample.target_observed:
            self._away_started_at = None
            self._multi_started_at = None
            self._requires_profile_check = False
            return None
        if (
            not self.presence_check_enabled
            and state in {"ACQUIRING", "TARGET_OCCLUDED", "TARGET_REACQUIRING", "AWAY"}
        ):
            self._reset_risk_state()
            return PostureDecision("UNKNOWN", "target_presence_check_disabled", True)
        if state == "TARGET_AMBIGUOUS":
            self._reset_risk_state()
            return PostureDecision(
                "TARGET_AMBIGUOUS",
                sample.target_reason or "ambiguous_face_body_association",
                True,
            )
        if state == "TARGET_OCCLUDED":
            self._reset_risk_state()
            return PostureDecision("TARGET_OCCLUDED", sample.target_reason or "target_occluded", True)
        if state == "TARGET_REACQUIRING":
            self._reset_risk_state()
            return PostureDecision(
                "TARGET_REACQUIRING",
                sample.target_reason or "target_reacquiring",
                True,
            )
        if state == "IDENTITY_UNCERTAIN":
            if not self.identity_check_enabled:
                self._requires_profile_check = False
                return None
            self._requires_profile_check = True
            profile_decision = self._profile_check_decision(sample)
            self._reset_risk_state()
            if profile_decision is None:
                self._requires_profile_check = False
                return None
            if profile_decision.status == "PROFILE_MISMATCH":
                return profile_decision
            return PostureDecision(
                "IDENTITY_UNCERTAIN",
                profile_decision.reason,
                True,
            )
        if state == "PROFILE_MISMATCH":
            self._reset_risk_state()
            return PostureDecision("PROFILE_MISMATCH", sample.target_reason or "profile_mismatch", True)
        if state == "AWAY":
            self._reset_risk_state()
            return PostureDecision("AWAY", sample.target_reason or "target_away", True)
        if state == "ACQUIRING":
            self._reset_risk_state()
            return PostureDecision("ACQUIRING", sample.target_reason or "target_not_locked", True)
        return None

    def _profile_check_decision(self, sample: VisionSample) -> Optional[PostureDecision]:
        if self.baseline is None:
            return None

        current_face_ratio, current_torso_ratio = self._profile_ratios(sample)
        reasons = []
        checked = False

        if self.baseline.face_shoulder_ratio is not None and current_face_ratio is not None:
            checked = True
            delta = abs(current_face_ratio - self.baseline.face_shoulder_ratio)
            relative_delta = delta / max(self.baseline.face_shoulder_ratio, 0.001)
            if relative_delta > 0.45:
                reasons.append(f"profile_face_shoulder_delta={relative_delta:.2f}")

        if self.baseline.torso_shoulder_ratio is not None and current_torso_ratio is not None:
            checked = True
            delta = abs(current_torso_ratio - self.baseline.torso_shoulder_ratio)
            relative_delta = delta / max(self.baseline.torso_shoulder_ratio, 0.001)
            if relative_delta > 0.35:
                reasons.append(f"profile_torso_shoulder_delta={relative_delta:.2f}")

        if reasons:
            return PostureDecision("PROFILE_MISMATCH", ",".join(reasons), True)
        if not checked:
            return PostureDecision("UNKNOWN", "profile_check_waiting", True)
        return None

    def _reset_risk_state(self) -> None:
        self._risk_started_at = None
        self._last_risky_at = None
        self._smoothed_score = 0.0

    def _distance_score(
        self,
        sample: VisionSample,
        active_metrics: List[str],
        missing_metrics: List[str],
        reasons: List[str],
    ) -> float:
        if self._eye_width_ratio(sample) is not None and self._eye_width_ratio(sample) < 0.75:
            missing_metrics.append("distance_unreliable_head_turn")
            return 0.0

        estimated_cm = self.estimated_distance_cm(sample)
        if estimated_cm is None:
            if self.baseline and self.baseline.calibrated_distance_cm is None:
                missing_metrics.append("distance_calibration")
            else:
                missing_metrics.append("face")
            return 0.0

        active_metrics.append("distance")
        if estimated_cm < 40.0:
            reasons.append(f"distance_too_close_cm={estimated_cm:.0f}")
            return 45.0
        if estimated_cm < 50.0:
            reasons.append(f"distance_too_close_cm={estimated_cm:.0f}")
            return 35.0
        if estimated_cm < 60.0:
            reasons.append(f"distance_near_cm={estimated_cm:.0f}")
            return 18.0
        if estimated_cm > 120.0:
            reasons.append(f"distance_too_far_cm={estimated_cm:.0f}")
            return 18.0
        if estimated_cm > 100.0:
            reasons.append(f"distance_far_cm={estimated_cm:.0f}")
            return 8.0
        return 0.0

    def _head_turn_score(
        self,
        sample: VisionSample,
        active_metrics: List[str],
        missing_metrics: List[str],
        reasons: List[str],
    ) -> float:
        if self.baseline is None or self.baseline.interpupillary_px is None:
            missing_metrics.append("head_turn_baseline")
            return 0.0

        if sample.interpupillary_px is None:
            if sample.pose_detected:
                active_metrics.append("head_turn")
                reasons.append("head_not_facing_camera")
                return 35.0
            missing_metrics.append("head_turn")
            return 0.0

        active_metrics.append("head_turn")
        eye_width_ratio = self._eye_width_ratio(sample)
        if eye_width_ratio is not None:
            if eye_width_ratio < 0.45:
                reasons.append(f"head_turn_eye_width_ratio={eye_width_ratio:.2f}")
                return 35.0
            if eye_width_ratio < 0.65:
                reasons.append(f"head_turn_eye_width_ratio={eye_width_ratio:.2f}")
                return 25.0
            if eye_width_ratio < 0.80:
                reasons.append(f"head_turn_eye_width_ratio={eye_width_ratio:.2f}")
                return 12.0

        if (
            sample.head_turn_ratio is None
            or self.baseline.head_turn_ratio is None
        ):
            return 0.0

        ratio_delta = abs(sample.head_turn_ratio - self.baseline.head_turn_ratio)
        if ratio_delta > 0.45:
            reasons.append(f"head_turn_ratio_delta={ratio_delta:.2f}")
            return 30.0
        if ratio_delta > 0.30:
            reasons.append(f"head_turn_ratio_delta={ratio_delta:.2f}")
            return 20.0
        if ratio_delta > 0.18:
            reasons.append(f"head_turn_ratio_delta={ratio_delta:.2f}")
            return 10.0
        return 0.0

    def _eye_width_ratio(self, sample: VisionSample) -> Optional[float]:
        if (
            self.baseline is None
            or self.baseline.interpupillary_px is None
            or self.baseline.interpupillary_px <= 0
            or sample.interpupillary_px is None
        ):
            return None
        return sample.interpupillary_px / self.baseline.interpupillary_px

    def _camera_scale_jump(
        self,
        sample: VisionSample,
        profile: CalibrationProfile,
    ) -> bool:
        """Detect a correlated raw-scale jump before scoring posture."""

        preferred_ipd = profile.preferred.get("interpupillary_px")
        preferred_width = profile.preferred.get("shoulder_width_px")
        if (
            preferred_ipd is None
            or preferred_width is None
            or preferred_ipd.mean <= 0.0
            or preferred_width.mean <= 0.0
            or sample.interpupillary_px is None
            or sample.shoulder_width_px is None
            or sample.interpupillary_px <= 0.0
            or sample.shoulder_width_px <= 0.0
        ):
            return False
        ipd_ratio = sample.interpupillary_px / preferred_ipd.mean
        width_ratio = sample.shoulder_width_px / preferred_width.mean
        if abs(ipd_ratio - width_ratio) > 0.12:
            return False
        return abs((ipd_ratio + width_ratio) / 2.0 - 1.0) >= (
            self.posture_policy.camera_scale_jump_ratio
        )

    def _shoulder_asymmetry_score(
        self,
        sample: VisionSample,
        active_metrics: List[str],
        missing_metrics: List[str],
        reasons: List[str],
    ) -> float:
        if self.baseline is None or self.baseline.signed_shoulder_diff_px is None:
            missing_metrics.append("shoulder_baseline")
            return 0.0
        shoulder_width_px = sample.shoulder_width_px or self.baseline.shoulder_width_px
        if sample.signed_shoulder_diff_px is None or not shoulder_width_px:
            missing_metrics.append("shoulder")
            return 0.0

        active_metrics.append("shoulder_asymmetry")
        shoulder_delta = abs(sample.signed_shoulder_diff_px - self.baseline.signed_shoulder_diff_px)
        angle_deg = math.degrees(math.atan2(shoulder_delta, shoulder_width_px))
        if angle_deg > 10.0:
            reasons.append(f"shoulder_asymmetry_deg={angle_deg:.1f}")
            return 25.0
        if angle_deg > 6.0:
            reasons.append(f"shoulder_asymmetry_deg={angle_deg:.1f}")
            return 17.0
        if angle_deg > 3.0:
            reasons.append(f"shoulder_asymmetry_deg={angle_deg:.1f}")
            return 8.0
        return 0.0

    def _shoulder_width_score(
        self,
        sample: VisionSample,
        active_metrics: List[str],
        missing_metrics: List[str],
        reasons: List[str],
    ) -> float:
        if self.baseline is None or not self.baseline.shoulder_width_px:
            missing_metrics.append("shoulder_width_baseline")
            return 0.0
        if sample.shoulder_width_px is None or sample.shoulder_width_px <= 0:
            missing_metrics.append("shoulder_width")
            return 0.0

        active_metrics.append("shoulder_width")
        width_ratio = sample.shoulder_width_px / self.baseline.shoulder_width_px
        if width_ratio < 0.35:
            reasons.append(f"shoulder_width_narrow_ratio={width_ratio:.2f}")
            return 35.0
        if width_ratio < 0.55:
            reasons.append(f"shoulder_width_narrow_ratio={width_ratio:.2f}")
            return 25.0
        if width_ratio < 0.75:
            reasons.append(f"shoulder_width_narrow_ratio={width_ratio:.2f}")
            return 12.0
        return 0.0

    def _trunk_lean_score(
        self,
        sample: VisionSample,
        active_metrics: List[str],
        missing_metrics: List[str],
        reasons: List[str],
    ) -> float:
        if self.baseline is None or self.baseline.trunk_lean_deg is None:
            missing_metrics.append("trunk_baseline")
            return 0.0
        if sample.trunk_lean_deg is None:
            missing_metrics.append("trunk")
            return 0.0

        active_metrics.append("trunk_lean")
        trunk_delta = abs(sample.trunk_lean_deg - self.baseline.trunk_lean_deg)
        if trunk_delta > 15.0:
            reasons.append(f"trunk_lean_delta_deg={trunk_delta:.1f}")
            return 25.0
        if trunk_delta > 10.0:
            reasons.append(f"trunk_lean_delta_deg={trunk_delta:.1f}")
            return 17.0
        if trunk_delta > 5.0:
            reasons.append(f"trunk_lean_delta_deg={trunk_delta:.1f}")
            return 8.0
        return 0.0

    def _smooth_risk_score(self, instant_score: float) -> float:
        alpha = 0.35
        self._smoothed_score = (
            alpha * instant_score
            + (1.0 - alpha) * self._smoothed_score
        )
        if instant_score == 0.0 and self._smoothed_score < 1.0:
            self._smoothed_score = 0.0
        return self._smoothed_score

    def _update_sustained_risk(
        self,
        sample: VisionSample,
        instant_score: float,
        smoothed_score: float,
    ) -> float:
        is_risky = (
            instant_score >= self.risk_start_score
            or smoothed_score >= self.risk_start_score
        )
        if is_risky:
            if self._risk_started_at is None:
                self._risk_started_at = sample.timestamp
            self._last_risky_at = sample.timestamp
            return max(0.0, (sample.timestamp - self._risk_started_at).total_seconds())

        if (
            self._risk_started_at is not None
            and self._last_risky_at is not None
            and (sample.timestamp - self._last_risky_at).total_seconds() < self.risk_clear_seconds
        ):
            return max(0.0, (sample.timestamp - self._risk_started_at).total_seconds())

        if smoothed_score < 25.0:
            self._risk_started_at = None
            self._last_risky_at = None
            return 0.0
        return 0.0

    def _duration_score(self, sustained_seconds: float) -> float:
        if sustained_seconds >= self.critical_sustain_seconds:
            return 20.0
        if sustained_seconds >= 15.0:
            return 12.0
        if sustained_seconds >= self.bad_sustain_seconds:
            return 6.0
        return 0.0


class VisionEngine:
    BLACK_FRAME_MEAN_LIMIT = 8.0
    BLACK_FRAME_VISIBLE_THRESHOLD = 20
    BLACK_FRAME_VISIBLE_RATIO_LIMIT = 0.015
    EXTREME_BLACK_MEAN_LIMIT = 2.5
    EXTREME_BLACK_MAX_LIMIT = 10
    BLACK_FRAME_WARNING_FRAMES = 5

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self._cap: Optional[cv2.VideoCapture] = None
        self._black_frame_count = 0
        self._target_fps = 15.0

        self._mp_face_mesh = mp.solutions.face_mesh
        self._mp_pose = mp.solutions.pose
        self._face_mesh = self._mp_face_mesh.FaceMesh(
            max_num_faces=2,
            refine_landmarks=True,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._pose = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def start(self) -> None:
        cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, 15)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            raise CameraPermissionError(f"Cannot open camera #{self.camera_id}.")

        self._cap = cap

    def set_capture_fps(self, fps: float) -> None:
        if fps > 0:
            self._target_fps = float(fps)
        if self._cap is not None and fps > 0:
            self._cap.set(cv2.CAP_PROP_FPS, fps)

    def get_capture_fps(self) -> float:
        return self._target_fps

    def read_frame_sample(self):
        if self._cap is None:
            raise RuntimeError("VisionEngine.start() must be called first.")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read a frame from the camera.")

        self._check_frame_visibility(frame)
        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        frame_h, frame_w = frame.shape[:2]

        face_result = self._face_mesh.process(frame_rgb)
        pose_result = self._pose.process(frame_rgb)

        left_eye_center, right_eye_center, face_nose_point, face_count = self._measure_face_points(
            face_result, frame_w, frame_h
        )
        interpupillary_px = None
        head_turn_ratio = None
        if left_eye_center is not None and right_eye_center is not None:
            interpupillary_px = math.dist(left_eye_center, right_eye_center)
            if face_nose_point is not None and interpupillary_px > 0:
                eye_mid_x = (left_eye_center[0] + right_eye_center[0]) / 2.0
                head_turn_ratio = (face_nose_point[0] - eye_mid_x) / interpupillary_px

        pose_values = self._measure_pose_points(pose_result, frame_w, frame_h)

        signed_shoulder_diff_px = None
        shoulder_diff_px = None
        shoulder_width_px = None
        trunk_lean_deg = None
        nose_point = None
        left_shoulder_point = None
        right_shoulder_point = None
        shoulder_center = None
        left_hip_point = None
        right_hip_point = None
        hip_center = None
        torso_height_px = None
        left_ear_point = None
        right_ear_point = None
        nose_confidence = None
        left_ear_confidence = None
        right_ear_confidence = None
        left_shoulder_confidence = None
        right_shoulder_confidence = None
        left_hip_confidence = None
        right_hip_confidence = None
        pose_quality = None
        if pose_values is not None:
            (
                signed_shoulder_diff_px,
                nose_point,
                left_shoulder_point,
                right_shoulder_point,
                shoulder_center,
                left_hip_point,
                right_hip_point,
                hip_center,
                trunk_lean_deg,
                left_ear_point,
                right_ear_point,
                nose_confidence,
                left_ear_confidence,
                right_ear_confidence,
                left_shoulder_confidence,
                right_shoulder_confidence,
                left_hip_confidence,
                right_hip_confidence,
                pose_quality,
            ) = pose_values
            shoulder_diff_px = abs(signed_shoulder_diff_px)
            shoulder_width_px = math.dist(left_shoulder_point, right_shoulder_point)
            if shoulder_center is not None and hip_center is not None:
                torso_height_px = math.dist(shoulder_center, hip_center)

        sample = VisionSample(
            timestamp=datetime.now(),
            interpupillary_px=interpupillary_px,
            shoulder_diff_px=shoulder_diff_px,
            signed_shoulder_diff_px=signed_shoulder_diff_px,
            shoulder_width_px=shoulder_width_px,
            trunk_lean_deg=trunk_lean_deg,
            face_detected=interpupillary_px is not None,
            pose_detected=shoulder_diff_px is not None,
            face_count=face_count,
            frame_width=frame_w,
            frame_height=frame_h,
            left_eye_center=left_eye_center,
            right_eye_center=right_eye_center,
            nose_point=nose_point,
            left_shoulder_point=left_shoulder_point,
            right_shoulder_point=right_shoulder_point,
            shoulder_center=shoulder_center,
            left_hip_point=left_hip_point,
            right_hip_point=right_hip_point,
            hip_center=hip_center,
            face_nose_point=face_nose_point,
            head_turn_ratio=head_turn_ratio,
            torso_height_px=torso_height_px,
            left_ear_point=left_ear_point,
            right_ear_point=right_ear_point,
            face_quality=(1.0 if interpupillary_px is not None and face_count == 1 else None),
            pose_quality=pose_quality,
            nose_confidence=nose_confidence,
            left_ear_confidence=left_ear_confidence,
            right_ear_confidence=right_ear_confidence,
            left_shoulder_confidence=left_shoulder_confidence,
            right_shoulder_confidence=right_shoulder_confidence,
            left_hip_confidence=left_hip_confidence,
            right_hip_confidence=right_hip_confidence,
        )
        return frame, sample

    def read_sample(self) -> VisionSample:
        _frame, sample = self.read_frame_sample()
        return sample

    def _check_frame_visibility(self, frame) -> None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_luma = float(gray.mean())
        max_luma = float(gray.max())
        visible_ratio = float((gray > self.BLACK_FRAME_VISIBLE_THRESHOLD).mean())
        almost_black = (
            mean_luma <= self.BLACK_FRAME_MEAN_LIMIT
            and visible_ratio <= self.BLACK_FRAME_VISIBLE_RATIO_LIMIT
        )
        extreme_black = (
            mean_luma <= self.EXTREME_BLACK_MEAN_LIMIT
            and max_luma <= self.EXTREME_BLACK_MAX_LIMIT
        )

        if not almost_black and not extreme_black:
            self._black_frame_count = 0
            return

        self._black_frame_count += 1
        if (
            extreme_black
            or self._black_frame_count >= self.BLACK_FRAME_WARNING_FRAMES
        ):
            raise CameraBlackFrameError(
                "Camera permission is available, but the camera is returning an "
                "all-black or nearly all-black image "
                f"(mean luma {mean_luma:.1f}, visible pixels {visible_ratio:.1%})."
            )

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._face_mesh.close()
        self._pose.close()

    @staticmethod
    def _landmark_center(landmarks: Iterable, indexes: Iterable[int], width: int, height: int) -> Point:
        points = [landmarks[index] for index in indexes]
        x = sum(point.x for point in points) / len(points) * width
        y = sum(point.y for point in points) / len(points) * height
        return x, y

    def _measure_face_points(
        self, face_result, width: int, height: int
    ) -> Tuple[Optional[Point], Optional[Point], Optional[Point], int]:
        if not face_result.multi_face_landmarks:
            return None, None, None, 0

        face_count = len(face_result.multi_face_landmarks)
        landmarks = face_result.multi_face_landmarks[0].landmark
        if len(landmarks) <= max(*LEFT_IRIS, *RIGHT_IRIS):
            return None, None, None, face_count

        left_center = self._landmark_center(landmarks, LEFT_IRIS, width, height)
        right_center = self._landmark_center(landmarks, RIGHT_IRIS, width, height)
        face_nose = None
        if len(landmarks) > FACE_NOSE:
            face_nose = self._pose_point(landmarks[FACE_NOSE], width, height)
        return left_center, right_center, face_nose, face_count

    @staticmethod
    def _pose_point(landmark, width: int, height: int) -> Point:
        return landmark.x * width, landmark.y * height

    def _measure_pose_points(
        self, pose_result, width: int, height: int
    ) -> Optional[
        Tuple[
            float,
            Optional[Point],
            Point,
            Point,
            Point,
            Optional[Point],
            Optional[Point],
            Optional[Point],
            Optional[float],
            Optional[Point],
            Optional[Point],
            float,
            float,
            float,
            float,
            float,
            float,
            float,
            float,
        ]
    ]:
        if not pose_result.pose_landmarks:
            return None

        landmarks = pose_result.pose_landmarks.landmark
        left = landmarks[LEFT_SHOULDER]
        right = landmarks[RIGHT_SHOULDER]

        # Keep a lower extraction floor than the runtime quality gate. The
        # calibration layer records repeatability and can disable noisy
        # features; dropping every borderline frame here made the five-second
        # anchor window fail before it could gather five valid samples.
        if left.visibility < 0.3 or right.visibility < 0.3:
            return None

        signed_shoulder_diff = (left.y - right.y) * height
        left_point = self._pose_point(left, width, height)
        right_point = self._pose_point(right, width, height)
        shoulder_center = (
            (left_point[0] + right_point[0]) / 2.0,
            (left_point[1] + right_point[1]) / 2.0,
        )

        nose = landmarks[NOSE]
        nose_point = None
        if nose.visibility >= 0.5:
            nose_point = self._pose_point(nose, width, height)

        left_ear = landmarks[LEFT_EAR]
        right_ear = landmarks[RIGHT_EAR]
        left_ear_point = (
            self._pose_point(left_ear, width, height)
            if left_ear.visibility >= 0.5
            else None
        )
        right_ear_point = (
            self._pose_point(right_ear, width, height)
            if right_ear.visibility >= 0.5
            else None
        )

        left_hip = landmarks[LEFT_HIP]
        right_hip = landmarks[RIGHT_HIP]
        left_hip_point = None
        right_hip_point = None
        hip_center = None
        trunk_lean_deg = None
        if left_hip.visibility >= 0.5 and right_hip.visibility >= 0.5:
            left_hip_point = self._pose_point(left_hip, width, height)
            right_hip_point = self._pose_point(right_hip, width, height)
            hip_center = (
                (left_hip_point[0] + right_hip_point[0]) / 2.0,
                (left_hip_point[1] + right_hip_point[1]) / 2.0,
            )
            dx = shoulder_center[0] - hip_center[0]
            dy = hip_center[1] - shoulder_center[1]
            trunk_lean_deg = math.degrees(math.atan2(dx, max(abs(dy), 1.0)))

        return (
            signed_shoulder_diff,
            nose_point,
            left_point,
            right_point,
            shoulder_center,
            left_hip_point,
            right_hip_point,
            hip_center,
            trunk_lean_deg,
            left_ear_point,
            right_ear_point,
            float(nose.visibility),
            float(left_ear.visibility),
            float(right_ear.visibility),
            float(left.visibility),
            float(right.visibility),
            float(left_hip.visibility),
            float(right_hip.visibility),
            # Aggregate pose quality represents the required upper-body core.
            # Hip visibility is propagated separately and gates only features
            # that actually depend on hips (torso ratio and trunk lean).
            float(min(left.visibility, right.visibility)),
        )


def format_value(value: Optional[float], unit: str = "px") -> str:
    if value is None:
        return "--"
    return f"{value:7.2f}{unit}"


def format_baseline(baseline: Optional[PostureBaseline]) -> str:
    if baseline is None:
        return "--"
    pupil = (
        f"{baseline.interpupillary_px:.2f}px"
        if baseline.interpupillary_px is not None
        else "--"
    )
    shoulder = (
        f"{baseline.signed_shoulder_diff_px:.2f}px"
        if baseline.signed_shoulder_diff_px is not None
        else "--"
    )
    distance = (
        f"{baseline.calibrated_distance_cm:.0f}cm"
        if baseline.calibrated_distance_cm is not None
        else "--"
    )
    trunk = (
        f"{baseline.trunk_lean_deg:.1f}deg"
        if baseline.trunk_lean_deg is not None
        else "--"
    )
    head = (
        f"{baseline.head_turn_ratio:.2f}"
        if baseline.head_turn_ratio is not None
        else "--"
    )
    return (
        f"pupil={pupil}, "
        f"shoulder={shoulder}, "
        f"distance={distance}, "
        f"trunk={trunk}, "
        f"head={head}"
    )


def format_calibration_profile(profile: Optional[CalibrationProfile]) -> str:
    """Compact numeric anchor summary for diagnostics."""
    if profile is None:
        return "--"
    parts = [
        f"preferred_n={profile.stage_counts.get('preferred', 0)}",
        f"relaxed_n={profile.stage_counts.get('relaxed', 0)}",
        f"quality={profile.calibration_quality:.2f}",
    ]
    for name in profile.enabled_features:
        preferred = profile.preferred.get(name)
        relaxed = profile.relaxed.get(name)
        if preferred is None or relaxed is None:
            continue
        parts.append(
            f"{name}:p={preferred.mean:.3f},r={relaxed.mean:.3f},"
            f"mdc={max(preferred.mdc, relaxed.mdc):.3f}"
        )
    return "; ".join(parts)


def run(
    camera_id: int,
    fps: float,
    width: int,
    height: int,
    calibration_samples: int,
    too_close_ratio: float,
    shoulder_threshold_px: float,
    max_samples: Optional[int],
) -> int:
    if fps <= 0:
        raise ValueError("fps must be greater than 0.")

    engine = VisionEngine(camera_id=camera_id, width=width, height=height)
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)

    analyzer = PostureAnalyzer(
        calibration_samples=calibration_samples,
        too_close_ratio=too_close_ratio,
        shoulder_threshold_px=shoulder_threshold_px,
    )
    interval = 1.0 / fps
    engine.start()
    print("EchoPosture vision test started. Press Ctrl+C to stop.")
    print(
        "time      face  pupil_dist_px  pose  shoulder_abs_px  "
        "shoulder_signed_px  posture      reason"
    )

    try:
        sample_count = 0
        baseline_reported = False
        while not stop_requested:
            loop_start = time.perf_counter()
            sample = engine.read_sample()
            decision = analyzer.evaluate(sample)
            if decision.calibrated and not baseline_reported:
                print(f"Baseline locked: {format_baseline(analyzer.baseline)}", flush=True)
                baseline_reported = True

            print(
                f"{sample.timestamp:%H:%M:%S}  "
                f"{'yes ' if sample.face_detected else 'no  '}  "
                f"{format_value(sample.interpupillary_px):>13}  "
                f"{'yes ' if sample.pose_detected else 'no  '}  "
                f"{format_value(sample.shoulder_diff_px):>15}  "
                f"{format_value(sample.signed_shoulder_diff_px):>18}  "
                f"{decision.status:<11}  "
                f"{decision.reason}",
                flush=True,
            )

            sample_count += 1
            if max_samples is not None and sample_count >= max_samples:
                break

            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0.0, interval - elapsed))
    finally:
        engine.close()
        cv2.destroyAllWindows()

    print("Vision test stopped.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPosture vision sensing test.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--fps", type=float, default=4.0, help="Detection frequency. Default: 4")
    parser.add_argument("--width", type=int, default=640, help="Capture width. Default: 640")
    parser.add_argument("--height", type=int, default=480, help="Capture height. Default: 480")
    parser.add_argument(
        "--calibration-samples",
        type=int,
        default=8,
        help="Valid samples used as the initial good-posture baseline. Default: 8",
    )
    parser.add_argument(
        "--too-close-ratio",
        type=float,
        default=1.25,
        help="BAD if pupil distance is greater than baseline times this ratio. Default: 1.25",
    )
    parser.add_argument(
        "--shoulder-threshold-px",
        type=float,
        default=28.0,
        help="BAD if signed shoulder height drifts from baseline by more than this. Default: 28",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Stop after this many processed samples. Default: run until Ctrl+C",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        raise SystemExit(
            run(
                args.camera,
                args.fps,
                args.width,
                args.height,
                args.calibration_samples,
                args.too_close_ratio,
                args.shoulder_threshold_px,
                args.max_samples,
            )
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
