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
TRANSITION = "transition"
RELAXED = "relaxed"
COMPLETE = "complete"

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

# Only observations that can mix another person into an anchor invalidate
# already accepted samples. Ordinary measurement failures abstain for that
# frame and leave prior evidence intact.
CALIBRATION_CONTAMINATION_REASONS = frozenset({"single_person", "target_ambiguous"})


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
    """Adjustable product timing for the production two-anchor flow.

    The visible countdown covers only ``preferred_seconds``.  The caller must
    explicitly end that stage after closing the countdown.  Samples are then
    ignored for ``transition_seconds`` before the background relaxed window starts.
    A short bounded extension lets a nearly-complete relaxed window recover
    from rejected samples without turning calibration into an unbounded wait.
    These durations are interaction policy, not physiological standards.
    """

    preferred_seconds: float = 5.0
    transition_seconds: float = 1.0
    relaxed_seconds: float = 5.0
    relaxed_max_extension_seconds: float = 2.0
    min_samples_per_stage: int = 5
    min_face_quality: float = 0.65
    # Match the MediaPipe landmark usability floor. Reliability is assessed
    # per feature by SEM/MDC; an unvalidated 0.65 whole-frame cutoff caused
    # otherwise usable 0.50-0.64 shoulder observations to be discarded.
    min_pose_quality: float = 0.50
    max_target_motion: float = 0.20

    def __post_init__(self) -> None:
        if self.preferred_seconds <= 0 or self.relaxed_seconds <= 0:
            raise ValueError("calibration stages must have positive durations")
        if self.transition_seconds < 0 or self.relaxed_max_extension_seconds < 0:
            raise ValueError("calibration transition and extension cannot be negative")
        if self.min_samples_per_stage < 1:
            raise ValueError("min_samples_per_stage must be positive")

    @property
    def total_seconds(self) -> float:
        """Nominal elapsed time, excluding the optional relaxed extension."""

        return self.preferred_seconds + self.transition_seconds + self.relaxed_seconds

    @property
    def maximum_total_seconds(self) -> float:
        return self.total_seconds + self.relaxed_max_extension_seconds


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
    rejection_counts: Mapping[str, int] = field(default_factory=dict)
    runtime_noise_floors: Mapping[str, float] = field(default_factory=dict)

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
            "rejection_counts": dict(self.rejection_counts),
            "runtime_noise_floors": dict(self.runtime_noise_floors),
        }


class CalibrationAccumulator:
    """Collect explicitly phased, quality-gated preferred and relaxed anchors.

    A contamination observation clears only the active anchor window. Low
    quality, missing-keypoint, motion, and temporary target failures abstain
    for that frame without erasing earlier accepted samples. Transition
    observations are always ignored and cannot contaminate either anchor.
    """

    def __init__(
        self,
        plan: Optional[CalibrationPlan] = None,
        policy: Optional["PosturePolicy"] = None,
    ) -> None:
        self.plan = plan or CalibrationPlan()
        self.policy = policy
        self.started_at = None
        self._phase = PREFERRED
        self._phase_started_at = None
        self._values: dict[str, dict[str, list[float]]] = {
            PREFERRED: {},
            RELAXED: {},
        }
        self._sample_counts = {PREFERRED: 0, RELAXED: 0}
        self._reset_reasons: list[str] = []
        self._rejection_counts: dict[str, int] = {}

    @property
    def stage_counts(self) -> dict[str, int]:
        return dict(self._sample_counts)

    @property
    def reset_reasons(self) -> tuple[str, ...]:
        return tuple(self._reset_reasons)

    @property
    def rejection_counts(self) -> dict[str, int]:
        return dict(self._rejection_counts)

    @property
    def phase(self) -> str:
        return self._phase

    def stage_at(self, timestamp) -> str:
        if self.started_at is None:
            self.started_at = timestamp
        if self._phase == TRANSITION:
            if self._phase_started_at is None:
                self._phase_started_at = timestamp
            elapsed = max(0.0, _elapsed_seconds(timestamp, self._phase_started_at))
            if elapsed >= self.plan.transition_seconds:
                self._phase = RELAXED
                self._phase_started_at = timestamp
        return self._phase

    def begin_transition(self, timestamp=None) -> None:
        """Finish preferred collection and begin the sample-free relax pause."""

        if self._phase != PREFERRED:
            raise ValueError(f"cannot begin transition from {self._phase}")
        self._phase = TRANSITION
        self._phase_started_at = timestamp

    def relaxed_elapsed(self, timestamp) -> float:
        phase = self.stage_at(timestamp)
        if phase != RELAXED or self._phase_started_at is None:
            return 0.0
        return max(0.0, _elapsed_seconds(timestamp, self._phase_started_at))

    def relaxed_target_reached(self, timestamp) -> bool:
        return self.relaxed_elapsed(timestamp) >= self.plan.relaxed_seconds

    def relaxed_deadline_reached(self, timestamp) -> bool:
        maximum = self.plan.relaxed_seconds + self.plan.relaxed_max_extension_seconds
        return self.relaxed_elapsed(timestamp) >= maximum

    def ready_to_finalize(self, timestamp) -> bool:
        return (
            self.relaxed_target_reached(timestamp)
            and self._sample_counts[RELAXED] >= self.plan.min_samples_per_stage
        )

    def reject(self, timestamp, reason: str) -> str:
        """Reset the active anchor after a genuine contamination event."""

        stage = self.stage_at(timestamp)
        if stage not in (PREFERRED, RELAXED):
            return stage
        self._values[stage].clear()
        self._sample_counts[stage] = 0
        self._reset_reasons.append(f"{stage}:{reason}")
        return stage

    def skip(self, timestamp, reason: str) -> str:
        """Audit an abstained observation without erasing accepted samples."""

        stage = self.stage_at(timestamp)
        if stage not in (PREFERRED, RELAXED):
            return stage
        key = f"{stage}:{reason}"
        self._rejection_counts[key] = self._rejection_counts.get(key, 0) + 1
        return stage

    def add(self, timestamp, values: Mapping[str, float]) -> str:
        stage = self.stage_at(timestamp)
        if stage not in (PREFERRED, RELAXED):
            return stage
        usable = {
            name: numeric
            for name, value in values.items()
            if name in CALIBRATION_FEATURES
            and (numeric := _finite_float(value)) is not None
        }
        # A calibration sample is only useful when it contains at least one
        # posture feature.  Distance/environment measurements alone must not
        # advance the stage counter and later turn into a misleading
        # ``no_feature_separates_above_mdc`` failure.
        if not any(name in POSTURE_FEATURES for name in usable):
            self.skip(timestamp, "no_posture_features")
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

        policy = self.policy or PosturePolicy()
        enabled: list[str] = []
        disabled: dict[str, str] = {}
        runtime_noise_floors: dict[str, float] = {}
        for name in POSTURE_FEATURES:
            preferred = stage_stats[PREFERRED].get(name)
            relaxed = stage_stats[RELAXED].get(name)
            if preferred is None or relaxed is None:
                disabled[name] = "insufficient_valid_samples"
                continue
            separation = abs(relaxed.mean - preferred.mean)
            noise_floor = runtime_noise_floor(preferred, relaxed, policy, name)
            runtime_noise_floors[name] = noise_floor
            required_separation = noise_floor * policy.runtime_min_signal_to_noise_ratio
            if separation <= required_separation:
                # Keep the established audit code for report consumers. The
                # governing floor now includes MDC and within-anchor runtime
                # repeatability, so this legacy name is conservative rather
                # than an exact description of the expanded test.
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
            rejection_counts=self.rejection_counts,
            runtime_noise_floors=runtime_noise_floors,
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
    # A long gap means the camera/worker did not observe the user throughout
    # that interval. Never backfill it as continuous exposure on the next
    # frame. This is an acquisition reliability limit, not a medical value.
    maximum_observation_gap_seconds: float = 2.0
    confirmation_seconds: float = 3.0
    cooldown_seconds: float = 60.0
    moving_threshold: float = 0.20
    camera_scale_jump_ratio: float = 0.18
    within_group_corroboration: float = 0.12
    between_group_corroboration: float = 0.10
    # Runtime decisions operate on individual observations, so their noise
    # band is based on within-anchor standard deviation rather than SEM alone.
    # These are adjustable reliability/product parameters, not physiology.
    runtime_noise_std_multiplier: float = 1.96
    # A two-band span leaves at least one full noise band after the acceptance
    # band is removed, avoiding a near-zero scoring denominator.
    runtime_min_signal_to_noise_ratio: float = 2.0
    # Calibration smoothing can make observed std/MDC unrealistically close
    # to zero. These conservative feature-unit floors prevent a tiny stage
    # drift from becoming a complete 0-to-1 posture axis. They are adjustable
    # product reliability parameters, not physiological thresholds.
    runtime_ratio_noise_floor: float = 0.015
    runtime_angle_noise_floor_deg: float = 1.5

    def __post_init__(self) -> None:
        if not (0.0 <= self.watch_exit < self.watch_enter <= 1.0):
            raise ValueError("watch hysteresis must satisfy exit < enter")
        if not (0.0 <= self.alert_exit < self.alert_enter <= 1.0):
            raise ValueError("alert hysteresis must satisfy exit < enter")
        if self.recovery_half_life_seconds <= 0:
            raise ValueError("recovery_half_life_seconds must be positive")
        if self.maximum_observation_gap_seconds <= 0:
            raise ValueError("maximum_observation_gap_seconds must be positive")
        if self.runtime_noise_std_multiplier <= 0:
            raise ValueError("runtime_noise_std_multiplier must be positive")
        if self.runtime_min_signal_to_noise_ratio <= 1.0:
            raise ValueError("runtime_min_signal_to_noise_ratio must be greater than one")
        if self.runtime_ratio_noise_floor < 0.0:
            raise ValueError("runtime_ratio_noise_floor cannot be negative")
        if self.runtime_angle_noise_floor_deg < 0.0:
            raise ValueError("runtime_angle_noise_floor_deg cannot be negative")


@dataclass(frozen=True)
class FeatureDeviation:
    feature: str
    deviation: float
    current: float
    preferred: float
    relaxed: float
    mdc: float
    runtime_noise: float = 0.0
    signal_reliability: float = 1.0


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
    policy: Optional[PosturePolicy] = None,
    runtime_noise_floor: Optional[float] = None,
) -> FeatureDeviation:
    """Measure excursion beyond the user's two-anchor normal posture band.

    MDC is retained for reporting, but SEM-derived MDC is not a suitable
    single-observation tolerance because it shrinks as calibration sample count
    grows.  The runtime acceptance band therefore also includes within-anchor
    standard deviation. Features whose anchor span is only marginally above
    that band are excluded at calibration time so a near-zero usable
    denominator cannot amplify ordinary frame jitter.

    ``preferred`` and ``relaxed`` are both user-accepted calibration postures.
    The interval between them is therefore a personal normal range, not a
    zero-to-one risk axis. Deviation begins only after the observation passes
    the relaxed boundary in the calibrated direction by more than the runtime
    noise band. This prevents the posture explicitly requested in stage two
    from being reclassified as high deviation immediately after calibration.
    """

    policy = policy or PosturePolicy()
    anchor_delta = relaxed.mean - preferred.mean
    direction = 1.0 if anchor_delta >= 0.0 else -1.0
    anchor_span = abs(anchor_delta)
    mdc = max(preferred.mdc, relaxed.mdc, 1e-9)
    noise_floor = (
        max(float(runtime_noise_floor), mdc)
        if runtime_noise_floor is not None
        else _runtime_noise_floor_for_feature(preferred, relaxed, policy, feature)
    )
    credible_anchor_span = anchor_span - noise_floor
    minimum_credible_span = noise_floor * (
        policy.runtime_min_signal_to_noise_ratio - 1.0
    )
    signal_reliability = (
        1.0
        if credible_anchor_span >= minimum_credible_span and credible_anchor_span > 0.0
        else 0.0
    )
    if signal_reliability == 0.0:
        deviation = 0.0
    else:
        projected_change = (float(current) - preferred.mean) * direction
        beyond_relaxed = projected_change - anchor_span
        credible_excursion = max(0.0, beyond_relaxed - noise_floor)
        deviation = max(0.0, min(1.5, credible_excursion / credible_anchor_span))
    return FeatureDeviation(
        feature=feature,
        deviation=deviation,
        current=float(current),
        preferred=preferred.mean,
        relaxed=relaxed.mean,
        mdc=mdc,
        runtime_noise=noise_floor,
        signal_reliability=signal_reliability,
    )


def runtime_noise_floor(
    preferred: FeatureStatistics,
    relaxed: FeatureStatistics,
    policy: Optional[PosturePolicy] = None,
    feature: Optional[str] = None,
) -> float:
    """Return the product-policy noise band for one runtime observation."""

    return _runtime_noise_floor_for_feature(preferred, relaxed, policy, feature)


def _runtime_noise_floor_for_feature(
    preferred: FeatureStatistics,
    relaxed: FeatureStatistics,
    policy: Optional[PosturePolicy] = None,
    feature: Optional[str] = None,
) -> float:
    """Implementation kept separate from the public compatibility keyword."""

    policy = policy or PosturePolicy()
    multiplier = policy.runtime_noise_std_multiplier
    absolute_floor = 0.0
    if feature in FORWARD_FEATURES:
        absolute_floor = policy.runtime_ratio_noise_floor
    elif feature in LATERAL_FEATURES:
        absolute_floor = policy.runtime_angle_noise_floor_deg
    return max(
        preferred.mdc,
        relaxed.mdc,
        multiplier * preferred.std,
        multiplier * relaxed.std,
        absolute_floor,
        1e-9,
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
            normalized_feature_deviation(
                name,
                current,
                preferred,
                relaxed,
                policy,
                profile.runtime_noise_floors.get(name),
            )
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
        observation_gap = elapsed > self.policy.maximum_observation_gap_seconds
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
        if observation_gap:
            return ExposureSnapshot(
                exposure_seconds=self.exposure_seconds,
                watch_active=self.watch_active,
                alert_active=self.alert_active,
                integrated_seconds=0.0,
                recovery_seconds=0.0,
                paused=True,
            )
        if self.alert_active:
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


def _confidences_meet_floor(sample, names: Sequence[str], floor: float) -> bool:
    confidences = [_finite_float(getattr(sample, name, None)) for name in names]
    # Compatibility backends may not expose landmark-level confidence. Their
    # existing detected/value completeness checks remain the fallback.
    if all(value is None for value in confidences):
        return True
    return all(value is not None and value >= floor for value in confidences)


def calibration_measurement_values(
    sample,
    plan: Optional[CalibrationPlan] = None,
) -> dict[str, float]:
    """Extract only features whose own required landmarks meet the quality gate."""

    plan = plan or CalibrationPlan()
    values = measurement_values(sample)
    floor = plan.min_pose_quality
    face_quality = _finite_float(getattr(sample, "face_quality", None))
    if face_quality is not None and face_quality < plan.min_face_quality:
        # Face-derived evidence must not survive its own detector quality
        # gate. Shoulder/lateral evidence can still be retained when its
        # landmark confidence is independently usable.
        values.pop("face_shoulder_ratio", None)
    shoulders_ok = _confidences_meet_floor(
        sample,
        ("left_shoulder_confidence", "right_shoulder_confidence"),
        floor,
    )
    hips_ok = _confidences_meet_floor(
        sample,
        ("left_hip_confidence", "right_hip_confidence"),
        floor,
    )
    if not shoulders_ok:
        for name in (
            "face_shoulder_ratio",
            "torso_shoulder_ratio",
            "ear_shoulder_ratio",
            "shoulder_asymmetry_deg",
            "shoulder_width_px",
            "signed_shoulder_diff_px",
        ):
            values.pop(name, None)
    if not hips_ok:
        for name in ("torso_shoulder_ratio", "trunk_lean_deg", "torso_height_px"):
            values.pop(name, None)
    for side in ("left", "right"):
        if not _confidences_meet_floor(sample, (f"{side}_ear_confidence",), floor):
            values.pop("ear_shoulder_ratio", None)
    return values


def runtime_measurement_values(
    sample,
    plan: Optional[CalibrationPlan] = None,
) -> dict[str, float]:
    """Extract posture values whose own landmarks are usable in this frame."""

    return calibration_measurement_values(sample, plan)


_FEATURE_CONFIDENCE_REQUIREMENTS: Mapping[str, tuple[str, ...]] = {
    "face_shoulder_ratio": (
        "left_shoulder_confidence",
        "right_shoulder_confidence",
    ),
    "torso_shoulder_ratio": (
        "left_shoulder_confidence",
        "right_shoulder_confidence",
        "left_hip_confidence",
        "right_hip_confidence",
    ),
    "ear_shoulder_ratio": (
        "left_shoulder_confidence",
        "right_shoulder_confidence",
        "left_ear_confidence",
        "right_ear_confidence",
    ),
    "shoulder_asymmetry_deg": (
        "left_shoulder_confidence",
        "right_shoulder_confidence",
    ),
    "trunk_lean_deg": (
        "left_shoulder_confidence",
        "right_shoulder_confidence",
        "left_hip_confidence",
        "right_hip_confidence",
    ),
}


def feature_measurement_quality(sample, feature: str) -> float:
    """Return quality for the measurements that actually drive one feature."""

    qualities: list[float] = []
    if feature == "face_shoulder_ratio":
        face_quality = _finite_float(getattr(sample, "face_quality", None))
        qualities.append(face_quality if face_quality is not None else 1.0)

    confidence_names = _FEATURE_CONFIDENCE_REQUIREMENTS.get(feature, ())
    confidences = [_finite_float(getattr(sample, name, None)) for name in confidence_names]
    if any(value is not None for value in confidences):
        if all(value is not None for value in confidences):
            qualities.append(min(value for value in confidences if value is not None))
        else:
            qualities.append(0.0)
    else:
        pose_quality = _finite_float(getattr(sample, "pose_quality", None))
        if pose_quality is not None:
            qualities.append(pose_quality)

    return max(0.0, min(1.0, min(qualities))) if qualities else 1.0


def aggregate_sample_quality(
    sample,
    feature_names: Optional[Sequence[str]] = None,
) -> float:
    if feature_names is not None:
        if not feature_names:
            return 0.0
        qualities = [feature_measurement_quality(sample, name) for name in feature_names]
        if qualities:
            return max(0.0, min(1.0, min(qualities)))
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
    face_count = getattr(sample, "face_count", 0)
    if face_count > 1:
        return "single_person"
    person_count = getattr(sample, "person_count", None)
    if person_count is not None and person_count > 1:
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
    if (
        face_count < 1
        or (person_count is not None and person_count < 1)
        or not getattr(sample, "face_detected", False)
        or not getattr(sample, "pose_detected", False)
    ):
        return "keypoints_missing"
    values = calibration_measurement_values(sample, plan)
    face_quality = _finite_float(getattr(sample, "face_quality", None))
    pose_quality = _finite_float(getattr(sample, "pose_quality", None))
    shoulder_confidences = [
        _finite_float(getattr(sample, name, None))
        for name in ("left_shoulder_confidence", "right_shoulder_confidence")
    ]
    if all(value is not None for value in shoulder_confidences):
        if min(value for value in shoulder_confidences if value is not None) < plan.min_pose_quality:
            return "pose_quality_low"
    elif pose_quality is not None and pose_quality < plan.min_pose_quality:
        # Backends without landmark-level confidence retain the aggregate gate.
        return "pose_quality_low"
    if face_quality is not None and face_quality < plan.min_face_quality:
        if "face_shoulder_ratio" not in values:
            # A low-quality face does not invalidate independent shoulder and
            # trunk evidence. Reject only when no posture evidence remains.
            if not any(name in POSTURE_FEATURES for name in values):
                return "face_quality_low"
    motion = _finite_float(getattr(sample, "target_motion", None))
    if motion is not None and motion > plan.max_target_motion:
        return "target_moving"
    if not any(name in POSTURE_FEATURES for name in values):
        return "no_posture_features"
    return None
