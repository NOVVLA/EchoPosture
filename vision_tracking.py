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
    max_missed_frames: int = 4
    occlusion_grace_seconds: float = 2.0
    away_confirm_seconds: float = 3.0
    multi_present_confirm_seconds: float = 0.3
    multi_exit_stable_seconds: float = 1.0
    min_bbox_iou: float = 0.05
    max_center_distance_ratio: float = 1.35
    association_ambiguity_margin: float = 0.08
    moving_speed_ratio_per_second: float = 0.20


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


@dataclass
class _Track:
    track_id: int
    observation: PersonObservation
    first_seen_at: Timestamp
    last_seen_at: Timestamp
    previous_center: Tuple[float, float]
    velocity: Tuple[float, float] = (0.0, 0.0)
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
        self._identity_pending = False
        self._identity_mismatch = False

    def reset(self) -> None:
        self._tracks.clear()
        self._next_track_id = 1
        self.target_track_id = None
        self.state = ACQUIRING
        self._target_missing_since = None
        self._multi_started_at = None
        self._multi_last_present_at = None
        self._multi_confirmed = False
        self._identity_pending = False
        self._identity_mismatch = False

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
        self._identity_mismatch = False
        return True

    def lock_calibration_target(self) -> bool:
        return self.lock_target()

    def resolve_identity(self, matches_target: Optional[bool]) -> None:
        if matches_target is None:
            self._identity_pending = True
            return
        self._identity_pending = False
        self._identity_mismatch = not matches_target

    def update(
        self,
        observations: Iterable[PersonObservation],
        timestamp: Optional[Timestamp] = None,
    ) -> TargetUpdate:
        observations = tuple(observations)
        timestamp = timestamp or self._timestamp(observations)
        ambiguous = any(observation.association_ambiguous for observation in observations)
        assignments, candidate_scores = self._associate(observations)
        matched_track_ids = {track.track_id for _, track, _, _ in assignments}
        unmatched_observations = [
            observation
            for index, observation in enumerate(observations)
            if not any(assigned_index == index for assigned_index, _, _, _ in assignments)
        ]

        for _, track, observation, match_score in assignments:
            self._update_track(track, observation, match_score)

        for track in self._tracks.values():
            if track.track_id not in matched_track_ids:
                track.missed_frames += 1

        for observation in unmatched_observations:
            self._create_track(observation)

        self._prune_tracks()
        target = self._tracks.get(self.target_track_id) if self.target_track_id else None
        target_observation = target.observation if target and target.missed_frames == 0 else None
        active_tracks = [track for track in self._tracks.values() if track.missed_frames == 0]
        other_tracks = [track for track in active_tracks if track.track_id != self.target_track_id]
        target_ambiguous = self._track_is_ambiguous(self.target_track_id, candidate_scores)

        if self.target_track_id is None:
            self.state = TARGET_AMBIGUOUS if ambiguous else ACQUIRING
            reason = "ambiguous_face_body_association" if ambiguous else "target_not_locked"
        elif target_observation is None and ambiguous:
            self.state = TARGET_AMBIGUOUS
            reason = "ambiguous_face_body_association"
        elif target_observation is not None and (
            target_observation.association_ambiguous or target_ambiguous
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
            if self._identity_mismatch:
                self.state = PROFILE_MISMATCH
                reason = "reacquired_candidate_profile_mismatch"
            elif self._identity_pending or (
                was_missing and missing_seconds >= self.config.occlusion_grace_seconds
            ):
                self._identity_pending = True
                self.state = IDENTITY_UNCERTAIN
                reason = "reacquired_candidate_needs_identity_confirmation"
            elif other_tracks:
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
            self._identity_mismatch = False
            if self._target_missing_since is None:
                self._target_missing_since = timestamp
            missing_seconds = max(0.0, _elapsed_seconds(timestamp, self._target_missing_since))
            if missing_seconds < self.config.occlusion_grace_seconds:
                self.state = TARGET_OCCLUDED
                reason = f"target_missing_observing_s={missing_seconds:.1f}"
            elif active_tracks:
                self.state = TARGET_REACQUIRING
                reason = "target_missing_candidate_present"
            elif missing_seconds >= self.config.away_confirm_seconds:
                self.state = AWAY
                reason = f"target_away_s={missing_seconds:.1f}"
            else:
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
            person_count=len(active_tracks),
            reason=reason,
            target_motion=target_motion,
            activity_state=activity_state,
        )

    @staticmethod
    def _normalized_motion(track: _Track) -> float:
        diagonal = math.hypot(
            track.observation.bbox_xyxy[2] - track.observation.bbox_xyxy[0],
            track.observation.bbox_xyxy[3] - track.observation.bbox_xyxy[1],
        )
        return math.hypot(*track.velocity) / max(1.0, diagonal)

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
        """Find a global one-to-one assignment for the current frame.

        Greedy observation-order matching can give a target to a bystander when
        people cross. Exhaustive search is cheap for the small person counts
        supported by this layer and lets motion prediction dominate the choice.
        """
        tracks = tuple(self._tracks.values())
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
            score_matrix.append(candidates)

        best_score = float("-inf")
        best_matches: List[Tuple[int, _Track, PersonObservation, float]] = []

        def search(
            index: int,
            used_track_ids: set[int],
            score: float,
            matches: List[Tuple[int, _Track, PersonObservation, float]],
        ) -> None:
            nonlocal best_score, best_matches
            if index >= len(observations):
                matched_bonus = len(matches) * 1e-6
                total = score + matched_bonus
                if total > best_score:
                    best_score = total
                    best_matches = list(matches)
                return
            search(index + 1, used_track_ids, score, matches)
            for track, match_score in score_matrix[index]:
                if track.track_id in used_track_ids:
                    continue
                used_track_ids.add(track.track_id)
                matches.append((index, track, observations[index], match_score))
                search(index + 1, used_track_ids, score + match_score, matches)
                matches.pop()
                used_track_ids.remove(track.track_id)

        search(0, set(), 0.0, [])
        return best_matches, candidate_scores

    def _match_score(self, track: _Track, observation: PersonObservation) -> Optional[float]:
        if observation.association_ambiguous:
            if track.track_id == self.target_track_id or not track.observation.association_ambiguous:
                return None
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
            return None
        motion_score = max(0.0, 1.0 - distance / self.config.max_center_distance_ratio)
        old_area = _area(track.observation.bbox_xyxy)
        new_area = _area(observation.bbox_xyxy)
        area_ratio = min(old_area, new_area) / max(old_area, new_area, 1.0)
        return motion_score * 0.75 + iou * 0.20 + area_ratio * 0.05

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
        elapsed_seconds = _elapsed_seconds(observation.timestamp, track.last_seen_at)
        track.previous_center = old_center
        if elapsed_seconds > 0:
            track.velocity = (
                (new_center[0] - old_center[0]) / elapsed_seconds,
                (new_center[1] - old_center[1]) / elapsed_seconds,
            )
        else:
            track.velocity = (new_center[0] - old_center[0], new_center[1] - old_center[1])
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

    def _prune_tracks(self) -> None:
        for track_id, track in tuple(self._tracks.items()):
            if track_id == self.target_track_id:
                continue
            if track.missed_frames > self.config.max_missed_frames:
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
