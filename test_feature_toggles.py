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
from posture_science import CalibrationAccumulator, CalibrationPlan, measurement_values
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
    assert first.status == "UNKNOWN", first
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
    assert ending_posture.status == "UNKNOWN", ending_posture
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

    beyond_relaxed = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=301), 1.6))
    assert beyond_relaxed.posture_deviation >= 0.50, beyond_relaxed
    assert beyond_relaxed.status == "WATCH", beyond_relaxed

    alert = beyond_relaxed
    for seconds in range(302, 315):
        alert = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=seconds), 2.0))
    assert alert.status == "BAD", alert
    assert alert.exposure_seconds >= 12.0
    assert alert.risk_score == alert.posture_deviation * 100.0
    assert alert.sustained_seconds == alert.exposure_seconds

    before = alert.exposure_seconds
    low_quality = analyzer.evaluate(
        scientific_sample(T0 + timedelta(seconds=320), 2.0, quality=0.40)
    )
    assert low_quality.status in {"UNKNOWN", "WATCH"}, low_quality
    assert low_quality.exposure_seconds == before

    moving = replace(
        scientific_sample(T0 + timedelta(seconds=325), 2.0),
        target_motion=0.5,
        activity_state="MOVING",
    )
    moving_decision = analyzer.evaluate(moving)
    assert moving_decision.status == "UNKNOWN", moving_decision
    assert moving_decision.exposure_seconds == before
    print("test_scientific_continuous_scoring_exposure_and_abstention OK")


def test_post_calibration_validation_requires_the_actual_normal_band():
    """A sub-WATCH deviation cannot unlock exposure after calibration."""

    analyzer = scientific_analyzer()
    near_band = analyzer.evaluate(scientific_sample(T0, 1.4))
    assert near_band.status == "UNKNOWN", near_band
    assert near_band.reason == "post_calibration_normal_range_validation"
    assert 0.0 < near_band.risk_score < analyzer.posture_policy.watch_exit * 100.0
    assert near_band.posture_deviation == 0.0
    assert near_band.exposure_seconds == 0.0

    first_in_band = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=1.0), 1.0))
    assert first_in_band.reason == "post_calibration_normal_range_validation"
    too_soon = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=2.1), 1.0))
    assert too_soon.status == "UNKNOWN", too_soon
    assert too_soon.reason == "post_calibration_normal_range_validation"
    validated = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=3.1), 1.0))
    assert validated.status == "GOOD", validated
    assert validated.reason == "post_calibration_normal_range_validated"
    assert validated.exposure_seconds == 0.0
    print("test_post_calibration_validation_requires_the_actual_normal_band OK")


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
    assert decision.status == "UNKNOWN", decision
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
            preferred.mean + direction * (abs(relaxed.mean - preferred.mean) + noise * 2.0)
        ) * sample.shoulder_width_px,
    )
    first = analyzer.evaluate(drifted)
    assert first.status == "UNKNOWN", first
    assert first.reason == "posture_evidence_inconclusive"
    assert first.exposure_seconds == 0.0
    later = analyzer.evaluate(replace(drifted, timestamp=T0 + timedelta(seconds=300)))
    assert later.status == "UNKNOWN", later
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
    assert decision.status == "UNKNOWN", decision
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
        assert decision.status == "GOOD", decision
        assert decision.posture_deviation == 0.0, decision
        assert decision.exposure_seconds == 0.0, decision
    scaled = replace(
        baseline,
        timestamp=T0 + timedelta(seconds=20),
        interpupillary_px=baseline.interpupillary_px * 1.35,
        shoulder_width_px=baseline.shoulder_width_px * 1.35,
    )
    decision = analyzer.evaluate(scaled)
    assert decision.status == "UNKNOWN", decision
    assert decision.reason == "camera_scale_jump_measurement_abstained"
    assert decision.exposure_seconds == 0.0
    print("test_fixed_posture_distance_scale_does_not_become_head_turn_watch OK")


if __name__ == "__main__":
    test_defaults_all_enabled()
    test_auto_calibration_requires_complete_single_person_sample()
    test_precision_toggle()
    test_presence_toggle()
    test_presence_toggle_resets_multi_debounce_anchor()
    test_identity_toggle()
    test_scientific_continuous_scoring_exposure_and_abstention()
    test_post_calibration_validation_requires_the_actual_normal_band()
    test_production_target_chain_ignores_high_fps_landmark_jitter()
    test_runtime_local_hip_quality_abstains_torso_features()
    test_single_feature_runtime_drift_does_not_open_watch_or_exposure()
    test_head_turn_abstains_without_static_exposure()
    test_fixed_posture_distance_scale_does_not_become_head_turn_watch()
    print("ALL TESTS PASSED")
