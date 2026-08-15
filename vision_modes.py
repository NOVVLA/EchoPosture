"""Product contract for selectable vision modes and backend availability."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple


VISION_MODE_COMPATIBILITY = "compatibility"
VISION_MODE_STANDARD = "standard"
VISION_MODE_PROFESSIONAL_BETA = "professional_beta"


@dataclass(frozen=True)
class VisionModeSpec:
    mode: str
    label_key: str
    intended_backend: str
    unavailable_reason_key: Optional[str] = None


@dataclass(frozen=True)
class ModeAvailability:
    available: bool
    reason_key: Optional[str] = None


VISION_MODE_SPECS: Tuple[VisionModeSpec, ...] = (
    VisionModeSpec(
        VISION_MODE_COMPATIBILITY,
        "vision_mode_compatibility",
        "mediapipe-compatibility",
    ),
    VisionModeSpec(
        VISION_MODE_STANDARD,
        "vision_mode_standard",
        "ultralytics-yolo26n-pose-cpu",
        "vision_mode_standard_unavailable",
    ),
    VisionModeSpec(
        VISION_MODE_PROFESSIONAL_BETA,
        "vision_mode_professional_beta",
        "ultralytics-yolo26-pose-cuda",
        "vision_mode_professional_unavailable",
    ),
)


PROFESSIONAL_MODEL_STEMS = ("yolo26l-pose", "yolo26x-pose")


def mode_spec(mode: str) -> VisionModeSpec:
    for spec in VISION_MODE_SPECS:
        if spec.mode == mode:
            return spec
    raise ValueError(f"unknown vision mode: {mode}")


def mode_available(
    mode: str,
    backend_factories: Mapping[str, Callable[[], object]],
) -> bool:
    mode_spec(mode)
    return mode in backend_factories


def professional_model_paths(
    *,
    model_path: Optional[os.PathLike[str] | str] = None,
) -> Tuple[Path, ...]:
    """Candidate professional weights, honouring the explicit override first."""
    configured = model_path or os.environ.get("ECHOPOSTURE_PROFESSIONAL_MODEL")
    if configured:
        return (Path(configured),)
    root = Path(__file__).resolve().parent / "models" / "pose"
    return tuple(root / f"{stem}.pt" for stem in PROFESSIONAL_MODEL_STEMS)


def probe_professional_support(
    torch_spec: object,
    *,
    model_path: Optional[os.PathLike[str] | str] = None,
) -> ModeAvailability:
    """Judge whether the professional tier is worth offering, without importing torch.

    Deep validation (``torch.cuda.is_available()``, driver age, real inference)
    happens in the backend's ``start()``; a failure there falls back visibly.
    """
    origin = getattr(torch_spec, "origin", None) if torch_spec is not None else None
    if not origin:
        return ModeAvailability(False, "vision_mode_pro_unavailable_no_cuda_torch")
    torch_lib = Path(origin).resolve().parent / "lib"
    try:
        cuda_runtime_present = any(torch_lib.glob("torch_cuda*.dll")) or any(
            torch_lib.glob("libtorch_cuda*.so*")
        )
    except OSError:
        cuda_runtime_present = False
    if not cuda_runtime_present:
        return ModeAvailability(False, "vision_mode_pro_unavailable_no_cuda_torch")

    system_root = os.environ.get("SystemRoot")
    if system_root and not (Path(system_root) / "System32" / "nvml.dll").is_file():
        return ModeAvailability(False, "vision_mode_pro_unavailable_no_driver")

    if not any(path.is_file() for path in professional_model_paths(model_path=model_path)):
        return ModeAvailability(False, "vision_mode_pro_unavailable_no_weights")
    return ModeAvailability(True)


def detect_mode_availability(
    *,
    model_path: Optional[os.PathLike[str] | str] = None,
    professional_model_path: Optional[os.PathLike[str] | str] = None,
    find_spec: Callable[[str], object] = importlib.util.find_spec,
) -> Mapping[str, ModeAvailability]:
    """Probe modes without importing torch, Ultralytics, MediaPipe, or CUDA."""
    root = Path(__file__).resolve().parent
    configured_model = model_path or os.environ.get("ECHOPOSTURE_STANDARD_MODEL")
    standard_model = Path(configured_model) if configured_model else root / "models" / "pose" / "yolo26n-pose.pt"

    def lookup(name: str) -> object:
        try:
            return find_spec(name)
        except (ImportError, ModuleNotFoundError, ValueError):
            return None

    compatibility_ok = lookup("cv2") is not None and lookup("mediapipe") is not None
    # torch and ultralytics are looked up once each and shared by both tiers, so
    # enabling the professional probe costs no extra module search.
    torch_spec = lookup("torch")
    ultralytics_ok = lookup("ultralytics") is not None
    standard_ok = torch_spec is not None and ultralytics_ok and standard_model.is_file()
    professional = (
        probe_professional_support(torch_spec, model_path=professional_model_path)
        if ultralytics_ok
        else ModeAvailability(False, "vision_mode_pro_unavailable_no_cuda_torch")
    )
    return {
        VISION_MODE_COMPATIBILITY: ModeAvailability(
            compatibility_ok,
            None if compatibility_ok else "vision_mode_compatibility_unavailable",
        ),
        VISION_MODE_STANDARD: ModeAvailability(
            standard_ok,
            None if standard_ok else "vision_mode_standard_unavailable",
        ),
        VISION_MODE_PROFESSIONAL_BETA: professional,
    }


def backend_name(backend: object) -> str:
    capabilities = getattr(backend, "capabilities", None)
    name = getattr(capabilities, "backend_name", None)
    return str(name) if name else backend.__class__.__name__


__all__ = [
    "PROFESSIONAL_MODEL_STEMS",
    "VISION_MODE_COMPATIBILITY",
    "VISION_MODE_PROFESSIONAL_BETA",
    "VISION_MODE_SPECS",
    "VISION_MODE_STANDARD",
    "ModeAvailability",
    "VisionModeSpec",
    "backend_name",
    "detect_mode_availability",
    "mode_available",
    "mode_spec",
    "probe_professional_support",
    "professional_model_paths",
]
