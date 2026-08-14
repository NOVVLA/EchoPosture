"""Deterministic face-to-body geometry checks for single-camera observations."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

Point = Tuple[float, float]
BBox = Tuple[float, float, float, float]

# These are broad image-space ownership envelopes, not anatomical thresholds.
# Identity is decided only by the face embedding verifier. This module merely
# decides which detected face can be submitted for which pose observation.
MAX_FACE_CENTER_X_OFFSET = 0.60
MIN_FACE_CENTER_Y = -0.20
MAX_FACE_CENTER_Y = 0.50
MAX_EYE_EAR_OFFSET_DIAGONAL = 0.18
MAX_NOSE_OFFSET_DIAGONAL = 0.16
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
    bbox_xyxy: BBox
    shoulder_center: Optional[Point] = None
    nose: Optional[Point] = None
    left_ear: Optional[Point] = None
    right_ear: Optional[Point] = None


@dataclass(frozen=True)
class FaceBodyAssociation:
    matched: bool
    score: float
    reason: str


def _midpoint(left: Point, right: Point) -> Point:
    return (left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def evaluate_face_body_association(
    face: DetectedFace,
    body: BodyGeometry,
) -> FaceBodyAssociation:
    """Score face ownership using only frame-space position and pose anchors."""

    left, top, right, bottom = body.bbox_xyxy
    width = float(right - left)
    height = float(bottom - top)
    if (
        width <= 1.0
        or height <= 1.0
        or not all(math.isfinite(float(value)) for value in body.bbox_xyxy)
    ):
        return FaceBodyAssociation(False, 0.0, "body_bbox_unavailable")
    face_center = _bbox_center(face.bbox_xyxy)
    if face_center is None:
        return FaceBodyAssociation(False, 0.0, "face_bbox_unavailable")

    normalized_x = (face_center[0] - (left + right) / 2.0) / width
    normalized_y = (face_center[1] - top) / height
    if abs(normalized_x) > MAX_FACE_CENTER_X_OFFSET:
        return FaceBodyAssociation(False, 0.0, "face_horizontal_position_mismatch")
    if not MIN_FACE_CENTER_Y <= normalized_y <= MAX_FACE_CENTER_Y:
        return FaceBodyAssociation(False, 0.0, "face_vertical_position_mismatch")

    diagonal = max(1.0, math.hypot(width, height))

    anchor_scores = []
    if body.left_ear is not None and body.right_ear is not None:
        body_ear_center = _midpoint(body.left_ear, body.right_ear)
        face_ear_center = face.eye_center or face_center
        ear_offset = math.dist(face_ear_center, body_ear_center) / diagonal
        if ear_offset > MAX_EYE_EAR_OFFSET_DIAGONAL:
            return FaceBodyAssociation(False, 0.0, "face_pose_ear_mismatch")
        anchor_scores.append(1.0 - ear_offset / MAX_EYE_EAR_OFFSET_DIAGONAL)

    if body.nose is not None and face.nose is not None:
        nose_offset = math.dist(face.nose, body.nose) / diagonal
        if nose_offset > MAX_NOSE_OFFSET_DIAGONAL:
            return FaceBodyAssociation(False, 0.0, "face_pose_nose_mismatch")
        anchor_scores.append(1.0 - nose_offset / MAX_NOSE_OFFSET_DIAGONAL)

    horizontal_score = 1.0 - abs(normalized_x) / MAX_FACE_CENTER_X_OFFSET
    vertical_midpoint = (MIN_FACE_CENTER_Y + MAX_FACE_CENTER_Y) / 2.0
    vertical_half_width = (MAX_FACE_CENTER_Y - MIN_FACE_CENTER_Y) / 2.0
    vertical_score = 1.0 - abs(normalized_y - vertical_midpoint) / vertical_half_width
    detector_score = _clamp01(float(face.confidence))
    score = (
        detector_score * 0.25
        + _clamp01(horizontal_score) * 0.20
        + _clamp01(vertical_score) * 0.20
    )
    if anchor_scores:
        score += sum(_clamp01(value) for value in anchor_scores) / len(anchor_scores) * 0.35
    else:
        score += 0.35
    return FaceBodyAssociation(True, _clamp01(score), "face_body_geometry_matched")


def _bbox_center(bbox: BBox) -> Optional[Point]:
    left, top, right, bottom = bbox
    if (
        right <= left
        or bottom <= top
        or not all(math.isfinite(float(value)) for value in bbox)
    ):
        return None
    return (left + right) / 2.0, (top + bottom) / 2.0


def select_face_for_body(
    faces: Sequence[DetectedFace],
    body: BodyGeometry,
) -> Tuple[Optional[DetectedFace], FaceBodyAssociation]:
    """Select one clear body-owned face, otherwise explicitly abstain."""

    evaluated = [
        (
            face,
            evaluate_face_body_association(face, body),
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
        return None, FaceBodyAssociation(False, 0.0, reason)
    if len(matched) > 1 and matched[0][1].score - matched[1][1].score < MIN_SELECTION_MARGIN:
        return None, FaceBodyAssociation(False, matched[0][1].score, "multiple_face_matches")
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
