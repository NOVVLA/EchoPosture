"""CUDA YOLO26l/x-pose backend for the professional Beta vision mode.

Like the standard tier this backend emits body-pose observations only; COCO
nose, eye, and ear keypoints stay body landmarks and are never promoted to face
detections, identity templates, or embeddings. The professional tier differs in
three ways: it runs on CUDA, it picks between the l and x weights from a real
measurement instead of a guess, and it reports its measured throughput so the UI
never has to claim a frame rate it did not observe.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections import deque
from dataclasses import replace as replace_dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

import numpy as np

from standard_pose_backend import StandardPoseBackend
from user_settings import settings_path
from vision_backend import VisionCapabilities
from windows_runtime_paths import RuntimePathBridgeError, prepare_package_dll_directory

# Ordered best-first: the largest model wins when it meets the latency target.
PROFESSIONAL_MODEL_ORDER = ("yolo26x-pose", "yolo26l-pose")
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent / "models" / "pose"

# 20 Hz is the acceptance target from the vision upgrade plan; 50 ms of P95
# inference latency is the per-frame budget that implies.
TARGET_P95_MS = 50.0
BENCHMARK_WARMUP_FRAMES = 3
BENCHMARK_SAMPLE_FRAMES = 12
BENCHMARK_CACHE_VERSION = 2
LIVE_LATENCY_WINDOW = 30

_MEASURED_FRAMES_BEFORE_REPORTING = 8


class ProfessionalBenchmarkError(RuntimeError):
    """No professional weight met the latency target on this machine."""


def _is_cuda_oom(exc: BaseException) -> bool:
    if type(exc).__name__ == "OutOfMemoryError":
        return True
    return "out of memory" in str(exc).lower()


def benchmark_cache_path() -> Path:
    """Sits beside settings.json but stays a separate file: settings.json holds
    only user preferences and must not grow performance telemetry."""
    return settings_path().with_name("professional_benchmark.json")


def percentile(values: Sequence[float], fraction: float) -> float:
    """Classic nearest-rank percentile: ceil(p*n)-1.

    Deliberately not interpolated. On the 12-sample benchmark P95 resolves to the
    worst observed frame, which is the conservative reading for a latency gate.
    """
    if not values:
        raise ValueError("percentile of an empty sample")
    ordered = sorted(values)
    rank = math.ceil(fraction * len(ordered))
    index = min(len(ordered) - 1, max(0, rank - 1))
    return ordered[index]


def select_professional_model(
    results: Mapping[str, Mapping[str, float]],
    *,
    target_p95_ms: float = TARGET_P95_MS,
) -> str:
    """Pick the largest weight whose measured P95 stays inside the frame budget."""
    for name in PROFESSIONAL_MODEL_ORDER:
        measurement = results.get(name)
        if measurement is None:
            continue
        if float(measurement["p95_ms"]) <= target_p95_ms:
            return name
    measured = ", ".join(
        f"{name} P95 {float(results[name]['p95_ms']):.1f}ms"
        for name in PROFESSIONAL_MODEL_ORDER
        if name in results
    )
    raise ProfessionalBenchmarkError(
        f"No professional weight met the {target_p95_ms:.0f}ms P95 budget ({measured or 'no samples'})."
    )


class ProfessionalPoseBackend(StandardPoseBackend):
    """CUDA YOLO26l/x-pose backend with measured model selection."""

    BENCHMARK_FRAME_SEED = 20260815

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        capture_fps: float = 4.0,
        model_path: Optional[os.PathLike[str] | str] = None,
        confidence: float = 0.35,
        keypoint_confidence: float = 0.30,
        device: str = "cuda:0",
        *,
        model=None,
        capture_factory: Optional[Callable[[int], object]] = None,
        startup_progress: Optional[Callable[[int, str], None]] = None,
        cuda_ready: Optional[Callable[[], bool]] = None,
        model_loader: Optional[Callable[[Path], object]] = None,
        benchmark_cache_path_override: Optional[os.PathLike[str] | str] = None,
        model_dir: Optional[os.PathLike[str] | str] = None,
        target_p95_ms: float = TARGET_P95_MS,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        configured = model_path or os.environ.get("ECHOPOSTURE_PROFESSIONAL_MODEL")
        super().__init__(
            camera_id=camera_id,
            width=width,
            height=height,
            capture_fps=capture_fps,
            # The parent resolves its own default when nothing is configured; the
            # real path is decided by the benchmark in _resolve_model().
            model_path=configured or DEFAULT_MODEL_DIR / f"{PROFESSIONAL_MODEL_ORDER[0]}.pt",
            confidence=confidence,
            keypoint_confidence=keypoint_confidence,
            device=device,
            model=model,
            capture_factory=capture_factory,
            startup_progress=startup_progress,
        )
        self._explicit_model_path = Path(configured) if configured else None
        self._model_dir = Path(model_dir) if model_dir else DEFAULT_MODEL_DIR
        self._cuda_ready = cuda_ready
        self._model_loader = model_loader
        self._cache_path = (
            Path(benchmark_cache_path_override)
            if benchmark_cache_path_override
            else benchmark_cache_path()
        )
        self._target_p95_ms = float(target_p95_ms)
        self._clock = clock
        self._selected_model: Optional[str] = None
        self._benchmark: Optional[dict] = None
        self._stepdown_reason: Optional[tuple] = None
        self._latencies: deque = deque(maxlen=LIVE_LATENCY_WINDOW)
        # Instance-level so the reported name can become concrete once the
        # benchmark has chosen a weight. The class attribute would lie.
        self.capabilities = VisionCapabilities(
            supports_multi_person_pose=True,
            supports_gpu=True,
            supports_world_coordinates=False,
            supports_face_bbox=False,
            backend_name="ultralytics-yolo26-pose-cuda",
        )

    # ---- startup -------------------------------------------------------

    def start(self) -> None:
        if self._model is None:
            self._require_cuda()
            self._resolve_model()
        else:
            self._selected_model = self._selected_model or self.model_path.stem
            self._apply_backend_name()
        super().start()

    def _require_cuda(self) -> None:
        if self._cuda_ready is not None:
            ready = bool(self._cuda_ready())
        else:
            try:
                prepare_package_dll_directory("torch")
                import torch
            except (ImportError, OSError, RuntimePathBridgeError) as exc:
                raise RuntimeError(
                    "Professional mode requires a CUDA build of PyTorch. Install "
                    f"requirements-professional.txt into the Python 3.11 runtime ({exc})."
                ) from exc
            ready = bool(torch.cuda.is_available())
        if not ready:
            raise RuntimeError(
                "Professional mode requires an available CUDA device, but torch reports none. "
                "Check the NVIDIA driver and that the CUDA PyTorch wheel is installed."
            )

    def _candidate_paths(self) -> list[tuple[str, Path]]:
        if self._explicit_model_path is not None:
            return [(self._explicit_model_path.stem, self._explicit_model_path)]
        candidates = []
        for name in PROFESSIONAL_MODEL_ORDER:
            path = self._model_dir / f"{name}.pt"
            if path.is_file():
                candidates.append((name, path))
        return candidates

    def _resolve_model(self) -> None:
        candidates = self._candidate_paths()
        if not candidates:
            raise RuntimeError(
                "Professional mode YOLO26l/x-pose weights are missing. Place yolo26l-pose.pt or "
                f"yolo26x-pose.pt in {self._model_dir} or set ECHOPOSTURE_PROFESSIONAL_MODEL. "
                "Automatic model downloads are disabled."
            )
        if self._explicit_model_path is not None:
            # An explicit override is a deliberate choice; do not second-guess it.
            name, path = candidates[0]
            self._selected_model = name
            self.model_path = path
            self._model = self._load_model(path)
            self._apply_backend_name()
            return

        cached = self._load_cache(candidates)
        if cached is not None:
            name = cached["selected"]
            path = dict(candidates)[name]
            self._benchmark = cached
            self._selected_model = name
            self.model_path = path
            self._model = self._load_model(path)
            self._apply_backend_name()
            return

        results, models = self._run_benchmark(candidates)
        name = select_professional_model(results, target_p95_ms=self._target_p95_ms)
        self._benchmark = {
            "version": BENCHMARK_CACHE_VERSION,
            "fingerprint": self._fingerprint(candidates),
            "results": results,
            "selected": name,
            "target_p95_ms": self._target_p95_ms,
        }
        self._selected_model = name
        self.model_path = dict(candidates)[name]
        self._model = models[name]
        self._apply_backend_name()
        self._save_cache(self._benchmark)

    def _load_model(self, path: Path):
        if self._model_loader is not None:
            return self._model_loader(path)
        try:
            prepare_package_dll_directory("torch")
            from ultralytics import YOLO
        except (ImportError, OSError, RuntimePathBridgeError) as exc:
            raise RuntimeError(
                "Professional mode requires ultralytics==8.4.120 with a CUDA PyTorch build. "
                "Install requirements-professional.txt into the Python 3.11 runtime and ensure "
                f"its native DLLs are loadable ({exc})."
            ) from exc
        return YOLO(str(path))

    def _apply_backend_name(self) -> None:
        name = self._selected_model or "yolo26-pose"
        self.capabilities = replace_dataclass(
            self.capabilities,
            backend_name=f"ultralytics-{name}-cuda",
        )

    # ---- benchmark -----------------------------------------------------

    def _benchmark_frame(self) -> np.ndarray:
        generator = np.random.default_rng(self.BENCHMARK_FRAME_SEED)
        return generator.integers(24, 232, size=(self.height, self.width, 3), dtype=np.uint8)

    def _run_benchmark(self, candidates: Sequence[tuple[str, Path]]):
        """Time each candidate on synthetic frames; never touches the camera."""
        frame = self._benchmark_frame()
        results: dict[str, dict[str, float]] = {}
        models: dict[str, object] = {}
        for name, path in candidates:
            self._report_startup(50, "onb_mode_benchmarking")
            try:
                model = self._load_model(path)
                samples = self._time_model(model, frame)
            except Exception as exc:  # noqa: BLE001 - re-raised unless it is OOM
                if not _is_cuda_oom(exc):
                    raise
                # A weight that cannot fit is simply not a candidate.
                self._stepdown_reason = (
                    "vision_pro_fallback_oom",
                    {"model": name, "fallback": self._next_candidate_label(candidates, name)},
                )
                continue
            models[name] = model
            results[name] = {
                "p50_ms": percentile(samples, 0.50),
                "p95_ms": percentile(samples, 0.95),
            }
        if not results:
            raise RuntimeError(
                "Every professional weight failed to run on this GPU (out of memory)."
            )
        return results, models

    @staticmethod
    def _next_candidate_label(candidates: Sequence[tuple[str, Path]], name: str) -> str:
        names = [item[0] for item in candidates]
        index = names.index(name)
        return names[index + 1] if index + 1 < len(names) else "standard"

    def _time_model(self, model, frame) -> list[float]:
        for _ in range(BENCHMARK_WARMUP_FRAMES):
            model.predict(source=frame, conf=self.confidence, device=self.device, verbose=False)
        samples = []
        for _ in range(BENCHMARK_SAMPLE_FRAMES):
            started = self._clock()
            model.predict(source=frame, conf=self.confidence, device=self.device, verbose=False)
            samples.append((self._clock() - started) * 1000.0)
        return samples

    def _fingerprint(self, candidates: Sequence[tuple[str, Path]]) -> dict:
        weights = {}
        for name, path in candidates:
            try:
                weights[name] = path.stat().st_size
            except OSError:
                weights[name] = -1
        return {"weights": weights, "device": self.device, "target_p95_ms": self._target_p95_ms}

    def _load_cache(self, candidates: Sequence[tuple[str, Path]]) -> Optional[dict]:
        if os.environ.get("ECHOPOSTURE_PRO_REBENCH"):
            return None
        try:
            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("version") != BENCHMARK_CACHE_VERSION:
            return None
        if payload.get("fingerprint") != self._fingerprint(candidates):
            return None
        selected = payload.get("selected")
        if selected not in dict(candidates):
            return None
        return payload

    def _save_cache(self, payload: dict) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._cache_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(temporary, self._cache_path)
        except OSError:
            # A missing cache only costs one re-benchmark; never fail startup.
            pass

    # ---- runtime -------------------------------------------------------

    def read_frame_sample(self):
        started = self._clock()
        frame, sample = super().read_frame_sample()
        self._latencies.append((self._clock() - started) * 1000.0)
        return frame, sample

    @property
    def selected_model(self) -> Optional[str]:
        return self._selected_model

    @property
    def benchmark(self) -> Optional[dict]:
        return self._benchmark

    @property
    def diagnostic_notice(self):
        """Report what is actually running, using measured frames only."""
        model = self._selected_model or "yolo26-pose"
        if len(self._latencies) < _MEASURED_FRAMES_BEFORE_REPORTING:
            return ("vision_pro_active_warmup", {"model": model})
        samples = list(self._latencies)
        p50 = percentile(samples, 0.50)
        p95 = percentile(samples, 0.95)
        return (
            "vision_pro_active_notice",
            {
                "model": model,
                "hz": f"{1000.0 / p50:.1f}" if p50 > 0 else "0.0",
                "p50": f"{p50:.1f}",
                "p95": f"{p95:.1f}",
            },
        )

    def close(self) -> None:
        super().close()
        self._latencies.clear()


__all__ = [
    "DEFAULT_MODEL_DIR",
    "PROFESSIONAL_MODEL_ORDER",
    "TARGET_P95_MS",
    "ProfessionalBenchmarkError",
    "ProfessionalPoseBackend",
    "benchmark_cache_path",
    "percentile",
    "select_professional_model",
]
