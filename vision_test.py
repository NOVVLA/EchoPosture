"""
EchoPosture - Step 1 vision sensing and posture decision test.

This script silently reads the webcam and prints:
1. Interpupillary pixel distance from MediaPipe Face Mesh iris landmarks.
2. Shoulder height difference from MediaPipe Pose landmarks.
3. A minimal GOOD/BAD/UNKNOWN posture decision after calibration.

No camera preview window is opened. Press Ctrl+C to stop.
"""

from __future__ import annotations

import argparse
import math
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional, Tuple

import cv2
import mediapipe as mp


Point = Tuple[float, float]


LEFT_IRIS = (468, 469, 470, 471, 472)
RIGHT_IRIS = (473, 474, 475, 476, 477)
NOSE = 0
LEFT_SHOULDER = 11
RIGHT_SHOULDER = 12


@dataclass(frozen=True)
class VisionSample:
    timestamp: datetime
    interpupillary_px: Optional[float]
    shoulder_diff_px: Optional[float]
    signed_shoulder_diff_px: Optional[float]
    face_detected: bool
    pose_detected: bool
    left_eye_center: Optional[Point] = None
    right_eye_center: Optional[Point] = None
    nose_point: Optional[Point] = None
    left_shoulder_point: Optional[Point] = None
    right_shoulder_point: Optional[Point] = None
    shoulder_center: Optional[Point] = None


@dataclass(frozen=True)
class PostureDecision:
    status: str
    reason: str
    calibrated: bool


@dataclass(frozen=True)
class PostureBaseline:
    interpupillary_px: Optional[float] = None
    signed_shoulder_diff_px: Optional[float] = None


class PostureAnalyzer:
    def __init__(
        self,
        calibration_samples: int = 8,
        too_close_ratio: float = 1.25,
        shoulder_threshold_px: float = 28.0,
        baseline: Optional[PostureBaseline] = None,
        auto_calibrate: bool = True,
    ) -> None:
        self.calibration_samples = max(1, calibration_samples)
        self.too_close_ratio = too_close_ratio
        self.shoulder_threshold_px = shoulder_threshold_px
        self.baseline = baseline
        self.auto_calibrate = auto_calibrate
        self._pupil_calibration_values: List[float] = []
        self._shoulder_calibration_values: List[float] = []

    @property
    def calibrated(self) -> bool:
        return self.baseline is not None and (
            self.baseline.interpupillary_px is not None
            or self.baseline.signed_shoulder_diff_px is not None
        )

    def evaluate(self, sample: VisionSample) -> PostureDecision:
        if self.auto_calibrate:
            self._update_baseline(sample)
        if self.baseline is None:
            if not self.auto_calibrate:
                return PostureDecision("NEEDS_CALIB", "press_calibrate", False)
            return PostureDecision("UNKNOWN", "no_usable_metrics", False)

        active_metrics = []
        missing_metrics = []
        reasons = []

        if self.baseline.interpupillary_px is None:
            missing_metrics.append("face_baseline")
        elif sample.interpupillary_px is None:
            missing_metrics.append("face")
        else:
            active_metrics.append("face")
            too_close_limit = self.baseline.interpupillary_px * self.too_close_ratio
            if sample.interpupillary_px > too_close_limit:
                reasons.append("too_close")

        if self.baseline.signed_shoulder_diff_px is None:
            missing_metrics.append("shoulder_baseline")
        elif sample.signed_shoulder_diff_px is None:
            missing_metrics.append("shoulder")
        else:
            active_metrics.append("shoulder")
            shoulder_delta = abs(
                sample.signed_shoulder_diff_px - self.baseline.signed_shoulder_diff_px
            )
            if shoulder_delta > self.shoulder_threshold_px:
                reasons.append("shoulder_tilt")

        if not active_metrics:
            calibration_status = self._calibration_status()
            if calibration_status:
                return PostureDecision("CALIBRATING", calibration_status, False)
            return PostureDecision("UNKNOWN", ",".join(missing_metrics), self.calibrated)

        if reasons:
            return PostureDecision("BAD", ",".join(reasons), self.calibrated)

        if missing_metrics:
            return PostureDecision(
                "GOOD_PART",
                f"{'+'.join(active_metrics)}_within_baseline;"
                f"missing={'+'.join(missing_metrics)}",
                self.calibrated,
            )
        return PostureDecision("GOOD", "within_baseline", self.calibrated)

    def set_baseline_from_sample(self, sample: VisionSample) -> bool:
        if sample.interpupillary_px is None and sample.signed_shoulder_diff_px is None:
            return False

        self.baseline = PostureBaseline(
            interpupillary_px=sample.interpupillary_px,
            signed_shoulder_diff_px=sample.signed_shoulder_diff_px,
        )
        self._pupil_calibration_values.clear()
        self._shoulder_calibration_values.clear()
        return True

    def reset_baseline(self) -> None:
        self.baseline = None
        self._pupil_calibration_values.clear()
        self._shoulder_calibration_values.clear()

    def _update_baseline(self, sample: VisionSample) -> None:
        pupil_baseline = self.baseline.interpupillary_px if self.baseline else None
        shoulder_baseline = self.baseline.signed_shoulder_diff_px if self.baseline else None

        if pupil_baseline is None and sample.interpupillary_px is not None:
            self._pupil_calibration_values.append(sample.interpupillary_px)
            if len(self._pupil_calibration_values) >= self.calibration_samples:
                pupil_baseline = sum(self._pupil_calibration_values) / len(
                    self._pupil_calibration_values
                )

        if shoulder_baseline is None and sample.signed_shoulder_diff_px is not None:
            self._shoulder_calibration_values.append(sample.signed_shoulder_diff_px)
            if len(self._shoulder_calibration_values) >= self.calibration_samples:
                shoulder_baseline = sum(self._shoulder_calibration_values) / len(
                    self._shoulder_calibration_values
                )

        if pupil_baseline is not None or shoulder_baseline is not None:
            self.baseline = PostureBaseline(
                interpupillary_px=pupil_baseline,
                signed_shoulder_diff_px=shoulder_baseline,
            )

    def _calibration_status(self) -> str:
        parts = []
        if self.baseline is None or self.baseline.interpupillary_px is None:
            parts.append(
                f"face={len(self._pupil_calibration_values)}/{self.calibration_samples}"
            )
        if self.baseline is None or self.baseline.signed_shoulder_diff_px is None:
            parts.append(
                f"shoulder={len(self._shoulder_calibration_values)}/{self.calibration_samples}"
            )
        return ",".join(parts)


class VisionEngine:
    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        min_detection_confidence: float = 0.6,
        min_tracking_confidence: float = 0.6,
    ) -> None:
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self._cap: Optional[cv2.VideoCapture] = None

        self._mp_face_mesh = mp.solutions.face_mesh
        self._mp_pose = mp.solutions.pose
        self._face_mesh = self._mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._pose = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            smooth_landmarks=True,
            enable_segmentation=False,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

    def start(self) -> None:
        cap = cv2.VideoCapture(self.camera_id, cv2.CAP_DSHOW)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, 15)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            raise RuntimeError(f"Cannot open camera #{self.camera_id}.")

        self._cap = cap

    def set_capture_fps(self, fps: float) -> None:
        if self._cap is not None and fps > 0:
            self._cap.set(cv2.CAP_PROP_FPS, fps)

    def read_frame_sample(self):
        if self._cap is None:
            raise RuntimeError("VisionEngine.start() must be called first.")

        ok, frame = self._cap.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read a frame from the camera.")

        frame = cv2.flip(frame, 1)
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        frame_h, frame_w = frame.shape[:2]

        face_result = self._face_mesh.process(frame_rgb)
        pose_result = self._pose.process(frame_rgb)

        left_eye_center, right_eye_center = self._measure_eye_centers(
            face_result, frame_w, frame_h
        )
        interpupillary_px = None
        if left_eye_center is not None and right_eye_center is not None:
            interpupillary_px = math.dist(left_eye_center, right_eye_center)

        pose_values = self._measure_pose_points(pose_result, frame_w, frame_h)

        signed_shoulder_diff_px = None
        shoulder_diff_px = None
        nose_point = None
        left_shoulder_point = None
        right_shoulder_point = None
        shoulder_center = None
        if pose_values is not None:
            (
                signed_shoulder_diff_px,
                nose_point,
                left_shoulder_point,
                right_shoulder_point,
                shoulder_center,
            ) = pose_values
            shoulder_diff_px = abs(signed_shoulder_diff_px)

        sample = VisionSample(
            timestamp=datetime.now(),
            interpupillary_px=interpupillary_px,
            shoulder_diff_px=shoulder_diff_px,
            signed_shoulder_diff_px=signed_shoulder_diff_px,
            face_detected=interpupillary_px is not None,
            pose_detected=shoulder_diff_px is not None,
            left_eye_center=left_eye_center,
            right_eye_center=right_eye_center,
            nose_point=nose_point,
            left_shoulder_point=left_shoulder_point,
            right_shoulder_point=right_shoulder_point,
            shoulder_center=shoulder_center,
        )
        return frame, sample

    def read_sample(self) -> VisionSample:
        _frame, sample = self.read_frame_sample()
        return sample

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._face_mesh.close()
        self._pose.close()

    @staticmethod
    def _landmark_center(landmarks: Iterable, indexes: Iterable[int], width: int, height: int) -> Point:
        points = [landmarks[index] for index in indexes]
        x = sum(point.x for point in points) / len(points) * width
        y = sum(point.y for point in points) / len(points) * height
        return x, y

    def _measure_eye_centers(
        self, face_result, width: int, height: int
    ) -> Tuple[Optional[Point], Optional[Point]]:
        if not face_result.multi_face_landmarks:
            return None, None

        landmarks = face_result.multi_face_landmarks[0].landmark
        if len(landmarks) <= max(*LEFT_IRIS, *RIGHT_IRIS):
            return None, None

        left_center = self._landmark_center(landmarks, LEFT_IRIS, width, height)
        right_center = self._landmark_center(landmarks, RIGHT_IRIS, width, height)
        return left_center, right_center

    @staticmethod
    def _pose_point(landmark, width: int, height: int) -> Point:
        return landmark.x * width, landmark.y * height

    def _measure_pose_points(
        self, pose_result, width: int, height: int
    ) -> Optional[Tuple[float, Optional[Point], Point, Point, Point]]:
        if not pose_result.pose_landmarks:
            return None

        landmarks = pose_result.pose_landmarks.landmark
        left = landmarks[LEFT_SHOULDER]
        right = landmarks[RIGHT_SHOULDER]

        if left.visibility < 0.5 or right.visibility < 0.5:
            return None

        signed_shoulder_diff = (left.y - right.y) * height
        left_point = self._pose_point(left, width, height)
        right_point = self._pose_point(right, width, height)
        shoulder_center = (
            (left_point[0] + right_point[0]) / 2.0,
            (left_point[1] + right_point[1]) / 2.0,
        )

        nose = landmarks[NOSE]
        nose_point = None
        if nose.visibility >= 0.5:
            nose_point = self._pose_point(nose, width, height)

        return signed_shoulder_diff, nose_point, left_point, right_point, shoulder_center


def format_value(value: Optional[float], unit: str = "px") -> str:
    if value is None:
        return "--"
    return f"{value:7.2f}{unit}"


def format_baseline(baseline: Optional[PostureBaseline]) -> str:
    if baseline is None:
        return "--"
    pupil = (
        f"{baseline.interpupillary_px:.2f}px"
        if baseline.interpupillary_px is not None
        else "--"
    )
    shoulder = (
        f"{baseline.signed_shoulder_diff_px:.2f}px"
        if baseline.signed_shoulder_diff_px is not None
        else "--"
    )
    return (
        f"pupil={pupil}, "
        f"shoulder={shoulder}"
    )


def run(
    camera_id: int,
    fps: float,
    width: int,
    height: int,
    calibration_samples: int,
    too_close_ratio: float,
    shoulder_threshold_px: float,
    max_samples: Optional[int],
) -> int:
    if fps <= 0:
        raise ValueError("fps must be greater than 0.")

    engine = VisionEngine(camera_id=camera_id, width=width, height=height)
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, request_stop)

    analyzer = PostureAnalyzer(
        calibration_samples=calibration_samples,
        too_close_ratio=too_close_ratio,
        shoulder_threshold_px=shoulder_threshold_px,
    )
    interval = 1.0 / fps
    engine.start()
    print("EchoPosture vision test started. Press Ctrl+C to stop.")
    print(
        "time      face  pupil_dist_px  pose  shoulder_abs_px  "
        "shoulder_signed_px  posture      reason"
    )

    try:
        sample_count = 0
        baseline_reported = False
        while not stop_requested:
            loop_start = time.perf_counter()
            sample = engine.read_sample()
            decision = analyzer.evaluate(sample)
            if decision.calibrated and not baseline_reported:
                print(f"Baseline locked: {format_baseline(analyzer.baseline)}", flush=True)
                baseline_reported = True

            print(
                f"{sample.timestamp:%H:%M:%S}  "
                f"{'yes ' if sample.face_detected else 'no  '}  "
                f"{format_value(sample.interpupillary_px):>13}  "
                f"{'yes ' if sample.pose_detected else 'no  '}  "
                f"{format_value(sample.shoulder_diff_px):>15}  "
                f"{format_value(sample.signed_shoulder_diff_px):>18}  "
                f"{decision.status:<11}  "
                f"{decision.reason}",
                flush=True,
            )

            sample_count += 1
            if max_samples is not None and sample_count >= max_samples:
                break

            elapsed = time.perf_counter() - loop_start
            time.sleep(max(0.0, interval - elapsed))
    finally:
        engine.close()
        cv2.destroyAllWindows()

    print("Vision test stopped.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EchoPosture vision sensing test.")
    parser.add_argument("--camera", type=int, default=0, help="Camera index. Default: 0")
    parser.add_argument("--fps", type=float, default=4.0, help="Detection frequency. Default: 4")
    parser.add_argument("--width", type=int, default=640, help="Capture width. Default: 640")
    parser.add_argument("--height", type=int, default=480, help="Capture height. Default: 480")
    parser.add_argument(
        "--calibration-samples",
        type=int,
        default=8,
        help="Valid samples used as the initial good-posture baseline. Default: 8",
    )
    parser.add_argument(
        "--too-close-ratio",
        type=float,
        default=1.25,
        help="BAD if pupil distance is greater than baseline times this ratio. Default: 1.25",
    )
    parser.add_argument(
        "--shoulder-threshold-px",
        type=float,
        default=28.0,
        help="BAD if signed shoulder height drifts from baseline by more than this. Default: 28",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Stop after this many processed samples. Default: run until Ctrl+C",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        raise SystemExit(
            run(
                args.camera,
                args.fps,
                args.width,
                args.height,
                args.calibration_samples,
                args.too_close_ratio,
                args.shoulder_threshold_px,
                args.max_samples,
            )
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
