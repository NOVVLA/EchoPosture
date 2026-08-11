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
    )


def scientific_analyzer() -> HighPrecisionPostureAnalyzer:
    accumulator = CalibrationAccumulator(CalibrationPlan())
    for index in range(5):
        sample = scientific_sample(T0 + timedelta(seconds=index * 0.2), 0.0)
        accumulator.add(index * 0.2, measurement_values(sample))
    for index in range(5):
        sample = scientific_sample(T0 + timedelta(seconds=2.1 + index * 0.2), 1.0)
        accumulator.add(2.1 + index * 0.2, measurement_values(sample))
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
    preferred = analyzer.evaluate(scientific_sample(T0, 0.0))
    assert preferred.status == "GOOD", preferred
    assert preferred.posture_deviation == 0.0

    midpoint = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=1), 0.5))
    assert 0.45 <= midpoint.posture_deviation <= 0.65, midpoint
    assert midpoint.status == "WATCH", midpoint

    analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=2), 1.0))
    alert = analyzer.evaluate(scientific_sample(T0 + timedelta(seconds=14), 1.0))
    assert alert.status == "BAD", alert
    assert alert.exposure_seconds >= 12.0
    assert alert.risk_score == alert.posture_deviation * 100.0
    assert alert.sustained_seconds == alert.exposure_seconds

    before = alert.exposure_seconds
    low_quality = analyzer.evaluate(
        scientific_sample(T0 + timedelta(seconds=20), 1.0, quality=0.40)
    )
    assert low_quality.status in {"UNKNOWN", "WATCH"}, low_quality
    assert low_quality.exposure_seconds == before

    moving = replace(
        scientific_sample(T0 + timedelta(seconds=25), 1.0),
        target_motion=0.5,
        activity_state="MOVING",
    )
    moving_decision = analyzer.evaluate(moving)
    assert moving_decision.status == "WATCH", moving_decision
    assert moving_decision.exposure_seconds == before
    print("test_scientific_continuous_scoring_exposure_and_abstention OK")


if __name__ == "__main__":
    test_defaults_all_enabled()
    test_auto_calibration_requires_complete_single_person_sample()
    test_precision_toggle()
    test_presence_toggle()
    test_presence_toggle_resets_multi_debounce_anchor()
    test_identity_toggle()
    test_scientific_continuous_scoring_exposure_and_abstention()
    print("ALL TESTS PASSED")
