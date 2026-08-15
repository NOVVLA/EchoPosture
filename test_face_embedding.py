"""Camera-free tests for transient local face-model input preparation."""

from __future__ import annotations

from datetime import datetime

import numpy as np

from face_embedding import FaceEmbeddingPipeline, prepare_face_input
from vision_backend import PersonObservation


def _observation() -> PersonObservation:
    return PersonObservation(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        detection_id=None,
        bbox_xyxy=(40.0, 30.0, 80.0, 90.0),
        body_keypoints=(),
        body_confidence=0.9,
        face_bbox_xyxy=(40.0, 30.0, 80.0, 90.0),
        face_landmarks=(
            (50.0, 48.0),
            (70.0, 48.0),
            (60.0, 60.0),
            (53.0, 73.0),
            (67.0, 73.0),
        ),
        face_quality=0.95,
    )


class FakeTensorEmbedder:
    def __init__(self) -> None:
        self.image_shape = None
        self.keypoints = None

    def embed_rgb_image(self, image_rgb, keypoints=None):
        self.image_shape = image_rgb.shape
        self.keypoints = keypoints
        return (3.0, 4.0)


def test_prepare_face_input_is_rgb_112_and_normalizes_five_points() -> None:
    frame = np.zeros((120, 140, 3), dtype=np.uint8)
    frame[:, :, 2] = 255
    prepared = prepare_face_input(frame, _observation())

    assert prepared.image_rgb.shape == (112, 112, 3)
    assert prepared.image_rgb.flags.c_contiguous
    assert tuple(prepared.image_rgb[56, 56]) == (255, 0, 0)
    assert len(prepared.normalized_keypoints) == 5
    assert all(0.0 <= value <= 1.0 for point in prepared.normalized_keypoints for value in point)


def test_pipeline_returns_numbers_without_retaining_frame_payload() -> None:
    embedder = FakeTensorEmbedder()
    pipeline = FaceEmbeddingPipeline(embedder)
    try:
        result = pipeline.request(
            np.zeros((120, 140, 3), dtype=np.uint8),
            _observation(),
        ).result(timeout=2.0)
        assert result.embedding == (3.0, 4.0)
        assert result.landmarks == _observation().face_landmarks
        assert embedder.image_shape == (112, 112, 3)
        assert len(embedder.keypoints) == 5
        assert not hasattr(result, "image")
    finally:
        pipeline.close()


if __name__ == "__main__":
    test_prepare_face_input_is_rgb_112_and_normalizes_five_points()
    test_pipeline_returns_numbers_without_retaining_frame_payload()
    print("ALL TESTS PASSED")
