"""Replay timestamped, metrics-only person observations through TargetManager."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from vision_backend import PersonObservation
from vision_tracking import TargetManager
from posture_science import ExposureAccumulator


REPLAY_EPOCH = datetime(2026, 1, 1)


@dataclass(frozen=True)
class ReplayFrameResult:
    line: int
    scenario: str
    timestamp_s: float
    state: str
    target_track_id: Optional[int]
    target_detection_id: Optional[int]
    person_count: int
    reason: str
    posture_status: Optional[str] = None
    posture_deviation: Optional[float] = None
    exposure_seconds: Optional[float] = None
    activity_state: Optional[str] = None


def _observation(payload: dict[str, Any], timestamp: datetime) -> PersonObservation:
    bbox = tuple(float(value) for value in payload["bbox_xyxy"])
    if len(bbox) != 4 or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        raise ValueError(f"invalid bbox_xyxy: {payload['bbox_xyxy']!r}")
    detection_id = payload.get("detection_id")
    if detection_id is not None:
        detection_id = int(detection_id)
    return PersonObservation(
        timestamp=timestamp,
        detection_id=detection_id,
        bbox_xyxy=bbox,
        body_keypoints=(),
        body_confidence=float(payload.get("body_confidence", 1.0)),
        face_bbox_xyxy=None,
        face_landmarks=None,
        face_quality=None,
        association_ambiguous=bool(payload.get("association_ambiguous", False)),
    )


def replay_lines(lines: Iterable[str]) -> tuple[ReplayFrameResult, ...]:
    manager = TargetManager()
    exposure = ExposureAccumulator()
    results: list[ReplayFrameResult] = []
    last_timestamp_s: Optional[float] = None
    locked_track_id: Optional[int] = None

    for line_number, raw_line in enumerate(lines, start=1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        payload = json.loads(raw_line)
        if payload.get("reset"):
            manager.reset()
            exposure.reset()
            last_timestamp_s = None
            locked_track_id = None

        timestamp_s = float(payload["timestamp_s"])
        if last_timestamp_s is not None and timestamp_s < last_timestamp_s:
            raise ValueError(f"line {line_number}: timestamp_s must be monotonic within a scenario")
        last_timestamp_s = timestamp_s
        timestamp = REPLAY_EPOCH + timedelta(seconds=timestamp_s)

        identity = payload.get("resolve_identity_before")
        if identity is not None:
            manager.resolve_identity(bool(identity))

        observations = tuple(
            _observation(item, timestamp) for item in payload.get("observations", ())
        )
        update = manager.update(observations, timestamp=timestamp)
        if payload.get("lock_target_after"):
            if not manager.lock_calibration_target():
                raise AssertionError(f"line {line_number}: target lock failed")
            locked_track_id = manager.target_track_id
            state = manager.state
        else:
            state = update.state

        if locked_track_id is not None and manager.target_track_id != locked_track_id:
            raise AssertionError(f"line {line_number}: target track changed silently")

        target_detection_id = (
            update.target_observation.detection_id
            if update.target_observation is not None
            else None
        )
        expected_state = payload.get("expected_state")
        if expected_state is not None and state != expected_state:
            raise AssertionError(
                f"line {line_number}: expected {expected_state}, got {state} ({update.reason})"
            )
        expected_detection_id = payload.get("expected_target_detection_id")
        if (
            "expected_target_detection_id" in payload
            and target_detection_id != expected_detection_id
        ):
            raise AssertionError(
                f"line {line_number}: expected target detection {expected_detection_id!r}, "
                f"got {target_detection_id!r}"
            )

        posture_status = None
        posture_deviation = None
        exposure_seconds = None
        activity_state = None
        if "posture_deviation" in payload:
            posture_deviation = float(payload["posture_deviation"])
            activity_state = str(payload.get("activity_state", "STATIC"))
            quality = float(payload.get("confidence", 1.0))
            paused = (
                activity_state == "MOVING"
                or bool(payload.get("camera_drift", False))
                or quality < exposure.policy.quality_floor
            )
            snapshot = exposure.update(
                timestamp,
                posture_deviation,
                paused=paused,
            )
            exposure_seconds = snapshot.exposure_seconds
            if payload.get("camera_drift"):
                posture_status = "UNKNOWN"
            elif activity_state == "MOVING":
                posture_status = "WATCH"
            elif quality < exposure.policy.quality_floor:
                posture_status = "UNKNOWN" if exposure_seconds == 0.0 else "WATCH"
            elif (
                exposure_seconds >= exposure.policy.critical_exposure_seconds
                and posture_deviation >= exposure.policy.severe_deviation
            ):
                posture_status = "CRITICAL"
            elif exposure_seconds >= exposure.policy.alert_exposure_seconds and snapshot.alert_active:
                posture_status = "BAD"
            elif snapshot.watch_active:
                posture_status = "WATCH"
            else:
                posture_status = "GOOD"

            expected_posture_status = payload.get("expected_posture_status")
            if expected_posture_status is not None and posture_status != expected_posture_status:
                raise AssertionError(
                    f"line {line_number}: expected posture {expected_posture_status}, "
                    f"got {posture_status}"
                )

        results.append(
            ReplayFrameResult(
                line=line_number,
                scenario=str(payload.get("scenario", "unnamed")),
                timestamp_s=timestamp_s,
                state=state,
                target_track_id=manager.target_track_id,
                target_detection_id=target_detection_id,
                person_count=update.person_count,
                reason=update.reason,
                posture_status=posture_status,
                posture_deviation=posture_deviation,
                exposure_seconds=exposure_seconds,
                activity_state=activity_state,
            )
        )
    return tuple(results)


def replay_file(path: Path) -> tuple[ReplayFrameResult, ...]:
    with path.open("r", encoding="utf-8") as handle:
        return replay_lines(handle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="JSONL observation replay")
    parser.add_argument("--json", action="store_true", help="print machine-readable results")
    args = parser.parse_args()

    results = replay_file(args.path)
    if args.json:
        print(json.dumps([asdict(result) for result in results], ensure_ascii=False))
    else:
        for result in results:
            print(
                f"{result.scenario} t={result.timestamp_s:.1f}s "
                f"state={result.state} target={result.target_track_id} "
                f"detection={result.target_detection_id} people={result.person_count}"
            )
        print(f"REPLAY PASSED: {len(results)} frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
