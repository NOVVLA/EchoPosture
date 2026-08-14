"""Camera-free contract tests for the YOLO26 standard pose backend."""

from __future__ import annotations

import sys
from types import ModuleType
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import numpy as np
import standard_pose_backend as standard_backend_module

from face_observation_enhancer import (
    FaceEnhancedBackend,
    face_enhanced_backend_factories,
)
from posture_science import (
    CalibrationAccumulator,
    CalibrationPlan,
    calibration_measurement_values,
    calibration_rejection_reason,
)
from standard_pose_backend import COCO_KEYPOINT_COUNT, StandardPoseBackend
from vision_backend import PersonObservation, observation_from_sample
from vision_modes import VISION_MODE_SPECS
from vision_test import calibration_sample_missing_fields


class FakeBoxes:
    def __init__(self, boxes: np.ndarray, confidences: np.ndarray) -> None:
        self.xyxy = boxes
        self.conf = confidences


class FakeKeypoints:
    def __init__(self, data: np.ndarray) -> None:
        self.data = data


class FakeResult:
    def __init__(self, boxes: np.ndarray, confidences: np.ndarray, data: np.ndarray) -> None:
        self.boxes = FakeBoxes(boxes, confidences)
        self.keypoints = FakeKeypoints(data)


class FakeModel:
    def __init__(self, result: FakeResult) -> None:
        self.result = result
        self.calls = []
        self.task = "pose"
        self.model = type("FakePoseModel", (), {"kpt_shape": [17, 3]})()

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [self.result]


class FakeCapture:
    def __init__(self) -> None:
        self.released = False
        self.settings = []

    def isOpened(self) -> bool:
        return True

    def set(self, prop, value) -> None:
        self.settings.append((prop, value))

    def read(self):
        return True, np.full((480, 640, 3), 80, dtype=np.uint8)

    def release(self) -> None:
        self.released = True


def pose_row(offset_x: float = 0.0) -> np.ndarray:
    row = np.zeros((COCO_KEYPOINT_COUNT, 3), dtype=float)
    row[:, 2] = 0.1
    points = {
        0: (320.0 + offset_x, 150.0, 0.92),
        1: (300.0 + offset_x, 145.0, 0.88),
        2: (340.0 + offset_x, 145.0, 0.87),
        3: (285.0 + offset_x, 160.0, 0.86),
        4: (355.0 + offset_x, 160.0, 0.85),
        5: (230.0 + offset_x, 245.0, 0.94),
        6: (410.0 + offset_x, 250.0, 0.93),
        11: (265.0 + offset_x, 390.0, 0.90),
        12: (385.0 + offset_x, 392.0, 0.89),
    }
    for index, values in points.items():
        row[index] = values
    return row


def make_backend(persons: int = 1):
    rows = np.stack([pose_row(index * 180.0) for index in range(persons)])
    boxes = np.array(
        [[180.0 + index * 180.0, 100.0, 460.0 + index * 180.0, 450.0] for index in range(persons)],
        dtype=float,
    )
    model = FakeModel(FakeResult(boxes, np.full(persons, 0.91), rows))
    capture = FakeCapture()
    backend = StandardPoseBackend(
        model=model,
        capture_factory=lambda _camera_id: capture,
    )
    return backend, model, capture


class FakeFaceEnhancer:
    def enrich(self, _frame, observations):
        enriched = []
        for observation in observations:
            features = replace(
                observation.posture_features,
                interpupillary_px=60.0,
                face_detected=True,
                left_eye_center=(290.0, 150.0),
                right_eye_center=(350.0, 150.0),
                face_nose_point=(320.0, 170.0),
                face_left_mouth_point=(300.0, 190.0),
                face_right_mouth_point=(340.0, 190.0),
                face_quality=0.95,
                face_required_for_calibration=True,
            )
            enriched.append(
                replace(
                    observation,
                    face_bbox_xyxy=(270.0, 110.0, 370.0, 215.0),
                    face_landmarks=(
                        (290.0, 150.0),
                        (350.0, 150.0),
                        (320.0, 170.0),
                        (300.0, 190.0),
                        (340.0, 190.0),
                    ),
                    face_quality=0.95,
                    posture_features=features,
                )
            )
        return tuple(enriched)

    def close(self) -> None:
        pass


def test_standard_backend_emits_pose_only_person_contract() -> None:
    backend, model, capture = make_backend()
    backend.start()
    _frame, sample = backend.read_frame_sample()
    observations = backend.observations_for_last_sample()

    assert len(observations) == 1
    observation = observations[0]
    assert len(observation.body_keypoints) == COCO_KEYPOINT_COUNT
    assert observation.detection_id is None
    assert observation.face_bbox_xyxy is None
    assert observation.face_landmarks is None
    assert observation.face_quality is None
    assert observation.face_embedding is None
    assert sample.face_detected is False
    assert sample.face_count == 0
    assert sample.face_required_for_calibration is False
    assert sample.pose_detected is True
    assert sample.person_count == 1
    assert sample.shoulder_width_px is not None
    assert sample.trunk_lean_deg is not None
    assert calibration_sample_missing_fields(sample) == ()
    assert calibration_rejection_reason(sample) is None
    plan = CalibrationPlan(
        preferred_seconds=0.1,
        transition_seconds=0.0,
        relaxed_seconds=0.1,
        relaxed_max_extension_seconds=0.0,
        min_samples_per_stage=1,
    )
    accumulator = CalibrationAccumulator(plan)
    accumulator.add(sample.timestamp, calibration_measurement_values(sample, plan))
    accumulator.begin_transition(sample.timestamp)
    relaxed_timestamp = sample.timestamp + timedelta(seconds=0.1)
    accumulator.add(
        relaxed_timestamp,
        calibration_measurement_values(sample, plan),
    )
    profile = accumulator.finalize(relaxed_timestamp)
    assert profile.scientific_ready
    assert "torso_shoulder_ratio" in profile.enabled_features
    assert "face_shoulder_ratio" not in profile.enabled_features
    assert model.calls[0]["device"] == "cpu"
    assert model.calls[0]["verbose"] is False

    backend.close()
    assert capture.released
    print("test_standard_backend_emits_pose_only_person_contract OK")


def test_standard_backend_preserves_all_people_without_global_posture_mix() -> None:
    backend, _model, _capture = make_backend(persons=2)
    backend.start()
    _frame, sample = backend.read_frame_sample()

    assert len(backend.observations_for_last_sample()) == 2
    assert sample.person_count == 2
    assert sample.pose_detected is False
    assert sample.shoulder_width_px is None
    assert sample.face_required_for_calibration is False
    assert calibration_rejection_reason(sample) == "single_person"
    backend.close()
    print("test_standard_backend_preserves_all_people_without_global_posture_mix OK")


def test_standard_backend_uses_shared_face_observation_contract() -> None:
    backend, _model, capture = make_backend()
    normalized = FaceEnhancedBackend(backend, enhancer_factory=FakeFaceEnhancer)
    normalized.start()
    _frame, sample = normalized.read_frame_sample()
    observations = normalized.observations_for_last_sample()

    assert len(observations) == 1
    assert isinstance(observations[0], PersonObservation)
    assert observations[0].face_bbox_xyxy == (270.0, 110.0, 370.0, 215.0)
    assert len(observations[0].face_landmarks or ()) == 5
    assert observations[0].face_quality == 0.95
    assert sample.face_detected
    assert sample.face_required_for_calibration
    assert normalized.capabilities.supports_face_bbox
    assert normalized.capabilities.backend_name.endswith("+shared-face")
    normalized.close()
    assert capture.released
    print("test_standard_backend_uses_shared_face_observation_contract OK")


def test_all_reserved_modes_share_one_normalized_observation_boundary() -> None:
    raw_backends = {spec.mode: make_backend()[0] for spec in VISION_MODE_SPECS}
    normalized_factories = face_enhanced_backend_factories(
        {
            mode: (lambda backend=backend: backend)
            for mode, backend in raw_backends.items()
        },
        enhancer_factory=FakeFaceEnhancer,
    )

    assert set(normalized_factories) == {spec.mode for spec in VISION_MODE_SPECS}
    for mode, factory in normalized_factories.items():
        backend = factory()
        backend.start()
        frame, sample = backend.read_frame_sample()
        observations = backend.observations_for_last_sample()
        assert frame.shape == (480, 640, 3), mode
        assert len(observations) == 1, mode
        assert isinstance(observations[0], PersonObservation), mode
        assert observations[0].face_bbox_xyxy is not None, mode
        assert len(observations[0].face_landmarks or ()) == 5, mode
        assert sample.face_detected, mode
        backend.close()
    print("test_all_reserved_modes_share_one_normalized_observation_boundary OK")


def test_pose_only_sample_does_not_reuse_stale_face_geometry() -> None:
    backend, _model, _capture = make_backend()
    backend.start()
    _frame, sample = backend.read_frame_sample()
    backend.close()
    stale = replace(
        sample,
        face_detected=False,
        face_count=0,
        face_bbox_xyxy=(270.0, 110.0, 370.0, 215.0),
        face_landmarks=(
            (290.0, 150.0),
            (350.0, 150.0),
            (320.0, 170.0),
            (300.0, 190.0),
            (340.0, 190.0),
        ),
    )
    observation = observation_from_sample(stale)[0]
    assert observation.face_bbox_xyxy is None
    assert observation.face_landmarks is None
    print("test_pose_only_sample_does_not_reuse_stale_face_geometry OK")


def test_standard_backend_refuses_implicit_model_download() -> None:
    missing = Path("models/pose/definitely-missing-yolo26n-pose.pt")
    backend = StandardPoseBackend(
        model_path=missing,
        capture_factory=lambda _camera_id: FakeCapture(),
    )
    try:
        backend.start()
    except RuntimeError as exc:
        assert "Automatic model downloads are disabled" in str(exc)
    else:
        raise AssertionError("missing local model must fail before any download")
    print("test_standard_backend_refuses_implicit_model_download OK")


def test_standard_backend_prepares_torch_dlls_before_loading_model() -> None:
    events = []
    capture = FakeCapture()
    model = FakeModel(
        FakeResult(
            np.empty((0, 4), dtype=float),
            np.empty((0,), dtype=float),
            np.empty((0, COCO_KEYPOINT_COUNT, 3), dtype=float),
        )
    )
    fake_ultralytics = ModuleType("ultralytics")

    def prepare(package_name: str) -> None:
        events.append(("prepare", package_name))

    def load_model(_path: str):
        events.append(("load", "model"))
        return model

    fake_ultralytics.YOLO = load_model
    original_prepare = standard_backend_module.prepare_package_dll_directory
    original_ultralytics = sys.modules.get("ultralytics")
    standard_backend_module.prepare_package_dll_directory = prepare
    sys.modules["ultralytics"] = fake_ultralytics
    try:
        backend = StandardPoseBackend(
            model_path=Path(__file__),
            capture_factory=lambda _camera_id: capture,
        )
        backend.start()
        backend.close()
    finally:
        standard_backend_module.prepare_package_dll_directory = original_prepare
        if original_ultralytics is None:
            sys.modules.pop("ultralytics", None)
        else:
            sys.modules["ultralytics"] = original_ultralytics

    assert events == [("prepare", "torch"), ("load", "model")]
    assert capture.released
    print("test_standard_backend_prepares_torch_dlls_before_loading_model OK")


def test_standard_backend_rejects_wrong_model_contract() -> None:
    backend, model, capture = make_backend()
    model.task = "detect"
    try:
        backend.start()
    except RuntimeError as exc:
        assert "requires a YOLO pose model" in str(exc)
    else:
        raise AssertionError("a non-pose model must fail before opening the camera")
    assert not capture.settings

    backend, model, capture = make_backend()
    model.model.kpt_shape = [15, 3]
    try:
        backend.start()
    except RuntimeError as exc:
        assert "COCO 17-keypoint pose layout" in str(exc)
    else:
        raise AssertionError("a non-COCO pose layout must fail before opening the camera")
    assert not capture.settings
    print("test_standard_backend_rejects_wrong_model_contract OK")


def main() -> int:
    test_standard_backend_emits_pose_only_person_contract()
    test_standard_backend_preserves_all_people_without_global_posture_mix()
    test_standard_backend_uses_shared_face_observation_contract()
    test_all_reserved_modes_share_one_normalized_observation_boundary()
    test_pose_only_sample_does_not_reuse_stale_face_geometry()
    test_standard_backend_refuses_implicit_model_download()
    test_standard_backend_prepares_torch_dlls_before_loading_model()
    test_standard_backend_rejects_wrong_model_contract()
    print("test_standard_pose_backend.py ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
