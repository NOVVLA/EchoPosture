"""Metrics-only replay matrix test for P4 state transitions."""

from __future__ import annotations

from pathlib import Path

from vision_replay import replay_file, replay_lines


def test_synthetic_replay_matrix():
    path = Path(__file__).parent / "docs" / "vision-evidence" / "benchmark-synthetic-p3-p4.jsonl"
    results = replay_file(path)
    assert len(results) == 24
    states = [result.state for result in results]
    assert "MULTI_PRESENT" in states
    assert "TARGET_REACQUIRING" in states
    assert "IDENTITY_UNCERTAIN" in states
    assert "TARGET_AMBIGUOUS" in states
    assert states[-1] == "AWAY"
    locked_ids = {
        result.target_track_id
        for result in results
        if result.target_track_id is not None
    }
    assert locked_ids == {1}
    print("test_synthetic_replay_matrix OK")


def test_numeric_posture_exposure_replay():
    lines = [
        '{"timestamp_s": 0, "posture_deviation": 1.0, "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 6, "posture_deviation": 1.0, "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 12, "posture_deviation": 1.0, "expected_posture_status": "BAD"}',
        '{"timestamp_s": 13, "posture_deviation": 1.0, "activity_state": "MOVING", "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 20, "posture_deviation": 1.0, "camera_drift": true, "expected_posture_status": "UNKNOWN"}',
        '{"timestamp_s": 30, "posture_deviation": 0.0, "expected_posture_status": "WATCH"}',
    ]
    results = replay_lines(lines)
    assert results[2].exposure_seconds == 12.0
    assert results[3].exposure_seconds == 12.0
    assert results[4].exposure_seconds == 12.0
    assert 0.0 < (results[5].exposure_seconds or 0.0) < 12.0
    print("test_numeric_posture_exposure_replay OK")


def test_watch_replay_does_not_preload_alert_exposure():
    lines = [
        '{"timestamp_s": 0, "posture_deviation": 0.60, "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 300, "posture_deviation": 0.60, "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 301, "posture_deviation": 1.0, "expected_posture_status": "WATCH"}',
        '{"timestamp_s": 302, "posture_deviation": 1.0, "expected_posture_status": "WATCH"}',
    ]
    results = replay_lines(lines)
    assert results[1].exposure_seconds == 0.0
    assert results[3].exposure_seconds == 2.0
    print("test_watch_replay_does_not_preload_alert_exposure OK")


if __name__ == "__main__":
    test_synthetic_replay_matrix()
    test_numeric_posture_exposure_replay()
    test_watch_replay_does_not_preload_alert_exposure()
    print("ALL TESTS PASSED")
