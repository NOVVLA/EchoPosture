"""
VisionWorker 逻辑层测试（无 GUI、无摄像头）。

运行方式：runtime\\python311\\python.exe test_vision_worker.py
用可编程的 FakeEngine 验证线程归属、信箱语义、校准流程与错误传播。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime

from vision_test import (
    CameraBlackFrameError,
    HighPrecisionPostureAnalyzer,
    VisionSample,
)
from vision_worker import (
    MODE_MONITORING,
    MODE_PAUSED,
    VisionWorker,
    average_calibration_sample,
    sample_is_usable,
)


def make_sample(ipd: float = 60.0) -> VisionSample:
    return VisionSample(
        timestamp=datetime.now(),
        interpupillary_px=ipd,
        shoulder_diff_px=4.0,
        signed_shoulder_diff_px=4.0,
        shoulder_width_px=220.0,
        trunk_lean_deg=2.0,
        face_detected=True,
        pose_detected=True,
        face_count=1,
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
    assert sample_is_usable(make_sample())
    print("test_average_matches_legacy_semantics OK")


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
    test_thread_affinity_and_mailbox()
    test_calibration_failure_and_error_propagation()
    test_monitoring_error_pauses_worker()
    test_start_failure_propagates_to_caller()
    test_set_capture_fps_roundtrip()
    print("ALL TESTS PASSED")
