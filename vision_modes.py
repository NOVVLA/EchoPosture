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
        "yolo26-pose-tensorrt",
        "vision_mode_professional_unavailable",
    ),
)


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


def detect_mode_availability(
    *,
    model_path: Optional[os.PathLike[str] | str] = None,
    find_spec: Callable[[str], object] = importlib.util.find_spec,
) -> Mapping[str, ModeAvailability]:
    """Probe modes without importing torch, Ultralytics, MediaPipe, or TensorRT."""
    root = Path(__file__).resolve().parent
    configured_model = model_path or os.environ.get("ECHOPOSTURE_STANDARD_MODEL")
    standard_model = Path(configured_model) if configured_model else root / "models" / "pose" / "yolo26n-pose.pt"

    def installed(name: str) -> bool:
        try:
            return find_spec(name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            return False

    compatibility_ok = installed("cv2") and installed("mediapipe")
    standard_ok = installed("torch") and installed("ultralytics") and standard_model.is_file()
    return {
        VISION_MODE_COMPATIBILITY: ModeAvailability(
            compatibility_ok,
            None if compatibility_ok else "vision_mode_compatibility_unavailable",
        ),
        VISION_MODE_STANDARD: ModeAvailability(
            standard_ok,
            None if standard_ok else "vision_mode_standard_unavailable",
        ),
        # TensorRT alone is not enough: no professional posture backend exists yet.
        VISION_MODE_PROFESSIONAL_BETA: ModeAvailability(
            False,
            "vision_mode_professional_unavailable",
        ),
    }


def backend_name(backend: object) -> str:
    capabilities = getattr(backend, "capabilities", None)
    name = getattr(capabilities, "backend_name", None)
    return str(name) if name else backend.__class__.__name__


__all__ = [
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
]
