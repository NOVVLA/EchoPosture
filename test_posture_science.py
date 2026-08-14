"""Deterministic tests for two-anchor posture and exposure logic."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

from posture_science import (
    CalibrationAccumulator,
    CalibrationPlan,
    CalibrationProfile,
    ExposureAccumulator,
    FeatureStatistics,
    PosturePolicy,
    RELAXED,
    TRANSITION,
    aggregate_sample_quality,
    calibration_measurement_values,
    calibration_rejection_reason,
    measurement_values,
    normalized_feature_deviation,
    projected_axis_values,
    runtime_noise_floor,
    runtime_movement_margin,
    score_posture_deviation,
    StaticHoldAccumulator,
    shared_scale_measurement_unstable,
)


def anchor_values(offset: float, stable_ear: float = 0.40) -> dict[str, float]:
    return {
        "face_shoulder_ratio": 0.30 + offset * 0.10,
        "torso_shoulder_ratio": 0.90 - offset * 0.20,
        "ear_shoulder_ratio": stable_ear,
        "shoulder_asymmetry_deg": 1.0 + offset * 6.0,
        "trunk_lean_deg": 1.0 + offset * 10.0,
        "interpupillary_px": 60.0 + offset * 2.0,
        "shoulder_width_px": 200.0,
        "signed_shoulder_diff_px": 3.0 + offset * 20.0,
        "torso_height_px": 180.0 - offset * 30.0,
        "head_turn_ratio": 0.01,
    }


def build_profile():
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index * 0.3, anchor_values(0.0))
    accumulator.begin_transition(5.0)
    assert accumulator.add(5.5, anchor_values(0.5)) == TRANSITION
    for index in range(5):
        accumulator.add(6.0 + index * 1.0, anchor_values(1.0))
    return accumulator.finalize(datetime(2026, 1, 1, 12, 0, 0))


def build_reported_defect_profile() -> CalibrationProfile:
    """Reproduce the dual-anchor profile from the intervention defect report."""

    rng = random.Random(7)

    def stats(mean: float, jitter: float) -> FeatureStatistics:
        return FeatureStatistics.from_values(
            [mean + rng.uniform(-jitter, jitter) for _ in range(20)]
        )

    preferred = {
        "face_shoulder_ratio": stats(0.295, 0.004),
        "torso_shoulder_ratio": stats(1.071, 0.010),
        "ear_shoulder_ratio": stats(0.360, 0.006),
        "shoulder_asymmetry_deg": stats(1.0, 0.5),
        "trunk_lean_deg": stats(2.0, 0.6),
        "projected_head_trunk_angle_deg": stats(4.0, 0.8),
    }
    relaxed = {
        "face_shoulder_ratio": stats(0.310, 0.004),
        "torso_shoulder_ratio": stats(1.020, 0.010),
        "ear_shoulder_ratio": stats(0.395, 0.006),
        "shoulder_asymmetry_deg": stats(1.6, 0.5),
        "trunk_lean_deg": stats(3.2, 0.6),
        "projected_head_trunk_angle_deg": stats(6.0, 0.8),
    }
    return CalibrationProfile(
        preferred=preferred,
        relaxed=relaxed,
        enabled_features=tuple(preferred),
        disabled_features={},
        calibration_quality=0.9,
        stage_counts={"preferred": 20, "relaxed": 20},
        created_at=datetime(2026, 8, 14, 12, 0, 0),
    )


def test_statistics_sem_mdc_cv() -> None:
    stats = FeatureStatistics.from_values([8.0, 10.0, 12.0])
    assert stats.n == 3
    assert math.isclose(stats.mean, 10.0)
    assert math.isclose(stats.std, 2.0)
    assert math.isclose(stats.sem, 2.0 / math.sqrt(3.0))
    assert math.isclose(stats.mdc, 1.96 * math.sqrt(2.0) * stats.sem)
    assert math.isclose(stats.cv or 0.0, 0.2)
    print("test_statistics_sem_mdc_cv OK")


def test_two_anchor_segmentation_and_noise_floor() -> None:
    profile = build_profile()
    assert profile.stage_counts == {"preferred": 5, "relaxed": 5}
    assert "face_shoulder_ratio" in profile.enabled_features
    assert "trunk_lean_deg" in profile.enabled_features
    assert "ear_shoulder_ratio" in profile.enabled_features
    ear_at_anchor = normalized_feature_deviation(
        "ear_shoulder_ratio",
        0.40,
        profile.preferred["ear_shoulder_ratio"],
        profile.relaxed["ear_shoulder_ratio"],
        runtime_noise_floor=profile.runtime_noise_floors["ear_shoulder_ratio"],
    )
    assert ear_at_anchor.deviation == 0.0
    assert 0.0 < profile.calibration_quality <= 1.0
    print("test_two_anchor_segmentation_and_noise_floor OK")


def test_similar_stable_anchors_form_a_valid_normal_range() -> None:
    """Natural relaxation is allowed to look the same as preferred posture."""

    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    preferred_values = [0.298, 0.301, 0.300, 0.302, 0.299]
    relaxed_values = [0.301, 0.303, 0.302, 0.304, 0.300]
    for index, value in enumerate(preferred_values):
        accumulator.add(index, {"face_shoulder_ratio": value})
    accumulator.begin_transition(5.0)
    for index, value in enumerate(relaxed_values):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": value})

    profile = accumulator.finalize()
    assert profile.stage_counts == {"preferred": 5, "relaxed": 5}
    assert profile.enabled_features == ("face_shoulder_ratio",)
    assert profile.scientific_ready
    print("test_similar_stable_anchors_form_a_valid_normal_range OK")


def test_identical_stable_anchors_form_a_valid_normal_range() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.300})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": 0.300})

    profile = accumulator.finalize()
    assert profile.enabled_features == ("face_shoulder_ratio",)
    noise = profile.runtime_noise_floors["face_shoulder_ratio"]
    at_anchor = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.300,
        profile.preferred["face_shoulder_ratio"],
        profile.relaxed["face_shoulder_ratio"],
        runtime_noise_floor=noise,
    )
    assert at_anchor.deviation == 0.0
    print("test_identical_stable_anchors_form_a_valid_normal_range OK")


def test_invalid_sample_resets_only_current_stage() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(3):
        accumulator.add(index * 0.2, anchor_values(0.0))
    accumulator.reject(0.7, "single_person")
    assert accumulator.stage_counts["preferred"] == 0
    for index in range(5):
        accumulator.add(0.8 + index * 0.2, anchor_values(0.0))
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index * 1.0, anchor_values(1.0))
    profile = accumulator.finalize()
    assert profile.stage_counts["preferred"] == 5
    assert "preferred:single_person" in profile.reset_reasons
    print("test_invalid_sample_resets_only_current_stage OK")


def test_low_quality_abstention_preserves_valid_samples() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(4):
        accumulator.add(index * 0.2, anchor_values(0.0))
    accumulator.skip(0.9, "pose_quality_low")
    assert accumulator.stage_counts["preferred"] == 4
    assert accumulator.reset_reasons == ()
    assert accumulator.rejection_counts == {"preferred:pose_quality_low": 1}
    accumulator.add(1.0, anchor_values(0.0))
    assert accumulator.stage_counts["preferred"] == 5
    print("test_low_quality_abstention_preserves_valid_samples OK")


def test_environment_only_values_do_not_count_as_posture_samples() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(4):
        stage = accumulator.add(
            index * 0.2,
            {
                "interpupillary_px": 60.0,
                "shoulder_width_px": 220.0,
            },
        )
        assert stage == "preferred"
    assert accumulator.stage_counts["preferred"] == 0
    assert accumulator.rejection_counts == {"preferred:no_posture_features": 4}
    accumulator.add(1.0, anchor_values(0.0))
    assert accumulator.stage_counts["preferred"] == 1
    print("test_environment_only_values_do_not_count_as_posture_samples OK")


def test_zero_person_dropout_abstains_but_multiple_people_contaminate() -> None:
    missing = SimpleNamespace(
        face_count=0,
        person_count=0,
        face_detected=False,
        pose_detected=False,
        target_state="TARGET_OCCLUDED",
    )
    multiple = SimpleNamespace(
        face_count=2,
        person_count=2,
        face_detected=True,
        pose_detected=True,
    )
    assert calibration_rejection_reason(missing) == "target_uncertain"
    assert calibration_rejection_reason(multiple) == "single_person"

    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(4):
        accumulator.add(index * 0.2, anchor_values(0.0))
    reason = calibration_rejection_reason(missing)
    assert reason not in {"single_person", "target_ambiguous"}
    accumulator.skip(0.9, reason or "unknown")
    assert accumulator.stage_counts["preferred"] == 4
    assert accumulator.reset_reasons == ()
    print("test_zero_person_dropout_abstains_but_multiple_people_contaminate OK")


def test_low_hip_visibility_does_not_reject_upper_body_evidence() -> None:
    sample = SimpleNamespace(
        face_count=1,
        person_count=1,
        target_state="TARGET_LOCKED",
        face_detected=True,
        pose_detected=True,
        face_quality=1.0,
        pose_quality=0.55,
        target_motion=0.0,
        interpupillary_px=60.0,
        shoulder_width_px=200.0,
        signed_shoulder_diff_px=4.0,
        torso_height_px=180.0,
        trunk_lean_deg=2.0,
        left_ear_point=(250.0, 150.0),
        right_ear_point=(350.0, 150.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 240.0),
        left_shoulder_confidence=0.55,
        right_shoulder_confidence=0.58,
        left_hip_confidence=0.45,
        right_hip_confidence=0.48,
        left_ear_confidence=0.90,
        right_ear_confidence=0.89,
    )
    assert calibration_rejection_reason(sample) is None
    assert CalibrationPlan().min_pose_quality == 0.30
    assert CalibrationPlan().min_hip_quality == 0.50
    values = calibration_measurement_values(sample)
    assert "face_shoulder_ratio" in values
    assert "shoulder_asymmetry_deg" in values
    assert "ear_shoulder_ratio" in values
    assert "ear_shoulder_offset_px" in values
    assert "torso_shoulder_ratio" not in values
    assert "trunk_lean_deg" not in values
    print("test_low_hip_visibility_does_not_reject_upper_body_evidence OK")


def test_lateral_features_are_invariant_to_rigid_frame_roll() -> None:
    """Camera roll changes image axes, not shoulder-versus-pelvis posture."""

    def rotate(point: tuple[float, float], degrees: float) -> tuple[float, float]:
        radians = math.radians(degrees)
        return (
            point[0] * math.cos(radians) - point[1] * math.sin(radians),
            point[0] * math.sin(radians) + point[1] * math.cos(radians),
        )

    def sample(
        degrees: float,
        scale: float = 1.0,
        translation: tuple[float, float] = (0.0, 0.0),
    ):
        points = {
            "left_eye_center": (-30.0, -140.0),
            "right_eye_center": (30.0, -140.0),
            "left_shoulder_point": (-100.0, -80.0),
            "right_shoulder_point": (100.0, -60.0),
            "left_hip_point": (-60.0, 80.0),
            "right_hip_point": (60.0, 80.0),
            "shoulder_center": (0.0, -70.0),
            "hip_center": (0.0, 80.0),
        }
        rotated = {
            name: (
                rotate(point, degrees)[0] * scale + translation[0],
                rotate(point, degrees)[1] * scale + translation[1],
            )
            for name, point in points.items()
        }
        signed_shoulder = (
            rotated["left_shoulder_point"][1]
            - rotated["right_shoulder_point"][1]
        )
        shoulder_width = math.dist(
            rotated["left_shoulder_point"],
            rotated["right_shoulder_point"],
        )
        shoulder_center = rotated["shoulder_center"]
        hip_center = rotated["hip_center"]
        trunk_lean = math.degrees(
            math.atan2(
                shoulder_center[0] - hip_center[0],
                max(abs(hip_center[1] - shoulder_center[1]), 1.0),
            )
        )
        return SimpleNamespace(
            interpupillary_px=60.0,
            shoulder_width_px=shoulder_width,
            signed_shoulder_diff_px=signed_shoulder,
            torso_height_px=math.dist(shoulder_center, hip_center),
            trunk_lean_deg=trunk_lean,
            head_turn_ratio=0.01,
            **rotated,
        )

    upright = calibration_measurement_values(sample(0.0))
    for degrees, scale, translation in (
        (-25.0, 0.70, (45.0, -30.0)),
        (-8.0, 1.30, (-20.0, 55.0)),
        (3.0, 0.90, (0.0, 0.0)),
        (12.0, 1.00, (100.0, 100.0)),
        (30.0, 1.15, (-75.0, 20.0)),
    ):
        transformed = calibration_measurement_values(
            sample(degrees, scale, translation)
        )
        assert math.isclose(
            upright["shoulder_asymmetry_deg"],
            transformed["shoulder_asymmetry_deg"],
            abs_tol=1e-9,
        )
        assert math.isclose(
            upright["trunk_lean_deg"],
            transformed["trunk_lean_deg"],
            abs_tol=1e-9,
        )
    rolled = calibration_measurement_values(sample(12.0))
    assert math.isclose(
        rolled["eye_line_angle_deg"] - upright["eye_line_angle_deg"],
        12.0,
        abs_tol=1e-9,
    )
    assert math.isclose(
        rolled["hip_line_angle_deg"] - upright["hip_line_angle_deg"],
        12.0,
        abs_tol=1e-9,
    )
    print("test_lateral_features_are_invariant_to_rigid_frame_roll OK")


def test_low_face_quality_preserves_independent_pose_evidence() -> None:
    sample = SimpleNamespace(
        face_count=1,
        person_count=1,
        target_state="TARGET_LOCKED",
        face_detected=True,
        pose_detected=True,
        face_quality=0.40,
        pose_quality=0.80,
        target_motion=0.0,
        interpupillary_px=60.0,
        shoulder_width_px=200.0,
        signed_shoulder_diff_px=4.0,
        torso_height_px=180.0,
        trunk_lean_deg=2.0,
        left_shoulder_confidence=0.80,
        right_shoulder_confidence=0.82,
        left_hip_confidence=0.80,
        right_hip_confidence=0.81,
    )
    values = calibration_measurement_values(sample)
    assert "face_shoulder_ratio" not in values
    assert "interpupillary_px" not in values
    assert "torso_shoulder_ratio" in values
    assert calibration_rejection_reason(sample) is None
    print("test_low_face_quality_preserves_independent_pose_evidence OK")


def test_feature_quality_uses_only_scored_landmarks() -> None:
    sample = SimpleNamespace(
        face_quality=0.95,
        pose_quality=0.95,
        left_shoulder_confidence=0.90,
        right_shoulder_confidence=0.88,
        left_hip_confidence=0.20,
        right_hip_confidence=0.22,
    )
    upper_quality = aggregate_sample_quality(
        sample,
        ("face_shoulder_ratio", "shoulder_asymmetry_deg"),
    )
    torso_quality = aggregate_sample_quality(sample, ("torso_shoulder_ratio",))
    assert math.isclose(upper_quality, 0.88)
    assert math.isclose(torso_quality, 0.20)
    assert aggregate_sample_quality(sample, ()) == 0.0
    print("test_feature_quality_uses_only_scored_landmarks OK")


def test_low_ear_quality_removes_raw_and_normalized_ear_evidence() -> None:
    sample = SimpleNamespace(
        face_detected=True,
        pose_detected=True,
        face_quality=0.95,
        pose_quality=0.95,
        interpupillary_px=60.0,
        shoulder_width_px=200.0,
        signed_shoulder_diff_px=4.0,
        torso_height_px=180.0,
        trunk_lean_deg=2.0,
        left_ear_point=(250.0, 150.0),
        right_ear_point=(350.0, 150.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 240.0),
        left_shoulder_confidence=0.90,
        right_shoulder_confidence=0.90,
        left_hip_confidence=0.90,
        right_hip_confidence=0.90,
        left_ear_confidence=0.20,
        right_ear_confidence=0.20,
        head_turn_ratio=0.01,
    )
    values = calibration_measurement_values(sample)
    assert "ear_shoulder_ratio" not in values
    assert "ear_shoulder_offset_px" not in values
    assert "face_shoulder_ratio" in values
    assert "torso_shoulder_ratio" in values
    print("test_low_ear_quality_removes_raw_and_normalized_ear_evidence OK")


def test_stage_sample_shortage_fails() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index * 0.2, anchor_values(0.0))
    accumulator.begin_transition(5.0)
    for index in range(4):
        accumulator.add(6.0 + index * 1.0, anchor_values(1.0))
    try:
        accumulator.finalize()
    except ValueError as exc:
        assert "relaxed_samples" in str(exc)
    else:
        raise AssertionError("short relaxed stage must fail calibration")
    print("test_stage_sample_shortage_fails OK")


def test_no_common_posture_feature_is_the_only_profile_level_failure() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.30})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"trunk_lean_deg": 2.0})

    try:
        accumulator.finalize()
    except ValueError as exc:
        assert str(exc) == "no_common_posture_features"
    else:
        raise AssertionError("disjoint stage features must not create a profile")
    print("test_no_common_posture_feature_is_the_only_profile_level_failure OK")


def test_watch_threshold_must_precede_alert_threshold() -> None:
    for alert_enter in (0.50, 0.40):
        try:
            PosturePolicy(
                watch_enter=0.50,
                alert_enter=alert_enter,
                alert_exit=0.30,
            )
        except ValueError as exc:
            assert str(exc) == "watch_enter must be less than alert_enter"
        else:
            raise AssertionError("watch_enter must remain below alert_enter")
    print("test_watch_threshold_must_precede_alert_threshold OK")


def test_explicit_phase_timing_and_bounded_extension() -> None:
    plan = CalibrationPlan(min_samples_per_stage=5)
    assert plan.preferred_seconds == 5.0
    assert plan.transition_seconds == 1.0
    assert plan.relaxed_seconds == 5.0
    assert plan.relaxed_max_extension_seconds == 2.0

    accumulator = CalibrationAccumulator(plan)
    for index in range(5):
        assert accumulator.add(index * 1.0, anchor_values(0.0)) == "preferred"
    assert accumulator.stage_counts == {"preferred": 5, "relaxed": 0}

    accumulator.begin_transition(5.0)
    assert accumulator.add(5.25, anchor_values(0.5)) == TRANSITION
    assert accumulator.reject(5.75, "target_moving") == TRANSITION
    assert accumulator.stage_counts == {"preferred": 5, "relaxed": 0}
    assert accumulator.reset_reasons == ()

    for index in range(4):
        assert accumulator.add(6.0 + index, anchor_values(1.0)) == RELAXED
    assert not accumulator.ready_to_finalize(11.0)
    assert not accumulator.relaxed_deadline_reached(11.0)
    assert accumulator.add(11.5, anchor_values(1.0)) == RELAXED
    assert accumulator.ready_to_finalize(11.5)
    assert not accumulator.relaxed_deadline_reached(11.5)
    profile = accumulator.finalize()
    assert profile.stage_counts == {"preferred": 5, "relaxed": 5}

    insufficient = CalibrationAccumulator(plan)
    for index in range(5):
        insufficient.add(index * 1.0, anchor_values(0.0))
    insufficient.begin_transition(5.0)
    for index in range(4):
        insufficient.add(6.0 + index, anchor_values(1.0))
    assert insufficient.relaxed_deadline_reached(13.0)
    assert not insufficient.ready_to_finalize(13.0)
    print("test_explicit_phase_timing_and_bounded_extension OK")


def test_mdc_normalization_and_group_deduplication() -> None:
    profile = build_profile()
    preferred = profile.preferred["face_shoulder_ratio"]
    relaxed = profile.relaxed["face_shoulder_ratio"]
    at_preferred = normalized_feature_deviation(
        "face_shoulder_ratio", preferred.mean, preferred, relaxed
    )
    at_relaxed = normalized_feature_deviation(
        "face_shoulder_ratio", relaxed.mean, preferred, relaxed
    )
    assert at_preferred.deviation == 0.0
    assert at_relaxed.deviation == 0.0

    midpoint = score_posture_deviation(anchor_values(0.5), profile)
    relaxed_score = score_posture_deviation(anchor_values(1.0), profile)
    assert midpoint.deviation == 0.0
    assert relaxed_score.deviation == 0.0

    score = score_posture_deviation(anchor_values(2.5), profile)
    assert math.isclose(score.forward_deviation, 1.0)
    assert score.lateral_deviation >= 0.95
    assert math.isclose(score.deviation, 1.0)
    assert score.deviation <= max(score.forward_deviation, score.lateral_deviation) + 0.10
    print("test_mdc_normalization_and_group_deduplication OK")


def test_reported_bad_posture_scenarios_are_actionable() -> None:
    profile = build_reported_defect_profile()
    policy = PosturePolicy()
    base = {
        "face_shoulder_ratio": 0.345,
        "shoulder_asymmetry_deg": 3.0,
        "trunk_lean_deg": 6.0,
    }
    scenarios = {
        "A": {
            **base,
            "torso_shoulder_ratio": 0.98,
            "ear_shoulder_ratio": 0.325,
            "projected_head_trunk_angle_deg": 9.0,
        },
        "B": {
            **base,
            "torso_shoulder_ratio": 0.94,
            "ear_shoulder_ratio": 0.295,
            "projected_head_trunk_angle_deg": 13.0,
        },
        "C": {
            **base,
            "torso_shoulder_ratio": 0.88,
            "ear_shoulder_ratio": 0.255,
            "projected_head_trunk_angle_deg": 18.0,
        },
        "D": {
            **base,
            "torso_shoulder_ratio": 0.82,
            "ear_shoulder_ratio": 0.21,
            "projected_head_trunk_angle_deg": 24.0,
        },
    }
    scores = {
        name: score_posture_deviation(values, profile, policy)
        for name, values in scenarios.items()
    }

    assert 0.0 < scores["A"].deviation < policy.watch_enter, scores["A"]
    assert scores["B"].deviation >= policy.watch_enter, scores["B"]
    assert scores["C"].deviation >= policy.alert_enter, scores["C"]
    assert scores["D"].deviation >= policy.severe_deviation, scores["D"]
    assert score_posture_deviation(
        {name: stats.mean for name, stats in profile.preferred.items()},
        profile,
        policy,
    ).deviation == 0.0
    assert score_posture_deviation(
        {name: stats.mean for name, stats in profile.relaxed.items()},
        profile,
        policy,
    ).deviation == 0.0
    print("test_reported_bad_posture_scenarios_are_actionable OK")


def test_range_deviation_is_bidirectional_and_uses_personal_anchor_span() -> None:
    policy = PosturePolicy()
    identical = FeatureStatistics.from_values([0.300] * 5)
    narrow_margin = policy.runtime_ratio_noise_floor
    lower = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.300 - narrow_margin - 0.035,
        identical,
        identical,
        policy,
    )
    upper = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.300 + narrow_margin + 0.035,
        identical,
        identical,
        policy,
    )
    inside_noise = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.300 + narrow_margin,
        identical,
        identical,
        policy,
    )
    assert math.isclose(lower.deviation, 0.5, rel_tol=1e-9)
    assert math.isclose(upper.deviation, 0.5, rel_tol=1e-9)
    assert inside_noise.deviation == 0.0

    wide_preferred = FeatureStatistics.from_values([0.250] * 5)
    wide_relaxed = FeatureStatistics.from_values([0.350] * 5)
    wide_margin = runtime_movement_margin(
        "face_shoulder_ratio",
        policy,
        anchor_span=wide_relaxed.mean - wide_preferred.mean,
    )
    same_excursion = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.350 + wide_margin + 0.035,
        wide_preferred,
        wide_relaxed,
        policy,
    )
    assert math.isclose(same_excursion.deviation, upper.deviation)
    assert same_excursion.acceptance_margin > upper.acceptance_margin
    print("test_range_deviation_is_bidirectional_and_uses_personal_anchor_span OK")


def test_legacy_anchor_separation_policy_is_ignored() -> None:
    strict_legacy_policy = PosturePolicy(runtime_min_signal_to_noise_ratio=999.0)
    accumulator = CalibrationAccumulator(
        CalibrationPlan(min_samples_per_stage=5),
        policy=strict_legacy_policy,
    )
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.300})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": 0.300})
    assert accumulator.finalize().scientific_ready
    print("test_legacy_anchor_separation_policy_is_ignored OK")


def test_single_feature_excursion_is_discounted_for_group_scoring() -> None:
    profile = build_profile()
    values = anchor_values(0.0)
    preferred = profile.preferred["face_shoulder_ratio"]
    relaxed = profile.relaxed["face_shoulder_ratio"]
    noise = profile.runtime_noise_floors["face_shoulder_ratio"]
    direction = 1.0 if relaxed.mean >= preferred.mean else -1.0
    values["face_shoulder_ratio"] = preferred.mean + direction * (
        abs(relaxed.mean - preferred.mean)
        + noise
        + runtime_movement_margin("face_shoulder_ratio")
        + 0.02
    )
    # Remove every independent feature from both physical groups except the
    # one drifting ratio. It remains weaker than corroborated evidence, but a
    # sustained pronounced excursion is no longer erased.
    values = {"face_shoulder_ratio": values["face_shoulder_ratio"]}
    score = score_posture_deviation(values, profile)
    assert score.raw_deviation > 0.0
    assert 0.0 < score.deviation < score.raw_deviation, score
    assert not score.corroborated, score
    print("test_single_feature_excursion_is_discounted_for_group_scoring OK")


def test_extreme_lone_forward_channel_is_explicit_evidence() -> None:
    profile = build_profile()
    torso_values = {
        "torso_shoulder_ratio": 0.45,
        "torso_height_px": 90.0,
        "shoulder_width_px": 200.0,
    }
    score = score_posture_deviation(torso_values, profile)

    assert score.forward_deviation >= PosturePolicy().lone_forward_channel_deviation
    assert score.deviation >= PosturePolicy().severe_deviation
    assert score.corroborated
    assert not shared_scale_measurement_unstable(torso_values, profile, score=score)

    head_values = {
        "face_shoulder_ratio": 0.08,
        "interpupillary_px": 16.0,
        "shoulder_width_px": 200.0,
    }
    head_score = score_posture_deviation(head_values, profile)
    assert head_score.forward_deviation >= PosturePolicy().lone_forward_channel_deviation
    assert head_score.corroborated
    assert not shared_scale_measurement_unstable(head_values, profile, score=head_score)

    denominator_only = {
        "torso_shoulder_ratio": 180.0 / 130.0,
        "torso_height_px": 180.0,
        "shoulder_width_px": 130.0,
    }
    drift_score = score_posture_deviation(denominator_only, profile)
    assert drift_score.corroborated
    assert shared_scale_measurement_unstable(
        denominator_only,
        profile,
        score=drift_score,
    )
    print("test_extreme_lone_forward_channel_is_explicit_evidence OK")


def test_shared_head_shoulder_ratios_are_one_evidence_channel() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(
            index,
            {
                "face_shoulder_ratio": 0.30,
                "ear_shoulder_ratio": 0.40,
            },
        )
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(
            6.0 + index,
            {
                "face_shoulder_ratio": 0.40,
                "ear_shoulder_ratio": 0.50,
            },
        )
    profile = accumulator.finalize()

    score = score_posture_deviation(
        {
            "face_shoulder_ratio": 0.50,
            "ear_shoulder_ratio": 0.60,
        },
        profile,
    )
    assert score.raw_deviation > 0.0
    assert 0.0 < score.deviation < score.raw_deviation, score
    assert not score.corroborated, score
    print("test_shared_head_shoulder_ratios_are_one_evidence_channel OK")


def test_shared_shoulder_scale_drift_abstains_from_ratio_scoring() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    preferred = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "shoulder_width_px": 200.0,
    }
    relaxed = {
        "face_shoulder_ratio": 1.0 / 3.0,
        "torso_shoulder_ratio": 1.00,
        "ear_shoulder_ratio": 4.0 / 9.0,
        "shoulder_width_px": 180.0,
    }
    for index in range(5):
        accumulator.add(index, preferred)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, relaxed)
    profile = accumulator.finalize()
    unchanged_numerators_with_drifted_width = {
        "face_shoulder_ratio": 60.0 / 145.0,
        "torso_shoulder_ratio": 180.0 / 145.0,
        "ear_shoulder_ratio": 80.0 / 145.0,
        "shoulder_width_px": 145.0,
    }

    score = score_posture_deviation(unchanged_numerators_with_drifted_width, profile)
    assert score.deviation >= PosturePolicy().alert_enter
    assert shared_scale_measurement_unstable(
        unchanged_numerators_with_drifted_width,
        profile,
    )
    assert not shared_scale_measurement_unstable(relaxed, profile)
    print("test_shared_shoulder_scale_drift_abstains_from_ratio_scoring OK")


def test_uniform_distance_scale_change_remains_measurable() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    preferred = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "shoulder_width_px": 200.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    relaxed = dict(preferred)
    for index in range(5):
        accumulator.add(index, preferred)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, relaxed)
    profile = accumulator.finalize()

    scaled = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "shoulder_width_px": 270.0,
        "interpupillary_px": 81.0,
        "torso_height_px": 243.0,
        "ear_shoulder_offset_px": 108.0,
    }
    score = score_posture_deviation(scaled, profile)
    assert score.deviation == 0.0
    assert score.raw_deviation == 0.0
    assert not shared_scale_measurement_unstable(scaled, profile, score=score)
    print("test_uniform_distance_scale_change_remains_measurable OK")


def test_raw_support_uses_measured_repeatability_not_percent_floor() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    anchor = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "shoulder_width_px": 200.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    for index in range(5):
        accumulator.add(index, anchor)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, anchor)
    profile = accumulator.finalize()

    torso_supported = {
        "face_shoulder_ratio": 60.0 / 180.0,
        "torso_shoulder_ratio": 186.0 / 180.0,
        "ear_shoulder_ratio": 80.0 / 180.0,
        "shoulder_width_px": 180.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 186.0,
        "ear_shoulder_offset_px": 80.0,
    }
    score = score_posture_deviation(torso_supported, profile)
    assert score.forward_deviation > 0.0, score
    assert not shared_scale_measurement_unstable(
        torso_supported,
        profile,
        score=score,
    )
    print("test_raw_support_uses_measured_repeatability_not_percent_floor OK")


def test_minor_shared_scale_drift_does_not_force_abstention() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    anchor = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "shoulder_width_px": 200.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    for index in range(5):
        accumulator.add(index, anchor)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, anchor)
    profile = accumulator.finalize()

    minor_width_change = {
        "face_shoulder_ratio": 60.0 / 208.0,
        "torso_shoulder_ratio": 180.0 / 208.0,
        "ear_shoulder_ratio": 80.0 / 208.0,
        "shoulder_width_px": 208.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    score = score_posture_deviation(minor_width_change, profile)
    assert 0.0 < score.forward_deviation < PosturePolicy().watch_enter, score
    assert not shared_scale_measurement_unstable(
        minor_width_change,
        profile,
        score=score,
    )
    print("test_minor_shared_scale_drift_does_not_force_abstention OK")


def test_independent_posture_evidence_bypasses_shared_scale_abstention() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    anchor = {
        "face_shoulder_ratio": 0.30,
        "torso_shoulder_ratio": 0.90,
        "ear_shoulder_ratio": 0.40,
        "trunk_lean_deg": 0.0,
        "projected_head_trunk_angle_deg": 0.0,
        "shoulder_width_px": 200.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    for index in range(5):
        accumulator.add(index, anchor)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, anchor)
    profile = accumulator.finalize()

    projected_lean = {
        "face_shoulder_ratio": 60.0 / 220.0,
        "torso_shoulder_ratio": 180.0 / 220.0,
        "ear_shoulder_ratio": 80.0 / 220.0,
        "trunk_lean_deg": 18.0,
        "projected_head_trunk_angle_deg": 18.0,
        "shoulder_width_px": 220.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
    }
    score = score_posture_deviation(projected_lean, profile)
    assert score.forward_deviation >= PosturePolicy().watch_enter, score
    assert score.lateral_deviation >= PosturePolicy().watch_enter, score
    assert not shared_scale_measurement_unstable(
        projected_lean,
        profile,
        score=score,
    )
    print("test_independent_posture_evidence_bypasses_shared_scale_abstention OK")


def test_shared_scale_drift_requires_raw_support_only_at_watch_level() -> None:
    """Sub-WATCH drift stays measurable; actionable drift needs raw support."""

    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    preferred = {
        "face_shoulder_ratio": 60.0 / 200.0,
        "torso_shoulder_ratio": 180.0 / 200.0,
        "ear_shoulder_ratio": 80.0 / 200.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
        "shoulder_width_px": 200.0,
    }
    relaxed = {
        "face_shoulder_ratio": 60.0 / 185.0,
        "torso_shoulder_ratio": 180.0 / 185.0,
        "ear_shoulder_ratio": 80.0 / 185.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
        "shoulder_width_px": 185.0,
    }
    for index in range(5):
        accumulator.add(index, preferred)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, relaxed)
    profile = accumulator.finalize()
    unchanged_numerators = {
        "face_shoulder_ratio": 60.0 / 170.0,
        "torso_shoulder_ratio": 180.0 / 170.0,
        "ear_shoulder_ratio": 80.0 / 170.0,
        "interpupillary_px": 60.0,
        "torso_height_px": 180.0,
        "ear_shoulder_offset_px": 80.0,
        "shoulder_width_px": 170.0,
    }

    score = score_posture_deviation(unchanged_numerators, profile)
    # The shared-denominator signal is visible but remains below the first
    # intervention threshold, so it cannot accumulate exposure and should not
    # freeze the rest of the frame.
    assert 0.0 < score.deviation < PosturePolicy().watch_enter
    assert score.raw_deviation > 0.0
    assert not shared_scale_measurement_unstable(
        unchanged_numerators,
        profile,
        score=score,
    )

    one_changed_numerator = dict(unchanged_numerators)
    one_changed_numerator["torso_height_px"] = 200.0
    one_changed_numerator["torso_shoulder_ratio"] = 200.0 / 175.0
    one_changed_score = score_posture_deviation(one_changed_numerator, profile)
    assert one_changed_score.deviation >= PosturePolicy().severe_deviation
    assert one_changed_score.raw_deviation >= one_changed_score.deviation
    assert one_changed_score.corroborated
    assert not shared_scale_measurement_unstable(
        one_changed_numerator,
        profile,
        score=one_changed_score,
    )

    corroborated_raw_change = dict(one_changed_numerator)
    corroborated_raw_change["ear_shoulder_offset_px"] = 100.0
    corroborated_raw_change["ear_shoulder_ratio"] = 100.0 / 175.0
    corroborated_score = score_posture_deviation(corroborated_raw_change, profile)
    assert corroborated_score.deviation >= PosturePolicy().alert_enter
    assert corroborated_score.corroborated
    assert not shared_scale_measurement_unstable(
        corroborated_raw_change,
        profile,
        score=corroborated_score,
    )
    print("test_in_range_shoulder_drift_requires_raw_forward_support OK")


def test_runtime_noise_band_uses_single_observation_repeatability() -> None:
    preferred = FeatureStatistics.from_values([0.98, 0.99, 1.00, 1.01, 1.02] * 20)
    relaxed = FeatureStatistics.from_values([1.18, 1.19, 1.20, 1.21, 1.22] * 20)

    # SEM/MDC becomes small with many samples, but one observation still has
    # the same within-anchor spread. A normal preferred fluctuation must not
    # enter WATCH merely because n is large.
    assert preferred.mdc < preferred.std
    near_preferred = normalized_feature_deviation(
        "face_shoulder_ratio",
        preferred.mean + 1.5 * preferred.std,
        preferred,
        relaxed,
    )
    assert near_preferred.deviation == 0.0, near_preferred
    assert near_preferred.runtime_noise >= 3.0 * preferred.std
    assert math.isclose(
        near_preferred.runtime_noise,
        runtime_noise_floor(preferred, relaxed),
    )
    print("test_runtime_noise_band_uses_single_observation_repeatability OK")


def test_marginal_anchor_range_is_valid_and_noise_bounded() -> None:
    plan = CalibrationPlan(min_samples_per_stage=5)
    accumulator = CalibrationAccumulator(plan)
    preferred_values = [0.98, 0.99, 1.00, 1.01, 1.02]
    relaxed_values = [1.01, 1.02, 1.03, 1.04, 1.05]
    for index, value in enumerate(preferred_values):
        accumulator.add(index, {"face_shoulder_ratio": value})
    accumulator.begin_transition(5.0)
    for index, value in enumerate(relaxed_values):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": value})

    profile = accumulator.finalize()
    assert profile.enabled_features == ("face_shoulder_ratio",)
    noise = profile.runtime_noise_floors["face_shoulder_ratio"]
    stats = FeatureStatistics.from_values(preferred_values)
    assert 0.03 > stats.mdc
    assert 0.0 < noise
    upper = profile.relaxed["face_shoulder_ratio"].mean
    span = upper - profile.preferred["face_shoulder_ratio"].mean
    acceptance_margin = max(
        noise,
        runtime_movement_margin(
            "face_shoulder_ratio",
            anchor_span=span,
        ),
    )
    inside_noise = normalized_feature_deviation(
        "face_shoulder_ratio",
        upper + acceptance_margin,
        profile.preferred["face_shoulder_ratio"],
        profile.relaxed["face_shoulder_ratio"],
        runtime_noise_floor=noise,
    )
    outside_noise = normalized_feature_deviation(
        "face_shoulder_ratio",
        upper + acceptance_margin + 0.035,
        profile.preferred["face_shoulder_ratio"],
        profile.relaxed["face_shoulder_ratio"],
        runtime_noise_floor=noise,
    )
    assert inside_noise.deviation == 0.0
    assert math.isclose(outside_noise.deviation, 0.5)
    print("test_marginal_anchor_range_is_valid_and_noise_bounded OK")


def test_near_identical_smoothed_anchors_form_a_narrow_range() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.300})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": 0.305})

    preferred = FeatureStatistics.from_values([0.300] * 5)
    relaxed = FeatureStatistics.from_values([0.305] * 5)
    assert preferred.std == 0.0 and relaxed.std == 0.0
    assert runtime_noise_floor(
        preferred,
        relaxed,
        feature="face_shoulder_ratio",
    ) == PosturePolicy().runtime_ratio_noise_floor

    profile = accumulator.finalize()
    assert profile.enabled_features == ("face_shoulder_ratio",)
    span = (
        profile.relaxed["face_shoulder_ratio"].mean
        - profile.preferred["face_shoulder_ratio"].mean
    )
    acceptance_margin = max(
        profile.runtime_noise_floors["face_shoulder_ratio"],
        runtime_movement_margin(
            "face_shoulder_ratio",
            anchor_span=span,
        ),
    )
    result = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.305
        + acceptance_margin
        + 0.035,
        profile.preferred["face_shoulder_ratio"],
        profile.relaxed["face_shoulder_ratio"],
        runtime_noise_floor=profile.runtime_noise_floors["face_shoulder_ratio"],
    )
    assert math.isclose(result.deviation, 0.5)
    print("test_near_identical_smoothed_anchors_form_a_narrow_range OK")


def test_narrow_anchor_span_does_not_amplify_runtime_jitter() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.300})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": 0.320})

    profile = accumulator.finalize()
    noise = profile.runtime_noise_floors["face_shoulder_ratio"]
    span = (
        profile.relaxed["face_shoulder_ratio"].mean
        - profile.preferred["face_shoulder_ratio"].mean
    )
    acceptance_margin = max(
        noise,
        runtime_movement_margin(
            "face_shoulder_ratio",
            anchor_span=span,
        ),
    )
    just_outside_range = normalized_feature_deviation(
        "face_shoulder_ratio",
        0.320 + acceptance_margin + 0.0035,
        profile.preferred["face_shoulder_ratio"],
        profile.relaxed["face_shoulder_ratio"],
        runtime_noise_floor=noise,
    )
    assert math.isclose(just_outside_range.deviation, 0.05, rel_tol=1e-9)
    print("test_narrow_anchor_span_does_not_amplify_runtime_jitter OK")


def test_exposure_uses_timestamps_pauses_and_decays() -> None:
    policy = PosturePolicy(recovery_half_life_seconds=10.0)
    exposure = ExposureAccumulator(policy)
    start = datetime(2026, 1, 1, 12, 0, 0)

    snapshot = exposure.update(start, 1.0)
    for seconds in range(1, 13):
        snapshot = exposure.update(start + timedelta(seconds=seconds), 1.0)
    assert math.isclose(snapshot.exposure_seconds, 12.0)
    assert snapshot.alert_active

    paused = exposure.pause(start + timedelta(seconds=112))
    assert math.isclose(paused.exposure_seconds, 12.0)
    assert paused.paused

    recovered = paused
    for seconds in range(113, 123):
        recovered = exposure.update(start + timedelta(seconds=seconds), 0.0)
    assert math.isclose(recovered.exposure_seconds, 6.0, rel_tol=1e-6)
    assert not recovered.watch_active
    assert not recovered.alert_active
    print("test_exposure_uses_timestamps_pauses_and_decays OK")


def test_long_observation_gap_does_not_backfill_exposure() -> None:
    exposure = ExposureAccumulator()
    exposure.update(0.0, 1.0)
    after_gap = exposure.update(300.0, 1.0)
    assert after_gap.paused
    assert after_gap.exposure_seconds == 0.0
    next_observed_second = exposure.update(301.0, 1.0)
    assert next_observed_second.exposure_seconds == 1.0
    print("test_long_observation_gap_does_not_backfill_exposure OK")


def test_watch_only_deviation_does_not_preload_exposure() -> None:
    exposure = ExposureAccumulator()
    exposure.update(0.0, 0.60)
    watching = exposure.update(300.0, 0.60)
    assert watching.watch_active
    assert not watching.alert_active
    assert watching.integrated_seconds == 0.0
    assert watching.exposure_seconds == 0.0

    exposure.update(301.0, 1.0)
    brief_alert = exposure.update(302.0, 1.0)
    assert brief_alert.exposure_seconds == 2.0
    assert brief_alert.exposure_seconds < exposure.policy.alert_exposure_seconds
    print("test_watch_only_deviation_does_not_preload_exposure OK")


def test_sustained_watch_deviation_accumulates_slower_exposure() -> None:
    policy = PosturePolicy(maximum_observation_gap_seconds=1.0)
    exposure = ExposureAccumulator(policy)
    start = datetime(2026, 1, 1, 12, 0, 0)
    short_watch = exposure.update(start, 0.60)
    for index in range(1, 101):
        short_watch = exposure.update(
            start + timedelta(seconds=index * 0.2),
            0.60,
        )
    assert 0.0 < short_watch.exposure_seconds < policy.alert_exposure_seconds
    assert short_watch.watch_active
    assert not short_watch.alert_active

    sustained_watch = short_watch
    for index in range(101, 301):
        sustained_watch = exposure.update(
            start + timedelta(seconds=index * 0.2),
            0.60,
        )
    assert sustained_watch.exposure_seconds >= policy.alert_exposure_seconds
    assert sustained_watch.watch_active
    assert not sustained_watch.alert_active
    print("test_sustained_watch_deviation_accumulates_slower_exposure OK")


def test_exposure_hysteresis() -> None:
    exposure = ExposureAccumulator()
    exposure.update(0.0, 0.49)
    assert not exposure.watch_active
    exposure.update(1.0, 0.50)
    assert exposure.watch_active
    exposure.update(2.0, 0.45)
    assert exposure.watch_active
    exposure.update(3.0, 0.40)
    assert not exposure.watch_active

    exposure.update(4.0, 0.70)
    assert exposure.alert_active
    exposure.update(5.0, 0.60)
    assert exposure.alert_active
    exposure.update(6.0, 0.55)
    assert not exposure.alert_active

    exposure.mark_alert(10.0)
    assert not exposure.alert_available(69.9)
    assert exposure.alert_available(70.0)
    print("test_exposure_hysteresis OK")


def test_low_track_activity_add_on_is_bounded_and_resets_when_ineligible() -> None:
    policy = PosturePolicy(
        static_hold_start_seconds=60.0,
        static_hold_full_seconds=180.0,
        static_hold_max_bonus=0.12,
        maximum_observation_gap_seconds=120.0,
    )
    hold = StaticHoldAccumulator(policy)
    start = datetime(2026, 1, 1, 12, 0, 0)

    normal = hold.update(start, posture_deviation=0.0, eligible=False)
    assert normal.bonus == 0.0
    normal = hold.update(start + timedelta(seconds=300), posture_deviation=0.0, eligible=False)
    assert normal.static_seconds == 0.0
    assert normal.bonus == 0.0

    hold.update(start + timedelta(seconds=301), posture_deviation=0.0, eligible=True)
    before_start = hold.update(start + timedelta(seconds=360), posture_deviation=0.0, eligible=True)
    assert before_start.static_seconds == 60.0
    assert before_start.bonus == 0.0
    ramped = hold.update(start + timedelta(seconds=420), posture_deviation=0.0, eligible=True)
    assert 0.0 < ramped.bonus < policy.static_hold_max_bonus
    capped = hold.update(start + timedelta(seconds=540), posture_deviation=0.0, eligible=True)
    assert capped.bonus == policy.static_hold_max_bonus

    reset = hold.update(start + timedelta(seconds=541), posture_deviation=0.8, eligible=False)
    assert reset.static_seconds == 0.0
    assert reset.bonus == 0.0
    print("test_low_track_activity_add_on_is_bounded_and_resets_when_ineligible OK")


def test_pronounced_lone_trunk_lean_is_lateral_evidence() -> None:
    profile = build_profile()
    values = anchor_values(0.0)
    values["shoulder_asymmetry_deg"] = profile.preferred["shoulder_asymmetry_deg"].mean
    values["trunk_lean_deg"] = 24.0
    values = {"trunk_lean_deg": values["trunk_lean_deg"], "shoulder_asymmetry_deg": values["shoulder_asymmetry_deg"]}
    score = score_posture_deviation(values, profile)
    assert score.lateral_deviation >= PosturePolicy().lone_trunk_lean_deviation
    assert score.deviation >= PosturePolicy().watch_enter
    assert score.corroborated
    print("test_pronounced_lone_trunk_lean_is_lateral_evidence OK")


def test_shared_projected_axis_does_not_corroborate_itself() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    anchor = {
        "shoulder_asymmetry_deg": 0.0,
        "trunk_lean_deg": 0.0,
        "projected_head_trunk_angle_deg": 0.0,
    }
    for index in range(5):
        accumulator.add(index, anchor)
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, anchor)
    profile = accumulator.finalize()

    score = score_posture_deviation(
        {
            "shoulder_asymmetry_deg": 0.0,
            "trunk_lean_deg": 4.6,
            # The same torso translation changes this derived angle in the
            # opposite direction. It is not an independent second landmark
            # event and must not satisfy the two-channel support rule.
            "projected_head_trunk_angle_deg": -4.6,
        },
        profile,
    )
    policy = PosturePolicy()
    assert math.isclose(score.raw_deviation, 0.6)
    assert math.isclose(
        score.lateral_deviation,
        score.raw_deviation * policy.single_channel_evidence_discount,
    )
    assert math.isclose(score.deviation, score.lateral_deviation)
    assert not score.corroborated
    print("test_shared_projected_axis_does_not_corroborate_itself OK")


def test_projected_axes_separate_head_tilt_from_trunk_translation() -> None:
    upright = SimpleNamespace(
        nose_point=(320.0, 170.0),
        shoulder_center=(320.0, 242.0),
        hip_center=(320.0, 390.0),
    )
    upright_values = projected_axis_values(upright)
    assert math.isclose(upright_values["projected_trunk_axis_deg"], 0.0)
    assert math.isclose(upright_values["projected_head_trunk_angle_deg"], 0.0)

    head_tilt = SimpleNamespace(
        nose_point=(370.0, 170.0),
        shoulder_center=(320.0, 242.0),
        hip_center=(320.0, 390.0),
    )
    head_values = projected_axis_values(head_tilt)
    assert head_values["projected_head_trunk_angle_deg"] > 30.0
    assert math.isclose(head_values["projected_trunk_axis_deg"], 0.0)

    torso_shift = SimpleNamespace(
        nose_point=(390.0, 170.0),
        shoulder_center=(390.0, 242.0),
        hip_center=(320.0, 390.0),
    )
    torso_values = projected_axis_values(torso_shift)
    assert torso_values["projected_trunk_axis_deg"] > 20.0
    assert math.isclose(torso_values["projected_head_trunk_angle_deg"], -torso_values["projected_trunk_axis_deg"])
    print("test_projected_axes_separate_head_tilt_from_trunk_translation OK")


def test_relative_axis_difference_wraps_near_vertical_edges() -> None:
    rolled = SimpleNamespace(
        shoulder_width_px=200.0,
        interpupillary_px=60.0,
        signed_shoulder_diff_px=3.0,
        torso_height_px=180.0,
        trunk_lean_deg=85.0,
        left_shoulder_point=(0.0, 0.0),
        right_shoulder_point=(10.0, 114.3),
        left_hip_point=(0.0, 0.0),
        right_hip_point=(10.0, -114.3),
    )
    values = measurement_values(rolled)
    # A rigid scene roll near the +/-90 edge puts the shoulder line at ~+85
    # and the hip line at ~-85 degrees. The true relative imbalance is ~10
    # degrees; raw subtraction would report a phantom ~170-degree deviation.
    assert abs(values["shoulder_asymmetry_deg"]) <= 15.0, values
    assert abs(values["trunk_lean_deg"]) <= 15.0, values
    print("test_relative_axis_difference_wraps_near_vertical_edges OK")


def test_relaxed_window_anchors_at_logical_transition_end() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index * 0.3, anchor_values(0.0))
    accumulator.begin_transition(5.0)
    # Sparse frame spacing observes the first relaxed-eligible frame 2.5 s
    # after the transition opened; the relaxed window must still be anchored
    # at the logical transition end (t=6.0), not at the observing frame.
    assert accumulator.stage_at(7.5) == RELAXED
    assert math.isclose(accumulator.relaxed_elapsed(7.5), 1.5)
    assert accumulator.relaxed_target_reached(11.0) is True
    print("test_relaxed_window_anchors_at_logical_transition_end OK")


if __name__ == "__main__":
    test_statistics_sem_mdc_cv()
    test_two_anchor_segmentation_and_noise_floor()
    test_similar_stable_anchors_form_a_valid_normal_range()
    test_identical_stable_anchors_form_a_valid_normal_range()
    test_invalid_sample_resets_only_current_stage()
    test_low_quality_abstention_preserves_valid_samples()
    test_environment_only_values_do_not_count_as_posture_samples()
    test_zero_person_dropout_abstains_but_multiple_people_contaminate()
    test_low_hip_visibility_does_not_reject_upper_body_evidence()
    test_lateral_features_are_invariant_to_rigid_frame_roll()
    test_low_face_quality_preserves_independent_pose_evidence()
    test_feature_quality_uses_only_scored_landmarks()
    test_low_ear_quality_removes_raw_and_normalized_ear_evidence()
    test_stage_sample_shortage_fails()
    test_no_common_posture_feature_is_the_only_profile_level_failure()
    test_watch_threshold_must_precede_alert_threshold()
    test_explicit_phase_timing_and_bounded_extension()
    test_mdc_normalization_and_group_deduplication()
    test_reported_bad_posture_scenarios_are_actionable()
    test_range_deviation_is_bidirectional_and_uses_personal_anchor_span()
    test_legacy_anchor_separation_policy_is_ignored()
    test_single_feature_excursion_is_discounted_for_group_scoring()
    test_extreme_lone_forward_channel_is_explicit_evidence()
    test_shared_head_shoulder_ratios_are_one_evidence_channel()
    test_shared_shoulder_scale_drift_abstains_from_ratio_scoring()
    test_uniform_distance_scale_change_remains_measurable()
    test_raw_support_uses_measured_repeatability_not_percent_floor()
    test_minor_shared_scale_drift_does_not_force_abstention()
    test_independent_posture_evidence_bypasses_shared_scale_abstention()
    test_shared_scale_drift_requires_raw_support_only_at_watch_level()
    test_runtime_noise_band_uses_single_observation_repeatability()
    test_marginal_anchor_range_is_valid_and_noise_bounded()
    test_near_identical_smoothed_anchors_form_a_narrow_range()
    test_narrow_anchor_span_does_not_amplify_runtime_jitter()
    test_exposure_uses_timestamps_pauses_and_decays()
    test_long_observation_gap_does_not_backfill_exposure()
    test_watch_only_deviation_does_not_preload_exposure()
    test_sustained_watch_deviation_accumulates_slower_exposure()
    test_exposure_hysteresis()
    test_low_track_activity_add_on_is_bounded_and_resets_when_ineligible()
    test_pronounced_lone_trunk_lean_is_lateral_evidence()
    test_shared_projected_axis_does_not_corroborate_itself()
    test_projected_axes_separate_head_tilt_from_trunk_translation()
    test_relative_axis_difference_wraps_near_vertical_edges()
    test_relaxed_window_anchors_at_logical_transition_end()
    print("ALL TESTS PASSED")
