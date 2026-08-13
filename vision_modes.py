"""Product contract for selectable vision modes and backend availability."""

from __future__ import annotations

from dataclasses import dataclass
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


VISION_MODE_SPECS: Tuple[VisionModeSpec, ...] = (
    VisionModeSpec(
        VISION_MODE_COMPATIBILITY,
        "vision_mode_compatibility",
        "mediapipe-compatibility",
    ),
    VisionModeSpec(
        VISION_MODE_STANDARD,
        "vision_mode_standard",
        "yolo26n-pose-onnx",
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


def backend_name(backend: object) -> str:
    capabilities = getattr(backend, "capabilities", None)
    name = getattr(capabilities, "backend_name", None)
    return str(name) if name else backend.__class__.__name__


__all__ = [
    "VISION_MODE_COMPATIBILITY",
    "VISION_MODE_PROFESSIONAL_BETA",
    "VISION_MODE_SPECS",
    "VISION_MODE_STANDARD",
    "VisionModeSpec",
    "backend_name",
    "mode_available",
    "mode_spec",
]
