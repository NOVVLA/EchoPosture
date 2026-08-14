"""Auditable posture-change and static-exposure logic.

This module deliberately contains no camera, GUI, persistence, or identity
code.  It turns numeric observations into within-person change estimates and
time-weighted exposure.  Every threshold below is a product interaction
policy, not a physiological limit or a medical dose.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
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
    "projected_head_trunk_angle_deg",
)
POSTURE_FEATURES = FORWARD_FEATURES + LATERAL_FEATURES

# These are retained in the calibration report for distance/environment
# diagnostics, but never contribute directly to posture deviation.
ENVIRONMENT_FEATURES = (
    "interpupillary_px",
    "shoulder_width_px",
    "signed_shoulder_diff_px",
    "shoulder_line_angle_deg",
    "torso_height_px",
    "ear_shoulder_offset_px",
    "head_turn_ratio",
    "eye_line_angle_deg",
    "hip_line_angle_deg",
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


def _advance_seconds(timestamp, seconds: float):
    """Add a duration to a datetime or monotonic-float timestamp."""

    if isinstance(timestamp, datetime):
        return timestamp + timedelta(seconds=seconds)
    return timestamp + seconds


def _finite_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _axis_angle_deg(first, second) -> float:
    """Return an undirected line angle in the stable [-90, 90) range."""

    angle = math.degrees(
        math.atan2(
            float(second[1]) - float(first[1]),
            float(second[0]) - float(first[0]),
        )
    )
    while angle >= 90.0:
        angle -= 180.0
    while angle < -90.0:
        angle += 180.0
    return angle


def _vertical_axis_angle_deg(top, bottom) -> float:
    """Return a directed screen-plane axis angle relative to image vertical."""

    dx = float(top[0]) - float(bottom[0])
    dy = float(bottom[1]) - float(top[1])
    return math.degrees(math.atan2(dx, max(abs(dy), 1.0)))


def _relative_axis_angle_deg(first: float, second: float) -> float:
    """Return the smallest directed difference between two projected axes."""

    return (float(first) - float(second) + 90.0) % 180.0 - 90.0


def projected_axis_values(sample) -> dict[str, float]:
    """Return auditable 2D image-plane axes without implying a spine angle.

    These values describe only projections in the camera image. They can be
    compared with the same user's calibration range, but cannot recover a 3D
    spinal curve or a clinical anatomical angle from a frontal monocular view.
    """

    values: dict[str, float] = {}
    shoulder_center = getattr(sample, "shoulder_center", None)
    hip_center = getattr(sample, "hip_center", None)
    nose = getattr(sample, "nose_point", None)
    if shoulder_center is not None and hip_center is not None:
        trunk_axis = _vertical_axis_angle_deg(shoulder_center, hip_center)
        values["projected_trunk_axis_deg"] = trunk_axis
        if nose is not None:
            head_axis = _vertical_axis_angle_deg(nose, shoulder_center)
            values["projected_head_axis_deg"] = head_axis
            values["projected_head_trunk_angle_deg"] = _relative_axis_angle_deg(
                head_axis,
                trunk_axis,
            )
    return values


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
    # Borderline upper-body landmarks may still provide a usable anchor when
    # collected repeatedly. Runtime decisions retain the stricter 0.65
    # quality floor, so this calibration grace does not enable intervention
    # from low-confidence observations. MediaPipe visibility commonly dips
    # below 0.40 at a frame edge; the per-feature repeatability/noise checks
    # remain responsible for disabling unstable anchor evidence.
    min_pose_quality: float = 0.30
    # Torso ratio and trunk lean depend on both hips. Keep their landmark
    # floor stricter so borderline shoulder samples do not smuggle weak hip
    # geometry into either anchor.
    min_hip_quality: float = 0.50
    max_target_motion: float = 0.20

    def __post_init__(self) -> None:
        if self.preferred_seconds <= 0 or self.relaxed_seconds <= 0:
            raise ValueError("calibration stages must have positive durations")
        if self.transition_seconds < 0 or self.relaxed_max_extension_seconds < 0:
            raise ValueError("calibration transition and extension cannot be negative")
        if self.min_samples_per_stage < 1:
            raise ValueError("min_samples_per_stage must be positive")
        if not (0.0 <= self.min_pose_quality <= 1.0):
            raise ValueError("min_pose_quality must be in [0, 1]")
        if not (0.0 <= self.min_hip_quality <= 1.0):
            raise ValueError("min_hip_quality must be in [0, 1]")

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
                # Anchor the relaxed window at the logical transition end, not
                # at the observing frame, so frame spacing cannot extend the
                # relaxed collection window past its intended deadline.
                self._phase_started_at = _advance_seconds(
                    self._phase_started_at,
                    self.plan.transition_seconds,
                )
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
        # common-feature failure.
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
            noise_floor = runtime_noise_floor(preferred, relaxed, policy, name)
            runtime_noise_floors[name] = noise_floor
            # Both anchors define accepted posture, so a small separation is
            # a legitimate narrow personal range rather than a calibration
            # failure. Runtime noise expands the range boundaries
            # independently; anchor separation is never a direction
            # requirement or a scoring denominator.
            enabled.append(name)

        if not enabled:
            raise ValueError("no_common_posture_features")

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
    # After calibration, require the target-locked runtime representation to
    # reproduce the personal normal band before exposure can accumulate. This
    # guards against a discontinuity between calibration samples and the
    # target-replaced monitoring stream. It is a product reliability delay,
    # not a physiological standard.
    post_calibration_validation_seconds: float = 2.0
    # A single excursion is usually a reach, lean, or seat adjustment. Require
    # the change to remain beyond the personal range before it can enter WATCH
    # or exposure integration. This is product debounce, not a health limit.
    posture_change_confirmation_seconds: float = 2.0
    confirmation_seconds: float = 3.0
    cooldown_seconds: float = 60.0
    moving_threshold: float = 0.20
    # Eye and hip lines that roll together indicate a changed image frame.
    # These are product reliability parameters, not anatomical standards.
    camera_roll_guard_deg: float = 3.0
    camera_roll_agreement_deg: float = 3.0
    within_group_corroboration: float = 0.12
    between_group_corroboration: float = 0.10
    # A single noisy landmark-derived feature cannot open an intervention
    # episode. At least one independent feature in the same physical group
    # must provide meaningful support. This is a product reliability rule,
    # not a physiological standard.
    minimum_group_support_deviation: float = 0.25
    # A lone channel is weaker evidence, not zero evidence. Discount it until
    # an independent channel supports the same physical group. This keeps
    # single-landmark noise below a corroborated event without creating a
    # hard cliff that hides a sustained, pronounced one-channel excursion.
    single_channel_evidence_discount: float = 0.75
    # A pronounced torso lean can be real side-reclining even when both
    # shoulders remain parallel. Permit that one independent angle only after
    # it is already clearly beyond the personal band; the normal two-feature
    # corroboration rule remains in force for shoulder asymmetry and all other
    # single-feature changes. This is a product reliability parameter, not an
    # anatomical limit.
    lone_trunk_lean_deviation: float = 0.65
    # A large head-to-trunk screen-plane angle is visible evidence that the
    # head and torso are not aligned even when the shoulder/pelvis axis stays
    # upright. This is a within-person 2D projection signal, not a spinal or
    # clinical angle. Ordinary single-feature changes still require support.
    lone_projected_head_trunk_deviation: float = 0.65
    # Shoulder-versus-pelvis imbalance can also be independently implausible
    # at the extreme end. Keep its threshold higher because arm movement and
    # partially visible shoulders can perturb this channel more easily.
    lone_shoulder_asymmetry_deviation: float = 0.85
    # A pronounced head-to-shoulder contraction/protraction or shoulder-to-
    # hip shortening can remain a single physical channel in a frontal view.
    # Permit one forward channel to stand alone only at the severe end.
    # Ordinary single-feature changes remain diagnostic-only. This is a
    # product interaction threshold, not an anatomical or medical standard.
    lone_forward_channel_deviation: float = 0.85
    # Head direction normally invalidates forward-posture geometry. A
    # moderate change therefore pauses scoring, while an extreme, stable,
    # high-quality direction change becomes its own auditable exposure
    # signal. These normalized FaceMesh deltas are product policy values.
    head_turn_observe_delta: float = 0.35
    head_turn_watch_delta: float = 0.45
    head_turn_full_delta: float = 0.70
    # Low track activity is an exposure-context signal, not posture geometry.
    # It may raise the combined risk index by a bounded amount even while the
    # calibrated posture remains normal, but it can never create WATCH/BAD or
    # posture exposure by itself. The current compatibility tracker measures
    # body-box translation and scale, so this is deliberately named and
    # interpreted as low *track* activity rather than proof of no body motion.
    static_hold_start_seconds: float = 60.0
    static_hold_full_seconds: float = 180.0
    static_hold_max_bonus: float = 0.12
    # Deprecated constructor compatibility. Eligibility is now determined by
    # reliable low track activity, independently of posture deviation.
    static_hold_min_deviation: float = 0.50
    # Runtime decisions operate on individual observations, so their noise
    # band is based on within-anchor standard deviation rather than SEM alone.
    # These are adjustable reliability/product parameters, not physiology.
    runtime_noise_std_multiplier: float = 3.0
    # Deprecated constructor compatibility only. This value is intentionally
    # ignored: anchor separation does not gate calibration or scale deviation.
    runtime_min_signal_to_noise_ratio: float = 2.0
    # Conservative feature-unit floors absorb boundary jitter. They are
    # adjustable product reliability parameters, not physiological thresholds.
    runtime_ratio_noise_floor: float = 0.010
    runtime_angle_noise_floor_deg: float = 1.0
    # Ordinary breathing, reaching, and seat adjustment are not measurement
    # noise. Bound the personal-span movement allowance with these absolute
    # caps, then compare it with the audited noise band so small natural
    # movement does not immediately change the user-visible state. These
    # margins are interaction policy, not physiological limits.
    runtime_ratio_movement_margin: float = 0.075
    runtime_angle_movement_margin_deg: float = 5.0
    # Natural movement allowance follows the user's accepted normal span.
    # The absolute movement margins above remain caps for unusually wide
    # anchor ranges; they are no longer added on top of the noise band.
    runtime_ratio_anchor_band_fraction: float = 0.75
    runtime_angle_anchor_band_fraction: float = 0.75
    # Outside the accepted range and its noise band, these independent scales
    # map raw feature units to a continuous product score. They deliberately
    # do not depend on how far apart the user's two normal anchors happen to be.
    runtime_ratio_response_scale: float = 0.07
    runtime_angle_response_scale_deg: float = 6.0
    # WATCH is lower-confidence evidence, so it integrates more slowly than
    # ALERT. A non-zero floor removes the permanent 0.69/0.70 exposure cliff.
    watch_exposure_min_weight: float = 0.25
    # Every normalized posture feature except trunk lean depends on the
    # detected shoulder span. If that shared denominator leaves both
    # calibrated anchor ranges by more than its repeatability allowance, the
    # ratios are not independent posture evidence. Abstain instead of turning
    # one landmark-width drift into several corroborating features. This is a
    # measurement-reliability parameter, not an anatomical threshold.
    shared_anchor_repeatability_floor_px: float = 2.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.watch_exit < self.watch_enter <= 1.0):
            raise ValueError("watch hysteresis must satisfy exit < enter")
        if not (0.0 <= self.alert_exit < self.alert_enter <= 1.0):
            raise ValueError("alert hysteresis must satisfy exit < enter")
        if self.watch_enter >= self.alert_enter:
            raise ValueError("watch_enter must be less than alert_enter")
        if self.recovery_half_life_seconds <= 0:
            raise ValueError("recovery_half_life_seconds must be positive")
        if self.maximum_observation_gap_seconds <= 0:
            raise ValueError("maximum_observation_gap_seconds must be positive")
        if self.post_calibration_validation_seconds < 0:
            raise ValueError("post_calibration_validation_seconds cannot be negative")
        if self.posture_change_confirmation_seconds < 0:
            raise ValueError("posture_change_confirmation_seconds cannot be negative")
        if self.runtime_noise_std_multiplier <= 0:
            raise ValueError("runtime_noise_std_multiplier must be positive")
        if self.runtime_ratio_noise_floor < 0.0:
            raise ValueError("runtime_ratio_noise_floor cannot be negative")
        if self.runtime_angle_noise_floor_deg < 0.0:
            raise ValueError("runtime_angle_noise_floor_deg cannot be negative")
        if self.runtime_ratio_movement_margin < 0.0:
            raise ValueError("runtime_ratio_movement_margin cannot be negative")
        if self.runtime_angle_movement_margin_deg < 0.0:
            raise ValueError("runtime_angle_movement_margin_deg cannot be negative")
        if not (0.0 <= self.runtime_ratio_anchor_band_fraction <= 1.0):
            raise ValueError("runtime_ratio_anchor_band_fraction must be in [0, 1]")
        if not (0.0 <= self.runtime_angle_anchor_band_fraction <= 1.0):
            raise ValueError("runtime_angle_anchor_band_fraction must be in [0, 1]")
        if self.runtime_ratio_response_scale <= 0.0:
            raise ValueError("runtime_ratio_response_scale must be positive")
        if self.runtime_angle_response_scale_deg <= 0.0:
            raise ValueError("runtime_angle_response_scale_deg must be positive")
        if self.shared_anchor_repeatability_floor_px < 0.0:
            raise ValueError("shared_anchor_repeatability_floor_px cannot be negative")
        if self.camera_roll_guard_deg < 0.0:
            raise ValueError("camera_roll_guard_deg cannot be negative")
        if self.camera_roll_agreement_deg < 0.0:
            raise ValueError("camera_roll_agreement_deg cannot be negative")
        if not (0.0 <= self.minimum_group_support_deviation <= 1.0):
            raise ValueError("minimum_group_support_deviation must be in [0, 1]")
        if not (0.0 <= self.single_channel_evidence_discount <= 1.0):
            raise ValueError("single_channel_evidence_discount must be in [0, 1]")
        if not (0.0 <= self.lone_trunk_lean_deviation <= 1.0):
            raise ValueError("lone_trunk_lean_deviation must be in [0, 1]")
        if not (0.0 <= self.lone_projected_head_trunk_deviation <= 1.0):
            raise ValueError("lone_projected_head_trunk_deviation must be in [0, 1]")
        if not (0.0 <= self.lone_shoulder_asymmetry_deviation <= 1.0):
            raise ValueError("lone_shoulder_asymmetry_deviation must be in [0, 1]")
        if not (0.0 <= self.lone_forward_channel_deviation <= 1.0):
            raise ValueError("lone_forward_channel_deviation must be in [0, 1]")
        if not (
            0.0 <= self.head_turn_observe_delta
            < self.head_turn_watch_delta
            < self.head_turn_full_delta
        ):
            raise ValueError("head-turn policy must satisfy observe < watch < full")
        if self.static_hold_start_seconds < 0.0:
            raise ValueError("static_hold_start_seconds cannot be negative")
        if self.static_hold_full_seconds <= self.static_hold_start_seconds:
            raise ValueError("static_hold_full_seconds must exceed start")
        if not (0.0 <= self.static_hold_max_bonus <= 1.0):
            raise ValueError("static_hold_max_bonus must be in [0, 1]")
        if not (0.0 <= self.static_hold_min_deviation <= 1.0):
            raise ValueError("static_hold_min_deviation must be in [0, 1]")
        if not (0.0 <= self.watch_exposure_min_weight <= 1.0):
            raise ValueError("watch_exposure_min_weight must be in [0, 1]")


@dataclass(frozen=True)
class FeatureDeviation:
    feature: str
    deviation: float
    current: float
    preferred: float
    relaxed: float
    mdc: float
    runtime_noise: float = 0.0
    acceptance_margin: float = 0.0
    signal_reliability: float = 1.0


@dataclass(frozen=True)
class PostureScore:
    deviation: float
    forward_deviation: float
    lateral_deviation: float
    features: tuple[FeatureDeviation, ...]
    coverage: float
    corroborated: bool = False
    raw_deviation: float = 0.0


def normalized_feature_deviation(
    feature: str,
    current: float,
    preferred: FeatureStatistics,
    relaxed: FeatureStatistics,
    policy: Optional[PosturePolicy] = None,
    runtime_noise_floor: Optional[float] = None,
) -> FeatureDeviation:
    """Measure bidirectional excursion beyond the two-anchor normal range.

    MDC is retained for reporting, but SEM-derived MDC is not a suitable
    single-observation tolerance because it shrinks as calibration sample count
    grows. The runtime acceptance band therefore also includes within-anchor
    standard deviation and a small feature-resolution floor.

    ``preferred`` and ``relaxed`` are both user-accepted calibration postures.
    Their ordered means define a personal normal range; neither anchor defines
    a bad direction or a score denominator. Deviation begins only after the
    observation leaves either boundary by more than the larger of the runtime
    noise band and the capped personal-span movement allowance, then uses an
    independent per-feature product response scale. Similar or identical
    anchors are therefore valid and cannot amplify frame jitter.
    """

    policy = policy or PosturePolicy()
    mdc = max(preferred.mdc, relaxed.mdc, 1e-9)
    noise_floor = (
        max(float(runtime_noise_floor), mdc)
        if runtime_noise_floor is not None
        else _runtime_noise_floor_for_feature(preferred, relaxed, policy, feature)
    )
    lower = min(preferred.mean, relaxed.mean)
    upper = max(preferred.mean, relaxed.mean)
    current_value = float(current)
    outside_distance = max(lower - current_value, current_value - upper, 0.0)
    anchor_span = upper - lower
    acceptance_margin = max(
        noise_floor,
        runtime_movement_margin(feature, policy, anchor_span=anchor_span),
    )
    # Treat the inclusive noise boundary as accepted. The epsilon prevents
    # binary floating-point representation from turning an exact policy
    # boundary into a microscopic non-zero deviation.
    credible_excursion = (
        0.0
        if outside_distance <= acceptance_margin + 1e-12
        else outside_distance - acceptance_margin
    )
    response_scale = _feature_response_scale(feature, policy)
    deviation = max(0.0, min(1.5, credible_excursion / response_scale))
    return FeatureDeviation(
        feature=feature,
        deviation=deviation,
        current=current_value,
        preferred=preferred.mean,
        relaxed=relaxed.mean,
        mdc=mdc,
        runtime_noise=noise_floor,
        acceptance_margin=acceptance_margin,
        signal_reliability=1.0,
    )


def _feature_response_scale(feature: str, policy: PosturePolicy) -> float:
    if feature in LATERAL_FEATURES:
        return policy.runtime_angle_response_scale_deg
    return policy.runtime_ratio_response_scale


def runtime_noise_floor(
    preferred: FeatureStatistics,
    relaxed: FeatureStatistics,
    policy: Optional[PosturePolicy] = None,
    feature: Optional[str] = None,
) -> float:
    """Return the product-policy noise band for one runtime observation."""

    return _runtime_noise_floor_for_feature(preferred, relaxed, policy, feature)


def runtime_movement_margin(
    feature: Optional[str],
    policy: Optional[PosturePolicy] = None,
    anchor_span: Optional[float] = None,
) -> float:
    """Return a personal-range movement allowance, capped in feature units."""

    policy = policy or PosturePolicy()
    if feature in LATERAL_FEATURES:
        maximum = policy.runtime_angle_movement_margin_deg
        fraction = policy.runtime_angle_anchor_band_fraction
    elif feature in FORWARD_FEATURES:
        maximum = policy.runtime_ratio_movement_margin
        fraction = policy.runtime_ratio_anchor_band_fraction
    else:
        return 0.0
    if anchor_span is None:
        return maximum
    return min(maximum, max(0.0, float(anchor_span)) * fraction)


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


def _group_score(
    values: Sequence[float],
    corroboration: float,
    minimum_support: float,
    single_channel_discount: float,
) -> tuple[float, bool]:
    ordered = sorted((max(0.0, value) for value in values), reverse=True)
    if not ordered:
        return 0.0, False
    primary = ordered[0]
    support = ordered[1] if len(ordered) > 1 else 0.0
    # A lone feature is weaker evidence. Discounting preserves the signal for
    # sustained exposure while independent support still receives full weight.
    if support < minimum_support:
        return min(1.0, primary * single_channel_discount), False
    return min(1.0, primary + min(corroboration, support * corroboration)), True


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
    # Face/shoulder and ear/shoulder are two views of the same head-to-shoulder
    # relation and share the same shoulder-width denominator. Treat them as
    # one evidence channel. Only torso/shoulder can independently support that
    # channel inside the forward group; otherwise one drifting shoulder span
    # would be counted twice and could open WATCH by itself.
    head_shoulder = max(
        by_name.get("face_shoulder_ratio", 0.0),
        by_name.get("ear_shoulder_ratio", 0.0),
    )
    torso_shoulder = by_name.get("torso_shoulder_ratio", 0.0)
    forward, forward_corroborated = _group_score(
        [head_shoulder, torso_shoulder],
        policy.within_group_corroboration,
        policy.minimum_group_support_deviation,
        policy.single_channel_evidence_discount,
    )
    # A frontal-view shoulder shrug or strong neck protraction can move only
    # one head/shoulder or torso/shoulder channel. Keep ordinary single-channel
    # changes inconclusive, but retain an extreme excursion as explicit
    # posture evidence rather than mislabelling it as normal.
    lone_forward = max(head_shoulder, torso_shoulder)
    if lone_forward >= policy.lone_forward_channel_deviation:
        forward = max(forward, min(1.0, lone_forward))
        forward_corroborated = True
    # Trunk lean and head-to-trunk angle share the same shoulder-to-hip axis.
    # Treat them as one projected-axis channel so translating the upper body
    # cannot manufacture two independent votes from one geometric event.
    # Shoulder-versus-pelvis asymmetry remains the separate lateral channel.
    trunk_lean = by_name.get("trunk_lean_deg", 0.0)
    projected_head_trunk = by_name.get("projected_head_trunk_angle_deg", 0.0)
    projected_axis = max(trunk_lean, projected_head_trunk)
    shoulder_asymmetry = by_name.get("shoulder_asymmetry_deg", 0.0)
    lateral, lateral_corroborated = _group_score(
        [projected_axis, shoulder_asymmetry],
        policy.within_group_corroboration,
        policy.minimum_group_support_deviation,
        policy.single_channel_evidence_discount,
    )
    # A genuine side-recline can rotate the torso around the pelvis while the
    # shoulder line remains almost parallel. Keep the two-feature rule for
    # ordinary lateral evidence, but let a pronounced pelvis-relative torso
    # lean stand on its own once it clears the explicit product reliability
    # parameter. This avoids suppressing the real posture pattern without
    # turning small single-feature jitter into an alert.
    if trunk_lean >= policy.lone_trunk_lean_deviation:
        lateral = max(lateral, trunk_lean)
        lateral_corroborated = True
    if projected_head_trunk >= policy.lone_projected_head_trunk_deviation:
        lateral = max(lateral, projected_head_trunk)
        lateral_corroborated = True
    if shoulder_asymmetry >= policy.lone_shoulder_asymmetry_deviation:
        lateral = max(lateral, shoulder_asymmetry)
        lateral_corroborated = True
    groups = sorted((forward, lateral), reverse=True)
    overall = min(
        1.0,
        groups[0]
        + min(policy.between_group_corroboration, groups[1] * policy.between_group_corroboration),
    )
    raw_forward = max(
        (by_name[name] for name in FORWARD_FEATURES if name in by_name),
        default=0.0,
    )
    raw_lateral = max(
        (by_name[name] for name in LATERAL_FEATURES if name in by_name),
        default=0.0,
    )
    raw_deviation = min(
        1.0,
        max(raw_forward, raw_lateral)
        + min(policy.between_group_corroboration, min(raw_forward, raw_lateral) * policy.between_group_corroboration),
    )
    coverage = len(feature_results) / max(1, len(profile.enabled_features))
    return PostureScore(
        deviation=overall,
        forward_deviation=forward,
        lateral_deviation=lateral,
        features=tuple(feature_results),
        coverage=coverage,
        corroborated=forward_corroborated or lateral_corroborated,
        raw_deviation=raw_deviation,
    )


def shared_scale_measurement_unstable(
    values: Mapping[str, float],
    profile: CalibrationProfile,
    policy: Optional[PosturePolicy] = None,
    score: Optional[PostureScore] = None,
) -> bool:
    """Detect a posture score driven by an unstable shared shoulder span.

    The normalized face, torso, ear, and shoulder-asymmetry features all use
    shoulder width. A pose-landmark width that moves beyond both accepted
    anchors can therefore move several ratios together while the person is
    physically unchanged. This check uses only the already-audited numeric
    calibration statistics and explicitly abstains; it never manufactures a
    GOOD or BAD posture judgment. Sub-WATCH forward noise cannot trigger an
    intervention, so it must not freeze the whole frame. Independent lateral
    evidence that already reaches WATCH also takes priority over this guard.
    """

    policy = policy or PosturePolicy()
    current = _finite_float(values.get("shoulder_width_px"))
    preferred = profile.preferred.get("shoulder_width_px")
    relaxed = profile.relaxed.get("shoulder_width_px")
    if (
        current is None
        or preferred is None
        or relaxed is None
        or preferred.mean <= 0.0
        or relaxed.mean <= 0.0
    ):
        return False

    def outside_anchor_band(name: str) -> Optional[bool]:
        observed = _finite_float(values.get(name))
        preferred_stats = profile.preferred.get(name)
        relaxed_stats = profile.relaxed.get(name)
        if observed is None or preferred_stats is None or relaxed_stats is None:
            return None
        repeatability = max(
            preferred_stats.mdc,
            relaxed_stats.mdc,
            policy.runtime_noise_std_multiplier * preferred_stats.std,
            policy.runtime_noise_std_multiplier * relaxed_stats.std,
            policy.shared_anchor_repeatability_floor_px,
        )
        lower = min(preferred_stats.mean, relaxed_stats.mean) - repeatability
        upper = max(preferred_stats.mean, relaxed_stats.mean) + repeatability
        return observed < lower or observed > upper

    # Shoulder span can legitimately change when the user moves towards or
    # away from the camera. It becomes a measurement reliability problem only
    # when it creates forward-ratio evidence without corresponding changes in
    # the raw numerators. Uniform whole-person scale changes keep the ratios
    # stable and must remain measurable at the new distance.
    if score is None:
        score = score_posture_deviation(values, profile, policy)
    if score.forward_deviation < policy.watch_enter:
        return False
    if score.lateral_deviation >= policy.watch_enter:
        return False
    feature_deviation = {item.feature: item.deviation for item in score.features}
    head_feature = max(
        ("face_shoulder_ratio", "ear_shoulder_ratio"),
        key=lambda name: feature_deviation.get(name, 0.0),
    )
    head_numerator = {
        "face_shoulder_ratio": "interpupillary_px",
        "ear_shoulder_ratio": "ear_shoulder_offset_px",
    }[head_feature]
    head_supported = outside_anchor_band(head_numerator)
    torso_supported = outside_anchor_band("torso_height_px")
    torso_deviation = feature_deviation.get("torso_shoulder_ratio", 0.0)
    head_deviation = feature_deviation.get(head_feature, 0.0)
    if (
        head_deviation >= policy.lone_forward_channel_deviation
        and torso_deviation < policy.minimum_group_support_deviation
    ):
        # For the explicit lone-head exception, its raw numerator must move.
        return head_supported is not True
    if (
        torso_deviation >= policy.lone_forward_channel_deviation
        and head_deviation < policy.minimum_group_support_deviation
    ):
        # The same rule applies to a lone, extreme shoulder-to-hip change.
        return torso_supported is not True
    # Abstain only when neither raw numerator supports the ratio change. One
    # real head or torso numerator excursion remains measurable even if the
    # other ratio also moved because the shoulder denominator changed.
    return head_supported is not True and torso_supported is not True


@dataclass(frozen=True)
class ExposureSnapshot:
    exposure_seconds: float
    watch_active: bool
    alert_active: bool
    integrated_seconds: float
    recovery_seconds: float
    paused: bool


@dataclass(frozen=True)
class StaticHoldSnapshot:
    """Continuous low-track-activity evidence and its bounded risk add-on."""

    static_seconds: float
    bonus: float
    paused: bool


class StaticHoldAccumulator:
    """Track one uninterrupted period with reliable low target-track motion.

    The add-on changes combined risk only. It is never posture evidence and
    cannot make a normal posture enter WATCH/BAD. Long gaps, detected movement,
    low measurement quality, or an uncertain target reset the hold.
    """

    def __init__(self, policy: Optional[PosturePolicy] = None) -> None:
        self.policy = policy or PosturePolicy()
        self.static_seconds = 0.0
        self.last_timestamp = None

    def reset(self) -> None:
        self.static_seconds = 0.0
        self.last_timestamp = None

    def _advance_time(self, timestamp) -> float:
        if self.last_timestamp is None:
            self.last_timestamp = timestamp
            return 0.0
        elapsed = max(0.0, _elapsed_seconds(timestamp, self.last_timestamp))
        self.last_timestamp = timestamp
        return elapsed

    def _snapshot(self, paused: bool) -> StaticHoldSnapshot:
        ramp = max(
            0.0,
            min(
                1.0,
                (self.static_seconds - self.policy.static_hold_start_seconds)
                / (self.policy.static_hold_full_seconds - self.policy.static_hold_start_seconds),
            ),
        )
        return StaticHoldSnapshot(
            static_seconds=self.static_seconds,
            bonus=self.policy.static_hold_max_bonus * ramp,
            paused=paused,
        )

    def update(
        self,
        timestamp,
        *,
        posture_deviation: float,
        eligible: bool,
        paused: bool = False,
    ) -> StaticHoldSnapshot:
        elapsed = self._advance_time(timestamp)
        gap = elapsed > self.policy.maximum_observation_gap_seconds
        if (
            paused
            or gap
            or not eligible
        ):
            self.static_seconds = 0.0
            return self._snapshot(True)
        self.static_seconds += elapsed
        return self._snapshot(False)


class ExposureAccumulator:
    """Integrate severity-weighted posture exposure using real timestamps."""

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
        elif self.watch_active and deviation >= self.policy.watch_enter:
            watch_span = self.policy.alert_enter - self.policy.watch_enter
            progress = min(
                1.0,
                max(0.0, (deviation - self.policy.watch_enter) / watch_span),
            )
            weight = self.policy.watch_exposure_min_weight + (
                1.0 - self.policy.watch_exposure_min_weight
            ) * progress
            integrated = elapsed * deviation * weight
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
    projected_axes = projected_axis_values(sample)
    values.update(projected_axes)
    left_eye = getattr(sample, "left_eye_center", None)
    right_eye = getattr(sample, "right_eye_center", None)
    if left_eye is not None and right_eye is not None:
        values["eye_line_angle_deg"] = _axis_angle_deg(left_eye, right_eye)
    left_hip = getattr(sample, "left_hip_point", None)
    right_hip = getattr(sample, "right_hip_point", None)
    hip_line_angle = None
    if left_hip is not None and right_hip is not None:
        hip_line_angle = _axis_angle_deg(left_hip, right_hip)
        values["hip_line_angle_deg"] = hip_line_angle
    if shoulder_width is not None and shoulder_width > 0.0:
        if interpupillary is not None:
            values["face_shoulder_ratio"] = interpupillary / shoulder_width
        if torso_height is not None:
            values["torso_shoulder_ratio"] = torso_height / shoulder_width
        if signed_shoulder is not None:
            left_shoulder = getattr(sample, "left_shoulder_point", None)
            right_shoulder = getattr(sample, "right_shoulder_point", None)
            shoulder_angle = (
                _axis_angle_deg(left_shoulder, right_shoulder)
                if left_shoulder is not None and right_shoulder is not None
                else math.degrees(math.atan2(-signed_shoulder, shoulder_width))
            )
            values["shoulder_line_angle_deg"] = shoulder_angle
            # Shoulder asymmetry is meaningful relative to the user's pelvis,
            # not the camera's horizontal axis. Subtracting the hip-line angle
            # makes a rigid camera/person roll rotation invariant while still
            # retaining a real shoulder-versus-pelvis imbalance.
            values["shoulder_asymmetry_deg"] = (
                # Wrap the difference so a rigid roll near the +/-90 edge is
                # reported as the small true relative angle instead of a
                # phantom ~180-degree imbalance.
                _relative_axis_angle_deg(shoulder_angle, hip_line_angle)
                if hip_line_angle is not None
                else shoulder_angle
            )

        ear_offsets_px: list[float] = []
        for side in ("left", "right"):
            ear = getattr(sample, f"{side}_ear_point", None)
            shoulder = getattr(sample, f"{side}_shoulder_point", None)
            if ear is not None and shoulder is not None:
                ear_offsets_px.append(float(shoulder[1]) - float(ear[1]))
        if ear_offsets_px:
            ear_offset_px = sum(ear_offsets_px) / len(ear_offsets_px)
            values["ear_shoulder_offset_px"] = ear_offset_px
            values["ear_shoulder_ratio"] = ear_offset_px / shoulder_width
    if trunk_lean is not None:
        # ``trunk_lean_deg`` is expressed against the image vertical. A rigid
        # frame roll changes it by the hip-line angle, so subtracting that
        # angle converts it to a pelvis-relative torso lean.
        projected_trunk = projected_axes.get("projected_trunk_axis_deg")
        if projected_trunk is not None:
            trunk_lean = projected_trunk
        values["trunk_lean_deg"] = (
            # Same wraparound guard as shoulder asymmetry: near-vertical axes
            # must not flip into a phantom ~180-degree lean after subtraction.
            _relative_axis_angle_deg(trunk_lean, hip_line_angle)
            if hip_line_angle is not None
            else trunk_lean
        )
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
        values.pop("interpupillary_px", None)
        values.pop("eye_line_angle_deg", None)
    shoulders_ok = _confidences_meet_floor(
        sample,
        ("left_shoulder_confidence", "right_shoulder_confidence"),
        floor,
    )
    hips_ok = _confidences_meet_floor(
        sample,
        ("left_hip_confidence", "right_hip_confidence"),
        max(floor, plan.min_hip_quality),
    )
    if not shoulders_ok:
        for name in (
            "face_shoulder_ratio",
            "torso_shoulder_ratio",
            "ear_shoulder_ratio",
            "ear_shoulder_offset_px",
            "shoulder_asymmetry_deg",
            "shoulder_width_px",
            "signed_shoulder_diff_px",
            "shoulder_line_angle_deg",
            "projected_head_trunk_angle_deg",
            "projected_head_axis_deg",
            "projected_trunk_axis_deg",
        ):
            values.pop(name, None)
    if not hips_ok:
        for name in (
            "torso_shoulder_ratio",
            "trunk_lean_deg",
            "torso_height_px",
            "hip_line_angle_deg",
            "projected_head_trunk_angle_deg",
            "projected_trunk_axis_deg",
        ):
            values.pop(name, None)
        # Preserve shoulder-only evidence without allowing low-confidence hip
        # points to rotate it. A single shoulder feature still cannot open
        # WATCH because the lateral group requires independent support.
        shoulder_line = values.get("shoulder_line_angle_deg")
        if shoulder_line is not None:
            values["shoulder_asymmetry_deg"] = shoulder_line
    for side in ("left", "right"):
        if not _confidences_meet_floor(sample, (f"{side}_ear_confidence",), floor):
            values.pop("ear_shoulder_ratio", None)
            values.pop("ear_shoulder_offset_px", None)
    if not _confidences_meet_floor(sample, ("nose_confidence",), floor):
        values.pop("projected_head_trunk_angle_deg", None)
        values.pop("projected_head_axis_deg", None)
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
    "projected_head_trunk_angle_deg": (
        "nose_confidence",
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
    face_required = bool(getattr(sample, "face_required_for_calibration", True))
    face_count = getattr(sample, "face_count", 0)
    if face_required and face_count > 1:
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
        (face_required and face_count < 1)
        or (person_count is not None and person_count < 1)
        or (face_required and not getattr(sample, "face_detected", False))
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
    if face_required and face_quality is not None and face_quality < plan.min_face_quality:
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
