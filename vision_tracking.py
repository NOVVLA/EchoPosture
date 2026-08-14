"""Deterministic target tracking and multi-person safety state machine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from vision_backend import PersonObservation, Timestamp


ACQUIRING = "ACQUIRING"
TARGET_LOCKED = "TARGET_LOCKED"
MULTI_PRESENT = "MULTI_PRESENT"
TARGET_OCCLUDED = "TARGET_OCCLUDED"
TARGET_REACQUIRING = "TARGET_REACQUIRING"
IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
PROFILE_MISMATCH = "PROFILE_MISMATCH"
AWAY = "AWAY"
TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"


@dataclass(frozen=True)
class TargetManagerConfig:
    # Track pruning is wall-clock based so identical timing holds across
    # backend frame rates (compatibility ~15 Hz vs standard ~4 Hz).
    max_missed_seconds: float = 1.0
    occlusion_grace_seconds: float = 2.0
    away_confirm_seconds: float = 3.0
    multi_present_confirm_seconds: float = 0.3
    association_ambiguous_confirm_seconds: float = 0.4
    multi_exit_stable_seconds: float = 1.0
    min_bbox_iou: float = 0.05
    max_center_distance_ratio: float = 1.35
    association_ambiguity_margin: float = 0.08
    # The compatibility backend can lose or sharply move torso landmarks
    # during a deep side-recline while the face remains continuously visible.
    # Use short-gap face continuity as an association aid so one person is not
    # split into a missing target plus a permanent candidate. These are
    # product tracking parameters, not identity or anatomical thresholds.
    face_continuity_max_gap_seconds: float = 0.5
    max_face_center_distance_ratio: float = 1.5
    min_face_area_ratio: float = 0.35
    min_face_continuity_quality: float = 0.50
    moving_speed_ratio_per_second: float = 0.20
    # Activity classification is intentionally slower than association
    # prediction so detector jitter does not become user movement.
    motion_smoothing_seconds: float = 0.20
    # Exact frame-wide association uses a bit-mask dynamic program. These
    # limits keep its worst case bounded and force an explicit abstention when
    # a crowded frame exceeds the product's supported tracking envelope.
    max_association_observations: int = 12
    max_association_tracks: int = 10
    max_association_states: int = 2048


@dataclass(frozen=True)
class TrackedPerson:
    track_id: int
    observation: PersonObservation
    first_seen_at: Timestamp
    last_seen_at: Timestamp
    continuity_score: float
    target_match_score: Optional[float]
    missed_frames: int = 0


@dataclass(frozen=True)
class TargetUpdate:
    state: str
    target_track_id: Optional[int]
    target_observation: Optional[PersonObservation]
    tracks: Tuple[TrackedPerson, ...]
    person_count: int
    reason: str
    target_motion: Optional[float] = None
    activity_state: str = "UNKNOWN"
    identity_candidate_track_id: Optional[int] = None
    identity_candidate_observation: Optional[PersonObservation] = None


@dataclass
class _Track:
    track_id: int
    observation: PersonObservation
    first_seen_at: Timestamp
    last_seen_at: Timestamp
    previous_center: Tuple[float, float]
    velocity: Tuple[float, float] = (0.0, 0.0)
    motion_velocity: Tuple[float, float] = (0.0, 0.0)
    scale_velocity: float = 0.0
    missed_frames: int = 0
    seen_frames: int = 1
    last_match_score: Optional[float] = None


def _center(bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
    return (bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0


def _area(bbox: Tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _iou(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    left = max(a[0], b[0])
    top = max(a[1], b[1])
    right = min(a[2], b[2])
    bottom = min(a[3], b[3])
    intersection = _area((left, top, right, bottom))
    union = _area(a) + _area(b) - intersection
    return intersection / union if union > 0 else 0.0


def _elapsed_seconds(current: Timestamp, previous: Timestamp) -> float:
    delta = current - previous
    return float(delta.total_seconds()) if hasattr(delta, "total_seconds") else float(delta)


def _distance_ratio(track: _Track, observation: PersonObservation) -> float:
    elapsed_seconds = max(0.0, _elapsed_seconds(observation.timestamp, track.last_seen_at))
    predicted = (
        _center(track.observation.bbox_xyxy)[0] + track.velocity[0] * elapsed_seconds,
        _center(track.observation.bbox_xyxy)[1] + track.velocity[1] * elapsed_seconds,
    )
    current = _center(observation.bbox_xyxy)
    diagonal = math.hypot(
        track.observation.bbox_xyxy[2] - track.observation.bbox_xyxy[0],
        track.observation.bbox_xyxy[3] - track.observation.bbox_xyxy[1],
    )
    return math.dist(predicted, current) / max(1.0, diagonal)


class TargetManager:
    """Associates observations while refusing silent target promotion."""

    def __init__(self, config: Optional[TargetManagerConfig] = None) -> None:
        self.config = config or TargetManagerConfig()
        self._tracks: Dict[int, _Track] = {}
        self._next_track_id = 1
        self.target_track_id: Optional[int] = None
        self.state = ACQUIRING
        self._target_missing_since: Optional[Timestamp] = None
        self._multi_started_at: Optional[Timestamp] = None
        self._multi_last_present_at: Optional[Timestamp] = None
        self._multi_confirmed = False
        self._association_ambiguous_since: Optional[Timestamp] = None
        self._association_ambiguous_key: Optional[Tuple[object, ...]] = None
        self._identity_pending = False
        self._identity_candidate_track_id: Optional[int] = None
        self._identity_mismatch_track_id: Optional[int] = None

    def reset(self) -> None:
        self._tracks.clear()
        self._next_track_id = 1
        self.target_track_id = None
        self.state = ACQUIRING
        self._target_missing_since = None
        self._multi_started_at = None
        self._multi_last_present_at = None
        self._multi_confirmed = False
        self._association_ambiguous_since = None
        self._association_ambiguous_key = None
        self._identity_pending = False
        self._identity_candidate_track_id = None
        self._identity_mismatch_track_id = None

    def lock_target(self, track_id: Optional[int] = None) -> bool:
        """Lock only an existing, unambiguous track; never create one implicitly."""
        candidates = [
            track
            for track in self._tracks.values()
            if track.missed_frames == 0 and not track.observation.association_ambiguous
        ]
        if track_id is None:
            if len(candidates) != 1:
                return False
            track_id = candidates[0].track_id
        track = self._tracks.get(track_id)
        if (
            track is None
            or track.missed_frames != 0
            or track.observation.association_ambiguous
        ):
            return False
        self.target_track_id = track_id
        self.state = TARGET_LOCKED
        self._target_missing_since = None
        self._multi_started_at = None
        self._multi_last_present_at = None
        self._multi_confirmed = False
        self._identity_pending = False
        self._identity_candidate_track_id = None
        self._identity_mismatch_track_id = None
        return True

    def lock_calibration_target(self) -> bool:
        return self.lock_target()

    def resolve_identity(
        self,
        matches_target: Optional[bool],
        candidate_track_id: Optional[int] = None,
    ) -> bool:
        expected_track_id = self._identity_candidate_track_id
        if candidate_track_id is not None and candidate_track_id != expected_track_id:
            return False
        if matches_target is None:
            self._identity_pending = True
            return True
        if expected_track_id is None:
            return False
        self._identity_pending = False
        if not matches_target:
            self._identity_mismatch_track_id = expected_track_id
            return True
        if expected_track_id != self.target_track_id and not self._bind_identity_candidate(
            expected_track_id
        ):
            return False
        self._identity_candidate_track_id = None
        self._identity_mismatch_track_id = None
        self.state = TARGET_LOCKED
        return True

    def update(
        self,
        observations: Iterable[PersonObservation],
        timestamp: Optional[Timestamp] = None,
    ) -> TargetUpdate:
        observations = tuple(observations)
        timestamp = timestamp or self._timestamp(observations)
        if (
            len(observations) > self.config.max_association_observations
            or len(self._tracks) > self.config.max_association_tracks
        ):
            return self._association_budget_update(observations, timestamp)
        ambiguous = any(observation.association_ambiguous for observation in observations)
        assignments, candidate_scores = self._associate(observations)
        matched_track_ids = {track.track_id for _, track, _, _ in assignments}
        unmatched_observations = [
            observation
            for index, observation in enumerate(observations)
            if not any(assigned_index == index for assigned_index, _, _, _ in assignments)
        ]
        if len(self._tracks) + len(unmatched_observations) > self.config.max_association_tracks:
            return self._association_budget_update(observations, timestamp)

        for _, track, observation, match_score in assignments:
            self._update_track(track, observation, match_score)

        for track in self._tracks.values():
            if track.track_id not in matched_track_ids:
                track.missed_frames += 1

        for observation in unmatched_observations:
            self._create_track(observation)

        self._prune_tracks(timestamp)
        target = self._tracks.get(self.target_track_id) if self.target_track_id else None
        target_observation = target.observation if target and target.missed_frames == 0 else None
        active_tracks = [track for track in self._tracks.values() if track.missed_frames == 0]
        scene_person_count = max(
            len(active_tracks),
            max(
                (
                    observation.scene_person_count or 0
                    for observation in observations
                ),
                default=0,
            ),
        )
        identity_candidate = self._identity_candidate(target, target_observation, active_tracks)
        other_tracks = [track for track in active_tracks if track.track_id != self.target_track_id]
        other_person_present = bool(other_tracks) or scene_person_count > 1
        target_ambiguous = self._track_is_ambiguous(self.target_track_id, candidate_scores)
        ambiguous_track_ids = tuple(
            sorted(
                track.track_id
                for track in active_tracks
                if track.observation.association_ambiguous
            )
        )
        if target_observation is not None and target_observation.association_ambiguous:
            ambiguity_key: Optional[Tuple[object, ...]] = ("target", self.target_track_id)
        elif self.target_track_id is None and ambiguous:
            ambiguity_key = ("acquiring",) + ambiguous_track_ids
        elif target_observation is None and ambiguous_track_ids:
            ambiguity_key = ("reacquiring",) + ambiguous_track_ids
        else:
            ambiguity_key = None
        face_ambiguity_confirmed = self._association_ambiguity_confirmed(
            ambiguity_key,
            timestamp,
        )

        if self.target_track_id is None:
            self.state = TARGET_AMBIGUOUS if face_ambiguity_confirmed else ACQUIRING
            reason = (
                "ambiguous_face_body_association"
                if face_ambiguity_confirmed
                else "face_body_association_observing"
                if ambiguous
                else "target_not_locked"
            )
        elif target_observation is None and ambiguous and face_ambiguity_confirmed:
            self.state = TARGET_AMBIGUOUS
            reason = "ambiguous_face_body_association"
        elif target_observation is not None and (
            (target_observation.association_ambiguous and face_ambiguity_confirmed)
            or target_ambiguous
        ):
            self.state = TARGET_AMBIGUOUS
            reason = (
                "target_face_body_association_ambiguous"
                if target_observation.association_ambiguous
                else "target_geometry_association_ambiguous"
            )
        elif target_observation is not None:
            was_missing = self._target_missing_since is not None
            missing_seconds = (
                max(0.0, _elapsed_seconds(timestamp, self._target_missing_since))
                if self._target_missing_since is not None
                else 0.0
            )
            self._target_missing_since = None
            if self._identity_mismatch_track_id == self.target_track_id:
                self.state = PROFILE_MISMATCH
                reason = "reacquired_candidate_identity_mismatch"
            elif self._identity_pending or (
                was_missing and missing_seconds >= self.config.occlusion_grace_seconds
            ):
                self._identity_pending = True
                self._identity_candidate_track_id = self.target_track_id
                self.state = IDENTITY_UNCERTAIN
                reason = "reacquired_candidate_needs_identity_confirmation"
            elif target_observation.association_ambiguous:
                self.state = TARGET_LOCKED
                reason = "target_face_body_association_observing"
            elif other_person_present:
                self._multi_last_present_at = timestamp
                if self._multi_started_at is None:
                    self._multi_started_at = timestamp
                elapsed = _elapsed_seconds(timestamp, self._multi_started_at)
                self._multi_confirmed = elapsed >= self.config.multi_present_confirm_seconds
                self.state = MULTI_PRESENT if self._multi_confirmed else TARGET_LOCKED
                reason = "other_track_present" if self.state == MULTI_PRESENT else "multi_present_observing"
            else:
                exit_elapsed = (
                    max(0.0, _elapsed_seconds(timestamp, self._multi_last_present_at))
                    if self._multi_last_present_at is not None
                    else self.config.multi_exit_stable_seconds
                )
                if self._multi_confirmed and exit_elapsed < self.config.multi_exit_stable_seconds:
                    self.state = MULTI_PRESENT
                    reason = f"multi_exit_stabilizing_s={exit_elapsed:.1f}"
                else:
                    self._multi_started_at = None
                    self._multi_last_present_at = None
                    self._multi_confirmed = False
                    self.state = TARGET_LOCKED
                    reason = "target_observed"
        else:
            self._multi_started_at = None
            self._multi_last_present_at = None
            self._multi_confirmed = False
            if self._target_missing_since is None:
                self._target_missing_since = timestamp
            missing_seconds = max(0.0, _elapsed_seconds(timestamp, self._target_missing_since))
            if identity_candidate is not None:
                self._identity_candidate_track_id = identity_candidate.track_id
                if self._identity_mismatch_track_id == identity_candidate.track_id:
                    self._identity_pending = False
                    self.state = PROFILE_MISMATCH
                    reason = "reacquired_candidate_identity_mismatch"
                else:
                    self._identity_pending = True
                    self.state = IDENTITY_UNCERTAIN
                    reason = "reacquired_candidate_needs_identity_confirmation"
            elif active_tracks:
                self._identity_candidate_track_id = None
                self._identity_pending = False
                if len(active_tracks) > 1 or (
                    ambiguous_track_ids and face_ambiguity_confirmed
                ):
                    self.state = TARGET_AMBIGUOUS
                    reason = "identity_candidate_ambiguous"
                elif ambiguous_track_ids:
                    self.state = TARGET_REACQUIRING
                    reason = "identity_candidate_face_observing"
                else:
                    self.state = TARGET_REACQUIRING
                    reason = "identity_candidate_face_unavailable"
            elif missing_seconds < self.config.occlusion_grace_seconds:
                self._identity_candidate_track_id = None
                self.state = TARGET_OCCLUDED
                reason = f"target_missing_observing_s={missing_seconds:.1f}"
            elif missing_seconds >= self.config.away_confirm_seconds:
                self._identity_candidate_track_id = None
                self.state = AWAY
                reason = f"target_away_s={missing_seconds:.1f}"
            else:
                self._identity_candidate_track_id = None
                self.state = TARGET_REACQUIRING
                reason = f"target_missing_s={missing_seconds:.1f}"

        target_motion = self._normalized_motion(target) if target_observation is not None else None
        activity_state = "UNKNOWN"
        if target_motion is not None:
            activity_state = (
                "MOVING"
                if target_motion > self.config.moving_speed_ratio_per_second
                else "STATIC"
            )

        return TargetUpdate(
            state=self.state,
            target_track_id=self.target_track_id,
            target_observation=target_observation,
            tracks=tuple(self._freeze_track(track) for track in self._tracks.values()),
            person_count=scene_person_count,
            reason=reason,
            target_motion=target_motion,
            activity_state=activity_state,
            identity_candidate_track_id=(
                identity_candidate.track_id
                if identity_candidate is not None
                else self.target_track_id
                if self.state == IDENTITY_UNCERTAIN and target_observation is not None
                else None
            ),
            identity_candidate_observation=(
                identity_candidate.observation
                if identity_candidate is not None
                else target_observation
                if self.state == IDENTITY_UNCERTAIN
                else None
            ),
        )

    def _association_budget_update(
        self,
        observations: Tuple[PersonObservation, ...],
        timestamp: Timestamp,
    ) -> TargetUpdate:
        """Abstain from association while still advancing track lifecycles."""

        # The crowded frame cannot be associated, so no track was matched: age
        # every track, start the target-missing clock, and prune stale tracks.
        # Abstaining from association must not freeze lifecycle state, or a
        # crowd could hide a real departure and keep stale tracks alive.
        for track in self._tracks.values():
            track.missed_frames += 1
        target = self._tracks.get(self.target_track_id) if self.target_track_id else None
        if target is not None and self._target_missing_since is None:
            self._target_missing_since = timestamp
        self._prune_tracks(timestamp)
        self.state = TARGET_AMBIGUOUS
        return TargetUpdate(
            state=TARGET_AMBIGUOUS,
            target_track_id=self.target_track_id,
            target_observation=None,
            tracks=tuple(self._freeze_track(track) for track in self._tracks.values()),
            person_count=len(observations),
            reason="association_budget_exceeded",
            target_motion=None,
            activity_state="UNKNOWN",
        )

    @staticmethod
    def _normalized_motion(track: _Track) -> float:
        diagonal = math.hypot(
            track.observation.bbox_xyxy[2] - track.observation.bbox_xyxy[0],
            track.observation.bbox_xyxy[3] - track.observation.bbox_xyxy[1],
        )
        translation_rate = math.hypot(*track.motion_velocity) / max(1.0, diagonal)
        # Forward/backward body motion can leave the box centre almost fixed
        # while its scale changes substantially. Treat relative box-scale
        # velocity as activity instead of mislabelling it as an unrecognised
        # posture measurement.
        return math.hypot(translation_rate, track.scale_velocity)

    def _timestamp(self, observations: Tuple[PersonObservation, ...]) -> Timestamp:
        if observations:
            return max(observation.timestamp for observation in observations)
        target = self._tracks.get(self.target_track_id) if self.target_track_id else None
        if target is not None:
            return target.last_seen_at
        return datetime.now()

    def _associate(
        self,
        observations: Tuple[PersonObservation, ...],
    ) -> Tuple[List[Tuple[int, _Track, PersonObservation, float]], Dict[int, List[float]]]:
        """Find a bounded global one-to-one assignment for the current frame."""
        tracks = tuple(sorted(self._tracks.values(), key=lambda track: track.track_id))
        candidate_scores: Dict[int, List[float]] = {track.track_id: [] for track in tracks}
        score_matrix: List[List[Tuple[_Track, float]]] = []
        for observation in observations:
            candidates: List[Tuple[_Track, float]] = []
            for track in tracks:
                score = self._match_score(track, observation)
                if score is None:
                    continue
                candidates.append((track, score))
                candidate_scores[track.track_id].append(score)
            score_matrix.append(sorted(candidates, key=lambda item: item[0].track_id))

        track_bits = {track.track_id: 1 << index for index, track in enumerate(tracks)}
        states: Dict[
            int,
            Tuple[float, List[Tuple[int, _Track, PersonObservation, float]]],
        ] = {0: (0.0, [])}
        for observation_index, candidates in enumerate(score_matrix):
            next_states = dict(states)
            for mask, (score, matches) in states.items():
                for track, match_score in candidates:
                    bit = track_bits[track.track_id]
                    if mask & bit:
                        continue
                    next_mask = mask | bit
                    next_score = score + match_score + 1e-6
                    previous = next_states.get(next_mask)
                    if previous is None or next_score > previous[0]:
                        next_states[next_mask] = (
                            next_score,
                            matches
                            + [
                                (
                                    observation_index,
                                    track,
                                    observations[observation_index],
                                    match_score,
                                )
                            ],
                        )
            if len(next_states) > self.config.max_association_states:
                # The configured track limit normally makes this unreachable;
                # retain only the best deterministic masks as a second guard.
                ranked = sorted(
                    next_states.items(),
                    key=lambda item: (-item[1][0], item[0]),
                )
                next_states = dict(ranked[: self.config.max_association_states])
            states = next_states

        _, best_matches = max(
            states.values(),
            key=lambda item: (item[0], len(item[1])),
        )
        return best_matches, candidate_scores

    def _match_score(self, track: _Track, observation: PersonObservation) -> Optional[float]:
        face_score = self._face_continuity_score(track, observation)
        if (
            observation.detection_id is not None
            and track.observation.detection_id is not None
            and observation.detection_id != track.observation.detection_id
        ):
            return None
        if (
            observation.detection_id is not None
            and observation.detection_id == track.observation.detection_id
        ):
            return 2.0

        iou = _iou(track.observation.bbox_xyxy, observation.bbox_xyxy)
        distance = _distance_ratio(track, observation)
        if iou < self.config.min_bbox_iou and distance > self.config.max_center_distance_ratio:
            return face_score
        motion_score = max(0.0, 1.0 - distance / self.config.max_center_distance_ratio)
        old_area = _area(track.observation.bbox_xyxy)
        new_area = _area(observation.bbox_xyxy)
        area_ratio = min(old_area, new_area) / max(old_area, new_area, 1.0)
        body_score = motion_score * 0.75 + iou * 0.20 + area_ratio * 0.05
        return max(body_score, face_score or 0.0)

    def _association_ambiguity_confirmed(
        self,
        key: Optional[Tuple[object, ...]],
        timestamp: Timestamp,
    ) -> bool:
        if key is None:
            self._association_ambiguous_since = None
            self._association_ambiguous_key = None
            return False
        if key != self._association_ambiguous_key:
            self._association_ambiguous_key = key
            self._association_ambiguous_since = timestamp
            return self.config.association_ambiguous_confirm_seconds <= 0.0
        assert self._association_ambiguous_since is not None
        elapsed = max(
            0.0,
            _elapsed_seconds(timestamp, self._association_ambiguous_since),
        )
        return elapsed >= self.config.association_ambiguous_confirm_seconds

    def _face_continuity_score(
        self,
        track: _Track,
        observation: PersonObservation,
        *,
        max_gap_seconds: Optional[float] = None,
    ) -> Optional[float]:
        previous = track.observation.face_bbox_xyxy
        current = observation.face_bbox_xyxy
        if previous is None or current is None:
            return None
        previous_quality = track.observation.face_quality
        current_quality = observation.face_quality
        if (
            previous_quality is None
            or current_quality is None
            or min(previous_quality, current_quality) < self.config.min_face_continuity_quality
        ):
            return None
        elapsed = max(0.0, _elapsed_seconds(observation.timestamp, track.last_seen_at))
        if elapsed > (
            self.config.face_continuity_max_gap_seconds
            if max_gap_seconds is None
            else max_gap_seconds
        ):
            return None
        previous_diagonal = math.hypot(
            previous[2] - previous[0],
            previous[3] - previous[1],
        )
        current_diagonal = math.hypot(
            current[2] - current[0],
            current[3] - current[1],
        )
        center_distance = math.dist(_center(previous), _center(current)) / max(
            1.0,
            previous_diagonal,
            current_diagonal,
        )
        previous_area = _area(previous)
        current_area = _area(current)
        area_ratio = min(previous_area, current_area) / max(
            previous_area,
            current_area,
            1.0,
        )
        max_center_distance = self.config.max_face_center_distance_ratio
        if (
            center_distance > max_center_distance
            or area_ratio < self.config.min_face_area_ratio
        ):
            return None
        distance_score = max(
            0.0,
            1.0 - center_distance / max_center_distance,
        )
        return distance_score * 0.75 + _iou(previous, current) * 0.20 + area_ratio * 0.05

    def _identity_candidate(
        self,
        target: Optional[_Track],
        target_observation: Optional[PersonObservation],
        active_tracks: List[_Track],
    ) -> Optional[_Track]:
        if target is None or target_observation is not None:
            return None
        candidates = [
            track
            for track in active_tracks
            if track.track_id != target.track_id
            and not track.observation.association_ambiguous
            and track.observation.face_bbox_xyxy is not None
            and len(track.observation.face_landmarks or ()) >= 3
            and (track.observation.face_quality or 0.0)
            >= self.config.min_face_continuity_quality
        ]
        return candidates[0] if len(candidates) == 1 else None

    def _bind_identity_candidate(self, candidate_track_id: int) -> bool:
        if self.target_track_id is None or candidate_track_id == self.target_track_id:
            return candidate_track_id == self.target_track_id
        target = self._tracks.get(self.target_track_id)
        candidate = self._tracks.get(candidate_track_id)
        if target is None or candidate is None or candidate.missed_frames != 0:
            return False
        target.observation = candidate.observation
        target.last_seen_at = candidate.last_seen_at
        target.previous_center = candidate.previous_center
        target.velocity = candidate.velocity
        target.motion_velocity = candidate.motion_velocity
        target.scale_velocity = candidate.scale_velocity
        target.missed_frames = 0
        target.seen_frames += candidate.seen_frames
        target.last_match_score = candidate.last_match_score
        del self._tracks[candidate_track_id]
        self._target_missing_since = None
        return True

    def _track_is_ambiguous(
        self,
        track_id: Optional[int],
        candidate_scores: Dict[int, List[float]],
    ) -> bool:
        if track_id is None:
            return False
        scores = sorted(candidate_scores.get(track_id, ()), reverse=True)
        return len(scores) > 1 and scores[0] - scores[1] < self.config.association_ambiguity_margin

    def _best_match(self, observation: PersonObservation, matched: set[int]) -> Optional[_Track]:
        """Compatibility helper for callers that used the old greedy primitive."""
        candidates = [track for track in self._tracks.values() if track.track_id not in matched]
        if observation.association_ambiguous:
            candidates = [
                track
                for track in candidates
                if track.track_id != self.target_track_id
                and track.observation.association_ambiguous
            ]
            if not candidates:
                return None
        same_detection = [
            track for track in candidates
            if observation.detection_id is not None
            and track.observation.detection_id == observation.detection_id
        ]
        if same_detection:
            return min(same_detection, key=lambda track: track.missed_frames)

        scored: List[Tuple[float, _Track]] = []
        for track in candidates:
            if (
                observation.detection_id is not None
                and track.observation.detection_id is not None
                and observation.detection_id != track.observation.detection_id
            ):
                continue
            iou = _iou(track.observation.bbox_xyxy, observation.bbox_xyxy)
            distance = _distance_ratio(track, observation)
            if iou < self.config.min_bbox_iou and distance > self.config.max_center_distance_ratio:
                continue
            scored.append((self._match_score(track, observation) or 0.0, track))
        return max(scored, key=lambda item: item[0])[1] if scored else None

    def _update_track(self, track: _Track, observation: PersonObservation, match_score: float) -> None:
        old_center = _center(track.observation.bbox_xyxy)
        new_center = _center(observation.bbox_xyxy)
        old_diagonal = math.hypot(
            track.observation.bbox_xyxy[2] - track.observation.bbox_xyxy[0],
            track.observation.bbox_xyxy[3] - track.observation.bbox_xyxy[1],
        )
        new_diagonal = math.hypot(
            observation.bbox_xyxy[2] - observation.bbox_xyxy[0],
            observation.bbox_xyxy[3] - observation.bbox_xyxy[1],
        )
        elapsed_seconds = _elapsed_seconds(observation.timestamp, track.last_seen_at)
        track.previous_center = old_center
        if elapsed_seconds > 0:
            instantaneous_velocity = (
                (new_center[0] - old_center[0]) / elapsed_seconds,
                (new_center[1] - old_center[1]) / elapsed_seconds,
            )
            instantaneous_scale_velocity = math.log(
                max(new_diagonal, 1.0) / max(old_diagonal, 1.0)
            ) / elapsed_seconds
        else:
            instantaneous_velocity = (new_center[0] - old_center[0], new_center[1] - old_center[1])
            instantaneous_scale_velocity = 0.0
        # Keep raw velocity for association prediction, but low-pass the
        # activity signal.  At camera frame rates, one-pixel landmark/bbox
        # jitter can imply a very large instantaneous pixels-per-second value.
        track.velocity = instantaneous_velocity
        if elapsed_seconds > 0:
            smoothing_window = max(0.01, self.config.motion_smoothing_seconds)
            alpha = min(1.0, elapsed_seconds / smoothing_window)
            track.motion_velocity = tuple(
                previous + alpha * (current - previous)
                for previous, current in zip(track.motion_velocity, instantaneous_velocity)
            )
            track.scale_velocity += alpha * (
                instantaneous_scale_velocity - track.scale_velocity
            )
        else:
            track.motion_velocity = instantaneous_velocity
            track.scale_velocity = instantaneous_scale_velocity
        track.observation = observation
        track.last_seen_at = observation.timestamp
        track.missed_frames = 0
        track.seen_frames += 1
        track.last_match_score = match_score

    def _create_track(self, observation: PersonObservation) -> None:
        track_id = self._next_track_id
        self._next_track_id += 1
        center = _center(observation.bbox_xyxy)
        self._tracks[track_id] = _Track(
            track_id=track_id,
            observation=observation,
            first_seen_at=observation.timestamp,
            last_seen_at=observation.timestamp,
            previous_center=center,
            last_match_score=None,
        )

    def _prune_tracks(self, timestamp: Timestamp) -> None:
        for track_id, track in tuple(self._tracks.items()):
            if track_id == self.target_track_id:
                continue
            missed_seconds = max(0.0, _elapsed_seconds(timestamp, track.last_seen_at))
            if missed_seconds > self.config.max_missed_seconds:
                del self._tracks[track_id]

    def _freeze_track(self, track: _Track) -> TrackedPerson:
        continuity = track.seen_frames / max(1, track.seen_frames + track.missed_frames)
        match = (
            track.last_match_score
            if track.track_id == self.target_track_id and track.missed_frames == 0
            else None
        )
        return TrackedPerson(
            track_id=track.track_id,
            observation=track.observation,
            first_seen_at=track.first_seen_at,
            last_seen_at=track.last_seen_at,
            continuity_score=continuity,
            target_match_score=match,
            missed_frames=track.missed_frames,
        )
