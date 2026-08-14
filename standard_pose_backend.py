"""YOLO26 pose backend for the Debug UI standard vision mode.

The backend deliberately exposes body-pose observations only. COCO nose,
eye, and ear keypoints remain body-pose landmarks; they are never promoted to
face detections, FaceMesh landmarks, identity templates, or embeddings.
"""

from __future__ import annotations

import math
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

import cv2
import numpy as np

from vision_backend import (
    Keypoint,
    PersonObservation,
    PostureFeatureExtractor,
    PostureFeatures,
    VisionCapabilities,
)
from vision_test import CameraBlackFrameError, CameraPermissionError, Point, VisionSample


COCO_NOSE = 0
COCO_LEFT_EYE = 1
COCO_RIGHT_EYE = 2
COCO_LEFT_EAR = 3
COCO_RIGHT_EAR = 4
COCO_LEFT_SHOULDER = 5
COCO_RIGHT_SHOULDER = 6
COCO_LEFT_HIP = 11
COCO_RIGHT_HIP = 12
COCO_KEYPOINT_COUNT = 17

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent / "models" / "pose" / "yolo26n-pose.pt"


def _as_array(value) -> np.ndarray:
    if value is None:
        return np.empty((0,), dtype=float)
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    numpy_method = getattr(value, "numpy", None)
    if callable(numpy_method):
        value = numpy_method()
    return np.asarray(value)


def _midpoint(first: Point, second: Point) -> Point:
    return (first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0


class StandardPoseBackend:
    """CPU YOLO26n-pose backend with no face or identity processing."""

    capabilities = VisionCapabilities(
        supports_multi_person_pose=True,
        supports_gpu=False,
        supports_world_coordinates=False,
        supports_face_bbox=False,
        backend_name="ultralytics-yolo26n-pose-cpu",
    )

    BLACK_FRAME_MEAN_LIMIT = 2.0
    BLACK_FRAME_VISIBLE_THRESHOLD = 8
    BLACK_FRAME_VISIBLE_RATIO_LIMIT = 0.001
    EXTREME_BLACK_MEAN_LIMIT = 0.5
    EXTREME_BLACK_MAX_LIMIT = 2.0
    BLACK_FRAME_WARNING_FRAMES = 3

    def __init__(
        self,
        camera_id: int = 0,
        width: int = 640,
        height: int = 480,
        capture_fps: float = 4.0,
        model_path: Optional[os.PathLike[str] | str] = None,
        confidence: float = 0.35,
        keypoint_confidence: float = 0.30,
        device: str = "cpu",
        *,
        model=None,
        capture_factory: Optional[Callable[[int], object]] = None,
    ) -> None:
        configured_path = model_path or os.environ.get("ECHOPOSTURE_STANDARD_MODEL")
        self.model_path = Path(configured_path) if configured_path else DEFAULT_MODEL_PATH
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self._capture_fps = max(1.0, float(capture_fps))
        self.confidence = max(0.0, min(1.0, float(confidence)))
        self.keypoint_confidence = max(0.0, min(1.0, float(keypoint_confidence)))
        self.device = device
        self._model = model
        self._injected_model = model is not None
        self._capture_factory = capture_factory or self._open_capture
        self._capture = None
        self._last_observations: Tuple[PersonObservation, ...] = ()
        self._black_frame_count = 0

    @staticmethod
    def _open_capture(camera_id: int):
        return cv2.VideoCapture(camera_id, cv2.CAP_DSHOW)

    def start(self) -> None:
        if self._model is None:
            if not self.model_path.is_file():
                raise RuntimeError(
                    "Standard mode YOLO26n-pose model is missing. Place yolo26n-pose.pt at "
                    f"{self.model_path} or set ECHOPOSTURE_STANDARD_MODEL. "
                    "Automatic model downloads are disabled."
                )
            try:
                from ultralytics import YOLO
            except ImportError as exc:
                raise RuntimeError(
                    "YOLO26n-pose standard mode requires ultralytics==8.4.120. Install "
                    "requirements-standard.txt into the Python 3.11 runtime."
                ) from exc
            self._model = YOLO(str(self.model_path))

        self._validate_model_contract()

        self._capture = self._capture_factory(self.camera_id)
        if self._capture is None or not self._capture.isOpened():
            self.close()
            raise CameraPermissionError(
                f"Cannot open camera {self.camera_id}. Check Windows camera privacy settings."
            )
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._capture.set(cv2.CAP_PROP_FPS, self._capture_fps)
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _validate_model_contract(self) -> None:
        task = getattr(self._model, "task", None)
        if task != "pose":
            raise RuntimeError(
                "Standard mode requires a YOLO pose model; "
                f"the selected model reports task={task!r}."
            )
        model = getattr(self._model, "model", None)
        keypoint_shape = getattr(model, "kpt_shape", None)
        if list(keypoint_shape or ()) != [COCO_KEYPOINT_COUNT, 3]:
            raise RuntimeError(
                "Standard mode requires the COCO 17-keypoint pose layout [17, 3]; "
                f"the selected model reports kpt_shape={keypoint_shape!r}."
            )

    def read_frame_sample(self):
        if self._capture is None or self._model is None:
            raise RuntimeError("StandardPoseBackend.start() must be called first.")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError("Failed to read a frame from the camera.")
        self._check_frame_visibility(frame)
        frame = cv2.flip(frame, 1)
        timestamp = datetime.now()
        results = self._model.predict(
            source=frame,
            conf=self.confidence,
            device=self.device,
            verbose=False,
        )
        result = results[0] if results else None
        self._last_observations = self._observations_from_result(
            result,
            timestamp,
            frame.shape[1],
            frame.shape[0],
        )
        sample = self._sample_for_scene(timestamp, frame.shape[1], frame.shape[0])
        return frame, sample

    def read_sample(self) -> VisionSample:
        _frame, sample = self.read_frame_sample()
        return sample

    def _observations_from_result(
        self,
        result,
        timestamp: datetime,
        frame_width: int,
        frame_height: int,
    ) -> Tuple[PersonObservation, ...]:
        if result is None:
            return ()
        boxes = getattr(result, "boxes", None)
        keypoints_result = getattr(result, "keypoints", None)
        if boxes is None or keypoints_result is None:
            return ()
        boxes_xyxy = _as_array(getattr(boxes, "xyxy", None))
        box_confidences = _as_array(getattr(boxes, "conf", None)).reshape(-1)
        keypoint_data = _as_array(getattr(keypoints_result, "data", None))
        if boxes_xyxy.ndim != 2 or keypoint_data.ndim != 3:
            return ()
        count = min(len(boxes_xyxy), len(box_confidences), len(keypoint_data))
        observations = []
        for index in range(count):
            row = keypoint_data[index]
            if row.shape[0] < COCO_KEYPOINT_COUNT or row.shape[1] < 3:
                continue
            keypoints = tuple(
                Keypoint(float(point[0]), float(point[1]), float(point[2]))
                for point in row[:COCO_KEYPOINT_COUNT]
            )
            features = self._posture_features(keypoints, frame_width, frame_height)
            bbox = tuple(float(value) for value in boxes_xyxy[index][:4])
            observations.append(
                PersonObservation(
                    timestamp=timestamp,
                    detection_id=None,
                    bbox_xyxy=bbox,
                    body_keypoints=keypoints,
                    body_confidence=float(box_confidences[index]),
                    face_bbox_xyxy=None,
                    face_landmarks=None,
                    face_quality=None,
                    association_ambiguous=False,
                    posture_features=features,
                    face_embedding=None,
                )
            )
        return tuple(observations)

    def _posture_features(
        self,
        keypoints: Sequence[Keypoint],
        frame_width: int,
        frame_height: int,
    ) -> PostureFeatures:
        def point(index: int) -> Optional[Point]:
            keypoint = keypoints[index]
            if keypoint.confidence < self.keypoint_confidence:
                return None
            return keypoint.x, keypoint.y

        nose = point(COCO_NOSE)
        left_ear = point(COCO_LEFT_EAR)
        right_ear = point(COCO_RIGHT_EAR)
        left_shoulder = point(COCO_LEFT_SHOULDER)
        right_shoulder = point(COCO_RIGHT_SHOULDER)
        left_hip = point(COCO_LEFT_HIP)
        right_hip = point(COCO_RIGHT_HIP)

        shoulder_center = None
        signed_shoulder_diff = None
        shoulder_width = None
        if left_shoulder is not None and right_shoulder is not None:
            shoulder_center = _midpoint(left_shoulder, right_shoulder)
            signed_shoulder_diff = left_shoulder[1] - right_shoulder[1]
            shoulder_width = math.dist(left_shoulder, right_shoulder)

        hip_center = None
        torso_height = None
        trunk_lean = None
        if left_hip is not None and right_hip is not None:
            hip_center = _midpoint(left_hip, right_hip)
            if shoulder_center is not None:
                torso_height = math.dist(shoulder_center, hip_center)
                dx = shoulder_center[0] - hip_center[0]
                dy = hip_center[1] - shoulder_center[1]
                trunk_lean = math.degrees(math.atan2(dx, max(abs(dy), 1.0)))

        required_confidences = (
            keypoints[COCO_LEFT_SHOULDER].confidence,
            keypoints[COCO_RIGHT_SHOULDER].confidence,
        )
        return PostureFeatures(
            interpupillary_px=None,
            shoulder_diff_px=(
                abs(signed_shoulder_diff) if signed_shoulder_diff is not None else None
            ),
            signed_shoulder_diff_px=signed_shoulder_diff,
            shoulder_width_px=shoulder_width,
            trunk_lean_deg=trunk_lean,
            face_detected=False,
            pose_detected=shoulder_center is not None,
            frame_width=frame_width,
            frame_height=frame_height,
            nose_point=nose,
            left_shoulder_point=left_shoulder,
            right_shoulder_point=right_shoulder,
            shoulder_center=shoulder_center,
            left_hip_point=left_hip,
            right_hip_point=right_hip,
            hip_center=hip_center,
            torso_height_px=torso_height,
            left_ear_point=left_ear,
            right_ear_point=right_ear,
            face_quality=None,
            pose_quality=min(required_confidences),
            nose_confidence=keypoints[COCO_NOSE].confidence,
            left_ear_confidence=keypoints[COCO_LEFT_EAR].confidence,
            right_ear_confidence=keypoints[COCO_RIGHT_EAR].confidence,
            left_shoulder_confidence=keypoints[COCO_LEFT_SHOULDER].confidence,
            right_shoulder_confidence=keypoints[COCO_RIGHT_SHOULDER].confidence,
            left_hip_confidence=keypoints[COCO_LEFT_HIP].confidence,
            right_hip_confidence=keypoints[COCO_RIGHT_HIP].confidence,
            face_required_for_calibration=False,
        )

    def _sample_for_scene(
        self,
        timestamp: datetime,
        frame_width: int,
        frame_height: int,
    ) -> VisionSample:
        if len(self._last_observations) == 1:
            sample = PostureFeatureExtractor.to_sample(self._last_observations[0])
            return replace(sample, person_count=1)
        return VisionSample(
            timestamp=timestamp,
            interpupillary_px=None,
            shoulder_diff_px=None,
            signed_shoulder_diff_px=None,
            shoulder_width_px=None,
            trunk_lean_deg=None,
            face_detected=False,
            pose_detected=False,
            face_count=0,
            frame_width=frame_width,
            frame_height=frame_height,
            person_count=len(self._last_observations),
            face_required_for_calibration=False,
        )

    def observations_for_last_sample(self) -> Tuple[PersonObservation, ...]:
        return self._last_observations

    def set_capture_fps(self, fps: float) -> None:
        self._capture_fps = max(1.0, float(fps))
        if self._capture is not None:
            self._capture.set(cv2.CAP_PROP_FPS, self._capture_fps)

    def get_capture_fps(self) -> float:
        return self._capture_fps

    def _check_frame_visibility(self, frame) -> None:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_luma = float(gray.mean())
        max_luma = float(gray.max())
        visible_ratio = float((gray > self.BLACK_FRAME_VISIBLE_THRESHOLD).mean())
        almost_black = (
            mean_luma <= self.BLACK_FRAME_MEAN_LIMIT
            and visible_ratio <= self.BLACK_FRAME_VISIBLE_RATIO_LIMIT
        )
        extreme_black = (
            mean_luma <= self.EXTREME_BLACK_MEAN_LIMIT
            and max_luma <= self.EXTREME_BLACK_MAX_LIMIT
        )
        if not almost_black and not extreme_black:
            self._black_frame_count = 0
            return
        self._black_frame_count += 1
        if extreme_black or self._black_frame_count >= self.BLACK_FRAME_WARNING_FRAMES:
            raise CameraBlackFrameError(
                "Camera permission is available, but the camera is returning an "
                "all-black or nearly all-black image "
                f"(mean luma {mean_luma:.1f}, visible pixels {visible_ratio:.1%})."
            )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        if not self._injected_model:
            self._model = None
        self._last_observations = ()
        self._black_frame_count = 0


__all__ = ["DEFAULT_MODEL_PATH", "StandardPoseBackend"]
