"""Transient in-memory face crop to numeric embedding pipeline."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple

import cv2
import numpy as np

from identity_verifier import FaceObservation
from vision_backend import PersonObservation


class FaceTensorEmbedder(Protocol):
    def embed_rgb_image(
        self,
        image_rgb: np.ndarray,
        keypoints: Optional[Tuple[Tuple[float, float], ...]] = None,
    ) -> Tuple[float, ...]: ...


class FaceEmbeddingUnavailable(ValueError):
    """Raised when a frame cannot form a valid model input."""


@dataclass(frozen=True)
class PreparedFaceInput:
    image_rgb: np.ndarray
    normalized_keypoints: Tuple[Tuple[float, float], ...]


# ArcFace's 112x112 five-point target used by the official InsightFace
# alignment utility: https://github.com/deepinsight/insightface/blob/master/
# python-package/insightface/utils/face_align.py
_ARCFACE_DST = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _ordered_five_points(
    points: Tuple[Tuple[float, float], ...],
) -> Optional[np.ndarray]:
    if len(points) != 5:
        return None
    # The observation order is both eyes, nose, then mouth corners. FaceMesh
    # is mirrored for the user, so ordering by x is the stable screen-space
    # convention expected by the canonical template.
    left_eye, right_eye = sorted(points[:2], key=lambda point: point[0])
    mouth_left, mouth_right = sorted(points[3:5], key=lambda point: point[0])
    return np.asarray([left_eye, right_eye, points[2], mouth_left, mouth_right], dtype=np.float32)


def prepare_face_input(
    frame_bgr: np.ndarray,
    observation: PersonObservation,
    *,
    size: int = 112,
    padding_ratio: float = 0.65,
) -> PreparedFaceInput:
    """Crop one face into an RGB square and normalize its numeric landmarks."""

    if frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3:
        raise FaceEmbeddingUnavailable("invalid_camera_frame")
    bbox = observation.face_bbox_xyxy
    if bbox is None:
        raise FaceEmbeddingUnavailable("face_bbox_unavailable")
    left, top, right, bottom = (float(value) for value in bbox)
    width = right - left
    height = bottom - top
    if width <= 1.0 or height <= 1.0:
        raise FaceEmbeddingUnavailable("invalid_face_bbox")

    side = max(width, height) * (1.0 + 2.0 * padding_ratio)
    center_x = (left + right) / 2.0
    center_y = (top + bottom) / 2.0
    frame_height, frame_width = frame_bgr.shape[:2]
    crop_left = max(0, int(round(center_x - side / 2.0)))
    crop_top = max(0, int(round(center_y - side / 2.0)))
    crop_right = min(frame_width, int(round(center_x + side / 2.0)))
    crop_bottom = min(frame_height, int(round(center_y + side / 2.0)))
    if crop_right - crop_left < 2 or crop_bottom - crop_top < 2:
        raise FaceEmbeddingUnavailable("face_crop_empty")

    crop = frame_bgr[crop_top:crop_bottom, crop_left:crop_right]
    raw_landmarks = tuple(observation.face_landmarks or ())
    ordered = _ordered_five_points(raw_landmarks) if size == 112 else None
    aligned_points: Optional[np.ndarray] = None
    if ordered is not None:
        ordered[:, 0] -= crop_left
        ordered[:, 1] -= crop_top
        transform, _ = cv2.estimateAffinePartial2D(
            ordered,
            _ARCFACE_DST,
            method=cv2.LMEDS,
        )
        if transform is not None:
            aligned_points = cv2.transform(ordered[None, :, :], transform)[0]
            image_rgb = cv2.cvtColor(
                cv2.warpAffine(crop, transform, (size, size), borderValue=0.0),
                cv2.COLOR_BGR2RGB,
            )
        else:
            image_rgb = cv2.cvtColor(
                cv2.resize(crop, (size, size), interpolation=cv2.INTER_LINEAR),
                cv2.COLOR_BGR2RGB,
            )
    else:
        image_rgb = cv2.cvtColor(
            cv2.resize(crop, (size, size), interpolation=cv2.INTER_LINEAR),
            cv2.COLOR_BGR2RGB,
        )
    image_rgb = np.ascontiguousarray(image_rgb)

    crop_width = float(crop_right - crop_left)
    crop_height = float(crop_bottom - crop_top)
    if aligned_points is not None:
        normalized = tuple(
            (float(point[0]) / size, float(point[1]) / size)
            for point in aligned_points
        )
    else:
        normalized = tuple(
            (
                (float(x) - crop_left) / crop_width,
                (float(y) - crop_top) / crop_height,
            )
            for x, y in raw_landmarks
        )
    if any(not (-0.25 <= x <= 1.25 and -0.25 <= y <= 1.25) for x, y in normalized):
        raise FaceEmbeddingUnavailable("face_landmarks_outside_crop")
    return PreparedFaceInput(image_rgb, normalized)


class FaceEmbeddingPipeline:
    """Run the local face model off the camera thread without retaining frames."""

    def __init__(
        self,
        embedder: FaceTensorEmbedder,
        executor: Optional[ThreadPoolExecutor] = None,
    ) -> None:
        self._embedder = embedder
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="FaceEmbedding",
        )
        self._owns_executor = executor is None
        self._lock = threading.Lock()
        self._closed = False

    def request(
        self,
        frame_bgr: np.ndarray,
        observation: PersonObservation,
    ) -> Future[FaceObservation]:
        prepared = prepare_face_input(frame_bgr, observation)
        with self._lock:
            if self._closed:
                raise RuntimeError("FaceEmbeddingPipeline is closed")
        return self._executor.submit(self._embed, prepared, observation)

    def _embed(
        self,
        prepared: PreparedFaceInput,
        observation: PersonObservation,
    ) -> FaceObservation:
        keypoints = prepared.normalized_keypoints or None
        try:
            embedding = self._embedder.embed_rgb_image(prepared.image_rgb, keypoints)
        finally:
            # The crop exists only for this inference call. Overwrite the
            # transient array before the executor releases its last reference.
            prepared.image_rgb.fill(0)
        return FaceObservation(
            timestamp=observation.timestamp,
            bbox_xyxy=observation.face_bbox_xyxy or (0.0, 0.0, 0.0, 0.0),
            landmarks=observation.face_landmarks or (),
            detector_quality=observation.face_quality or 0.0,
            embedding=tuple(float(value) for value in embedding),
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=True, cancel_futures=True)


__all__ = [
    "FaceEmbeddingPipeline",
    "FaceEmbeddingUnavailable",
    "PreparedFaceInput",
    "prepare_face_input",
]
