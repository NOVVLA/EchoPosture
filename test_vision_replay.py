"""Metrics-only replay matrix test for P4 state transitions."""

from __future__ import annotations

from pathlib import Path

from vision_replay import replay_file


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


if __name__ == "__main__":
    test_synthetic_replay_matrix()
    print("ALL TESTS PASSED")
