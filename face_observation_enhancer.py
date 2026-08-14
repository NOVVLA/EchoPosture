"""Mode-independent face enrichment for pose backend observations."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable, Mapping, Optional, Sequence, Tuple

import cv2
import mediapipe as mp
import numpy as np

from face_body_association import (
    MIN_SELECTION_MARGIN,
    BodyGeometry,
    DetectedFace,
    evaluate_face_body_association,
)
from mediapipe_resources import ensure_ascii_mediapipe_resource_path
from vision_backend import (
    PersonObservation,
    PostureFeatureExtractor,
    VisionCapabilities,
)


class FaceObservationEnhancer:
    """Attach one clearly owned face to each model-independent body."""

    def __init__(self, min_detection_confidence: float = 0.6) -> None:
        ensure_ascii_mediapipe_resource_path(mp)
        self._mp_face_detection = mp.solutions.face_detection
        self._face_detection = self._mp_face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=min_detection_confidence,
        )
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=min_detection_confidence,
        )
        self.last_face_count = 0

    def enrich(
        self,
        frame_bgr: np.ndarray,
        observations: Sequence[PersonObservation],
    ) -> Tuple[PersonObservation, ...]:
        if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
            raise ValueError("invalid_camera_frame")
        observations = tuple(observations)
        if observations and all(
            observation.face_bbox_xyxy is not None
            and len(observation.face_landmarks or ()) == 5
            for observation in observations
        ):
            self.last_face_count = max(
                len(observations),
                max(
                    (observation.scene_person_count or 0 for observation in observations),
                    default=0,
                ),
            )
            return observations

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        frame_rgb.flags.writeable = False
        height, width = frame_bgr.shape[:2]
        faces = self._detect_faces(frame_rgb, width, height)
        self.last_face_count = len(faces)
        landmarks = tuple(self._measure_face_landmarks(frame_rgb, face) for face in faces)
        assignments, ambiguous_bodies = self._associate(faces, observations)
        scene_count = max(
            len(observations),
            len(faces),
            max(
                (observation.scene_person_count or 0 for observation in observations),
                default=0,
            ),
        )

        enriched = []
        for body_index, observation in enumerate(observations):
            if observation.face_bbox_xyxy is not None and len(observation.face_landmarks or ()) == 5:
                enriched.append(replace(observation, scene_person_count=scene_count))
                continue
            face_index = assignments.get(body_index)
            if face_index is None or landmarks[face_index] is None:
                enriched.append(
                    replace(
                        observation,
                        association_ambiguous=(
                            observation.association_ambiguous
                            or body_index in ambiguous_bodies
                        ),
                        scene_person_count=scene_count,
                    )
                )
                continue
            face = faces[face_index]
            face_landmarks = landmarks[face_index]
            quality = self._score_face_quality(frame_bgr, face, face_landmarks)
            features = observation.posture_features
            if features is not None:
                left_eye, right_eye, nose, left_mouth, right_mouth = face_landmarks
                eye_distance = math.dist(left_eye, right_eye)
                eye_mid_x = (left_eye[0] + right_eye[0]) / 2.0
                features = replace(
                    features,
                    interpupillary_px=eye_distance,
                    face_detected=True,
                    left_eye_center=left_eye,
                    right_eye_center=right_eye,
                    face_nose_point=nose,
                    face_left_mouth_point=left_mouth,
                    face_right_mouth_point=right_mouth,
                    head_turn_ratio=(nose[0] - eye_mid_x) / max(eye_distance, 1.0),
                    face_quality=quality,
                    face_required_for_calibration=True,
                )
            enriched.append(
                replace(
                    observation,
                    face_bbox_xyxy=face.bbox_xyxy,
                    face_landmarks=face_landmarks,
                    face_quality=quality,
                    association_ambiguous=False,
                    posture_features=features,
                    scene_person_count=scene_count,
                )
            )
        return tuple(enriched)

    def _associate(
        self,
        faces: Sequence[DetectedFace],
        observations: Sequence[PersonObservation],
    ) -> tuple[dict[int, int], set[int]]:
        scores: dict[tuple[int, int], float] = {}
        for body_index, observation in enumerate(observations):
            body = self._body_geometry(observation)
            for face_index, face in enumerate(faces):
                result = evaluate_face_body_association(face, body)
                if result.matched:
                    scores[(body_index, face_index)] = result.score

        accepted = {}
        ambiguous_bodies: set[int] = set()
        for body_index in range(len(observations)):
            candidates = sorted(
                (
                    (score, face_index)
                    for (candidate_body, face_index), score in scores.items()
                    if candidate_body == body_index
                ),
                reverse=True,
            )
            if not candidates:
                if faces:
                    ambiguous_bodies.add(body_index)
                continue
            if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < MIN_SELECTION_MARGIN:
                ambiguous_bodies.add(body_index)
                continue
            score, face_index = candidates[0]
            competing_bodies = sorted(
                (
                    other_score
                    for (other_body, candidate_face), other_score in scores.items()
                    if candidate_face == face_index and other_body != body_index
                ),
                reverse=True,
            )
            if competing_bodies and score - competing_bodies[0] < MIN_SELECTION_MARGIN:
                ambiguous_bodies.add(body_index)
                continue
            accepted[body_index] = face_index
        return accepted, ambiguous_bodies

    @staticmethod
    def _body_geometry(observation: PersonObservation) -> BodyGeometry:
        features = observation.posture_features
        return BodyGeometry(
            bbox_xyxy=observation.bbox_xyxy,
            shoulder_center=features.shoulder_center if features is not None else None,
            nose=features.nose_point if features is not None else None,
            left_ear=features.left_ear_point if features is not None else None,
            right_ear=features.right_ear_point if features is not None else None,
        )

    def _detect_faces(self, frame_rgb, width: int, height: int) -> Tuple[DetectedFace, ...]:
        result = self._face_detection.process(frame_rgb)
        if result is None or not result.detections:
            return ()

        key = self._mp_face_detection.FaceKeyPoint

        def point(detection, landmark) -> tuple[float, float]:
            relative = self._mp_face_detection.get_key_point(detection, landmark)
            return relative.x * width, relative.y * height

        faces = []
        for detection in result.detections:
            relative = detection.location_data.relative_bounding_box
            bbox = (
                max(0.0, relative.xmin * width),
                max(0.0, relative.ymin * height),
                min(float(width), (relative.xmin + relative.width) * width),
                min(float(height), (relative.ymin + relative.height) * height),
            )
            if bbox[2] - bbox[0] <= 1.0 or bbox[3] - bbox[1] <= 1.0:
                continue
            faces.append(
                DetectedFace(
                    bbox_xyxy=bbox,
                    confidence=float(detection.score[0]) if detection.score else 0.0,
                    left_eye=point(detection, key.LEFT_EYE),
                    right_eye=point(detection, key.RIGHT_EYE),
                    nose=point(detection, key.NOSE_TIP),
                    mouth=point(detection, key.MOUTH_CENTER),
                    left_ear=point(detection, key.LEFT_EAR_TRAGION),
                    right_ear=point(detection, key.RIGHT_EAR_TRAGION),
                )
            )
        return tuple(faces)

    def _measure_face_landmarks(
        self,
        frame_rgb: np.ndarray,
        face: DetectedFace,
    ) -> Optional[Tuple[Tuple[float, float], ...]]:
        frame_height, frame_width = frame_rgb.shape[:2]
        left, top, right, bottom = face.bbox_xyxy
        padding = max(right - left, bottom - top) * 0.25
        crop_left = max(0, int(math.floor(left - padding)))
        crop_top = max(0, int(math.floor(top - padding)))
        crop_right = min(frame_width, int(math.ceil(right + padding)))
        crop_bottom = min(frame_height, int(math.ceil(bottom + padding)))
        if crop_right - crop_left < 2 or crop_bottom - crop_top < 2:
            return None
        crop = np.ascontiguousarray(frame_rgb[crop_top:crop_bottom, crop_left:crop_right])
        crop.flags.writeable = False
        result = self._face_mesh.process(crop)
        if result is None or not result.multi_face_landmarks:
            return None
        points = result.multi_face_landmarks[0].landmark

        def center(indexes: Sequence[int]) -> tuple[float, float]:
            x = sum(points[index].x for index in indexes) / len(indexes) * crop.shape[1]
            y = sum(points[index].y for index in indexes) / len(indexes) * crop.shape[0]
            return x + crop_left, y + crop_top

        return (
            center((33, 133)),
            center((362, 263)),
            center((1,)),
            center((61,)),
            center((291,)),
        )

    @staticmethod
    def _score_face_quality(
        frame_bgr: np.ndarray,
        face: DetectedFace,
        landmarks: Tuple[Tuple[float, float], ...],
    ) -> float:
        frame_height, frame_width = frame_bgr.shape[:2]
        left, top, right, bottom = face.bbox_xyxy
        area_ratio = (right - left) * (bottom - top) / max(1.0, frame_width * frame_height)
        size_score = min(1.0, math.sqrt(max(0.0, area_ratio) / 0.02))
        left_eye, right_eye, nose, left_mouth, right_mouth = landmarks
        ordered = (
            (left_eye[1] + right_eye[1]) / 2.0
            < nose[1]
            < (left_mouth[1] + right_mouth[1]) / 2.0
        )
        return max(
            0.0,
            min(1.0, face.confidence * 0.55 + size_score * 0.25 + (0.20 if ordered else 0.0)),
        )

    def close(self) -> None:
        self._face_detection.close()
        self._face_mesh.close()


class FaceEnhancedBackend:
    """Decorator that normalizes face output for every pose backend mode."""

    def __init__(
        self,
        backend,
        enhancer_factory: Callable[[], FaceObservationEnhancer] = FaceObservationEnhancer,
    ) -> None:
        self._backend = backend
        self._enhancer_factory = enhancer_factory
        self._enhancer: Optional[FaceObservationEnhancer] = None
        self._last_observations: Tuple[PersonObservation, ...] = ()
        capabilities = backend.capabilities
        self.capabilities = VisionCapabilities(
            supports_multi_person_pose=capabilities.supports_multi_person_pose,
            supports_gpu=capabilities.supports_gpu,
            supports_world_coordinates=capabilities.supports_world_coordinates,
            supports_face_bbox=True,
            backend_name=f"{capabilities.backend_name}+shared-face",
        )

    @property
    def diagnostic_notice(self):
        return getattr(self._backend, "diagnostic_notice", None)

    def start(self) -> None:
        self._backend.start()

    def read_frame_sample(self):
        frame, sample = self._backend.read_frame_sample()
        observations = tuple(self._backend.observations_for_last_sample())
        needs_enrichment = not observations or any(
            observation.face_bbox_xyxy is None
            or len(observation.face_landmarks or ()) != 5
            for observation in observations
        )
        if needs_enrichment:
            if self._enhancer is None:
                self._enhancer = self._enhancer_factory()
            observations = self._enhancer.enrich(frame, observations)
        self._last_observations = observations
        if len(observations) == 1:
            sample = replace(
                PostureFeatureExtractor.to_sample(observations[0]),
                person_count=max(1, observations[0].scene_person_count or 0),
            )
        elif observations:
            sample = replace(
                sample,
                face_detected=False,
                pose_detected=False,
                face_count=max(
                    (observation.scene_person_count or 0 for observation in observations),
                    default=0,
                ),
                person_count=max(
                    len(observations),
                    max(
                        (observation.scene_person_count or 0 for observation in observations),
                        default=0,
                    ),
                ),
            )
        return frame, sample

    def read_sample(self):
        _frame, sample = self.read_frame_sample()
        return sample

    def observations_for_last_sample(self) -> Tuple[PersonObservation, ...]:
        return self._last_observations

    def set_capture_fps(self, fps: float) -> None:
        self._backend.set_capture_fps(fps)

    def get_capture_fps(self) -> float:
        return self._backend.get_capture_fps()

    def close(self) -> None:
        if self._enhancer is not None:
            self._enhancer.close()
            self._enhancer = None
        self._backend.close()
        self._last_observations = ()


def face_enhanced_backend_factories(
    backend_factories: Mapping[str, Callable[[], object]],
    enhancer_factory: Callable[[], FaceObservationEnhancer] = FaceObservationEnhancer,
) -> dict[str, Callable[[], FaceEnhancedBackend]]:
    """Apply the same face-observation boundary to every registered mode."""

    return {
        mode: (
            lambda backend_factory=backend_factory: FaceEnhancedBackend(
                backend_factory(),
                enhancer_factory=enhancer_factory,
            )
        )
        for mode, backend_factory in backend_factories.items()
    }


__all__ = [
    "FaceEnhancedBackend",
    "FaceObservationEnhancer",
    "face_enhanced_backend_factories",
]
