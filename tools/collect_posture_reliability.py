"""Collect a metrics-only two-anchor reliability report from a camera.

The command is intentionally explicit.  It never writes frames, face crops,
identity vectors, or video. It collects two equal numeric sample blocks with a
short transition between them. This reliability protocol is separate from the
production UI timing path.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
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
    runtime_noise_floor,
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
    split = frames // 2
    relaxed_prompted = False
    try:
        engine.start()
        print(
            f"Hold the preferred comfortable posture for {split} samples.",
            file=sys.stderr,
        )
        while samples < frames:
            if samples == split and not relaxed_prompted:
                relaxed_prompted = True
                print(
                    "Preferred block complete. Relax naturally; relaxed sampling starts in 1 second.",
                    file=sys.stderr,
                )
                time.sleep(1.0)
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
    ranges: dict[str, dict] = {}
    for name in sorted(set(preferred) & set(relaxed)):
        preferred_stats = preferred[name]
        relaxed_stats = relaxed[name]
        preferred_measurement = FeatureStatistics(**preferred_stats)
        relaxed_measurement = FeatureStatistics(**relaxed_stats)
        delta = abs(relaxed_stats["mean"] - preferred_stats["mean"])
        mdc_floor = max(preferred_stats["mdc"], relaxed_stats["mdc"])
        single_observation_noise = runtime_noise_floor(
            preferred_measurement,
            relaxed_measurement,
            policy,
            name,
        )
        response_scale = (
            policy.runtime_angle_response_scale_deg
            if name in {"shoulder_asymmetry_deg", "trunk_lean_deg"}
            else policy.runtime_ratio_response_scale
        )
        watch_change = single_observation_noise + policy.watch_enter * response_scale
        alert_change = single_observation_noise + policy.alert_enter * response_scale
        ranges[name] = {
            "anchor_delta": delta,
            "normal_range_lower": min(preferred_stats["mean"], relaxed_stats["mean"]),
            "normal_range_upper": max(preferred_stats["mean"], relaxed_stats["mean"]),
            "noise_floor_mdc": mdc_floor,
            "single_observation_noise_floor": single_observation_noise,
            "anchor_delta_within_runtime_noise": delta <= single_observation_noise,
            "response_scale": response_scale,
            "watch_enter_outside_range": watch_change,
            "alert_enter_outside_range": alert_change,
            "watch_change_below_mdc": watch_change <= mdc_floor,
            "watch_change_below_runtime_noise": watch_change <= single_observation_noise,
            "note": (
                "Anchor separation is descriptive only and never gates calibration; "
                "both anchors define the accepted normal range."
            ),
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
        "anchor_ranges": ranges,
        "policy": {
            "watch_enter": policy.watch_enter,
            "alert_enter": policy.alert_enter,
            "critical_deviation": policy.severe_deviation,
            "runtime_noise_std_multiplier": policy.runtime_noise_std_multiplier,
            "runtime_ratio_noise_floor": policy.runtime_ratio_noise_floor,
            "runtime_angle_noise_floor_deg": policy.runtime_angle_noise_floor_deg,
            "runtime_ratio_response_scale": policy.runtime_ratio_response_scale,
            "runtime_angle_response_scale_deg": policy.runtime_angle_response_scale_deg,
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
