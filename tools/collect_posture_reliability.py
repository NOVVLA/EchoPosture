"""Collect a metrics-only two-anchor reliability report from a camera.

The command is intentionally explicit.  It never writes frames, face crops,
identity vectors, or video.  The first 40 percent of samples are treated as
the preferred anchor and the remainder as the relaxed anchor; keep the first
part comfortable and the second part naturally relaxed while running it.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime
from pathlib import Path

import cv2
import mediapipe as mp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from posture_science import (  # noqa: E402
    CALIBRATION_FEATURES,
    FeatureStatistics,
    PosturePolicy,
    measurement_values,
)
from vision_test import VisionEngine  # noqa: E402


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    return {
        name: getattr(FeatureStatistics.from_values(values), name)
        for name in ("mean", "std", "n", "sem", "mdc", "cv")
    }


def collect(frames: int, camera_id: int, width: int, height: int) -> dict:
    if frames < 10:
        raise ValueError("--frames must be at least 10")
    engine = VisionEngine(camera_id=camera_id, width=width, height=height)
    buckets: dict[str, dict[str, list[float]]] = {
        "preferred": {name: [] for name in CALIBRATION_FEATURES},
        "relaxed": {name: [] for name in CALIBRATION_FEATURES},
    }
    dropped_frames = 0
    samples = 0
    split = max(1, round(frames * 0.4))
    try:
        engine.start()
        while samples < frames:
            try:
                sample = engine.read_sample()
            except Exception:
                dropped_frames += 1
                if dropped_frames > frames:
                    raise
                continue
            bucket = "preferred" if samples < split else "relaxed"
            for name, value in measurement_values(sample).items():
                if name in buckets[bucket]:
                    buckets[bucket][name].append(float(value))
            samples += 1
    finally:
        engine.close()

    preferred = {name: _stats(values) for name, values in buckets["preferred"].items() if values}
    relaxed = {name: _stats(values) for name, values in buckets["relaxed"].items() if values}
    policy = PosturePolicy()
    separation: dict[str, dict] = {}
    for name in sorted(set(preferred) & set(relaxed)):
        preferred_stats = preferred[name]
        relaxed_stats = relaxed[name]
        delta = abs(relaxed_stats["mean"] - preferred_stats["mean"])
        noise_floor = max(preferred_stats["mdc"], relaxed_stats["mdc"])
        policy_change = delta * policy.watch_enter
        separation[name] = {
            "anchor_delta": delta,
            "noise_floor_mdc": noise_floor,
            "watch_policy_change": policy_change,
            "watch_change_below_mdc": policy_change <= noise_floor,
        }

    return {
        "created_at": datetime.now().astimezone().isoformat(),
        "metadata": {
            "hardware": platform.platform(),
            "python": sys.version.split()[0],
            "opencv": cv2.__version__,
            "mediapipe": getattr(mp, "__version__", "unknown"),
            "backend": "mediapipe-compatibility",
            "camera_id": camera_id,
            "resolution": {"width": width, "height": height},
            "model": "MediaPipe Pose model_complexity=0 + Face Mesh refine_landmarks",
        },
        "samples": {
            "requested": frames,
            "captured": samples,
            "preferred": min(split, samples),
            "relaxed": max(0, samples - split),
            "dropped": dropped_frames,
        },
        "preferred": preferred,
        "relaxed": relaxed,
        "anchor_separation": separation,
        "policy": {
            "watch_enter": policy.watch_enter,
            "alert_enter": policy.alert_enter,
            "critical_deviation": policy.severe_deviation,
            "note": "Product interaction parameters, not physiological standards.",
        },
        "unverified_items": [
            "external clinical validity and medical angle measurement",
            "repeatability across users, cameras, resolutions, and lighting",
            "effect of reminders on user comfort and adherence",
        ],
        "storage": "Numeric report only; no frames, crops, identity data, or vectors are saved.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=200)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = collect(args.frames, args.camera, args.width, args.height)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output is None:
        print(encoded)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
        print(f"WROTE NUMERIC RELIABILITY REPORT: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
