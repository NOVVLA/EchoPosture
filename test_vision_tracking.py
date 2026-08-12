"""P3/P4 unified backend and target-manager tests without camera or GUI."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Optional

from vision_backend import (
    CompatibilityBackend,
    PersonObservation,
    observation_from_sample,
)
from vision_test import HighPrecisionPostureAnalyzer, VisionSample
from vision_tracking import (
    ACQUIRING,
    AWAY,
    IDENTITY_UNCERTAIN,
    MULTI_PRESENT,
    TARGET_AMBIGUOUS,
    TARGET_LOCKED,
    TARGET_OCCLUDED,
    TARGET_REACQUIRING,
    TargetManagerConfig,
    TargetManager,
)
from vision_worker import VisionWorker

T0 = datetime(2026, 1, 1, 12, 0, 0)


def make_sample(ts: datetime = T0, face_count: int = 1) -> VisionSample:
    return VisionSample(
        timestamp=ts,
        interpupillary_px=60.0,
        shoulder_diff_px=4.0,
        signed_shoulder_diff_px=4.0,
        shoulder_width_px=220.0,
        trunk_lean_deg=2.0,
        face_detected=face_count > 0,
        pose_detected=True,
        face_count=face_count,
        left_eye_center=(290.0, 150.0),
        right_eye_center=(350.0, 150.0),
        face_nose_point=(320.0, 170.0),
        nose_point=(320.0, 170.0),
        left_shoulder_point=(220.0, 240.0),
        right_shoulder_point=(420.0, 244.0),
        left_hip_point=(260.0, 390.0),
        right_hip_point=(380.0, 390.0),
        head_turn_ratio=0.02,
        torso_height_px=160.0,
    )


def observation(
    detection_id: Optional[int],
    ts: datetime,
    left: float,
    top: float = 100.0,
    ambiguous: bool = False,
    posture_sample: Optional[VisionSample] = None,
) -> PersonObservation:
    posture_features = (
        observation_from_sample(posture_sample)[0].posture_features
        if posture_sample is not None
        else None
    )
    return PersonObservation(
        timestamp=ts,
        detection_id=detection_id,
        bbox_xyxy=(left, top, left + 100.0, top + 240.0),
        body_keypoints=(),
        body_confidence=0.9,
        face_bbox_xyxy=(left + 25.0, top, left + 75.0, top + 60.0),
        face_landmarks=None,
        face_quality=0.9,
        association_ambiguous=ambiguous,
        posture_features=posture_features,
    )


def test_compatibility_observation_contract():
    converted = observation_from_sample(make_sample())
    assert len(converted) == 1
    person = converted[0]
    assert person.body_confidence == 1.0
    assert person.face_bbox_xyxy is not None
    assert not person.association_ambiguous

    missing_face_anchor = observation_from_sample(replace(make_sample(), face_nose_point=None))[0]
    assert missing_face_anchor.association_ambiguous

    multi = observation_from_sample(make_sample(face_count=2))[0]
    assert multi.association_ambiguous
    assert multi.face_bbox_xyxy is None

    class FakeLegacyEngine:
        def __init__(self):
            self.started = False
            self.closed = False

        def start(self):
            self.started = True

        def read_sample(self):
            return make_sample()

        def set_capture_fps(self, _fps):
            pass

        def get_capture_fps(self):
            return 15.0

        def close(self):
            self.closed = True

    legacy = FakeLegacyEngine()
    backend = CompatibilityBackend(lambda: legacy)
    backend.start()
    assert backend.read_sample() == make_sample()
    assert len(backend.observations_for_last_sample()) == 1
    assert backend.capabilities.supports_multi_person_pose is False
    backend.close()
    assert legacy.closed
    print("test_compatibility_observation_contract OK")


def test_target_lock_and_multi_person_continuation():
    manager = TargetManager()
    first = manager.update([observation(1, T0, 100.0)], timestamp=T0)
    assert first.state == ACQUIRING
    assert manager.lock_calibration_target()
    target_id = manager.target_track_id

    locked = manager.update([observation(1, T0 + timedelta(seconds=0.1), 105.0)])
    assert locked.state == TARGET_LOCKED
    observing = manager.update(
        [
            observation(1, T0 + timedelta(seconds=0.2), 110.0),
            observation(2, T0 + timedelta(seconds=0.2), 420.0),
        ]
    )
    assert observing.state == TARGET_LOCKED
    multi = manager.update(
        [
            observation(1, T0 + timedelta(seconds=0.6), 115.0),
            observation(2, T0 + timedelta(seconds=0.6), 415.0),
        ]
    )
    assert multi.state == MULTI_PRESENT
    assert multi.target_track_id == target_id
    assert multi.target_observation.detection_id == 1
    assert multi.person_count == 2

    stabilizing = manager.update([observation(1, T0 + timedelta(seconds=0.8), 120.0)])
    assert stabilizing.state == MULTI_PRESENT
    stable_single = manager.update([observation(1, T0 + timedelta(seconds=1.7), 125.0)])
    assert stable_single.state == TARGET_LOCKED
    print("test_target_lock_and_multi_person_continuation OK")


def test_ambiguous_bystander_does_not_suppress_clear_target():
    manager = TargetManager()
    manager.update([observation(1, T0, 100.0)])
    assert manager.lock_calibration_target()

    manager.update(
        [
            observation(1, T0 + timedelta(seconds=0.1), 105.0),
            observation(9, T0 + timedelta(seconds=0.1), 420.0, ambiguous=True),
        ]
    )
    update = manager.update(
        [
            observation(1, T0 + timedelta(seconds=0.5), 110.0),
            observation(9, T0 + timedelta(seconds=0.5), 415.0, ambiguous=True),
        ]
    )
    assert update.state == MULTI_PRESENT
    assert update.target_observation.detection_id == 1
    assert update.person_count == 2
    print("test_ambiguous_bystander_does_not_suppress_clear_target OK")


def test_crossing_keeps_target_identity():
    manager = TargetManager()
    manager.update([observation(1, T0, 100.0)])
    assert manager.lock_calibration_target()
    target_id = manager.target_track_id

    manager.update(
        [
            observation(1, T0 + timedelta(seconds=1), 220.0),
            observation(2, T0 + timedelta(seconds=1), 320.0),
        ]
    )
    crossed = manager.update(
        [
            observation(1, T0 + timedelta(seconds=2), 380.0),
            observation(2, T0 + timedelta(seconds=2), 140.0),
        ]
    )
    assert crossed.target_track_id == target_id
    assert crossed.target_observation.detection_id == 1
    print("test_crossing_keeps_target_identity OK")


def test_velocity_prediction_and_non_target_lifecycle():
    manager = TargetManager()
    manager.update([observation(None, T0, 100.0)])
    assert manager.lock_calibration_target()
    target_id = manager.target_track_id

    manager.update([observation(None, T0 + timedelta(seconds=1), 200.0)])
    predicted = manager.update([observation(None, T0 + timedelta(seconds=1.5), 250.0)])
    assert predicted.target_track_id == target_id
    assert predicted.target_observation.bbox_xyxy[0] == 250.0
    assert predicted.tracks[0].target_match_score is not None
    assert predicted.tracks[0].target_match_score > 0.0

    manager.update(
        [
            observation(None, T0 + timedelta(seconds=2), 300.0),
            observation(2, T0 + timedelta(seconds=2), 600.0),
        ]
    )
    latest = None
    for index in range(1, 7):
        latest = manager.update(
            [observation(None, T0 + timedelta(seconds=2 + index), 300.0 + index * 5.0)]
        )
    assert latest is not None
    assert len(latest.tracks) == 1
    assert latest.tracks[0].track_id == target_id
    print("test_velocity_prediction_and_non_target_lifecycle OK")


def test_geometry_prediction_keeps_target_without_detection_ids():
    manager = TargetManager()
    manager.update([observation(None, T0, 100.0)])
    assert manager.lock_calibration_target()
    target_id = manager.target_track_id

    manager.update(
        [
            observation(None, T0 + timedelta(seconds=1), 220.0),
            observation(None, T0 + timedelta(seconds=1), 320.0),
        ]
    )
    crossed = manager.update(
        [
            observation(None, T0 + timedelta(seconds=2), 380.0),
            observation(None, T0 + timedelta(seconds=2), 140.0),
        ]
    )
    assert crossed.target_track_id == target_id
    assert crossed.target_observation.bbox_xyxy[0] == 380.0
    print("test_geometry_prediction_keeps_target_without_detection_ids OK")


def test_geometry_tie_enters_ambiguous_state_without_silent_switch():
    manager = TargetManager(TargetManagerConfig(association_ambiguity_margin=0.08))
    manager.update([observation(None, T0, 300.0)])
    assert manager.lock_calibration_target()
    manager.update([observation(None, T0 + timedelta(seconds=1), 300.0)])

    update = manager.update(
        [
            observation(None, T0 + timedelta(seconds=2), 250.0),
            observation(None, T0 + timedelta(seconds=2), 350.0),
        ]
    )
    assert update.state == TARGET_AMBIGUOUS
    assert update.target_track_id == 1
    assert update.target_observation is not None
    print("test_geometry_tie_enters_ambiguous_state_without_silent_switch OK")


def test_occlusion_reacquisition_and_no_silent_promotion():
    manager = TargetManager()
    manager.update([observation(1, T0, 100.0)])
    assert manager.lock_calibration_target()
    target_id = manager.target_track_id

    occluded = manager.update(
        [observation(2, T0 + timedelta(seconds=1), 400.0)],
        timestamp=T0 + timedelta(seconds=1),
    )
    assert occluded.state == TARGET_OCCLUDED
    assert occluded.target_track_id == target_id
    assert occluded.target_observation is None

    reacquiring = manager.update(
        [observation(2, T0 + timedelta(seconds=3), 390.0)],
        timestamp=T0 + timedelta(seconds=3),
    )
    assert reacquiring.state == TARGET_REACQUIRING
    assert reacquiring.target_track_id == target_id
    assert reacquiring.target_observation is None

    returned = manager.update(
        [
            observation(1, T0 + timedelta(seconds=4), 120.0),
            observation(2, T0 + timedelta(seconds=4), 380.0),
        ]
    )
    assert returned.state == IDENTITY_UNCERTAIN
    assert returned.target_observation.detection_id == 1
    manager.resolve_identity(True)
    confirmed = manager.update(
        [
            observation(1, T0 + timedelta(seconds=4.1), 125.0),
            observation(2, T0 + timedelta(seconds=4.1), 375.0),
        ]
    )
    assert confirmed.state in {TARGET_LOCKED, MULTI_PRESENT}
    assert confirmed.target_track_id == target_id
    print("test_occlusion_reacquisition_and_no_silent_promotion OK")


def test_compatibility_without_stable_detection_id_requires_reacquire_check():
    manager = TargetManager()
    first = replace(observation(1, T0, 100.0), detection_id=None)
    manager.update([first])
    assert manager.lock_calibration_target()

    manager.update([], timestamp=T0 + timedelta(seconds=1))
    replacement = replace(observation(2, T0 + timedelta(seconds=3.2), 100.0), detection_id=None)
    update = manager.update([replacement])
    assert update.state == IDENTITY_UNCERTAIN
    assert update.target_observation == replacement
    print("test_compatibility_without_stable_detection_id_requires_reacquire_check OK")


def test_numeric_timestamp_contract():
    manager = TargetManager()
    manager.update([observation(1, 0.0, 100.0)], timestamp=0.0)
    assert manager.lock_calibration_target()
    manager.update([], timestamp=1.0)
    away = manager.update([], timestamp=4.1)
    assert away.state == AWAY
    print("test_numeric_timestamp_contract OK")


def test_away_and_ambiguous_states():
    uncalibrated = TargetManager()
    uncalibrated.update([observation(7, T0, 100.0, ambiguous=True)])
    assert not uncalibrated.lock_calibration_target()

    manager = TargetManager()
    manager.update([observation(1, T0, 100.0)])
    assert manager.lock_calibration_target()
    manager.update([], timestamp=T0 + timedelta(seconds=1))
    away = manager.update([], timestamp=T0 + timedelta(seconds=4.1))
    assert away.state == AWAY

    ambiguous = manager.update(
        [observation(3, T0 + timedelta(seconds=5), 150.0, ambiguous=True)]
    )
    assert ambiguous.state == TARGET_AMBIGUOUS
    print("test_away_and_ambiguous_states OK")


def test_analyzer_continues_target_during_multi_present():
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, calibrated_distance_cm=60.0)
    assert analyzer.set_baseline_from_sample(make_sample(), 60.0)

    tracked_multi = replace(
        make_sample(T0 + timedelta(seconds=1), face_count=2),
        target_track_id=1,
        target_state=MULTI_PRESENT,
        target_observed=True,
        person_count=2,
    )
    decision = analyzer.evaluate(tracked_multi)
    assert decision.status not in {"MULTI_USER", "TARGET_AMBIGUOUS"}, decision

    ambiguous = replace(
        tracked_multi,
        target_state=TARGET_AMBIGUOUS,
        target_observed=False,
        target_reason="ambiguous_face_body_association",
    )
    decision = analyzer.evaluate(ambiguous)
    assert decision.status == TARGET_AMBIGUOUS
    print("test_analyzer_continues_target_during_multi_present OK")


def test_tracking_states_respect_presence_and_identity_toggles():
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, calibrated_distance_cm=60.0)
    assert analyzer.set_baseline_from_sample(make_sample(), 60.0)

    analyzer.presence_check_enabled = False
    absent = replace(
        make_sample(T0 + timedelta(seconds=1), face_count=0),
        interpupillary_px=None,
        face_detected=False,
        target_state="AWAY",
        target_observed=False,
        target_reason="target_away_s=4.0",
    )
    decision = analyzer.evaluate(absent)
    assert decision.status == "UNKNOWN", decision

    analyzer.identity_check_enabled = False
    uncertain = replace(
        make_sample(T0 + timedelta(seconds=2)),
        target_state=IDENTITY_UNCERTAIN,
        target_observed=True,
    )
    decision = analyzer.evaluate(uncertain)
    assert decision.status not in {"IDENTITY_UNCERTAIN", "PROFILE_MISMATCH"}, decision
    print("test_tracking_states_respect_presence_and_identity_toggles OK")


def test_worker_compatibility_backend_publishes_target_update():
    class FakeEngine:
        def __init__(self):
            self.closed = False

        def start(self):
            pass

        def set_capture_fps(self, _fps):
            pass

        def read_sample(self):
            return make_sample()

        def get_capture_fps(self):
            return 30.0

        def close(self):
            self.closed = True

    from vision_backend import CompatibilityBackend

    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, calibrated_distance_cm=60.0)
    manager = TargetManager()
    backend = CompatibilityBackend(FakeEngine)
    worker = VisionWorker(
        engine_factory=lambda: backend,
        analyzer=analyzer,
        target_manager=manager,
        target_fps=120.0,
    )
    worker.start(timeout=5.0)
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=2)

    import time

    deadline = time.monotonic() + 5.0
    result = None
    while time.monotonic() < deadline and result is None:
        result = worker.take_calibration_result()
        time.sleep(0.01)
    assert result is not None and result.ok, result
    worker.resume()
    deadline = time.monotonic() + 5.0
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = worker.latest()
        if snapshot.target_update is not None:
            break
        time.sleep(0.01)
    worker.stop()
    assert snapshot is not None and snapshot.target_update is not None
    assert snapshot.target_update.target_track_id == 1
    assert snapshot.sample.target_state == TARGET_LOCKED
    assert snapshot.decision.target_track_id == 1
    assert backend._engine is None
    print("test_worker_compatibility_backend_publishes_target_update OK")


def test_worker_scores_locked_target_observation_not_global_sample():
    import time

    manager = TargetManager()
    analyzer = HighPrecisionPostureAnalyzer(auto_calibrate=False, calibrated_distance_cm=60.0)

    class FakeMultiBackend:
        def __init__(self):
            self.read_count = 0
            self.last_observations = ()

        def start(self):
            pass

        def set_capture_fps(self, _fps):
            pass

        def close(self):
            pass

        def read_sample(self):
            self.read_count += 1
            ts = T0 + timedelta(seconds=self.read_count * 0.2)
            target_sample = make_sample(ts)
            if manager.target_track_id is None:
                self.last_observations = (
                    observation(1, ts, 100.0, posture_sample=target_sample),
                )
                return target_sample

            bystander_sample = replace(make_sample(ts), interpupillary_px=100.0)
            self.last_observations = (
                observation(1, ts, 105.0, posture_sample=target_sample),
                observation(2, ts, 420.0, posture_sample=bystander_sample),
            )
            return bystander_sample

        def observations_for_last_sample(self):
            return self.last_observations

    backend = FakeMultiBackend()
    worker = VisionWorker(
        engine_factory=lambda: backend,
        analyzer=analyzer,
        target_manager=manager,
        target_fps=120.0,
    )
    worker.start(timeout=5.0)
    worker.begin_calibration_sampling()
    worker.finalize_calibration(60.0, sample_count=2)

    deadline = time.monotonic() + 5.0
    result = None
    while time.monotonic() < deadline and result is None:
        result = worker.take_calibration_result()
        time.sleep(0.01)
    assert result is not None and result.ok, result

    worker.resume()
    deadline = time.monotonic() + 5.0
    snapshot = None
    while time.monotonic() < deadline:
        snapshot = worker.latest()
        if snapshot.decision and snapshot.decision.environment_state == MULTI_PRESENT:
            break
        time.sleep(0.01)
    worker.stop()

    assert snapshot is not None and snapshot.decision is not None
    assert snapshot.decision.environment_state == MULTI_PRESENT
    assert snapshot.decision.status == "GOOD", snapshot.decision
    assert snapshot.sample.interpupillary_px == 60.0
    assert snapshot.target_update.target_observation.detection_id == 1
    print("test_worker_scores_locked_target_observation_not_global_sample OK")


def test_target_motion_and_activity_state_are_time_normalized():
    manager = TargetManager()
    first = manager.update((observation(1, T0, 100.0),), timestamp=T0)
    assert first.target_motion is None
    assert first.activity_state == "UNKNOWN"
    assert manager.lock_target(1)

    static = manager.update(
        (observation(1, T0 + timedelta(seconds=1), 100.0),),
        timestamp=T0 + timedelta(seconds=1),
    )
    assert static.target_motion == 0.0
    assert static.activity_state == "STATIC"

    moving = manager.update(
        (observation(1, T0 + timedelta(seconds=2), 220.0),),
        timestamp=T0 + timedelta(seconds=2),
    )
    assert moving.target_motion is not None and moving.target_motion > 0.20
    assert moving.activity_state == "MOVING"
    print("test_target_motion_and_activity_state_are_time_normalized OK")


def test_high_fps_detector_jitter_stays_static():
    """One-pixel bbox jitter must not gate unchanged posture as moving."""
    manager = TargetManager()
    manager.update((observation(1, T0, 100.0),), timestamp=T0)
    assert manager.lock_target(1)

    updates = []
    frame_dt = timedelta(seconds=1.0 / 72.0)
    for index in range(1, 240):
        # A realistic detector can alternate by a pixel while the user is
        # perfectly still.  The target remains at the same physical location.
        jitter = 1.0 if index % 2 else -1.0
        updates.append(
            manager.update(
                (observation(1, T0 + frame_dt * index, 100.0 + jitter),),
                timestamp=T0 + frame_dt * index,
            )
        )

    assert all(update.activity_state == "STATIC" for update in updates[10:])
    assert max(update.target_motion or 0.0 for update in updates[10:]) < 0.20
    print("test_high_fps_detector_jitter_stays_static OK")


def test_sustained_target_motion_still_enters_moving_state():
    manager = TargetManager()
    manager.update((observation(1, T0, 100.0),), timestamp=T0)
    assert manager.lock_target(1)

    frame_dt = timedelta(seconds=1.0 / 72.0)
    updates = []
    for index in range(1, 80):
        left = 100.0 + (100.0 * index / 72.0)
        updates.append(
            manager.update(
                (observation(1, T0 + frame_dt * index, left),),
                timestamp=T0 + frame_dt * index,
            )
        )

    assert any(update.activity_state == "MOVING" for update in updates[10:])
    assert updates[-1].target_motion is not None and updates[-1].target_motion > 0.20
    print("test_sustained_target_motion_still_enters_moving_state OK")


if __name__ == "__main__":
    test_compatibility_observation_contract()
    test_target_lock_and_multi_person_continuation()
    test_ambiguous_bystander_does_not_suppress_clear_target()
    test_crossing_keeps_target_identity()
    test_velocity_prediction_and_non_target_lifecycle()
    test_geometry_prediction_keeps_target_without_detection_ids()
    test_geometry_tie_enters_ambiguous_state_without_silent_switch()
    test_occlusion_reacquisition_and_no_silent_promotion()
    test_compatibility_without_stable_detection_id_requires_reacquire_check()
    test_numeric_timestamp_contract()
    test_away_and_ambiguous_states()
    test_analyzer_continues_target_during_multi_present()
    test_tracking_states_respect_presence_and_identity_toggles()
    test_worker_compatibility_backend_publishes_target_update()
    test_worker_scores_locked_target_observation_not_global_sample()
    test_target_motion_and_activity_state_are_time_normalized()
    test_high_fps_detector_jitter_stays_static()
    test_sustained_target_motion_still_enters_moving_state()
    print("ALL TESTS PASSED")
