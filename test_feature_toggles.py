"""
HighPrecisionPostureAnalyzer 功能开关测试（无 GUI、无摄像头）。

运行方式：runtime\\python311\\python.exe test_feature_toggles.py
验证控制台三节椎骨（PRECISION / PRESENCE / IDENTITY）对应的后端开关：
- 默认全开，行为与历史版本一致；
- 关闭后对应决策分支真正停用；
- 重新打开后行为恢复。
"""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional

from vision_test import HighPrecisionPostureAnalyzer, VisionSample
from posture_science import (
    CalibrationAccumulator,
    CalibrationPlan,
    measurement_values,
    runtime_movement_margin,
)
from vision_backend import PostureFeatureExtractor, observation_from_sample
from vision_tracking import TargetManager

T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_sample(
    ts: datetime,
    ipd: Optional[float] = 60.0,
    shoulder: float = 4.0,
    width: float = 220.0,
    trunk: float = 2.0,
    face: bool = True,
    pose: bool = True,
    face_count: Optional[int] = None,
    torso: float = 180.0,
) -> VisionSample:
    return VisionSample(
        timestamp=ts,
        interpupillary_px=ipd if face else None,
        shoulder_diff_px=abs(shoulder) if pose else None,
        signed_shoulder_diff_px=shoulder if pose else None,
        shoulder_width_px=width if pose else None,
        trunk_lean_deg=trunk if pose else None,
        face_detected=face,
        pose_detected=pose,
        face_count=(face_count if face_count is not None else (1 if face else 0)),
        head_turn_ratio=0.02 if face else None,
        torso_height_px=torso if pose else None,
    )


def calibrated_analyzer() -> HighPrecisionPostureAnalyzer:
    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False, calibrated_distance_cm=60.0
    )
    assert analyzer.set_baseline_from_sample(make_sample(T0), 60.0)
    return analyzer


def scientific_sample(ts: datetime, relaxed: float = 0.0, quality: float = 1.0) -> VisionSample:
    width = 200.0
    shoulder_deg = 1.0 + relaxed * 6.0
    return VisionSample(
        timestamp=ts,
        interpupillary_px=60.0 + relaxed * 20.0,
        shoulder_diff_px=abs(width * math.tan(math.radians(shoulder_deg))),
        signed_shoulder_diff_px=width * math.tan(math.radians(shoulder_deg)),
        shoulder_width_px=width,
        trunk_lean_deg=1.0 + relaxed * 10.0,
        face_detected=True,
        pose_detected=True,
        face_count=1,
        head_turn_ratio=0.01,
        torso_height_px=180.0 - relaxed * 40.0,
        face_quality=quality,
        pose_quality=quality,
        target_motion=0.0,
        activity_state="STATIC",
        left_eye_center=(290.0, 150.0),
        right_eye_center=(350.0, 150.0),
        face_nose_point=(320.0, 170.0),
        nose_point=(320.0, 170.0),
        left_ear_point=(278.0, 168.0),
        right_ear_point=(362.0, 168.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 244.0),
        left_hip_point=(260.0, 390.0),
        right_hip_point=(380.0, 390.0),
        shoulder_center=(320.0, 242.0),
        hip_center=(320.0, 390.0),
    )


def scientific_analyzer() -> HighPrecisionPostureAnalyzer:
    accumulator = CalibrationAccumulator(CalibrationPlan())
    for index in range(5):
        sample = scientific_sample(T0 + timedelta(seconds=index * 0.2), 0.0)
        accumulator.add(index * 0.2, measurement_values(sample))
    accumulator.begin_transition(5.0)
    for index in range(5):
        sample = scientific_sample(T0 + timedelta(seconds=6.0 + index), 1.0)
        accumulator.add(6.0 + index, measurement_values(sample))
    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False,
        calibrated_distance_cm=60.0,
        require_dual_anchor=True,
    )
    assert not analyzer.set_baseline_from_sample(scientific_sample(T0), 60.0)
    assert analyzer.set_baseline_from_sample(
        scientific_sample(T0), 60.0, legacy_debug=True
    )
    analyzer.reset_baseline()
    assert analyzer.set_calibration_profile(accumulator.finalize(), 60.0)
    return analyzer


def validate_scientific_profile(
    analyzer: HighPrecisionPostureAnalyzer,
    start: datetime = T0,
) -> None:
    """Complete the production post-calibration normal-range validation."""

    first = analyzer.evaluate(scientific_sample(start, 1.0))
    assert first.status == "OBSERVING", first
    assert first.reason == "post_calibration_normal_range_validation", first
    validated = analyzer.evaluate(scientific_sample(start + timedelta(seconds=2.1), 1.0))
    assert validated.status == "GOOD", validated
    assert validated.reason == "post_calibration_normal_range_validated", validated
    assert validated.exposure_seconds == 0.0


def test_defaults_all_enabled():
    analyzer = HighPrecisionPostureAnalyzer()
    assert analyzer.precision_enabled
    assert analyzer.presence_check_enabled
    assert analyzer.identity_check_enabled
    print("test_defaults_all_enabled OK")


def test_auto_calibration_requires_complete_single_person_sample():
    analyzer = HighPrecisionPostureAnalyzer(calibration_samples=1)

    multi = make_sample(T0, face_count=2)
    analyzer.evaluate(multi)
    assert analyzer.baseline is None

    partial = make_sample(T0 + timedelta(seconds=1), pose=False)
    analyzer.evaluate(partial)
    assert analyzer.baseline is None

    complete = make_sample(T0 + timedelta(seconds=2))
    analyzer.evaluate(complete)
    assert analyzer.baseline is not None
    print("test_auto_calibration_requires_complete_single_person_sample OK")


def test_precision_toggle():
    analyzer = calibrated_analyzer()

    # 开：走高精度科学评分
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=1)))
    assert decision.status == "GOOD", decision
    assert decision.reason == "within_scientific_limits", decision

    # 关：回退到基础阈值判定
    analyzer.precision_enabled = False
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=2)))
    assert decision.status == "GOOD", decision
    assert decision.reason == "within_baseline", decision

    # 关：靠太近触发基础 BAD，且折算 risk_score 供干预链路使用
    too_close = make_sample(T0 + timedelta(seconds=3), ipd=100.0)
    decision = analyzer.evaluate(too_close)
    assert decision.status == "BAD" and "too_close" in decision.reason, decision
    assert decision.risk_score >= 45.0, decision

    # 关：BAD 持续 12s 以上时 sustained_seconds 随之累积（干预门槛）
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=16), ipd=100.0))
    assert decision.sustained_seconds >= 12.0, decision

    # 重新打开：恢复科学评分输出
    analyzer.precision_enabled = True
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=25)))
    assert decision.status == "GOOD", decision
    assert decision.reason == "within_scientific_limits", decision
    print("test_precision_toggle OK")


def test_presence_toggle():
    analyzer = calibrated_analyzer()

    # 单帧多人不应立即切换状态；持续超过确认窗口后才进入 MULTI_USER。
    multi = make_sample(T0 + timedelta(seconds=1), face_count=2)
    decision = analyzer.evaluate(multi)
    assert decision.status == "UNKNOWN", decision
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=1.4), face_count=2))
    assert decision.status == "MULTI_USER", decision

    # 关：同样的多人画面不再抑制，正常评分
    analyzer.presence_check_enabled = False
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=2), face_count=2))
    assert decision.status not in {"MULTI_USER", "AWAY"}, decision

    # 开：离开超过宽限期 → AWAY
    analyzer.presence_check_enabled = True
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=3), face=False, pose=False))
    decision = analyzer.evaluate(
        make_sample(T0 + timedelta(seconds=6), face=False, pose=False)
    )
    assert decision.status == "AWAY", decision

    # 回到座位，清掉换人复查，再测试关闭状态下的离开
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=7)))

    # 关：离开只会因指标缺失得到 UNKNOWN，不产出 AWAY
    analyzer.presence_check_enabled = False
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=8), face=False, pose=False))
    decision = analyzer.evaluate(
        make_sample(T0 + timedelta(seconds=12), face=False, pose=False)
    )
    assert decision.status == "UNKNOWN", decision
    print("test_presence_toggle OK")


def test_presence_toggle_resets_multi_debounce_anchor():
    analyzer = calibrated_analyzer()

    first_multi = make_sample(T0 + timedelta(seconds=1), face_count=2)
    assert analyzer.evaluate(first_multi).status == "UNKNOWN"

    analyzer.presence_check_enabled = False
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=2), face_count=2))

    analyzer.presence_check_enabled = True
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=2.1), face_count=2))
    assert decision.status == "UNKNOWN", decision
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=2.5), face_count=2))
    assert decision.status == "MULTI_USER", decision
    print("test_presence_toggle_resets_multi_debounce_anchor OK")


def test_identity_toggle():
    analyzer = calibrated_analyzer()

    # 先触发一次“需要复查体型”的事件（短暂离开）
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=1), face=False, pose=False))

    # 开：回座后瞳距/肩宽比大幅偏离基线 → PROFILE_MISMATCH
    stranger = make_sample(T0 + timedelta(seconds=2), ipd=30.0)
    decision = analyzer.evaluate(stranger)
    assert decision.status == "PROFILE_MISMATCH", decision

    # 关：同样的画面不再拦截，交给正常评分
    analyzer.identity_check_enabled = False
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=3), ipd=30.0))
    assert decision.status != "PROFILE_MISMATCH", decision

    # 关闭在场检测时，多人/离开事件仍会为换人保护记录复查标记
    analyzer.identity_check_enabled = True
    analyzer.presence_check_enabled = False
    analyzer.evaluate(make_sample(T0 + timedelta(seconds=4), face_count=2))
    decision = analyzer.evaluate(make_sample(T0 + timedelta(seconds=5), ipd=30.0))
    assert decision.status == "PROFILE_MISMATCH", decision
    print("test_identity_toggle OK")


def test_scientific_continuous_scoring_exposure_and_abstention():
    analyzer = scientific_analyzer()

    # Both anchors are user-accepted posture. The relaxed anchor and every
    # posture between the anchors must remain inside the personal normal band.
    ending_posture = analyzer.evaluate(scientific_sample(T0, 1.0))
    assert ending_posture.status == "OBSERVING", ending_posture
    assert ending_posture.reason == "post_calibration_normal_range_validation"
    assert ending_posture.posture_deviation == 0.0
    assert ending_posture.exposure_seconds == 0.0
    still_relaxed = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=2.1), 1.0))
    assert still_relaxed.status == "GOOD", still_relaxed
    assert still_relaxed.reason == "post_calibration_normal_range_validated"
    assert still_relaxed.posture_deviation == 0.0
    assert still_relaxed.exposure_seconds == 0.0

    preferred = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=61), 0.0))
    assert preferred.status == "GOOD", preferred
    assert preferred.exposure_seconds == 0.0

    midpoint = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=62), 0.5))
    assert midpoint.status == "GOOD", midpoint
    assert midpoint.posture_deviation == 0.0, midpoint
    assert midpoint.exposure_seconds == 0.0

    # Remaining in the chosen preferred posture must stay safe over the same
    # multi-minute horizon reported in the field. Ordinary sub-noise jitter
    # cannot open WATCH or integrate exposure after activation.
    for seconds, jitter in ((120, 0.02), (180, 0.0), (240, 0.03), (300, 0.01)):
        stable = analyzer.evaluate(
            scientific_sample(T0 + timedelta(seconds=seconds), jitter)
        )
        assert stable.status == "GOOD", stable
        assert stable.exposure_seconds == 0.0, stable

    beyond_relaxed = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=301), 2.2))
    assert beyond_relaxed.posture_deviation == 0.0, beyond_relaxed
    assert beyond_relaxed.status == "ADJUSTING", beyond_relaxed

    alert = beyond_relaxed
    for seconds in range(302, 317):
        alert = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=seconds), 2.2))
    assert alert.status == "BAD", alert
    assert alert.exposure_seconds >= 12.0
    assert alert.risk_score == alert.posture_deviation * 100.0
    assert alert.sustained_seconds == alert.exposure_seconds

    before = alert.exposure_seconds
    low_quality = analyzer.evaluate(
        scientific_sample(T0 + timedelta(seconds=320), 2.0, quality=0.40)
    )
    assert low_quality.status == "OBSERVING", low_quality
    assert low_quality.exposure_seconds == before

    moving = replace(
        scientific_sample(T0 + timedelta(seconds=325), 2.0),
        target_motion=0.5,
        activity_state="MOVING",
    )
    moving_decision = analyzer.evaluate(moving)
    assert moving_decision.status == "MOVING", moving_decision
    assert moving_decision.activity_state == "MOVING"
    assert moving_decision.exposure_seconds == before
    print("test_scientific_continuous_scoring_exposure_and_abstention OK")


def test_post_calibration_validation_requires_the_actual_normal_band():
    """A sub-WATCH deviation cannot unlock exposure after calibration."""

    analyzer = scientific_analyzer()
    near_band = analyzer.evaluate(scientific_sample(T0, 1.2))
    assert near_band.status == "OBSERVING", near_band
    assert near_band.reason == "post_calibration_normal_range_validation"
    assert 0.0 <= near_band.risk_score < analyzer.posture_policy.watch_exit * 100.0
    assert near_band.posture_deviation == 0.0
    assert near_band.exposure_seconds == 0.0

    first_in_band = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=1.0), 1.0))
    assert first_in_band.reason == "post_calibration_normal_range_validation"
    validated = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=2.1), 1.0))
    assert validated.status == "GOOD", validated
    assert validated.reason == "post_calibration_normal_range_validated"
    assert validated.exposure_seconds == 0.0
    print("test_post_calibration_validation_requires_the_actual_normal_band OK")


def test_brief_posture_excursion_is_adjustment_not_watch() -> None:
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)

    reach = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=10.0), 2.2))
    assert reach.status == "ADJUSTING", reach
    assert reach.reason == "posture_adjustment_exposure_paused"
    assert reach.posture_deviation == 0.0
    assert reach.exposure_seconds == 0.0

    recovered = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=10.8), 0.5))
    assert recovered.status == "GOOD", recovered
    assert recovered.exposure_seconds == 0.0

    second_reach = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=12.0), 2.2))
    assert second_reach.status == "ADJUSTING", second_reach
    assert second_reach.exposure_seconds == 0.0
    print("test_brief_posture_excursion_is_adjustment_not_watch OK")


def test_natural_midrange_lean_stays_good_without_observation() -> None:
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)

    # A moderate, single-frame lean/reach is within the explicit product
    # deadband. It must not flash WATCH/ADJUSTING merely because it crosses
    # the narrow calibrated anchor interval.
    decision = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=10.0), 1.5))
    assert decision.status == "GOOD", decision
    assert decision.reason == "minor_posture_variation", decision
    assert decision.exposure_seconds == 0.0
    print("test_natural_midrange_lean_stays_good_without_observation OK")


def test_sustained_posture_excursion_enters_watch_after_confirmation() -> None:
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)

    first = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=10.0), 2.2))
    still_adjusting = analyzer.evaluate(
        scientific_sample(T0 + timedelta(seconds=11.9), 2.2)
    )
    confirmed = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=12.1), 2.2))
    assert first.status == "ADJUSTING", first
    assert still_adjusting.status == "ADJUSTING", still_adjusting
    assert confirmed.status == "WATCH", confirmed
    assert confirmed.posture_deviation >= analyzer.posture_policy.watch_enter
    assert confirmed.exposure_seconds == 0.0
    print("test_sustained_posture_excursion_enters_watch_after_confirmation OK")


def test_production_target_chain_ignores_high_fps_landmark_jitter():
    """Unchanged posture must stay GOOD after target-sample replacement."""
    analyzer = scientific_analyzer()
    manager = TargetManager()
    base = scientific_sample(T0)
    first_observation = observation_from_sample(base)
    assert first_observation
    manager.update(first_observation, timestamp=T0)
    assert manager.lock_calibration_target()

    validate_scientific_profile(analyzer, T0)

    jitters = (0.8, -0.7, 1.1, -0.9, 0.4, -1.0, 0.6, -0.5)
    frame_dt = timedelta(seconds=1.0 / 72.0)
    decisions = []
    for index in range(1, 2001):
        jitter = jitters[index % len(jitters)]
        shifted = replace(
            base,
            timestamp=T0 + frame_dt * index,
            left_eye_center=(290.0 + jitter, 150.0 + jitter),
            right_eye_center=(350.0 + jitter, 150.0 + jitter),
            face_nose_point=(320.0 + jitter, 170.0 + jitter),
            nose_point=(320.0 + jitter, 170.0 + jitter),
            left_ear_point=(278.0 + jitter, 168.0 + jitter),
            right_ear_point=(362.0 + jitter, 168.0 + jitter),
            left_shoulder_point=(220.0 + jitter, 240.0 + jitter),
            right_shoulder_point=(420.0 + jitter, 244.0 + jitter),
            left_hip_point=(260.0 + jitter, 390.0 + jitter),
            right_hip_point=(380.0 + jitter, 390.0 + jitter),
            shoulder_center=(320.0 + jitter, 242.0 + jitter),
            hip_center=(320.0 + jitter, 390.0 + jitter),
        )
        update = manager.update(
            observation_from_sample(shifted),
            timestamp=shifted.timestamp,
        )
        assert update.target_observation is not None
        target_sample = PostureFeatureExtractor.to_sample(update.target_observation)
        target_sample = replace(
            target_sample,
            target_track_id=update.target_track_id,
            target_state=update.state,
            target_observed=True,
            person_count=update.person_count,
            target_motion=update.target_motion,
            activity_state=update.activity_state,
            target_reason=update.reason,
        )
        decisions.append(analyzer.evaluate(target_sample))

    assert all(decision.status == "GOOD" for decision in decisions[20:])
    assert all(decision.activity_state == "STATIC" for decision in decisions[20:])
    assert max(decision.posture_deviation for decision in decisions) == 0.0
    assert max(decision.exposure_seconds for decision in decisions) == 0.0
    print("test_production_target_chain_ignores_high_fps_landmark_jitter OK")


def test_runtime_local_hip_quality_abstains_torso_features():
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)

    low_hip = replace(
        scientific_sample(T0 + timedelta(seconds=3.0), 0.0),
        torso_height_px=140.0,
        left_hip_confidence=0.20,
        right_hip_confidence=0.20,
        pose_quality=0.95,
    )
    decision = analyzer.evaluate(low_hip)
    assert decision.status == "OBSERVING", decision
    assert decision.posture_deviation == 0.0, decision
    assert decision.exposure_seconds == 0.0, decision
    assert decision.confidence < analyzer.posture_policy.quality_floor, decision
    print("test_runtime_local_hip_quality_abstains_torso_features OK")


def test_single_feature_runtime_drift_does_not_open_watch_or_exposure():
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)
    sample = scientific_sample(T0)
    values = measurement_values(sample)
    feature = "face_shoulder_ratio"
    preferred = analyzer.calibration_profile.preferred[feature]
    relaxed = analyzer.calibration_profile.relaxed[feature]
    noise = analyzer.calibration_profile.runtime_noise_floors[feature]
    direction = 1.0 if relaxed.mean >= preferred.mean else -1.0
    drifted = replace(
        sample,
        interpupillary_px=(
        preferred.mean
        + direction
        * (
            abs(relaxed.mean - preferred.mean)
            + noise
            + runtime_movement_margin(feature)
            + 0.02
        )
        ) * sample.shoulder_width_px,
    )
    first = analyzer.evaluate(drifted)
    assert first.status == "GOOD", first
    assert first.reason == "minor_posture_variation", first
    assert first.exposure_seconds == 0.0
    later = analyzer.evaluate(replace(drifted, timestamp=T0 + timedelta(seconds=300)))
    assert later.status == "GOOD", later
    assert later.exposure_seconds == 0.0
    print("test_single_feature_runtime_drift_does_not_open_watch_or_exposure OK")


def test_head_turn_abstains_without_static_exposure():
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)
    upright = scientific_sample(T0, 0.0)
    assert analyzer.evaluate(upright).status == "GOOD"
    turned = replace(
        scientific_sample(T0 + timedelta(seconds=10), 0.0),
        head_turn_ratio=0.50,
    )
    decision = analyzer.evaluate(turned)
    assert decision.status == "OBSERVING", decision
    assert decision.reason == "head_turn_measurement_abstained"
    assert decision.posture_deviation == 0.0
    assert decision.exposure_seconds == 0.0
    recovered = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=11), 0.0))
    assert recovered.status == "GOOD", recovered
    assert recovered.exposure_seconds == 0.0
    print("test_head_turn_abstains_without_static_exposure OK")


def test_fixed_posture_distance_scale_does_not_become_head_turn_watch():
    """Distance/face scale changes are environment noise, not posture state."""
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)
    baseline = scientific_sample(T0, 0.0)
    for index, scale in enumerate((0.50, 0.60, 0.70, 0.74, 0.80, 1.20, 1.35)):
        sample = replace(
            baseline,
            timestamp=T0 + timedelta(seconds=index + 1),
            interpupillary_px=baseline.interpupillary_px * scale,
        )
        decision = analyzer.evaluate(sample)
        assert decision.status in {"GOOD", "ADJUSTING"}, decision
        assert decision.status not in {"WATCH", "BAD", "CRITICAL"}, decision
        if decision.status == "ADJUSTING":
            assert decision.reason == "posture_evidence_inconclusive", decision
        assert decision.posture_deviation == 0.0, decision
        assert decision.exposure_seconds == 0.0, decision
    def scale_point(point, factor: float):
        return None if point is None else (point[0] * factor, point[1] * factor)

    # A geometrically uniform distance change preserves every normalized
    # posture feature. It remains GOOD at the new distance rather than forcing
    # the user back to the calibration position.
    for index, scale in enumerate((0.65, 0.80, 1.20, 1.35), start=20):
        scaled = replace(
            baseline,
            timestamp=T0 + timedelta(seconds=index),
            interpupillary_px=baseline.interpupillary_px * scale,
            shoulder_diff_px=baseline.shoulder_diff_px * scale,
            signed_shoulder_diff_px=baseline.signed_shoulder_diff_px * scale,
            shoulder_width_px=baseline.shoulder_width_px * scale,
            torso_height_px=baseline.torso_height_px * scale,
            left_eye_center=scale_point(baseline.left_eye_center, scale),
            right_eye_center=scale_point(baseline.right_eye_center, scale),
            face_nose_point=scale_point(baseline.face_nose_point, scale),
            nose_point=scale_point(baseline.nose_point, scale),
            left_ear_point=scale_point(baseline.left_ear_point, scale),
            right_ear_point=scale_point(baseline.right_ear_point, scale),
            left_shoulder_point=scale_point(baseline.left_shoulder_point, scale),
            right_shoulder_point=scale_point(baseline.right_shoulder_point, scale),
            left_hip_point=scale_point(baseline.left_hip_point, scale),
            right_hip_point=scale_point(baseline.right_hip_point, scale),
            shoulder_center=scale_point(baseline.shoulder_center, scale),
            hip_center=scale_point(baseline.hip_center, scale),
        )
        decision = analyzer.evaluate(scaled)
        assert decision.status == "GOOD", decision
        assert decision.posture_deviation == 0.0
        assert decision.exposure_seconds == 0.0
    print("test_fixed_posture_distance_scale_does_not_become_head_turn_watch OK")


def test_unchanged_posture_shared_shoulder_width_drift_never_accumulates_exposure():
    """One drifting ratio denominator must not become several posture votes."""

    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)
    baseline = scientific_sample(T0, 0.0)
    decisions = []
    for index in range(1, 1801):
        # Face size, torso height, ear height, shoulder slope, and trunk lean
        # remain unchanged. Only the pose detector's shoulder span drifts from
        # 200 px to 160 px, reproducing the shared-denominator false alarm.
        fraction = min(1.0, index / 180.0)
        sample = replace(
            baseline,
            timestamp=T0 + timedelta(seconds=3.0 + index / 6.0),
            shoulder_width_px=200.0 - 40.0 * fraction,
            left_shoulder_point=(220.0 + 20.0 * fraction, 240.0),
            right_shoulder_point=(420.0 - 20.0 * fraction, 244.0),
        )
        decisions.append(analyzer.evaluate(sample))

    assert all(decision.status not in {"WATCH", "BAD", "CRITICAL"} for decision in decisions)
    assert all(
        decision.reason
        in {
            "within_personal_posture_range",
            "minor_posture_variation",
            "posture_evidence_inconclusive",
            "shared_shoulder_scale_measurement_abstained",
        }
        for decision in decisions
    )
    assert max(decision.posture_deviation for decision in decisions) == 0.0
    assert max(decision.exposure_seconds for decision in decisions) == 0.0
    print(
        "test_unchanged_posture_shared_shoulder_width_drift_never_accumulates_exposure OK"
    )


def test_gradual_shared_scale_drift_does_not_intervene_before_guard():
    """Slow denominator drift must not open intervention before the guard."""

    def sample(
        timestamp: datetime,
        width: float,
        *,
        interpupillary: float = 60.0,
        torso_height: float = 180.0,
        ear_y: float = 142.0,
    ) -> VisionSample:
        half_width = width / 2.0
        return replace(
            scientific_sample(timestamp, 0.0),
            interpupillary_px=interpupillary,
            shoulder_width_px=width,
            torso_height_px=torso_height,
            left_ear_point=(278.0, ear_y),
            right_ear_point=(362.0, ear_y),
            left_shoulder_point=(320.0 - half_width, 240.0),
            right_shoulder_point=(320.0 + half_width, 244.0),
        )

    accumulator = CalibrationAccumulator(CalibrationPlan())
    for index in range(5):
        calibration_sample = sample(T0 + timedelta(seconds=index), 200.0)
        accumulator.add(index, measurement_values(calibration_sample))
    accumulator.begin_transition(5.0)
    for index in range(5):
        calibration_sample = sample(T0 + timedelta(seconds=6 + index), 185.0)
        accumulator.add(6.0 + index, measurement_values(calibration_sample))

    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False,
        calibrated_distance_cm=60.0,
        require_dual_anchor=True,
    )
    assert analyzer.set_calibration_profile(accumulator.finalize(), 60.0)
    first = analyzer.evaluate(sample(T0, 185.0))
    assert first.reason == "post_calibration_normal_range_validation", first
    validated = analyzer.evaluate(sample(T0 + timedelta(seconds=2.1), 185.0))
    assert validated.reason == "post_calibration_normal_range_validated", validated

    decisions = []
    for index in range(1, 1801):
        fraction = min(1.0, index / 180.0)
        width = 185.0 - 10.0 * fraction
        decisions.append(
            analyzer.evaluate(
                sample(T0 + timedelta(seconds=3.0 + index / 6.0), width)
            )
        )

    assert all(decision.status not in {"WATCH", "BAD", "CRITICAL"} for decision in decisions)
    assert all(
        decision.reason
        in {
            "within_personal_posture_range",
            "minor_posture_variation",
            "posture_evidence_inconclusive",
            "shared_shoulder_scale_measurement_abstained",
        }
        for decision in decisions
    )
    assert max(decision.posture_deviation for decision in decisions) == 0.0
    assert max(decision.exposure_seconds for decision in decisions) == 0.0

    genuine = []
    for seconds in range(304, 321):
        genuine.append(
            analyzer.evaluate(
                sample(
                    T0 + timedelta(seconds=seconds),
                    180.0,
                    interpupillary=75.0,
                    torso_height=210.0,
                    ear_y=115.0,
                )
            )
        )
    assert genuine[0].status == "ADJUSTING", genuine[0]
    assert genuine[0].reason != "shared_shoulder_scale_measurement_abstained"
    assert genuine[-1].status == "BAD", genuine[-1]
    assert genuine[-1].exposure_seconds >= analyzer.posture_policy.alert_exposure_seconds
    print("test_gradual_shared_scale_drift_does_not_intervene_before_guard OK")


def test_real_forward_change_with_stable_shoulder_scale_still_alerts():
    """The reliability guard must not suppress corroborated posture change."""

    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)
    decisions = []
    for seconds in range(3, 19):
        # Shoulder width stays at the calibrated 200 px. Independent face and
        # torso geometry move beyond the relaxed anchor together, representing
        # a measurable forward-posture change rather than denominator drift.
        sample = replace(
            scientific_sample(T0 + timedelta(seconds=seconds), 1.0),
            interpupillary_px=105.0,
            torso_height_px=95.0,
        )
        decisions.append(analyzer.evaluate(sample))

    assert decisions[0].reason != "shared_shoulder_scale_measurement_abstained"
    assert decisions[0].status == "ADJUSTING", decisions[0]
    assert decisions[2].status == "WATCH", decisions[2]
    assert decisions[2].posture_deviation >= analyzer.posture_policy.alert_enter
    assert decisions[-1].status == "BAD", decisions[-1]
    assert decisions[-1].exposure_seconds >= analyzer.posture_policy.alert_exposure_seconds
    print("test_real_forward_change_with_stable_shoulder_scale_still_alerts OK")


def test_rigid_frame_roll_never_becomes_lateral_exposure():
    """A rolled camera/image frame cannot accuse an unchanged body posture."""

    def rotate(point: tuple[float, float], degrees: float) -> tuple[float, float]:
        center_x, center_y = 320.0, 260.0
        radians = math.radians(degrees)
        x = point[0] - center_x
        y = point[1] - center_y
        return (
            center_x + x * math.cos(radians) - y * math.sin(radians),
            center_y + x * math.sin(radians) + y * math.cos(radians),
        )

    def rolled_sample(timestamp: datetime, degrees: float, relaxed: float) -> VisionSample:
        base = scientific_sample(timestamp, relaxed)
        points = {
            name: rotate(getattr(base, name), degrees)
            for name in (
                "left_eye_center",
                "right_eye_center",
                "face_nose_point",
                "nose_point",
                "left_ear_point",
                "right_ear_point",
                "left_shoulder_point",
                "right_shoulder_point",
                "left_hip_point",
                "right_hip_point",
                "shoulder_center",
                "hip_center",
            )
        }
        signed_shoulder = points["left_shoulder_point"][1] - points["right_shoulder_point"][1]
        shoulder_width = math.dist(points["left_shoulder_point"], points["right_shoulder_point"])
        shoulder_center = points["shoulder_center"]
        hip_center = points["hip_center"]
        trunk_lean = math.degrees(
            math.atan2(
                shoulder_center[0] - hip_center[0],
                max(abs(hip_center[1] - shoulder_center[1]), 1.0),
            )
        )
        return replace(
            base,
            **points,
            shoulder_diff_px=abs(signed_shoulder),
            signed_shoulder_diff_px=signed_shoulder,
            shoulder_width_px=shoulder_width,
            trunk_lean_deg=trunk_lean,
            torso_height_px=math.dist(shoulder_center, hip_center),
        )

    accumulator = CalibrationAccumulator(CalibrationPlan())
    for index in range(5):
        preferred = rolled_sample(T0 + timedelta(seconds=index), 0.0, 0.0)
        accumulator.add(index, measurement_values(preferred))
    accumulator.begin_transition(5.0)
    for index in range(5):
        relaxed = rolled_sample(T0 + timedelta(seconds=6 + index), 0.0, 1.0)
        accumulator.add(6.0 + index, measurement_values(relaxed))

    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False,
        calibrated_distance_cm=60.0,
        require_dual_anchor=True,
    )
    assert analyzer.set_calibration_profile(accumulator.finalize(), 60.0)
    analyzer.evaluate(rolled_sample(T0, 0.0, 1.0))
    validated = analyzer.evaluate(rolled_sample(T0 + timedelta(seconds=2.1), 0.0, 1.0))
    assert validated.reason == "post_calibration_normal_range_validated", validated

    decisions = [
        analyzer.evaluate(
            rolled_sample(T0 + timedelta(seconds=3 + index), 8.0, 1.0)
        )
        for index in range(1, 31)
    ]
    assert all(decision.status not in {"WATCH", "BAD", "CRITICAL"} for decision in decisions)
    assert all(decision.exposure_seconds == 0.0 for decision in decisions)
    assert any(
        decision.reason == "camera_roll_measurement_abstained"
        for decision in decisions
    )

    # A real shoulder-versus-pelvis imbalance changes only the shoulder line;
    # the pelvis and eyes remain stable, so the camera-roll guard must not fire.
    genuine = rolled_sample(T0 + timedelta(seconds=40), 0.0, 1.0)
    moved_right_shoulder = (
        genuine.right_shoulder_point[0],
        genuine.right_shoulder_point[1] + 40.0,
    )
    signed_shoulder = genuine.left_shoulder_point[1] - moved_right_shoulder[1]
    genuine = replace(
        genuine,
        right_shoulder_point=moved_right_shoulder,
        shoulder_width_px=math.dist(genuine.left_shoulder_point, moved_right_shoulder),
        shoulder_diff_px=abs(signed_shoulder),
        signed_shoulder_diff_px=signed_shoulder,
    )
    decision = analyzer.evaluate(genuine)
    assert decision.reason != "camera_roll_measurement_abstained", decision
    print("test_rigid_frame_roll_never_becomes_lateral_exposure OK")


def test_real_pelvis_relative_lateral_change_still_alerts():
    """Rotation invariance must retain a real torso/shoulder imbalance."""

    def lateral_sample(
        timestamp: datetime,
        shoulder_degrees: float,
        torso_degrees: float,
    ) -> VisionSample:
        sample = scientific_sample(timestamp, 1.0)
        hip_center = sample.hip_center
        assert hip_center is not None
        torso_length = math.dist(sample.shoulder_center, hip_center)
        torso_angle = math.radians(torso_degrees)
        shoulder_center = (
            hip_center[0] + torso_length * math.sin(torso_angle),
            hip_center[1] - torso_length * math.cos(torso_angle),
        )
        shoulder_width = 200.0
        shoulder_angle = math.radians(shoulder_degrees)
        half_dx = shoulder_width / 2.0 * math.cos(shoulder_angle)
        half_dy = shoulder_width / 2.0 * math.sin(shoulder_angle)
        left_shoulder = (
            shoulder_center[0] - half_dx,
            shoulder_center[1] - half_dy,
        )
        right_shoulder = (
            shoulder_center[0] + half_dx,
            shoulder_center[1] + half_dy,
        )
        signed_shoulder = left_shoulder[1] - right_shoulder[1]
        return replace(
            sample,
            left_shoulder_point=left_shoulder,
            right_shoulder_point=right_shoulder,
            shoulder_center=shoulder_center,
            shoulder_width_px=math.dist(left_shoulder, right_shoulder),
            shoulder_diff_px=abs(signed_shoulder),
            signed_shoulder_diff_px=signed_shoulder,
            trunk_lean_deg=torso_degrees,
            torso_height_px=torso_length,
        )

    accumulator = CalibrationAccumulator(CalibrationPlan())
    for index in range(5):
        preferred = lateral_sample(T0 + timedelta(seconds=index), 0.0, 0.0)
        accumulator.add(index, measurement_values(preferred))
    accumulator.begin_transition(5.0)
    for index in range(5):
        relaxed = lateral_sample(T0 + timedelta(seconds=6 + index), 5.0, 7.0)
        accumulator.add(6.0 + index, measurement_values(relaxed))
    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False,
        calibrated_distance_cm=60.0,
        require_dual_anchor=True,
    )
    profile = accumulator.finalize()
    assert "shoulder_asymmetry_deg" in profile.enabled_features
    assert "trunk_lean_deg" in profile.enabled_features
    assert analyzer.set_calibration_profile(profile, 60.0)
    analyzer.evaluate(lateral_sample(T0, 5.0, 7.0))
    validated = analyzer.evaluate(
        lateral_sample(T0 + timedelta(seconds=2.1), 5.0, 7.0)
    )
    assert validated.reason == "post_calibration_normal_range_validated", validated

    # A real side-recline may keep both shoulders nearly parallel. The
    # pelvis-relative torso lean must still become lateral evidence on its own.
    decisions = [
        analyzer.evaluate(
            lateral_sample(T0 + timedelta(seconds=3 + seconds), 5.0, 24.0)
        )
        for seconds in range(1, 17)
    ]
    assert decisions[0].reason != "camera_roll_measurement_abstained", decisions[0]
    assert decisions[0].status == "ADJUSTING", decisions[0]
    assert decisions[2].status == "WATCH", decisions[2]
    assert decisions[-1].status == "BAD", decisions[-1]
    assert decisions[-1].exposure_seconds >= analyzer.posture_policy.alert_exposure_seconds
    print("test_real_pelvis_relative_lateral_change_still_alerts OK")


def test_static_hold_add_on_is_visible_but_bounded() -> None:
    analyzer = scientific_analyzer()
    validate_scientific_profile(analyzer, T0)

    decision = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=10.0), 2.2))
    assert decision.status == "ADJUSTING", decision
    for seconds in range(11, 82):
        decision = analyzer.evaluate(
            scientific_sample(T0 + timedelta(seconds=seconds), 2.2)
        )
    assert decision.static_hold_seconds > 60.0, decision
    assert 0.0 < decision.static_hold_bonus <= analyzer.posture_policy.static_hold_max_bonus
    assert decision.status in {"BAD", "CRITICAL"}

    normal = scientific_analyzer()
    validate_scientific_profile(normal, T0)
    for seconds in range(3, 240):
        normal_decision = normal.evaluate(
            scientific_sample(T0 + timedelta(seconds=seconds), 0.0)
        )
    assert normal_decision.status == "GOOD", normal_decision
    assert normal_decision.static_hold_seconds == 0.0
    assert normal_decision.static_hold_bonus == 0.0
    print("test_static_hold_add_on_is_visible_but_bounded OK")


if __name__ == "__main__":
    test_defaults_all_enabled()
    test_auto_calibration_requires_complete_single_person_sample()
    test_precision_toggle()
    test_presence_toggle()
    test_presence_toggle_resets_multi_debounce_anchor()
    test_identity_toggle()
    test_scientific_continuous_scoring_exposure_and_abstention()
    test_post_calibration_validation_requires_the_actual_normal_band()
    test_brief_posture_excursion_is_adjustment_not_watch()
    test_natural_midrange_lean_stays_good_without_observation()
    test_sustained_posture_excursion_enters_watch_after_confirmation()
    test_production_target_chain_ignores_high_fps_landmark_jitter()
    test_runtime_local_hip_quality_abstains_torso_features()
    test_single_feature_runtime_drift_does_not_open_watch_or_exposure()
    test_head_turn_abstains_without_static_exposure()
    test_fixed_posture_distance_scale_does_not_become_head_turn_watch()
    test_unchanged_posture_shared_shoulder_width_drift_never_accumulates_exposure()
    test_gradual_shared_scale_drift_does_not_intervene_before_guard()
    test_real_forward_change_with_stable_shoulder_scale_still_alerts()
    test_rigid_frame_roll_never_becomes_lateral_exposure()
    test_real_pelvis_relative_lateral_change_still_alerts()
    test_static_hold_add_on_is_visible_but_bounded()
    print("ALL TESTS PASSED")
