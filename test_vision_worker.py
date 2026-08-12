"""
VisionWorker 逻辑层测试（无 GUI、无摄像头）。

运行方式：runtime\\python311\\python.exe test_vision_worker.py
用可编程的 FakeEngine 验证线程归属、信箱语义、校准流程与错误传播。
"""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

from posture_science import CalibrationPlan, TRANSITION
from vision_test import (
    CameraBlackFrameError,
    HighPrecisionPostureAnalyzer,
    VisionEngine,
    VisionSample,
    calibration_sample_is_complete,
    calibration_sample_missing_fields,
)
from vision_worker import (
    MODE_MONITORING,
    MODE_PAUSED,
    VisionWorker,
    average_calibration_sample,
)


def make_sample(ipd: float = 60.0, face_count: int = 1) -> VisionSample:
    return VisionSample(
        timestamp=datetime.now(),
        interpupillary_px=ipd,
        shoulder_diff_px=4.0,
        signed_shoulder_diff_px=4.0,
        shoulder_width_px=220.0,
        trunk_lean_deg=2.0,
        face_detected=True,
        pose_detected=True,
        face_count=face_count,
        head_turn_ratio=0.02,
        torso_height_px=180.0,
    )


class FakeEngine:
    """可编程引擎：记录每个调用发生的线程，可注入异常。"""

    def __init__(self) -> None:
        self.thread_idents: dict = {}
        self.read_count = 0
        self.fail_after: int = -1          # 第 N 次 read 开始抛错（-1 = 不抛）
        self.fail_exc: Exception = CameraBlackFrameError("fake black frame")
        self.fps = 0.0
        self.closed = threading.Event()

    def start(self) -> None:
        self.thread_idents["start"] = threading.get_ident()

    def set_capture_fps(self, fps: float) -> None:
        self.fps = fps

    def get_capture_fps(self) -> float:
        return self.fps

    def read_sample(self) -> VisionSample:
        self.thread_idents.setdefault("read", threading.get_ident())
        self.read_count += 1
        if 0 <= self.fail_after < self.read_count:
            raise self.fail_exc
        return make_sample(ipd=60.0 + self.read_count * 0.1)

    def close(self) -> None:
        self.thread_idents["close"] = threading.get_ident()
        self.closed.set()


class IncompleteEngine(FakeEngine):
    def read_sample(self) -> VisionSample:
        self.thread_idents.setdefault("read", threading.get_ident())
        self.read_count += 1
        return replace(make_sample(), pose_detected=False, trunk_lean_deg=None)


def wait_until(predicate, timeout=5.0, interval=0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def build_worker(engine: FakeEngine, fps: float = 60.0):
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False,
                                            calibrated_distance_cm=60.0)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer,
                          target_fps=fps)
    return worker, analyzer


def test_thread_affinity_and_mailbox():
    engine = FakeEngine()
    worker, analyzer = build_worker(engine)
    worker.start(timeout=5.0)
    main_ident = threading.get_ident()
    assert engine.thread_idents["start"] != main_ident, "engine.start 必须在工作线程"

    # 先校准（worker 内 set_baseline），再开监测
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=3)
    assert wait_until(lambda: analyzer.baseline is not None), "校准后应有基线"
    assert wait_until(lambda: worker.take_calibration_result() is not None), "应收到校准回执"

    worker.resume()
    assert wait_until(lambda: worker.latest().decision is not None)
    snap1 = worker.latest()
    assert wait_until(lambda: worker.latest().seq > snap1.seq), "信箱应被新快照覆盖"
    assert engine.thread_idents["read"] != main_ident, "read_sample 必须在工作线程"
    assert worker.is_monitoring_active()

    # pause 后立即反映状态，且不再产出
    worker.pause()
    assert not worker.is_monitoring_active()
    time.sleep(0.2)
    seq_at_pause = worker.latest().seq
    time.sleep(0.3)
    assert worker.latest().seq == seq_at_pause, "暂停后信箱不应再更新"

    worker.stop(join_timeout=3.0)
    assert not worker.is_alive(), "stop 后线程应在超时内退出"
    assert engine.closed.wait(1.0), "engine.close 必须被调用"
    assert engine.thread_idents["close"] != main_ident, "engine.close 必须在工作线程"
    print("test_thread_affinity_and_mailbox OK")


def test_average_matches_legacy_semantics():
    samples = [make_sample(60.0), make_sample(62.0), make_sample(64.0)]
    avg = average_calibration_sample(samples)
    assert avg is not None
    assert abs(avg.interpupillary_px - 62.0) < 1e-6
    assert avg.face_detected and avg.pose_detected
    assert average_calibration_sample([]) is None
    fallback = make_sample(50.0)
    assert average_calibration_sample([], fallback) is fallback
    assert calibration_sample_is_complete(make_sample())
    assert not calibration_sample_is_complete(make_sample(face_count=2))
    assert calibration_sample_missing_fields(make_sample(face_count=2)) == ("single_person",)
    assert not calibration_sample_is_complete(
        replace(make_sample(), person_count=2, target_state="TARGET_LOCKED")
    )
    assert calibration_sample_missing_fields(
        replace(make_sample(), target_state="TARGET_AMBIGUOUS")
    ) == ("single_person",)
    assert average_calibration_sample(
        [make_sample(60.0), make_sample(80.0, face_count=2)]
    ) is not None
    assert average_calibration_sample([make_sample(face_count=2)]) is None
    assert average_calibration_sample([], fallback=make_sample(face_count=2)) is None
    print("test_average_matches_legacy_semantics OK")


def make_dual_sample(ts: datetime, relaxed: float = 0.0, face_count: int = 1) -> VisionSample:
    return replace(
        make_sample(ipd=60.0 + relaxed * 20.0, face_count=face_count),
        timestamp=ts,
        shoulder_width_px=200.0,
        torso_height_px=180.0 - relaxed * 40.0,
        trunk_lean_deg=2.0 + relaxed * 10.0,
        face_quality=1.0,
        pose_quality=1.0,
        target_motion=0.0,
        activity_state="STATIC",
    )


def test_pose_quality_uses_shoulders_not_optional_hips() -> None:
    landmarks = [SimpleNamespace(x=0.5, y=0.5, visibility=1.0) for _ in range(33)]
    landmarks[11] = SimpleNamespace(x=0.35, y=0.4, visibility=0.55)
    landmarks[12] = SimpleNamespace(x=0.65, y=0.4, visibility=0.58)
    landmarks[23] = SimpleNamespace(x=0.4, y=0.75, visibility=0.40)
    landmarks[24] = SimpleNamespace(x=0.6, y=0.75, visibility=0.45)
    result = SimpleNamespace(
        pose_landmarks=SimpleNamespace(landmark=landmarks),
    )
    engine = object.__new__(VisionEngine)

    values = engine._measure_pose_points(result, 640, 480)

    assert values is not None
    assert values[-1] == 0.55
    assert values[5] is None and values[6] is None
    assert values[8] is None
    print("test_pose_quality_uses_shoulders_not_optional_hips OK")


def test_multi_person_resets_calibration_window():
    engine = FakeEngine()
    worker, _ = build_worker(engine)
    worker._collect_calibration_sample(make_sample(60.0))
    worker._collect_calibration_sample(make_sample(60.0, face_count=2))
    assert worker._calib_samples == []
    assert worker._last_usable_sample is None
    print("test_multi_person_resets_calibration_window OK")


def test_target_manager_presence_resets_calibration_window():
    engine = FakeEngine()
    worker, _ = build_worker(engine)
    worker._collect_calibration_sample(
        replace(make_sample(), person_count=1, target_state="ACQUIRING")
    )
    worker._collect_calibration_sample(
        replace(make_sample(), person_count=2, target_state="TARGET_LOCKED")
    )
    assert worker._calib_samples == []
    assert worker._last_usable_sample is None
    print("test_target_manager_presence_resets_calibration_window OK")


def test_calibration_failure_and_error_propagation():
    # 校准失败：引擎一直抛错 → 回执 ok=False，错误进信箱
    engine = FakeEngine()
    engine.fail_after = 0
    worker, analyzer = build_worker(engine)
    worker.start(timeout=5.0)
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=3)

    result_box = {}
    def got_result():
        r = worker.take_calibration_result()
        if r is not None:
            result_box["r"] = r
            return True
        return False
    assert wait_until(got_result), "应收到校准回执"
    assert result_box["r"].ok is False, "全失败时回执应为失败"
    err = worker.take_error()
    assert isinstance(err, CameraBlackFrameError), f"应传播摄像头错误，得到 {err!r}"
    assert worker.take_error() is None, "错误是一次性回执"
    assert analyzer.baseline is None
    worker.stop()
    print("test_calibration_failure_and_error_propagation OK")


def test_calibration_failure_reports_missing_fields():
    engine = IncompleteEngine()
    worker, analyzer = build_worker(engine)
    worker.start(timeout=5.0)
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=2)

    result_box = {}

    def got_result():
        result = worker.take_calibration_result()
        if result is not None:
            result_box["result"] = result
            return True
        return False

    assert wait_until(got_result), "应收到校准回执"
    assert result_box["result"].ok is False
    assert result_box["result"].missing_fields == ("pose_detected", "trunk_lean_deg")
    assert analyzer.baseline is None
    worker.stop()
    print("test_calibration_failure_reports_missing_fields OK")


def test_dual_anchor_worker_calibration_and_stage_counts():
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(
        auto_calibrate=False,
        require_dual_anchor=True,
    )
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    worker._calibration_accumulator = None
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(5):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=index))
        )
    assert worker._calibration_accumulator is not None
    worker._calibration_accumulator.begin_transition(start + timedelta(seconds=5))
    worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=5.5), 0.5))
    assert worker._calibration_accumulator.phase == TRANSITION
    assert worker._calibration_accumulator.stage_counts == {"preferred": 5, "relaxed": 0}
    for index in range(5):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=6 + index), 1.0)
        )
    worker._finalize_dual_anchor_calibration(60.0, 1)
    result = worker.take_calibration_result()
    assert result is not None and result.ok, result
    assert dict(result.stage_counts) == {"preferred": 5, "relaxed": 5}
    assert analyzer.calibration_profile is not None
    print("test_dual_anchor_worker_calibration_and_stage_counts OK")


def test_dual_anchor_worker_rejects_multi_person_and_short_stage():
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, require_dual_anchor=True)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(3):
        worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=index * 0.2)))
    worker._collect_calibration_sample(
        make_dual_sample(start + timedelta(seconds=0.8), face_count=2)
    )
    assert worker._calibration_accumulator is not None
    assert worker._calibration_accumulator.stage_counts["preferred"] == 0
    worker._collect_calibration_sample(
        replace(
            make_dual_sample(start + timedelta(seconds=0.9)),
            target_state="TARGET_OCCLUDED",
        )
    )
    assert worker._calibration_accumulator.stage_counts["preferred"] == 0
    for index in range(5):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=1.0 + index * 0.2))
        )
    assert worker._calibration_accumulator is not None
    worker._calibration_accumulator.begin_transition(start + timedelta(seconds=5.0))
    for index in range(4):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=6.0 + index), 1.0)
        )
    worker._finalize_dual_anchor_calibration(60.0, 2)
    result = worker.take_calibration_result()
    assert result is not None and not result.ok
    assert any("relaxed_samples" in field for field in result.missing_fields)
    print("test_dual_anchor_worker_rejects_multi_person_and_short_stage OK")


def test_dual_anchor_worker_skips_quality_dropout_without_resetting_stage() -> None:
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, require_dual_anchor=True)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(4):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=index * 0.5))
        )
    assert worker._calibration_accumulator is not None
    worker._collect_calibration_sample(
        replace(
            make_dual_sample(start + timedelta(seconds=2.1)),
            pose_quality=0.35,
        )
    )
    assert worker._calibration_accumulator.stage_counts["preferred"] == 4
    worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=2.5)))
    assert worker._calibration_accumulator.stage_counts["preferred"] == 5
    assert worker._calibration_accumulator.rejection_counts == {
        "preferred:pose_quality_low": 1
    }
    print("test_dual_anchor_worker_skips_quality_dropout_without_resetting_stage OK")


def test_dual_anchor_worker_accepts_borderline_pose_quality_for_anchor_repeatability():
    """Stable 0.45 pose quality is usable for anchor repeatability."""
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, require_dual_anchor=True)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(5):
        worker._collect_calibration_sample(
            replace(
                make_dual_sample(start + timedelta(seconds=index)),
                pose_quality=0.45,
            )
        )
    assert worker._calibration_accumulator is not None
    assert worker._calibration_accumulator.stage_counts["preferred"] == 5
    worker._calibration_accumulator.begin_transition(start + timedelta(seconds=5))
    for index in range(5):
        worker._collect_calibration_sample(
            replace(
                make_dual_sample(start + timedelta(seconds=6 + index), 1.0),
                pose_quality=0.45,
            )
        )
    worker._dual_calibration_request = (60.0, 9)
    worker._finalize_dual_anchor_calibration(60.0, 9)
    result = worker.take_calibration_result()
    assert result is not None and result.ok, result
    assert dict(result.stage_counts) == {"preferred": 5, "relaxed": 5}
    print("test_dual_anchor_worker_accepts_borderline_pose_quality_for_anchor_repeatability OK")


def test_dual_anchor_worker_skips_zero_person_dropout_without_resetting_stage() -> None:
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, require_dual_anchor=True)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(4):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=index * 0.5))
        )
    assert worker._calibration_accumulator is not None
    worker._collect_calibration_sample(
        replace(
            make_dual_sample(start + timedelta(seconds=2.1)),
            face_count=0,
            person_count=0,
            face_detected=False,
            pose_detected=False,
            target_state="TARGET_OCCLUDED",
        )
    )
    assert worker._calibration_accumulator.stage_counts["preferred"] == 4
    assert worker._calibration_accumulator.reset_reasons == ()
    worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=2.5)))
    assert worker._calibration_accumulator.stage_counts["preferred"] == 5
    print("test_dual_anchor_worker_skips_zero_person_dropout_without_resetting_stage OK")


def test_dual_anchor_worker_uses_bounded_relaxed_extension() -> None:
    engine = FakeEngine()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, require_dual_anchor=True)
    worker = VisionWorker(engine_factory=lambda: engine, analyzer=analyzer)
    worker._calibration_plan = CalibrationPlan(
        preferred_seconds=5.0,
        transition_seconds=1.0,
        relaxed_seconds=5.0,
        relaxed_max_extension_seconds=2.0,
    )
    start = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(5):
        worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=index)))
    assert worker._calibration_accumulator is not None
    worker._calibration_accumulator.begin_transition(start + timedelta(seconds=5))
    worker._dual_calibration_request = (60.0, 7)

    # Four valid relaxed samples by the nominal five-second target do not fail.
    for index in range(4):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=6 + index), 1.0)
        )
    worker._collect_calibration_sample(
        replace(
            make_dual_sample(start + timedelta(seconds=11), 1.0),
            pose_quality=0.1,
        )
    )
    assert worker.take_calibration_result() is None
    assert worker._calibration_accumulator is not None

    for index in range(5):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=11.1 + index * 0.1), 1.0)
        )
    result = worker.take_calibration_result()
    assert result is not None and result.ok, result
    assert dict(result.stage_counts) == {"preferred": 5, "relaxed": 5}

    # A second run with persistent rejection fails at the extension deadline.
    analyzer.reset_baseline()
    worker._calibration_accumulator = None
    worker._calibration_missing_fields = set()
    for index in range(5):
        worker._collect_calibration_sample(make_dual_sample(start + timedelta(seconds=index)))
    assert worker._calibration_accumulator is not None
    worker._calibration_accumulator.begin_transition(start + timedelta(seconds=5))
    worker._dual_calibration_request = (60.0, 8)
    for index in range(4):
        worker._collect_calibration_sample(
            make_dual_sample(start + timedelta(seconds=6 + index), 1.0)
        )
    worker._collect_calibration_sample(
        replace(
            make_dual_sample(start + timedelta(seconds=13), 1.0),
            pose_quality=0.1,
        )
    )
    failed = worker.take_calibration_result()
    assert failed is not None and not failed.ok
    assert any("relaxed_samples" in field for field in failed.missing_fields)
    print("test_dual_anchor_worker_uses_bounded_relaxed_extension OK")


def test_monitoring_error_pauses_worker():
    engine = FakeEngine()
    engine.fail_after = 5
    worker, _ = build_worker(engine, fps=200.0)
    worker.start(timeout=5.0)
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=2)
    assert wait_until(lambda: worker.take_calibration_result() is not None)
    worker.resume()
    assert wait_until(lambda: worker.take_error() is not None, timeout=5.0)
    assert wait_until(lambda: worker._mode == MODE_PAUSED), "出错后 worker 应自暂停"
    worker.stop()
    print("test_monitoring_error_pauses_worker OK")


def test_start_failure_propagates_to_caller():
    class BrokenEngine(FakeEngine):
        def start(self) -> None:
            raise RuntimeError("no camera")

    worker, _ = build_worker(BrokenEngine())
    try:
        worker.start(timeout=5.0)
    except RuntimeError as exc:
        assert "no camera" in str(exc)
    else:
        raise AssertionError("engine.start 失败应同步抛给调用线程")
    print("test_start_failure_propagates_to_caller OK")


def test_set_capture_fps_roundtrip():
    engine = FakeEngine()
    worker, _ = build_worker(engine, fps=30.0)
    worker.start(timeout=5.0)
    assert engine.fps == 30.0
    worker.set_capture_fps(15.0)
    assert worker.get_capture_fps() == 15.0
    assert wait_until(lambda: engine.fps == 15.0), "fps 命令应在工作线程生效"
    worker.stop()
    print("test_set_capture_fps_roundtrip OK")


if __name__ == "__main__":
    test_average_matches_legacy_semantics()
    test_pose_quality_uses_shoulders_not_optional_hips()
    test_multi_person_resets_calibration_window()
    test_target_manager_presence_resets_calibration_window()
    test_thread_affinity_and_mailbox()
    test_calibration_failure_and_error_propagation()
    test_calibration_failure_reports_missing_fields()
    test_dual_anchor_worker_calibration_and_stage_counts()
    test_dual_anchor_worker_rejects_multi_person_and_short_stage()
    test_dual_anchor_worker_skips_quality_dropout_without_resetting_stage()
    test_dual_anchor_worker_accepts_borderline_pose_quality_for_anchor_repeatability()
    test_dual_anchor_worker_skips_zero_person_dropout_without_resetting_stage()
    test_dual_anchor_worker_uses_bounded_relaxed_extension()
    test_monitoring_error_pauses_worker()
    test_start_failure_propagates_to_caller()
    test_set_capture_fps_roundtrip()
    print("ALL TESTS PASSED")
