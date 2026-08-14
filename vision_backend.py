"""统一视觉后端契约和当前 MediaPipe 兼容适配器。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional, Protocol, Tuple

from vision_test import Point, VisionEngine, VisionSample

Timestamp = float | datetime


@dataclass(frozen=True)
class Keypoint:
    x: float
    y: float
    confidence: float = 1.0


@dataclass(frozen=True)
class PostureFeatures:
    interpupillary_px: Optional[float]
    shoulder_diff_px: Optional[float]
    signed_shoulder_diff_px: Optional[float]
    shoulder_width_px: Optional[float]
    trunk_lean_deg: Optional[float]
    face_detected: bool
    pose_detected: bool
    frame_width: Optional[int] = None
    frame_height: Optional[int] = None
    left_eye_center: Optional[Point] = None
    right_eye_center: Optional[Point] = None
    nose_point: Optional[Point] = None
    left_shoulder_point: Optional[Point] = None
    right_shoulder_point: Optional[Point] = None
    shoulder_center: Optional[Point] = None
    left_hip_point: Optional[Point] = None
    right_hip_point: Optional[Point] = None
    hip_center: Optional[Point] = None
    face_nose_point: Optional[Point] = None
    face_left_mouth_point: Optional[Point] = None
    face_right_mouth_point: Optional[Point] = None
    head_turn_ratio: Optional[float] = None
    torso_height_px: Optional[float] = None
    left_ear_point: Optional[Point] = None
    right_ear_point: Optional[Point] = None
    face_quality: Optional[float] = None
    pose_quality: Optional[float] = None
    nose_confidence: Optional[float] = None
    left_ear_confidence: Optional[float] = None
    right_ear_confidence: Optional[float] = None
    left_shoulder_confidence: Optional[float] = None
    right_shoulder_confidence: Optional[float] = None
    left_hip_confidence: Optional[float] = None
    right_hip_confidence: Optional[float] = None
    target_motion: Optional[float] = None
    activity_state: Optional[str] = None
    camera_drift: bool = False
    face_required_for_calibration: bool = True


@dataclass(frozen=True)
class PersonObservation:
    """Model-independent observation for one candidate person."""

    timestamp: Timestamp
    detection_id: Optional[int]
    bbox_xyxy: Tuple[float, float, float, float]
    body_keypoints: Tuple[Keypoint, ...]
    body_confidence: float
    face_bbox_xyxy: Optional[Tuple[float, float, float, float]]
    face_landmarks: Optional[Tuple[Point, ...]]
    face_quality: Optional[float]
    association_ambiguous: bool = False
    posture_features: Optional[PostureFeatures] = None
    # Optional in-memory identity vector supplied by a future face backend.
    # It is never serialized by the compatibility adapter.
    face_embedding: Optional[Tuple[float, ...]] = None


@dataclass(frozen=True)
class VisionCapabilities:
    supports_multi_person_pose: bool
    supports_gpu: bool
    supports_world_coordinates: bool
    supports_face_bbox: bool
    backend_name: str


class VisionBackend(Protocol):
    capabilities: VisionCapabilities

    def start(self) -> None: ...

    def read_sample(self) -> VisionSample: ...

    def observations_for_last_sample(self) -> Tuple[PersonObservation, ...]: ...

    def set_capture_fps(self, fps: float) -> None: ...

    def get_capture_fps(self) -> float: ...

    def close(self) -> None: ...


class PostureFeatureExtractor:
    """Convert one target observation into the legacy analyzer input."""

    @staticmethod
    def to_sample(observation: PersonObservation) -> VisionSample:
        features = observation.posture_features
        if features is None:
            return VisionSample(
                timestamp=observation.timestamp,
                interpupillary_px=None,
                shoulder_diff_px=None,
                signed_shoulder_diff_px=None,
                shoulder_width_px=None,
                trunk_lean_deg=None,
                face_detected=False,
                pose_detected=False,
                face_count=0,
                face_required_for_calibration=True,
            )
        return VisionSample(
            timestamp=observation.timestamp,
            interpupillary_px=features.interpupillary_px,
            shoulder_diff_px=features.shoulder_diff_px,
            signed_shoulder_diff_px=features.signed_shoulder_diff_px,
            shoulder_width_px=features.shoulder_width_px,
            trunk_lean_deg=features.trunk_lean_deg,
            face_detected=features.face_detected,
            pose_detected=features.pose_detected,
            face_count=1 if features.face_detected else 0,
            frame_width=features.frame_width,
            frame_height=features.frame_height,
            left_eye_center=features.left_eye_center,
            right_eye_center=features.right_eye_center,
            nose_point=features.nose_point,
            left_shoulder_point=features.left_shoulder_point,
            right_shoulder_point=features.right_shoulder_point,
            shoulder_center=features.shoulder_center,
            left_hip_point=features.left_hip_point,
            right_hip_point=features.right_hip_point,
            hip_center=features.hip_center,
            face_nose_point=features.face_nose_point,
            face_left_mouth_point=features.face_left_mouth_point,
            face_right_mouth_point=features.face_right_mouth_point,
            head_turn_ratio=features.head_turn_ratio,
            torso_height_px=features.torso_height_px,
            left_ear_point=features.left_ear_point,
            right_ear_point=features.right_ear_point,
            face_quality=features.face_quality,
            pose_quality=features.pose_quality,
            nose_confidence=features.nose_confidence,
            left_ear_confidence=features.left_ear_confidence,
            right_ear_confidence=features.right_ear_confidence,
            left_shoulder_confidence=features.left_shoulder_confidence,
            right_shoulder_confidence=features.right_shoulder_confidence,
            left_hip_confidence=features.left_hip_confidence,
            right_hip_confidence=features.right_hip_confidence,
            target_motion=features.target_motion,
            activity_state=features.activity_state,
            camera_drift=features.camera_drift,
            face_required_for_calibration=features.face_required_for_calibration,
        )


def _bbox_from_points(points: Tuple[Point, ...], pad_ratio: float = 0.08) -> Tuple[float, float, float, float]:
    if not points:
        return 0.0, 0.0, 0.0, 0.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    width = max(1.0, right - left)
    height = max(1.0, bottom - top)
    return (
        left - width * pad_ratio,
        top - height * pad_ratio,
        right + width * pad_ratio,
        bottom + height * pad_ratio,
    )


def _point_inside_expanded_bbox(point: Point, bbox: Tuple[float, float, float, float]) -> bool:
    left, top, right, bottom = bbox
    width = max(1.0, right - left)
    height = max(1.0, bottom - top)
    return (
        left - width * 0.45 <= point[0] <= right + width * 0.45
        and top - height * 1.25 <= point[1] <= bottom + height * 0.35
    )


def observation_from_sample(sample: VisionSample) -> Tuple[PersonObservation, ...]:
    """Convert the single-person MediaPipe sample without inventing a second body."""

    body_points = tuple(
        point
        for point in (
            sample.nose_point,
            sample.left_ear_point,
            sample.right_ear_point,
            sample.left_shoulder_point,
            sample.right_shoulder_point,
            sample.left_hip_point,
            sample.right_hip_point,
        )
        if point is not None
    )
    face_points = tuple(
        point
        for point in (
            sample.left_eye_center,
            sample.right_eye_center,
            sample.face_nose_point,
            sample.face_left_mouth_point,
            sample.face_right_mouth_point,
        )
        if point is not None
    )
    if not body_points and not face_points:
        return ()

    body_bbox = _bbox_from_points(body_points or face_points)
    face_bbox = _bbox_from_points(face_points, pad_ratio=0.2) if face_points else None
    ambiguous = sample.face_count > 1
    if not ambiguous and sample.face_detected and sample.pose_detected:
        # A single pose and a single face are not enough by themselves: the
        # face anchor must fall within the body's expanded spatial envelope.
        ambiguous = (
            not body_points
            or sample.face_nose_point is None
            or not _point_inside_expanded_bbox(sample.face_nose_point, body_bbox)
        )

    keypoints = tuple(
        Keypoint(point[0], point[1], confidence)
        for point, confidence in (
            (sample.nose_point, sample.nose_confidence),
            (sample.left_ear_point, sample.left_ear_confidence),
            (sample.right_ear_point, sample.right_ear_confidence),
            (sample.left_shoulder_point, sample.left_shoulder_confidence),
            (sample.right_shoulder_point, sample.right_shoulder_confidence),
            (sample.left_hip_point, sample.left_hip_confidence),
            (sample.right_hip_point, sample.right_hip_confidence),
        )
        if point is not None
        for confidence in (confidence if confidence is not None else 1.0,)
    )
    return (
        PersonObservation(
            timestamp=sample.timestamp,
            # MediaPipe Pose does not expose a stable person ID. Leaving this
            # empty forces reacquisition through geometry plus identity checks.
            detection_id=None,
            bbox_xyxy=body_bbox,
            body_keypoints=keypoints,
            body_confidence=(
                sample.pose_quality
                if sample.pose_quality is not None
                else (1.0 if sample.pose_detected and body_points else 0.0)
            ),
            face_bbox_xyxy=None if sample.face_count > 1 else face_bbox,
            face_landmarks=None if sample.face_count > 1 else face_points or None,
            face_quality=(
                sample.face_quality
                if sample.face_detected and sample.face_count == 1
                else None
            ),
            association_ambiguous=ambiguous,
            posture_features=PostureFeatures(
                interpupillary_px=sample.interpupillary_px,
                shoulder_diff_px=sample.shoulder_diff_px,
                signed_shoulder_diff_px=sample.signed_shoulder_diff_px,
                shoulder_width_px=sample.shoulder_width_px,
                trunk_lean_deg=sample.trunk_lean_deg,
                face_detected=sample.face_detected and sample.face_count == 1,
                pose_detected=sample.pose_detected,
                frame_width=sample.frame_width,
                frame_height=sample.frame_height,
                left_eye_center=None if sample.face_count > 1 else sample.left_eye_center,
                right_eye_center=None if sample.face_count > 1 else sample.right_eye_center,
                nose_point=sample.nose_point,
                left_shoulder_point=sample.left_shoulder_point,
                right_shoulder_point=sample.right_shoulder_point,
                shoulder_center=sample.shoulder_center,
                left_hip_point=sample.left_hip_point,
                right_hip_point=sample.right_hip_point,
                hip_center=sample.hip_center,
                face_nose_point=None if sample.face_count > 1 else sample.face_nose_point,
                face_left_mouth_point=(
                    None if sample.face_count > 1 else sample.face_left_mouth_point
                ),
                face_right_mouth_point=(
                    None if sample.face_count > 1 else sample.face_right_mouth_point
                ),
                head_turn_ratio=None if sample.face_count > 1 else sample.head_turn_ratio,
                torso_height_px=sample.torso_height_px,
                left_ear_point=sample.left_ear_point,
                right_ear_point=sample.right_ear_point,
                face_quality=sample.face_quality,
                pose_quality=sample.pose_quality,
                nose_confidence=sample.nose_confidence,
                left_ear_confidence=sample.left_ear_confidence,
                right_ear_confidence=sample.right_ear_confidence,
                left_shoulder_confidence=sample.left_shoulder_confidence,
                right_shoulder_confidence=sample.right_shoulder_confidence,
                left_hip_confidence=sample.left_hip_confidence,
                right_hip_confidence=sample.right_hip_confidence,
                target_motion=sample.target_motion,
                activity_state=sample.activity_state,
                camera_drift=sample.camera_drift,
                face_required_for_calibration=sample.face_required_for_calibration,
            ),
        ),
    )


class CompatibilityBackend:
    """Adapter that preserves the existing MediaPipe engine behavior."""

    capabilities = VisionCapabilities(
        supports_multi_person_pose=False,
        supports_gpu=False,
        supports_world_coordinates=False,
        supports_face_bbox=True,
        backend_name="mediapipe-compatibility",
    )

    def __init__(self, engine_factory: Callable[[], VisionEngine]) -> None:
        self._engine_factory = engine_factory
        self._engine: Optional[VisionEngine] = None
        self._last_observations: Tuple[PersonObservation, ...] = ()

    def start(self) -> None:
        self._engine = self._engine_factory()
        self._engine.start()

    def read_sample(self) -> VisionSample:
        if self._engine is None:
            raise RuntimeError("CompatibilityBackend.start() must be called first.")
        sample = self._engine.read_sample()
        self._store_sample(sample)
        return sample

    def read_frame_sample(self):
        """Read a camera frame and its sample for diagnostic UIs.

        The production Worker only needs `read_sample`; this optional adapter
        method lets a diagnostic panel draw the exact frame whose observation
        was sent through the target manager.
        """
        if self._engine is None:
            raise RuntimeError("CompatibilityBackend.start() must be called first.")
        reader = getattr(self._engine, "read_frame_sample", None)
        if reader is None:
            return None, self.read_sample()
        frame, sample = reader()
        self._store_sample(sample)
        return frame, sample

    def _store_sample(self, sample: VisionSample) -> None:
        self._last_observations = observation_from_sample(sample)

    def observations_for_last_sample(self) -> Tuple[PersonObservation, ...]:
        return self._last_observations

    def set_capture_fps(self, fps: float) -> None:
        if self._engine is not None:
            self._engine.set_capture_fps(fps)

    def get_capture_fps(self) -> float:
        if self._engine is None:
            return 0.0
        return self._engine.get_capture_fps()

    def close(self) -> None:
        if self._engine is not None:
            self._engine.close()
            self._engine = None
        self._last_observations = ()
