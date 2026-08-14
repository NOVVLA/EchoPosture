"""Deterministic compatibility-mode face/body ownership regression tests."""

from __future__ import annotations

from face_body_association import (
    BodyGeometry,
    DetectedFace,
    evaluate_face_body_association,
    select_face_for_body,
)


BODY = BodyGeometry(
    bbox_xyxy=(180.0, 100.0, 460.0, 450.0),
    shoulder_center=(320.0, 242.0),
    nose=(320.0, 170.0),
    left_ear=(278.0, 168.0),
    right_ear=(362.0, 168.0),
)


def face(
    *,
    center_x: float = 320.0,
    eye_y: float = 150.0,
    eye_distance: float = 60.0,
    confidence: float = 0.95,
) -> DetectedFace:
    half_eye = eye_distance / 2.0
    return DetectedFace(
        bbox_xyxy=(center_x - 50.0, eye_y - 35.0, center_x + 50.0, eye_y + 75.0),
        confidence=confidence,
        left_eye=(center_x - half_eye, eye_y),
        right_eye=(center_x + half_eye, eye_y),
        nose=(center_x, eye_y + 20.0),
        mouth=(center_x, eye_y + 48.0),
    )


def test_normal_single_face_matches_body() -> None:
    result = evaluate_face_body_association(face(), BODY)
    assert result.matched, result
    assert result.score > 0.5


def test_high_intruder_face_is_rejected_by_cross_model_geometry() -> None:
    result = evaluate_face_body_association(face(eye_y=40.0), BODY)
    assert not result.matched
    assert result.reason in {"face_pose_ear_mismatch", "face_pose_nose_mismatch"}


def test_same_height_bystander_face_is_rejected() -> None:
    result = evaluate_face_body_association(face(center_x=510.0), BODY)
    assert not result.matched
    assert result.reason == "face_horizontal_position_mismatch"


def test_eye_distance_change_neither_confirms_nor_rejects_identity() -> None:
    normal = evaluate_face_body_association(face(eye_distance=60.0), BODY)
    close_or_foreshortened = evaluate_face_body_association(face(eye_distance=32.0), BODY)
    assert normal.matched
    assert close_or_foreshortened.matched
    assert normal.reason == close_or_foreshortened.reason == "face_body_geometry_matched"


def test_clear_body_face_is_selected_while_intruder_remains_countable() -> None:
    selected, result = select_face_for_body(
        (face(eye_y=40.0), face()),
        BODY,
    )
    assert result.matched
    assert selected == face()


if __name__ == "__main__":
    test_normal_single_face_matches_body()
    test_high_intruder_face_is_rejected_by_cross_model_geometry()
    test_same_height_bystander_face_is_rejected()
    test_eye_distance_change_neither_confirms_nor_rejects_identity()
    test_clear_body_face_is_selected_while_intruder_remains_countable()
    print("ALL TESTS PASSED")
