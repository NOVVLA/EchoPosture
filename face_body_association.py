"""Deterministic face-to-body geometry checks for single-camera observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]

# Initial product safety bounds. They are deliberately broad and must be
# revised from consented real-camera evidence; they are not anatomical or
# medical claims.
MIN_FACE_ABOVE_SHOULDERS_RATIO = -1.60
MAX_FACE_ABOVE_SHOULDERS_RATIO = -0.15
MAX_FACE_SHOULDER_OFFSET_RATIO = 0.75
MIN_EYE_SHOULDER_RATIO = 0.10
MAX_EYE_SHOULDER_RATIO = 0.40
MAX_REFERENCE_SCALE_CHANGE = 0.35
MAX_EYE_EAR_OFFSET_RATIO = 0.50
MAX_NOSE_OFFSET_RATIO = 0.45
MIN_SELECTION_MARGIN = 0.12


@dataclass(frozen=True)
class DetectedFace:
    bbox_xyxy: BBox
    confidence: float
    left_eye: Optional[Point] = None
    right_eye: Optional[Point] = None
    nose: Optional[Point] = None
    mouth: Optional[Point] = None
    left_ear: Optional[Point] = None
    right_ear: Optional[Point] = None

    @property
    def eye_center(self) -> Optional[Point]:
        if self.left_eye is None or self.right_eye is None:
            return None
        return _midpoint(self.left_eye, self.right_eye)

    @property
    def eye_distance(self) -> Optional[float]:
        if self.left_eye is None or self.right_eye is None:
            return None
        return math.dist(self.left_eye, self.right_eye)


@dataclass(frozen=True)
class BodyGeometry:
    shoulder_center: Point
    shoulder_width: float
    nose: Optional[Point] = None
    left_ear: Optional[Point] = None
    right_ear: Optional[Point] = None


@dataclass(frozen=True)
class FaceBodyAssociation:
    matched: bool
    score: float
    reason: str
    face_shoulder_ratio: Optional[float]


def _midpoint(left: Point, right: Point) -> Point:
    return (left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def evaluate_face_body_association(
    face: DetectedFace,
    body: BodyGeometry,
    *,
    reference_face_shoulder_ratio: Optional[float] = None,
) -> FaceBodyAssociation:
    """Evaluate whether one detected face can safely belong to one pose."""

    shoulder_width = float(body.shoulder_width)
    if not math.isfinite(shoulder_width) or shoulder_width <= 1.0:
        return FaceBodyAssociation(False, 0.0, "shoulder_scale_unavailable", None)
    eye_center = face.eye_center
    eye_distance = face.eye_distance
    if eye_center is None or eye_distance is None or eye_distance <= 1.0:
        return FaceBodyAssociation(False, 0.0, "face_eye_geometry_unavailable", None)

    dx_ratio = (eye_center[0] - body.shoulder_center[0]) / shoulder_width
    dy_ratio = (eye_center[1] - body.shoulder_center[1]) / shoulder_width
    if not (
        MIN_FACE_ABOVE_SHOULDERS_RATIO
        <= dy_ratio
        <= MAX_FACE_ABOVE_SHOULDERS_RATIO
    ):
        return FaceBodyAssociation(False, 0.0, "face_vertical_position_mismatch", None)
    if abs(dx_ratio) > MAX_FACE_SHOULDER_OFFSET_RATIO:
        return FaceBodyAssociation(False, 0.0, "face_horizontal_position_mismatch", None)

    scale_ratio = eye_distance / shoulder_width
    if not MIN_EYE_SHOULDER_RATIO <= scale_ratio <= MAX_EYE_SHOULDER_RATIO:
        return FaceBodyAssociation(False, 0.0, "face_body_scale_mismatch", scale_ratio)
    if reference_face_shoulder_ratio is not None and reference_face_shoulder_ratio > 0:
        relative_scale = scale_ratio / reference_face_shoulder_ratio
        if not (
            1.0 - MAX_REFERENCE_SCALE_CHANGE
            <= relative_scale
            <= 1.0 + MAX_REFERENCE_SCALE_CHANGE
        ):
            return FaceBodyAssociation(False, 0.0, "face_body_reference_scale_mismatch", scale_ratio)

    cross_model_anchor_available = False
    ear_score = 1.0
    if body.left_ear is not None and body.right_ear is not None:
        cross_model_anchor_available = True
        body_ear_center = _midpoint(body.left_ear, body.right_ear)
        ear_offset = math.dist(eye_center, body_ear_center) / shoulder_width
        if ear_offset > MAX_EYE_EAR_OFFSET_RATIO:
            return FaceBodyAssociation(False, 0.0, "face_pose_ear_mismatch", scale_ratio)
        ear_score = 1.0 - ear_offset / MAX_EYE_EAR_OFFSET_RATIO

    nose_score = 1.0
    if body.nose is not None and face.nose is not None:
        cross_model_anchor_available = True
        nose_offset = math.dist(face.nose, body.nose) / shoulder_width
        if nose_offset > MAX_NOSE_OFFSET_RATIO:
            return FaceBodyAssociation(False, 0.0, "face_pose_nose_mismatch", scale_ratio)
        nose_score = 1.0 - nose_offset / MAX_NOSE_OFFSET_RATIO
    if not cross_model_anchor_available:
        return FaceBodyAssociation(False, 0.0, "cross_model_face_anchor_unavailable", scale_ratio)

    horizontal_score = 1.0 - abs(dx_ratio) / MAX_FACE_SHOULDER_OFFSET_RATIO
    vertical_midpoint = (
        MIN_FACE_ABOVE_SHOULDERS_RATIO + MAX_FACE_ABOVE_SHOULDERS_RATIO
    ) / 2.0
    vertical_half_width = (
        MAX_FACE_ABOVE_SHOULDERS_RATIO - MIN_FACE_ABOVE_SHOULDERS_RATIO
    ) / 2.0
    vertical_score = 1.0 - abs(dy_ratio - vertical_midpoint) / vertical_half_width
    detector_score = _clamp01(float(face.confidence))
    score = (
        detector_score * 0.30
        + _clamp01(horizontal_score) * 0.20
        + _clamp01(vertical_score) * 0.15
        + _clamp01(ear_score) * 0.15
        + _clamp01(nose_score) * 0.20
    )
    return FaceBodyAssociation(True, score, "face_body_geometry_matched", scale_ratio)


def select_face_for_body(
    faces: Sequence[DetectedFace],
    body: BodyGeometry,
    *,
    reference_face_shoulder_ratio: Optional[float] = None,
) -> Tuple[Optional[DetectedFace], FaceBodyAssociation]:
    """Select one clear body-owned face, otherwise explicitly abstain."""

    evaluated = [
        (
            face,
            evaluate_face_body_association(
                face,
                body,
                reference_face_shoulder_ratio=reference_face_shoulder_ratio,
            ),
        )
        for face in faces
    ]
    matched = sorted(
        ((face, result) for face, result in evaluated if result.matched),
        key=lambda item: item[1].score,
        reverse=True,
    )
    if not matched:
        reason = evaluated[0][1].reason if len(evaluated) == 1 else "no_face_matches_body"
        return None, FaceBodyAssociation(False, 0.0, reason, None)
    if len(matched) > 1 and matched[0][1].score - matched[1][1].score < MIN_SELECTION_MARGIN:
        return None, FaceBodyAssociation(False, matched[0][1].score, "multiple_face_matches", None)
    return matched[0]


__all__ = [
    "BBox",
    "BodyGeometry",
    "DetectedFace",
    "FaceBodyAssociation",
    "Point",
    "evaluate_face_body_association",
    "select_face_for_body",
]
