"""GPU-free contract tests for the professional CUDA pose backend.

Nothing here imports torch, touches a GPU, or opens a camera: every CUDA-facing
decision goes through an injection point so the suite runs on any machine.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np

from face_observation_enhancer import FaceEnhancedBackend
from professional_pose_backend import (
    PROFESSIONAL_MODEL_ORDER,
    ProfessionalBenchmarkError,
    ProfessionalPoseBackend,
    percentile,
    select_professional_model,
)
from standard_pose_backend import COCO_KEYPOINT_COUNT
from test_standard_pose_backend import FakeCapture, FakeModel, FakeResult, pose_row


class CudaOutOfMemoryError(RuntimeError):
    """Mirrors torch.cuda.OutOfMemoryError by name, without importing torch."""


CudaOutOfMemoryError.__name__ = "OutOfMemoryError"


def _fake_result(persons: int = 1) -> FakeResult:
    rows = np.stack([pose_row(index * 180.0) for index in range(persons)])
    boxes = np.array(
        [[180.0 + index * 180.0, 100.0, 460.0 + index * 180.0, 450.0] for index in range(persons)],
        dtype=float,
    )
    return FakeResult(boxes, np.full(persons, 0.91), rows)


class TimedFakeModel(FakeModel):
    """FakeModel whose predict() advances an injected clock by a fixed cost."""

    def __init__(self, name: str, cost_ms: float, clock: "FakeClock", oom: bool = False) -> None:
        super().__init__(_fake_result())
        self.name = name
        self.cost_ms = cost_ms
        self._clock = clock
        self._oom = oom

    def predict(self, **kwargs):
        if self._oom:
            raise CudaOutOfMemoryError("CUDA out of memory. Tried to allocate 2.00 GiB")
        self._clock.advance(self.cost_ms / 1000.0)
        return super().predict(**kwargs)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


def _weights(directory: Path, names=PROFESSIONAL_MODEL_ORDER) -> Path:
    for index, name in enumerate(names):
        (directory / f"{name}.pt").write_bytes(b"\x00" * (index + 1))
    return directory


def _make_backend(
    directory: Path,
    costs: dict,
    *,
    oom: set = frozenset(),
    cache: Path = None,
    cuda_ready=lambda: True,
    **kwargs,
):
    clock = FakeClock()
    loaded = []

    def loader(path: Path):
        name = path.stem
        loaded.append(name)
        return TimedFakeModel(name, costs.get(name, 10.0), clock, oom=name in oom)

    capture = FakeCapture()
    backend = ProfessionalPoseBackend(
        capture_factory=lambda _camera_id: capture,
        cuda_ready=cuda_ready,
        model_loader=loader,
        model_dir=directory,
        benchmark_cache_path_override=cache or directory / "benchmark.json",
        clock=clock,
        **kwargs,
    )
    return backend, loaded, capture, clock


def test_percentile_and_model_selection_follow_the_latency_budget() -> None:
    assert percentile([5.0], 0.95) == 5.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0

    # The largest weight wins whenever it fits the budget.
    assert (
        select_professional_model(
            {"yolo26x-pose": {"p50_ms": 30.0, "p95_ms": 41.0}, "yolo26l-pose": {"p50_ms": 18.0, "p95_ms": 22.0}}
        )
        == "yolo26x-pose"
    )
    # x over budget steps down to l.
    assert (
        select_professional_model(
            {"yolo26x-pose": {"p50_ms": 70.0, "p95_ms": 88.0}, "yolo26l-pose": {"p50_ms": 18.0, "p95_ms": 22.0}}
        )
        == "yolo26l-pose"
    )
    # Neither fits: refuse rather than ship a mode that cannot hit 20 Hz.
    try:
        select_professional_model(
            {"yolo26x-pose": {"p50_ms": 90.0, "p95_ms": 120.0}, "yolo26l-pose": {"p50_ms": 60.0, "p95_ms": 74.0}}
        )
    except ProfessionalBenchmarkError as exc:
        assert "120.0ms" in str(exc) and "74.0ms" in str(exc)
    else:
        raise AssertionError("an over-budget benchmark must not select a model")


def test_backend_runs_on_cuda_and_reports_the_selected_weight() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 30.0, "yolo26l-pose": 15.0}
        )
        backend.start()

        assert backend.selected_model == "yolo26x-pose"
        assert backend.capabilities.supports_gpu is True
        assert backend.capabilities.backend_name == "ultralytics-yolo26x-pose-cuda"
        assert set(loaded) == {"yolo26x-pose", "yolo26l-pose"}

        backend.read_sample()
        call = backend._model.calls[-1]
        assert call["device"] == "cuda:0"
        observation = backend.observations_for_last_sample()[0]
        assert len(observation.body_keypoints) == COCO_KEYPOINT_COUNT
        # Same observation contract as standard mode: pose only, never face.
        assert observation.face_bbox_xyxy is None
        assert observation.face_landmarks is None
        assert observation.face_embedding is None
        backend.close()


def test_over_budget_x_steps_down_to_l() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 80.0, "yolo26l-pose": 20.0}
        )
        backend.start()
        assert backend.selected_model == "yolo26l-pose"
        assert backend.capabilities.backend_name == "ultralytics-yolo26l-pose-cuda"
        backend.close()


def test_both_weights_over_budget_refuses_to_start() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 120.0, "yolo26l-pose": 70.0}
        )
        try:
            backend.start()
        except ProfessionalBenchmarkError:
            pass
        else:
            raise AssertionError("start() must fail so the caller can fall back visibly")


def test_out_of_memory_on_x_falls_through_to_l() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {"yolo26l-pose": 20.0}, oom={"yolo26x-pose"}
        )
        backend.start()
        assert backend.selected_model == "yolo26l-pose"
        assert backend._stepdown_reason[0] == "vision_pro_fallback_oom"
        assert backend._stepdown_reason[1]["fallback"] == "yolo26l-pose"
        backend.close()


def test_out_of_memory_on_every_weight_refuses_to_start() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {}, oom={"yolo26x-pose", "yolo26l-pose"}
        )
        try:
            backend.start()
        except RuntimeError as exc:
            assert "out of memory" in str(exc).lower()
        else:
            raise AssertionError("an all-OOM GPU must not yield a running professional backend")


def test_missing_cuda_refuses_to_start() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 20.0}, cuda_ready=lambda: False
        )
        try:
            backend.start()
        except RuntimeError as exc:
            assert "CUDA" in str(exc)
        else:
            raise AssertionError("professional mode must not run without CUDA")
        assert loaded == [], "no weight should be loaded before CUDA is confirmed"


def test_missing_weights_refuse_to_start_without_downloading() -> None:
    with tempfile.TemporaryDirectory() as raw:
        backend, _loaded, _capture, _clock = _make_backend(Path(raw), {})
        try:
            backend.start()
        except RuntimeError as exc:
            assert "Automatic model downloads are disabled" in str(exc)
        else:
            raise AssertionError("missing weights must fail loudly")


def test_benchmark_is_cached_and_invalidated_by_a_weight_change() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        cache = directory / "benchmark.json"
        costs = {"yolo26x-pose": 30.0, "yolo26l-pose": 15.0}

        first, first_loaded, _capture, _clock = _make_backend(directory, costs, cache=cache)
        first.start()
        first.close()
        assert len(first_loaded) == 2, "the first run must measure both candidates"
        payload = json.loads(cache.read_text(encoding="utf-8"))
        assert payload["selected"] == "yolo26x-pose"
        assert set(payload["results"]) == {"yolo26x-pose", "yolo26l-pose"}

        second, second_loaded, _capture, _clock = _make_backend(directory, costs, cache=cache)
        second.start()
        second.close()
        assert second_loaded == ["yolo26x-pose"], "a cache hit must load only the chosen weight"
        assert second.selected_model == "yolo26x-pose"

        # A replaced weight invalidates the fingerprint and forces a re-measure.
        (directory / "yolo26x-pose.pt").write_bytes(b"\x00" * 99)
        third, third_loaded, _capture, _clock = _make_backend(directory, costs, cache=cache)
        third.start()
        third.close()
        assert len(third_loaded) == 2, "changed weights must trigger a fresh benchmark"


def test_explicit_model_override_skips_the_benchmark() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, loaded, _capture, _clock = _make_backend(
            directory,
            {"yolo26l-pose": 15.0},
            model_path=directory / "yolo26l-pose.pt",
        )
        backend.start()
        assert loaded == ["yolo26l-pose"]
        assert backend.selected_model == "yolo26l-pose"
        assert backend.benchmark is None
        backend.close()


def test_diagnostic_notice_reports_measured_frames_only() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 25.0, "yolo26l-pose": 12.0}
        )
        backend.start()

        key, values = backend.diagnostic_notice
        assert key == "vision_pro_active_warmup", "no measured rate before enough live frames"
        assert values["model"] == "yolo26x-pose"

        for _ in range(12):
            backend.read_sample()
        key, values = backend.diagnostic_notice
        assert key == "vision_pro_active_notice"
        assert values["model"] == "yolo26x-pose"
        # 25 ms of injected inference cost reads back as roughly 40 Hz.
        assert 38.0 <= float(values["hz"]) <= 42.0
        assert 24.0 <= float(values["p50"]) <= 26.0
        backend.close()


def test_face_enhanced_wrapper_follows_the_resolved_backend_name() -> None:
    with tempfile.TemporaryDirectory() as raw:
        directory = _weights(Path(raw))
        backend, _loaded, _capture, _clock = _make_backend(
            directory, {"yolo26x-pose": 30.0, "yolo26l-pose": 15.0}
        )
        wrapped = FaceEnhancedBackend(backend)
        assert wrapped.capabilities.backend_name == "ultralytics-yolo26-pose-cuda+shared-face"
        backend.start()
        # The wrapper must not keep reporting the pre-benchmark placeholder.
        assert wrapped.capabilities.backend_name == "ultralytics-yolo26x-pose-cuda+shared-face"
        assert wrapped.capabilities.supports_face_bbox is True
        assert wrapped.diagnostic_notice[0] == "vision_pro_active_warmup"
        backend.close()


def main() -> int:
    test_percentile_and_model_selection_follow_the_latency_budget()
    test_backend_runs_on_cuda_and_reports_the_selected_weight()
    test_over_budget_x_steps_down_to_l()
    test_both_weights_over_budget_refuses_to_start()
    test_out_of_memory_on_x_falls_through_to_l()
    test_out_of_memory_on_every_weight_refuses_to_start()
    test_missing_cuda_refuses_to_start()
    test_missing_weights_refuse_to_start_without_downloading()
    test_benchmark_is_cached_and_invalidated_by_a_weight_change()
    test_explicit_model_override_skips_the_benchmark()
    test_diagnostic_notice_reports_measured_frames_only()
    test_face_enhanced_wrapper_follows_the_resolved_backend_name()
    print("test_professional_pose_backend OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
