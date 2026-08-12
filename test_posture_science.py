"""Deterministic tests for two-anchor posture and exposure logic."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from types import SimpleNamespace

from posture_science import (
    CalibrationAccumulator,
    CalibrationPlan,
    ExposureAccumulator,
    FeatureStatistics,
    PosturePolicy,
    RELAXED,
    TRANSITION,
    aggregate_sample_quality,
    calibration_measurement_values,
    calibration_rejection_reason,
    normalized_feature_deviation,
    runtime_noise_floor,
    score_posture_deviation,
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
    assert profile.disabled_features["ear_shoulder_ratio"] == (
        "anchor_separation_not_above_mdc"
    )
    assert 0.0 < profile.calibration_quality <= 1.0
    print("test_two_anchor_segmentation_and_noise_floor OK")


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
    assert CalibrationPlan().min_pose_quality == 0.50
    values = calibration_measurement_values(sample)
    assert "face_shoulder_ratio" in values
    assert "shoulder_asymmetry_deg" in values
    assert "ear_shoulder_ratio" in values
    assert "torso_shoulder_ratio" not in values
    assert "trunk_lean_deg" not in values
    print("test_low_hip_visibility_does_not_reject_upper_body_evidence OK")


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
    assert math.isclose(at_relaxed.deviation, 1.0)

    score = score_posture_deviation(anchor_values(1.0), profile)
    assert math.isclose(score.forward_deviation, 1.0)
    assert math.isclose(score.lateral_deviation, 1.0)
    assert math.isclose(score.deviation, 1.0)
    assert score.deviation <= max(score.forward_deviation, score.lateral_deviation) + 0.10
    print("test_mdc_normalization_and_group_deduplication OK")


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
    assert near_preferred.runtime_noise >= 1.96 * preferred.std
    assert math.isclose(
        near_preferred.runtime_noise,
        runtime_noise_floor(preferred, relaxed),
    )
    print("test_runtime_noise_band_uses_single_observation_repeatability OK")


def test_marginal_anchor_signal_is_disabled_by_runtime_noise() -> None:
    plan = CalibrationPlan(min_samples_per_stage=5)
    accumulator = CalibrationAccumulator(plan)
    preferred_values = [0.98, 0.99, 1.00, 1.01, 1.02]
    relaxed_values = [1.01, 1.02, 1.03, 1.04, 1.05]
    for index, value in enumerate(preferred_values):
        accumulator.add(index, {"face_shoulder_ratio": value})
    accumulator.begin_transition(5.0)
    for index, value in enumerate(relaxed_values):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": value})

    try:
        accumulator.finalize()
    except ValueError as exc:
        assert str(exc) == "no_feature_separates_above_mdc"
        stats = FeatureStatistics.from_values(preferred_values)
        assert 0.03 > stats.mdc
        assert 0.03 <= 1.96 * stats.std
    else:
        raise AssertionError("marginal single-observation signal must be disabled")
    print("test_marginal_anchor_signal_is_disabled_by_runtime_noise OK")


def test_near_identical_smoothed_anchors_do_not_create_false_signal() -> None:
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

    try:
        accumulator.finalize()
    except ValueError as exc:
        assert str(exc) == "no_feature_separates_above_mdc"
    else:
        raise AssertionError("near-identical smoothed anchors must not create posture signal")
    print("test_near_identical_smoothed_anchors_do_not_create_false_signal OK")


def test_narrow_credible_anchor_span_is_disabled() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index, {"face_shoulder_ratio": 0.300})
    accumulator.begin_transition(5.0)
    for index in range(5):
        accumulator.add(6.0 + index, {"face_shoulder_ratio": 0.320})

    try:
        accumulator.finalize()
    except ValueError as exc:
        assert str(exc) == "no_feature_separates_above_mdc"
    else:
        raise AssertionError("a 0.005 credible span must not amplify runtime jitter")
    print("test_narrow_credible_anchor_span_is_disabled OK")


def test_exposure_uses_timestamps_pauses_and_decays() -> None:
    policy = PosturePolicy(recovery_half_life_seconds=10.0)
    exposure = ExposureAccumulator(policy)
    start = datetime(2026, 1, 1, 12, 0, 0)

    exposure.update(start, 1.0)
    snapshot = exposure.update(start + timedelta(seconds=12), 1.0)
    assert math.isclose(snapshot.exposure_seconds, 12.0)
    assert snapshot.alert_active

    paused = exposure.pause(start + timedelta(seconds=112))
    assert math.isclose(paused.exposure_seconds, 12.0)
    assert paused.paused

    recovered = exposure.update(start + timedelta(seconds=122), 0.0)
    assert math.isclose(recovered.exposure_seconds, 6.0, rel_tol=1e-6)
    assert not recovered.watch_active
    assert not recovered.alert_active
    print("test_exposure_uses_timestamps_pauses_and_decays OK")


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


if __name__ == "__main__":
    test_statistics_sem_mdc_cv()
    test_two_anchor_segmentation_and_noise_floor()
    test_invalid_sample_resets_only_current_stage()
    test_low_quality_abstention_preserves_valid_samples()
    test_zero_person_dropout_abstains_but_multiple_people_contaminate()
    test_low_hip_visibility_does_not_reject_upper_body_evidence()
    test_feature_quality_uses_only_scored_landmarks()
    test_stage_sample_shortage_fails()
    test_explicit_phase_timing_and_bounded_extension()
    test_mdc_normalization_and_group_deduplication()
    test_runtime_noise_band_uses_single_observation_repeatability()
    test_marginal_anchor_signal_is_disabled_by_runtime_noise()
    test_near_identical_smoothed_anchors_do_not_create_false_signal()
    test_narrow_credible_anchor_span_is_disabled()
    test_exposure_uses_timestamps_pauses_and_decays()
    test_watch_only_deviation_does_not_preload_exposure()
    test_exposure_hysteresis()
    print("ALL TESTS PASSED")
