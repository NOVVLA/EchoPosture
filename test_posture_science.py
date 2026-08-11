"""Deterministic tests for two-anchor posture and exposure logic."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from posture_science import (
    CalibrationAccumulator,
    CalibrationPlan,
    ExposureAccumulator,
    FeatureStatistics,
    PosturePolicy,
    normalized_feature_deviation,
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
    for index in range(5):
        accumulator.add(2.1 + index * 0.3, anchor_values(1.0))
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
    for index in range(5):
        accumulator.add(2.1 + index * 0.2, anchor_values(1.0))
    profile = accumulator.finalize()
    assert profile.stage_counts["preferred"] == 5
    assert "preferred:single_person" in profile.reset_reasons
    print("test_invalid_sample_resets_only_current_stage OK")


def test_stage_sample_shortage_fails() -> None:
    accumulator = CalibrationAccumulator(CalibrationPlan(min_samples_per_stage=5))
    for index in range(5):
        accumulator.add(index * 0.2, anchor_values(0.0))
    for index in range(4):
        accumulator.add(2.1 + index * 0.2, anchor_values(1.0))
    try:
        accumulator.finalize()
    except ValueError as exc:
        assert "relaxed_samples" in str(exc)
    else:
        raise AssertionError("short relaxed stage must fail calibration")
    print("test_stage_sample_shortage_fails OK")


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
    test_stage_sample_shortage_fails()
    test_mdc_normalization_and_group_deduplication()
    test_exposure_uses_timestamps_pauses_and_decays()
    test_exposure_hysteresis()
    print("ALL TESTS PASSED")
