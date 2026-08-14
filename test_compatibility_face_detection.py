"""Camera-free BlazeFace compatibility-path regression tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np

from face_body_association import DetectedFace
from vision_backend import observation_from_sample
from vision_test import VisionEngine, VisionSample, calibration_sample_missing_fields
from vision_tracking import MULTI_PRESENT, TARGET_AMBIGUOUS, TargetManager

T0 = datetime(2026, 1, 1, 12, 0, 0)


def sample(timestamp: datetime = T0) -> VisionSample:
    landmarks = (
        (290.0, 150.0),
        (350.0, 150.0),
        (320.0, 170.0),
        (300.0, 190.0),
        (340.0, 190.0),
    )
    detector_landmarks = (
        (290.0, 150.0),
        (350.0, 150.0),
        (320.0, 170.0),
        (320.0, 190.0),
        (278.0, 168.0),
        (362.0, 168.0),
    )
    return VisionSample(
        timestamp=timestamp,
        interpupillary_px=60.0,
        shoulder_diff_px=4.0,
        signed_shoulder_diff_px=4.0,
        shoulder_width_px=200.0,
        trunk_lean_deg=2.0,
        face_detected=True,
        pose_detected=True,
        face_count=1,
        face_bbox_xyxy=(270.0, 115.0, 370.0, 225.0),
        face_landmarks=landmarks,
        face_detector_landmarks=detector_landmarks,
        face_detector_score=0.95,
        face_quality=0.90,
        left_eye_center=landmarks[0],
        right_eye_center=landmarks[1],
        face_nose_point=landmarks[2],
        face_left_mouth_point=landmarks[3],
        face_right_mouth_point=landmarks[4],
        nose_point=(320.0, 170.0),
        left_ear_point=(278.0, 168.0),
        right_ear_point=(362.0, 168.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 244.0),
        shoulder_center=(320.0, 242.0),
        left_hip_point=(260.0, 390.0),
        right_hip_point=(380.0, 390.0),
        hip_center=(320.0, 390.0),
    )


class _FaceKeyPoint:
    LEFT_EYE = "left_eye"
    RIGHT_EYE = "right_eye"
    NOSE_TIP = "nose"
    MOUTH_CENTER = "mouth"
    LEFT_EAR_TRAGION = "left_ear"
    RIGHT_EAR_TRAGION = "right_ear"


class _FakeFaceDetectionApi:
    FaceKeyPoint = _FaceKeyPoint

    @staticmethod
    def get_key_point(detection, key):
        return detection.points[key]


def _detection(offset: float):
    point = lambda x, y: SimpleNamespace(x=x + offset, y=y)
    return SimpleNamespace(
        score=(0.90,),
        location_data=SimpleNamespace(
            relative_bounding_box=SimpleNamespace(
                xmin=0.10 + offset,
                ymin=0.10,
                width=0.20,
                height=0.25,
            )
        ),
        points={
            "left_eye": point(0.14, 0.16),
            "right_eye": point(0.22, 0.16),
            "nose": point(0.18, 0.20),
            "mouth": point(0.18, 0.25),
            "left_ear": point(0.11, 0.19),
            "right_ear": point(0.25, 0.19),
        },
    )


def test_blazeface_count_is_not_capped_at_two() -> None:
    engine = object.__new__(VisionEngine)
    engine._mp_face_detection = _FakeFaceDetectionApi()
    result = SimpleNamespace(detections=[_detection(0.0), _detection(0.2), _detection(0.4)])
    faces = engine._measure_face_detections(result, 640, 480)
    assert len(faces) == 3
    assert all(face.confidence == 0.90 for face in faces)


def test_face_mesh_receives_only_selected_face_crop() -> None:
    class FakeFaceMesh:
        def __init__(self) -> None:
            self.shape = None

        def process(self, crop):
            self.shape = crop.shape
            return SimpleNamespace(multi_face_landmarks=None)

    engine = object.__new__(VisionEngine)
    engine._face_mesh = FakeFaceMesh()
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    selected = DetectedFace((250.0, 100.0, 350.0, 220.0), 0.95)
    engine._measure_selected_face(frame, selected)
    assert engine._face_mesh.shape is not None
    assert engine._face_mesh.shape[0] < frame.shape[0]
    assert engine._face_mesh.shape[1] < frame.shape[1]


def test_face_quality_is_continuous_and_low_inputs_fail_quality_gates() -> None:
    frame = np.full((480, 640, 3), 130, dtype=np.uint8)
    frame[115:225:2, 270:370] = 180
    good_sample = sample()
    good_face = DetectedFace(good_sample.face_bbox_xyxy, 0.95)
    good = VisionEngine._score_face_quality(frame, good_face, good_sample.face_landmarks)

    poor_face = DetectedFace((10.0, 10.0, 25.0, 25.0), 0.55)
    poor = VisionEngine._score_face_quality(np.zeros_like(frame), poor_face, None)
    assert 0.65 < good < 1.0
    assert 0.0 <= poor < 0.50
    assert "face_quality_low" in calibration_sample_missing_fields(
        replace(good_sample, face_quality=poor)
    )


def test_intruder_only_face_is_not_attached_to_seated_body() -> None:
    intruder = replace(
        sample(),
        interpupillary_px=60.0,
        face_bbox_xyxy=(270.0, 5.0, 370.0, 100.0),
        face_landmarks=(
            (290.0, 40.0),
            (350.0, 40.0),
            (320.0, 55.0),
            (300.0, 75.0),
            (340.0, 75.0),
        ),
        face_detector_landmarks=(
            (290.0, 40.0),
            (350.0, 40.0),
            (320.0, 55.0),
            (320.0, 75.0),
            (278.0, 58.0),
            (362.0, 58.0),
        ),
    )
    observation = observation_from_sample(intruder)[0]
    assert observation.association_ambiguous


def test_high_intruder_is_not_rescued_by_short_face_continuity() -> None:
    manager = TargetManager()
    initial = observation_from_sample(sample())[0]
    manager.update((initial,), timestamp=T0)
    assert manager.lock_calibration_target()

    intruder = replace(
        sample(T0 + timedelta(seconds=0.1)),
        face_bbox_xyxy=(270.0, 5.0, 370.0, 100.0),
        face_landmarks=(
            (290.0, 40.0),
            (350.0, 40.0),
            (320.0, 55.0),
            (300.0, 75.0),
            (340.0, 75.0),
        ),
        face_detector_landmarks=(
            (290.0, 40.0),
            (350.0, 40.0),
            (320.0, 55.0),
            (320.0, 75.0),
            (278.0, 58.0),
            (362.0, 58.0),
        ),
    )
    observation = observation_from_sample(intruder)[0]
    update = manager.update((observation,), timestamp=observation.timestamp)

    assert update.state == TARGET_AMBIGUOUS, update
    assert update.target_observation is None


def test_unmatched_faces_contribute_scene_count_without_replacing_target() -> None:
    manager = TargetManager()
    initial = observation_from_sample(sample())[0]
    manager.update((initial,), timestamp=T0)
    assert manager.lock_calibration_target()

    crowded = observation_from_sample(
        replace(sample(T0 + timedelta(seconds=0.4)), face_count=3)
    )[0]
    first = manager.update((crowded,), timestamp=crowded.timestamp)
    assert first.reason == "multi_present_observing"
    crowded = observation_from_sample(
        replace(sample(T0 + timedelta(seconds=0.8)), face_count=3)
    )[0]
    update = manager.update((crowded,), timestamp=crowded.timestamp)
    assert update.state == MULTI_PRESENT, update
    assert update.person_count == 3
    assert update.target_observation is not None


if __name__ == "__main__":
    test_blazeface_count_is_not_capped_at_two()
    test_face_mesh_receives_only_selected_face_crop()
    test_face_quality_is_continuous_and_low_inputs_fail_quality_gates()
    test_intruder_only_face_is_not_attached_to_seated_body()
    test_high_intruder_is_not_rescued_by_short_face_continuity()
    test_unmatched_faces_contribute_scene_count_without_replacing_target()
    print("ALL TESTS PASSED")
