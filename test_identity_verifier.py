"""Deterministic tests for the P5 local identity verifier."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from identity_verifier import (
    IDENTITY_CONFIRMED,
    IDENTITY_MISMATCH,
    IDENTITY_UNCERTAIN,
    TRIGGER_HEARTBEAT,
    TRIGGER_REACQUIRED,
    FaceObservation,
    IdentityVerifier,
    IdentityVerifierConfig,
    PrecomputedEmbedder,
    align_landmarks,
    score_face_quality,
)


def _face(timestamp: float, embedding: tuple[float, ...], *, size: float = 100.0) -> FaceObservation:
    return FaceObservation(
        timestamp=timestamp,
        bbox_xyxy=(0.0, 0.0, size, size),
        landmarks=((20.0, 35.0), (80.0, 35.0), (50.0, 60.0)),
        embedding=embedding,
    )


def _verifier(**overrides) -> IdentityVerifier:
    values = {
        "min_frames": 3,
        "max_frames": 8,
        "debounce_results": 2,
        "heartbeat_seconds": 5.0,
    }
    values.update(overrides)
    return IdentityVerifier(PrecomputedEmbedder(), IdentityVerifierConfig(**values))


def test_quality_and_landmark_alignment_are_deterministic() -> None:
    observation = _face(0.0, (1.0, 0.0))
    quality = score_face_quality(observation)
    assert quality.accepted
    assert 0.0 < quality.score <= 1.0
    assert align_landmarks(observation.landmarks, observation.bbox_xyxy)[0] == (0.2, 0.35)

    poor = _face(0.0, (1.0, 0.0), size=12.0)
    assert not score_face_quality(poor).accepted


def test_multi_frame_aggregation_and_debounce() -> None:
    verifier = _verifier()
    try:
        enrollment = verifier.enroll([_face(float(index), (1.0, 0.0)) for index in range(3)])
        assert enrollment.ok
        assert enrollment.accepted_frames == 3

        results = [verifier.verify(_face(10.0 + index, (1.0, 0.0))) for index in range(3)]
        assert results[0].state == IDENTITY_UNCERTAIN
        assert results[-1].state == IDENTITY_CONFIRMED
        assert results[-1].valid_frames == 3
    finally:
        verifier.close()


def test_mismatch_is_debounced_and_quality_failure_stays_safe() -> None:
    verifier = _verifier()
    try:
        assert verifier.enroll([_face(float(index), (1.0, 0.0)) for index in range(3)]).ok
        result = None
        for index in range(3):
            result = verifier.verify(_face(20.0 + index, (0.0, 1.0)))
        assert result is not None
        assert result.state == IDENTITY_MISMATCH

        poor = verifier.verify(_face(30.0, (0.0, 1.0), size=12.0))
        assert poor.state == IDENTITY_MISMATCH
        assert poor.reason == "face_quality_insufficient"
    finally:
        verifier.close()


def test_async_submit_event_gate_and_close_clear_in_memory_state() -> None:
    with ThreadPoolExecutor(max_workers=1) as executor:
        verifier = IdentityVerifier(
            PrecomputedEmbedder(),
            IdentityVerifierConfig(min_frames=1, max_frames=4, debounce_results=1),
            executor=executor,
        )
        assert verifier.enroll([_face(0.0, (1.0, 0.0))]).ok
        first = verifier.request(_face(1.0, (1.0, 0.0)), trigger=TRIGGER_REACQUIRED, track_id=1)
        assert first is not None
        assert first.result(timeout=2).state == IDENTITY_CONFIRMED
        blocked = verifier.request(_face(1.1, (1.0, 0.0)), trigger=TRIGGER_REACQUIRED, track_id=1)
        assert blocked is None
        heartbeat = verifier.request(_face(7.0, (1.0, 0.0)), trigger=TRIGGER_HEARTBEAT, track_id=1)
        assert heartbeat is not None
        assert heartbeat.result(timeout=2).state == IDENTITY_CONFIRMED
        reacquisition_session = verifier.start_session(1)
        fresh = verifier.request(
            _face(7.1, (1.0, 0.0)),
            trigger=TRIGGER_REACQUIRED,
            track_id=1,
            session_id=reacquisition_session,
        )
        assert fresh is not None
        assert fresh.result(timeout=2).state == IDENTITY_CONFIRMED
        verifier.close()
        assert not verifier.has_template


def test_new_candidate_session_cannot_reuse_confirmed_history() -> None:
    verifier = _verifier()
    try:
        assert verifier.enroll([_face(float(index), (1.0, 0.0)) for index in range(3)]).ok
        owner_session = verifier.start_session(1)
        owner_results = [
            verifier.verify(
                _face(10.0 + index, (1.0, 0.0)),
                trigger=TRIGGER_HEARTBEAT,
                track_id=1,
                session_id=owner_session,
            )
            for index in range(6)
        ]
        assert owner_results[-1].state == IDENTITY_CONFIRMED

        intruder_session = verifier.start_session(2)
        first_intruder = verifier.verify(
            _face(20.0, (0.0, 1.0)),
            trigger=TRIGGER_REACQUIRED,
            track_id=2,
            session_id=intruder_session,
        )
        assert first_intruder.state == IDENTITY_UNCERTAIN
        assert first_intruder.valid_frames == 1

        intruder_results = [first_intruder]
        for index in range(1, 3):
            intruder_results.append(
                verifier.verify(
                    _face(20.0 + index, (0.0, 1.0)),
                    trigger=TRIGGER_REACQUIRED,
                    track_id=2,
                    session_id=intruder_session,
                )
            )
        assert intruder_results[-1].state == IDENTITY_MISMATCH
        assert intruder_results[-1].valid_frames == 3
    finally:
        verifier.close()


def test_reacquisition_of_same_track_starts_an_independent_window() -> None:
    verifier = _verifier()
    try:
        assert verifier.enroll([_face(float(index), (1.0, 0.0)) for index in range(3)]).ok
        first_session = verifier.start_session(4)
        for index in range(3):
            confirmed = verifier.verify(
                _face(30.0 + index, (1.0, 0.0)),
                track_id=4,
                session_id=first_session,
            )
        assert confirmed.state == IDENTITY_CONFIRMED

        reacquisition_session = verifier.start_session(4)
        assert reacquisition_session != first_session
        first_reacquired = verifier.verify(
            _face(40.0, (0.0, 1.0)),
            track_id=4,
            session_id=reacquisition_session,
        )
        assert first_reacquired.state == IDENTITY_UNCERTAIN
        assert first_reacquired.valid_frames == 1

        late_old_result = verifier.verify(
            _face(41.0, (1.0, 0.0)),
            track_id=4,
            session_id=first_session,
        )
        assert late_old_result.valid_frames == 1
        second_reacquired = verifier.verify(
            _face(42.0, (0.0, 1.0)),
            track_id=4,
            session_id=reacquisition_session,
        )
        assert second_reacquired.valid_frames == 2
        assert second_reacquired.score == 0.0
    finally:
        verifier.close()


def test_no_image_payload_is_retained() -> None:
    observation = _face(0.0, (1.0, 0.0))
    assert not hasattr(observation, "image")
    assert not hasattr(observation, "crop")


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("ALL TESTS PASSED")
