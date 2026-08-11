"""Auditable posture-change and static-exposure logic.

This module deliberately contains no camera, GUI, persistence, or identity
code.  It turns numeric observations into within-person change estimates and
time-weighted exposure.  Every threshold below is a product interaction
policy, not a physiological limit or a medical dose.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Mapping, Optional, Sequence


PREFERRED = "preferred"
RELAXED = "relaxed"

FORWARD_FEATURES = (
    "face_shoulder_ratio",
    "torso_shoulder_ratio",
    "ear_shoulder_ratio",
)
LATERAL_FEATURES = (
    "shoulder_asymmetry_deg",
    "trunk_lean_deg",
)
POSTURE_FEATURES = FORWARD_FEATURES + LATERAL_FEATURES

# These are retained in the calibration report for distance/environment
# diagnostics, but never contribute directly to posture deviation.
ENVIRONMENT_FEATURES = (
    "interpupillary_px",
    "shoulder_width_px",
    "signed_shoulder_diff_px",
    "torso_height_px",
    "head_turn_ratio",
)
CALIBRATION_FEATURES = POSTURE_FEATURES + ENVIRONMENT_FEATURES


def _elapsed_seconds(current, previous) -> float:
    delta = current - previous
    if hasattr(delta, "total_seconds"):
        return float(delta.total_seconds())
    return float(delta)


def _finite_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


@dataclass(frozen=True)
class FeatureStatistics:
    """Repeatability statistics for one numeric feature.

    ``cv`` is a dimensionless ratio.  ``mdc`` uses the conventional
    95-percent repeatability estimate ``1.96 * sqrt(2) * SEM``.  It describes
    measurement noise only; it does not establish clinical importance.
    """

    mean: float
    std: float
    n: int
    sem: float
    mdc: float
    cv: Optional[float]

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "FeatureStatistics":
        usable = [float(value) for value in values if math.isfinite(float(value))]
        if not usable:
            raise ValueError("at least one finite value is required")
        n = len(usable)
        mean = sum(usable) / n
        if n > 1:
            variance = sum((value - mean) ** 2 for value in usable) / (n - 1)
            std = math.sqrt(max(0.0, variance))
        else:
            std = 0.0
        sem = std / math.sqrt(n)
        mdc = 1.96 * math.sqrt(2.0) * sem
        cv = std / abs(mean) if abs(mean) > 1e-12 else None
        return cls(mean=mean, std=std, n=n, sem=sem, mdc=mdc, cv=cv)


@dataclass(frozen=True)
class CalibrationPlan:
    """Fixed one-page calibration schedule."""

    preferred_seconds: float = 2.0
    relaxed_seconds: float = 3.0
    min_samples_per_stage: int = 5
    min_face_quality: float = 0.65
    min_pose_quality: float = 0.65
    max_target_motion: float = 0.20

    def __post_init__(self) -> None:
        if self.preferred_seconds <= 0 or self.relaxed_seconds <= 0:
            raise ValueError("calibration stages must have positive durations")
        if self.min_samples_per_stage < 1:
            raise ValueError("min_samples_per_stage must be positive")

    @property
    def total_seconds(self) -> float:
        return self.preferred_seconds + self.relaxed_seconds

    def stage_at(self, timestamp, started_at) -> Optional[str]:
        elapsed = max(0.0, _elapsed_seconds(timestamp, started_at))
        if elapsed < self.preferred_seconds:
            return PREFERRED
        if elapsed < self.total_seconds:
            return RELAXED
        return None


@dataclass(frozen=True)
class CalibrationProfile:
    """Two within-person posture anchors plus their repeatability evidence."""

    preferred: Mapping[str, FeatureStatistics]
    relaxed: Mapping[str, FeatureStatistics]
    enabled_features: tuple[str, ...]
    disabled_features: Mapping[str, str]
    calibration_quality: float
    stage_counts: Mapping[str, int]
    created_at: datetime
    reset_reasons: tuple[str, ...] = ()

    @property
    def scientific_ready(self) -> bool:
        return bool(self.enabled_features)

    def to_dict(self) -> dict:
        return {
            "preferred": {name: asdict(stats) for name, stats in self.preferred.items()},
            "relaxed": {name: asdict(stats) for name, stats in self.relaxed.items()},
            "enabled_features": list(self.enabled_features),
            "disabled_features": dict(self.disabled_features),
            "calibration_quality": self.calibration_quality,
            "stage_counts": dict(self.stage_counts),
            "created_at": self.created_at.isoformat(),
            "reset_reasons": list(self.reset_reasons),
        }


class CalibrationAccumulator:
    """Collect fixed-time, quality-gated preferred and relaxed anchors.

    An invalid observation clears the current stage window.  The schedule does
    not slide or extend, so a contaminated stage fails instead of being hidden
    by later averaging.
    """

    def __init__(self, plan: Optional[CalibrationPlan] = None) -> None:
        self.plan = plan or CalibrationPlan()
        self.started_at = None
        self._values: dict[str, dict[str, list[float]]] = {
            PREFERRED: {},
            RELAXED: {},
        }
        self._sample_counts = {PREFERRED: 0, RELAXED: 0}
        self._reset_reasons: list[str] = []

    @property
    def stage_counts(self) -> dict[str, int]:
        return dict(self._sample_counts)

    @property
    def reset_reasons(self) -> tuple[str, ...]:
        return tuple(self._reset_reasons)

    def _stage(self, timestamp) -> Optional[str]:
        if self.started_at is None:
            self.started_at = timestamp
        return self.plan.stage_at(timestamp, self.started_at)

    def reject(self, timestamp, reason: str) -> Optional[str]:
        stage = self._stage(timestamp)
        if stage is None:
            return None
        self._values[stage].clear()
        self._sample_counts[stage] = 0
        self._reset_reasons.append(f"{stage}:{reason}")
        return stage

    def add(self, timestamp, values: Mapping[str, float]) -> Optional[str]:
        stage = self._stage(timestamp)
        if stage is None:
            return None
        usable = {
            name: numeric
            for name, value in values.items()
            if name in CALIBRATION_FEATURES
            and (numeric := _finite_float(value)) is not None
        }
        if not usable:
            self.reject(timestamp, "no_numeric_features")
            return stage
        self._sample_counts[stage] += 1
        for name, value in usable.items():
            self._values[stage].setdefault(name, []).append(value)
        return stage

    def failure_fields(self) -> tuple[str, ...]:
        fields: list[str] = []
        minimum = self.plan.min_samples_per_stage
        for stage in (PREFERRED, RELAXED):
            if self._sample_counts[stage] < minimum:
                fields.append(f"{stage}_samples")
        fields.extend(reason.split(":", 1)[1] for reason in self._reset_reasons[-3:])
        return tuple(dict.fromkeys(fields))

    def finalize(self, created_at: Optional[datetime] = None) -> CalibrationProfile:
        missing = self.failure_fields()
        if any(name.endswith("_samples") for name in missing):
            raise ValueError(",".join(missing))

        stage_stats: dict[str, dict[str, FeatureStatistics]] = {
            PREFERRED: {},
            RELAXED: {},
        }
        minimum = self.plan.min_samples_per_stage
        for stage in (PREFERRED, RELAXED):
            for name, values in self._values[stage].items():
                if len(values) >= minimum:
                    stage_stats[stage][name] = FeatureStatistics.from_values(values)

        enabled: list[str] = []
        disabled: dict[str, str] = {}
        for name in POSTURE_FEATURES:
            preferred = stage_stats[PREFERRED].get(name)
            relaxed = stage_stats[RELAXED].get(name)
            if preferred is None or relaxed is None:
                disabled[name] = "insufficient_valid_samples"
                continue
            separation = abs(relaxed.mean - preferred.mean)
            noise_floor = max(preferred.mdc, relaxed.mdc, 1e-9)
            if separation <= noise_floor:
                disabled[name] = "anchor_separation_not_above_mdc"
                continue
            enabled.append(name)

        if not enabled:
            raise ValueError("no_feature_separates_above_mdc")

        minimum_count = min(self._sample_counts.values())
        sample_quality = min(1.0, minimum_count / max(minimum, 1))
        feature_quality = len(enabled) / len(POSTURE_FEATURES)
        calibration_quality = max(0.0, min(1.0, 0.55 * sample_quality + 0.45 * feature_quality))
        return CalibrationProfile(
            preferred=stage_stats[PREFERRED],
            relaxed=stage_stats[RELAXED],
            enabled_features=tuple(enabled),
            disabled_features=disabled,
            calibration_quality=calibration_quality,
            stage_counts=self.stage_counts,
            created_at=created_at or datetime.now(),
            reset_reasons=self.reset_reasons,
        )


@dataclass(frozen=True)
class PosturePolicy:
    """Adjustable product interaction policy; not a biological standard."""

    watch_enter: float = 0.50
    watch_exit: float = 0.40
    alert_enter: float = 0.70
    alert_exit: float = 0.55
    severe_deviation: float = 0.85
    quality_floor: float = 0.65
    alert_exposure_seconds: float = 12.0
    critical_exposure_seconds: float = 30.0
    recovery_half_life_seconds: float = 12.0
    confirmation_seconds: float = 3.0
    cooldown_seconds: float = 60.0
    moving_threshold: float = 0.20
    camera_scale_jump_ratio: float = 0.18
    within_group_corroboration: float = 0.12
    between_group_corroboration: float = 0.10

    def __post_init__(self) -> None:
        if not (0.0 <= self.watch_exit < self.watch_enter <= 1.0):
            raise ValueError("watch hysteresis must satisfy exit < enter")
        if not (0.0 <= self.alert_exit < self.alert_enter <= 1.0):
            raise ValueError("alert hysteresis must satisfy exit < enter")
        if self.recovery_half_life_seconds <= 0:
            raise ValueError("recovery_half_life_seconds must be positive")


@dataclass(frozen=True)
class FeatureDeviation:
    feature: str
    deviation: float
    current: float
    preferred: float
    relaxed: float
    mdc: float


@dataclass(frozen=True)
class PostureScore:
    deviation: float
    forward_deviation: float
    lateral_deviation: float
    features: tuple[FeatureDeviation, ...]
    coverage: float


def normalized_feature_deviation(
    feature: str,
    current: float,
    preferred: FeatureStatistics,
    relaxed: FeatureStatistics,
) -> FeatureDeviation:
    """Project a current value from preferred toward relaxed after MDC."""

    anchor_delta = relaxed.mean - preferred.mean
    direction = 1.0 if anchor_delta >= 0.0 else -1.0
    anchor_span = abs(anchor_delta)
    noise_floor = max(preferred.mdc, relaxed.mdc, 1e-9)
    if anchor_span <= noise_floor:
        deviation = 0.0
    else:
        projected_change = (float(current) - preferred.mean) * direction
        credible_change = max(0.0, projected_change - noise_floor)
        credible_anchor_span = max(anchor_span - noise_floor, 1e-9)
        deviation = max(0.0, min(1.5, credible_change / credible_anchor_span))
    return FeatureDeviation(
        feature=feature,
        deviation=deviation,
        current=float(current),
        preferred=preferred.mean,
        relaxed=relaxed.mean,
        mdc=noise_floor,
    )


def _group_score(values: Sequence[float], corroboration: float) -> float:
    ordered = sorted((max(0.0, value) for value in values), reverse=True)
    if not ordered:
        return 0.0
    primary = ordered[0]
    support = ordered[1] if len(ordered) > 1 else 0.0
    return min(1.0, primary + min(corroboration, support * corroboration))


def score_posture_deviation(
    values: Mapping[str, float],
    profile: CalibrationProfile,
    policy: Optional[PosturePolicy] = None,
) -> PostureScore:
    policy = policy or PosturePolicy()
    feature_results: list[FeatureDeviation] = []
    for name in profile.enabled_features:
        current = _finite_float(values.get(name))
        preferred = profile.preferred.get(name)
        relaxed = profile.relaxed.get(name)
        if current is None or preferred is None or relaxed is None:
            continue
        feature_results.append(
            normalized_feature_deviation(name, current, preferred, relaxed)
        )

    by_name = {result.feature: result.deviation for result in feature_results}
    forward = _group_score(
        [by_name[name] for name in FORWARD_FEATURES if name in by_name],
        policy.within_group_corroboration,
    )
    lateral = _group_score(
        [by_name[name] for name in LATERAL_FEATURES if name in by_name],
        policy.within_group_corroboration,
    )
    groups = sorted((forward, lateral), reverse=True)
    overall = min(1.0, groups[0] + min(policy.between_group_corroboration, groups[1] * policy.between_group_corroboration))
    coverage = len(feature_results) / max(1, len(profile.enabled_features))
    return PostureScore(
        deviation=overall,
        forward_deviation=forward,
        lateral_deviation=lateral,
        features=tuple(feature_results),
        coverage=coverage,
    )


@dataclass(frozen=True)
class ExposureSnapshot:
    exposure_seconds: float
    watch_active: bool
    alert_active: bool
    integrated_seconds: float
    recovery_seconds: float
    paused: bool


class ExposureAccumulator:
    """Integrate equivalent high-deviation seconds using real timestamps."""

    def __init__(self, policy: Optional[PosturePolicy] = None) -> None:
        self.policy = policy or PosturePolicy()
        self.exposure_seconds = 0.0
        self.watch_active = False
        self.alert_active = False
        self.last_timestamp = None
        self.last_alert_timestamp = None

    def reset(self) -> None:
        self.exposure_seconds = 0.0
        self.watch_active = False
        self.alert_active = False
        self.last_timestamp = None
        self.last_alert_timestamp = None

    def _advance_time(self, timestamp) -> float:
        if self.last_timestamp is None:
            self.last_timestamp = timestamp
            return 0.0
        elapsed = max(0.0, _elapsed_seconds(timestamp, self.last_timestamp))
        self.last_timestamp = timestamp
        return elapsed

    def pause(self, timestamp) -> ExposureSnapshot:
        self._advance_time(timestamp)
        return ExposureSnapshot(
            exposure_seconds=self.exposure_seconds,
            watch_active=self.watch_active,
            alert_active=self.alert_active,
            integrated_seconds=0.0,
            recovery_seconds=0.0,
            paused=True,
        )

    def update(self, timestamp, deviation: float, paused: bool = False) -> ExposureSnapshot:
        elapsed = self._advance_time(timestamp)
        if paused:
            return ExposureSnapshot(
                self.exposure_seconds,
                self.watch_active,
                self.alert_active,
                0.0,
                0.0,
                True,
            )

        deviation = max(0.0, min(1.0, float(deviation)))
        if self.watch_active:
            if deviation <= self.policy.watch_exit:
                self.watch_active = False
        elif deviation >= self.policy.watch_enter:
            self.watch_active = True

        if self.alert_active:
            if deviation <= self.policy.alert_exit:
                self.alert_active = False
        elif deviation >= self.policy.alert_enter:
            self.alert_active = True

        integrated = 0.0
        recovered = 0.0
        if self.watch_active:
            integrated = elapsed * deviation
            self.exposure_seconds += integrated
        elif elapsed > 0.0 and self.exposure_seconds > 0.0:
            before = self.exposure_seconds
            decay = math.exp(
                -math.log(2.0) * elapsed / self.policy.recovery_half_life_seconds
            )
            self.exposure_seconds *= decay
            if self.exposure_seconds < 1e-6:
                self.exposure_seconds = 0.0
            recovered = before - self.exposure_seconds

        return ExposureSnapshot(
            exposure_seconds=self.exposure_seconds,
            watch_active=self.watch_active,
            alert_active=self.alert_active,
            integrated_seconds=integrated,
            recovery_seconds=recovered,
            paused=False,
        )

    def alert_available(self, timestamp) -> bool:
        if self.last_alert_timestamp is None:
            return True
        return (
            _elapsed_seconds(timestamp, self.last_alert_timestamp)
            >= self.policy.cooldown_seconds
        )

    def mark_alert(self, timestamp) -> None:
        self.last_alert_timestamp = timestamp


def measurement_values(sample) -> dict[str, float]:
    """Extract numeric calibration/scoring values from a sample-like object."""

    values: dict[str, float] = {}
    for name in ENVIRONMENT_FEATURES:
        value = _finite_float(getattr(sample, name, None))
        if value is not None:
            values[name] = value

    shoulder_width = _finite_float(getattr(sample, "shoulder_width_px", None))
    interpupillary = _finite_float(getattr(sample, "interpupillary_px", None))
    torso_height = _finite_float(getattr(sample, "torso_height_px", None))
    signed_shoulder = _finite_float(getattr(sample, "signed_shoulder_diff_px", None))
    trunk_lean = _finite_float(getattr(sample, "trunk_lean_deg", None))
    if shoulder_width is not None and shoulder_width > 0.0:
        if interpupillary is not None:
            values["face_shoulder_ratio"] = interpupillary / shoulder_width
        if torso_height is not None:
            values["torso_shoulder_ratio"] = torso_height / shoulder_width
        if signed_shoulder is not None:
            values["shoulder_asymmetry_deg"] = math.degrees(
                math.atan2(signed_shoulder, shoulder_width)
            )

        ear_offsets: list[float] = []
        for side in ("left", "right"):
            ear = getattr(sample, f"{side}_ear_point", None)
            shoulder = getattr(sample, f"{side}_shoulder_point", None)
            if ear is not None and shoulder is not None:
                ear_offsets.append((float(shoulder[1]) - float(ear[1])) / shoulder_width)
        if ear_offsets:
            values["ear_shoulder_ratio"] = sum(ear_offsets) / len(ear_offsets)
    if trunk_lean is not None:
        values["trunk_lean_deg"] = trunk_lean
    return values


def aggregate_sample_quality(sample) -> float:
    qualities: list[float] = []
    face_quality = _finite_float(getattr(sample, "face_quality", None))
    pose_quality = _finite_float(getattr(sample, "pose_quality", None))
    if getattr(sample, "face_detected", False):
        qualities.append(face_quality if face_quality is not None else 1.0)
    if getattr(sample, "pose_detected", False):
        qualities.append(pose_quality if pose_quality is not None else 1.0)
    return max(0.0, min(1.0, min(qualities))) if qualities else 0.0


def calibration_rejection_reason(
    sample,
    plan: Optional[CalibrationPlan] = None,
) -> Optional[str]:
    plan = plan or CalibrationPlan()
    if getattr(sample, "face_count", 0) != 1:
        return "single_person"
    person_count = getattr(sample, "person_count", None)
    if person_count is not None and person_count != 1:
        return "single_person"
    if getattr(sample, "target_state", None) in {"MULTI_PRESENT", "TARGET_AMBIGUOUS"}:
        return "target_ambiguous"
    if getattr(sample, "target_state", None) in {
        "TARGET_OCCLUDED",
        "TARGET_REACQUIRING",
        "AWAY",
        "IDENTITY_UNCERTAIN",
        "PROFILE_MISMATCH",
    }:
        return "target_uncertain"
    if not getattr(sample, "face_detected", False) or not getattr(sample, "pose_detected", False):
        return "keypoints_missing"
    face_quality = _finite_float(getattr(sample, "face_quality", None))
    pose_quality = _finite_float(getattr(sample, "pose_quality", None))
    if face_quality is not None and face_quality < plan.min_face_quality:
        return "face_quality_low"
    if pose_quality is not None and pose_quality < plan.min_pose_quality:
        return "pose_quality_low"
    motion = _finite_float(getattr(sample, "target_motion", None))
    if motion is not None and motion > plan.max_target_motion:
        return "target_moving"
    if not measurement_values(sample):
        return "no_numeric_features"
    return None
