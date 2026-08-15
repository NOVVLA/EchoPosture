"""Local target identity verification primitives.

The module deliberately stores only small numeric face metadata and embeddings.
Camera frames, image crops, and temporary bystander vectors are never retained
or written by this layer. A real face model can be supplied through the
``embedder`` protocol once its weights and distribution terms are approved.
"""

from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Optional, Protocol, Sequence, Tuple

Timestamp = float | datetime
Point = Tuple[float, float]

IDENTITY_CONFIRMED = "IDENTITY_CONFIRMED"
IDENTITY_UNCERTAIN = "IDENTITY_UNCERTAIN"
IDENTITY_MISMATCH = "IDENTITY_MISMATCH"

TRIGGER_REACQUIRED = "reacquired"
TRIGGER_HEARTBEAT = "heartbeat"
TRIGGER_EXPLICIT = "explicit"


@dataclass(frozen=True)
class FaceObservation:
    """One transient face observation with no image payload."""

    timestamp: Timestamp
    bbox_xyxy: Tuple[float, float, float, float]
    landmarks: Tuple[Point, ...] = ()
    detector_quality: float = 1.0
    embedding: Optional[Tuple[float, ...]] = None


@dataclass(frozen=True)
class FaceQualityConfig:
    min_width_px: float = 48.0
    min_height_px: float = 48.0
    min_landmarks: int = 3
    min_score: float = 0.35


@dataclass(frozen=True)
class FaceQuality:
    score: float
    accepted: bool
    reasons: Tuple[str, ...] = ()


def _finite(value: float) -> bool:
    return math.isfinite(float(value))


def align_landmarks(
    landmarks: Sequence[Point],
    bbox_xyxy: Tuple[float, float, float, float],
) -> Tuple[Point, ...]:
    """Normalize landmarks to the face box for model-independent alignment."""

    left, top, right, bottom = bbox_xyxy
    width = right - left
    height = bottom - top
    if width <= 0 or height <= 0:
        return ()
    return tuple(((x - left) / width, (y - top) / height) for x, y in landmarks)


def score_face_quality(
    observation: FaceObservation,
    config: Optional[FaceQualityConfig] = None,
) -> FaceQuality:
    """Score size, detector confidence, landmark completeness, and geometry."""

    config = config or FaceQualityConfig()
    left, top, right, bottom = observation.bbox_xyxy
    width = right - left
    height = bottom - top
    reasons: list[str] = []
    if (
        not all(_finite(value) for value in observation.bbox_xyxy)
        or width <= 0
        or height <= 0
    ):
        reasons.append("invalid_bbox")
    if width < config.min_width_px:
        reasons.append("face_too_small")
    if height < config.min_height_px:
        reasons.append("face_too_small")
    if len(observation.landmarks) < config.min_landmarks:
        reasons.append("insufficient_landmarks")
    if not all(_finite(value) for point in observation.landmarks for value in point):
        reasons.append("invalid_landmarks")

    aligned = align_landmarks(observation.landmarks, observation.bbox_xyxy)
    out_of_bounds = any(
        x < -0.25 or x > 1.25 or y < -0.25 or y > 1.25
        for x, y in aligned
    )
    if out_of_bounds:
        reasons.append("landmarks_outside_face")

    size_score = min(1.0, width / max(1.0, config.min_width_px))
    size_score = min(size_score, height / max(1.0, config.min_height_px))
    landmark_score = min(1.0, len(observation.landmarks) / max(1, config.min_landmarks))
    geometry_score = 0.0 if out_of_bounds else 1.0
    detector_score = max(0.0, min(1.0, float(observation.detector_quality)))
    score = (
        0.35 * size_score
        + 0.25 * landmark_score
        + 0.20 * geometry_score
        + 0.20 * detector_score
    )
    if score < config.min_score:
        reasons.append("quality_below_threshold")
    return FaceQuality(score=score, accepted=not reasons, reasons=tuple(dict.fromkeys(reasons)))


class IdentityEmbedder(Protocol):
    """Small adapter boundary for CVLFace/AdaFace or a deterministic test model."""

    def embed(self, observation: FaceObservation) -> Sequence[float]: ...


class PrecomputedEmbedder:
    """Adapter used by tests and future backends that already emit embeddings."""

    def embed(self, observation: FaceObservation) -> Sequence[float]:
        if observation.embedding is None:
            raise ValueError("face observation has no precomputed embedding")
        return observation.embedding


@dataclass(frozen=True)
class IdentityVerifierConfig:
    min_frames: int = 8
    max_frames: int = 20
    confirm_threshold: float = 0.80
    mismatch_threshold: float = 0.45
    debounce_results: int = 2
    heartbeat_seconds: float = 5.0
    min_event_interval_seconds: float = 0.25
    quality: FaceQualityConfig = FaceQualityConfig()

    def __post_init__(self) -> None:
        if not 1 <= self.min_frames <= self.max_frames:
            raise ValueError("min_frames must be between 1 and max_frames")
        if not 0.0 <= self.mismatch_threshold < self.confirm_threshold <= 1.0:
            raise ValueError("identity thresholds must be ordered in [0, 1]")
        if self.debounce_results < 1:
            raise ValueError("debounce_results must be positive")


@dataclass(frozen=True)
class EnrollmentResult:
    ok: bool
    accepted_frames: int
    reason: str


@dataclass(frozen=True)
class IdentityVerificationResult:
    state: str
    score: Optional[float]
    valid_frames: int
    total_frames: int
    reason: str
    trigger: str = TRIGGER_EXPLICIT


@dataclass
class _VerificationSession:
    scores: deque[float]
    total_frames: int = 0
    candidate_state: str = IDENTITY_UNCERTAIN
    candidate_count: int = 0
    stable_state: str = IDENTITY_UNCERTAIN


def _timestamp_seconds(value: Timestamp) -> float:
    return value.timestamp() if isinstance(value, datetime) else float(value)


def _normalise(vector: Sequence[float]) -> Tuple[float, ...]:
    values = tuple(float(value) for value in vector)
    if not values or not all(_finite(value) for value in values):
        raise ValueError("embedding must contain finite values")
    magnitude = math.sqrt(sum(value * value for value in values))
    if magnitude <= 1e-12:
        raise ValueError("embedding must not be zero")
    return tuple(value / magnitude for value in values)


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    left_norm = _normalise(left)
    right_norm = _normalise(right)
    if len(left_norm) != len(right_norm):
        raise ValueError("embedding dimensions do not match")
    return max(-1.0, min(1.0, sum(a * b for a, b in zip(left_norm, right_norm))))


class IdentityVerifier:
    """Asynchronous, debounced, in-memory three-state verifier."""

    def __init__(
        self,
        embedder: IdentityEmbedder | Callable[[FaceObservation], Sequence[float]],
        config: Optional[IdentityVerifierConfig] = None,
        executor: Optional[ThreadPoolExecutor] = None,
        owns_embedder: bool = False,
    ) -> None:
        self.config = config or IdentityVerifierConfig()
        self._embedder = embedder
        self._owns_embedder = bool(owns_embedder)
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="IdentityVerifier",
        )
        self._owns_executor = executor is None
        self._lock = threading.Lock()
        self._template: Optional[Tuple[float, ...]] = None
        self._sessions: dict[tuple[Optional[int], int], _VerificationSession] = {}
        self._session_serial = 0
        self._last_trigger_at: dict[
            tuple[str, Optional[int], Optional[int]], float
        ] = {}
        self._closed = False

    @property
    def has_template(self) -> bool:
        with self._lock:
            return self._template is not None

    def enroll(self, observations: Iterable[FaceObservation]) -> EnrollmentResult:
        embeddings: list[Tuple[float, ...]] = []
        for observation in observations:
            quality = score_face_quality(observation, self.config.quality)
            if not quality.accepted:
                continue
            try:
                embeddings.append(_normalise(self._embed(observation)))
            except (TypeError, ValueError):
                continue
        if len(embeddings) < self.config.min_frames:
            return EnrollmentResult(False, len(embeddings), "insufficient_quality_frames")
        dimension = len(embeddings[0])
        if any(len(embedding) != dimension for embedding in embeddings):
            return EnrollmentResult(False, 0, "embedding_dimension_mismatch")
        mean = tuple(sum(embedding[index] for embedding in embeddings) for index in range(dimension))
        template = _normalise(mean)
        with self._lock:
            self._template = template
            self._sessions.clear()
            self._last_trigger_at.clear()
        return EnrollmentResult(True, len(embeddings), "template_ready")

    def clear_template(self) -> None:
        with self._lock:
            self._template = None
            self._sessions.clear()
            self._last_trigger_at.clear()

    def start_session(self, track_id: Optional[int]) -> int:
        """Create an isolated verification window for one target candidate."""

        with self._lock:
            if self._closed:
                raise RuntimeError("IdentityVerifier is closed")
            self._session_serial += 1
            session_id = self._session_serial
            # The application has one selected posture target at a time. Keep
            # only its active window so abandoned track IDs cannot accumulate.
            self._sessions.clear()
            self._sessions[(track_id, session_id)] = self._new_session()
            self._last_trigger_at.clear()
            return session_id

    def verify(
        self,
        observation: FaceObservation,
        *,
        trigger: str = TRIGGER_EXPLICIT,
        track_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ) -> IdentityVerificationResult:
        quality = score_face_quality(observation, self.config.quality)
        session_key = (track_id, 0 if session_id is None else session_id)
        with self._lock:
            session = self._sessions.setdefault(session_key, self._new_session())
            session.total_frames += 1
            template = self._template
            total_frames = session.total_frames
        if template is None:
            return IdentityVerificationResult(
                IDENTITY_UNCERTAIN,
                None,
                0,
                total_frames,
                "no_template",
                trigger,
            )
        if not quality.accepted:
            with self._lock:
                stable_state = session.stable_state
                valid_frames = len(session.scores)
            return IdentityVerificationResult(
                stable_state,
                None,
                valid_frames,
                total_frames,
                "face_quality_insufficient", trigger,
            )
        try:
            score = cosine_similarity(template, self._embed(observation))
        except (TypeError, ValueError):
            with self._lock:
                stable_state = session.stable_state
                valid_frames = len(session.scores)
            return IdentityVerificationResult(
                stable_state,
                None,
                valid_frames,
                total_frames,
                "embedding_unavailable", trigger,
            )
        with self._lock:
            session.scores.append(score)
            valid_frames = len(session.scores)
            aggregate = statistics.median(session.scores)
            candidate = (
                IDENTITY_CONFIRMED if aggregate >= self.config.confirm_threshold
                else IDENTITY_MISMATCH if aggregate <= self.config.mismatch_threshold
                else IDENTITY_UNCERTAIN
            )
            if candidate == session.candidate_state:
                session.candidate_count += 1
            else:
                session.candidate_state = candidate
                session.candidate_count = 1
            if candidate == IDENTITY_UNCERTAIN:
                session.stable_state = IDENTITY_UNCERTAIN
            elif (
                valid_frames >= self.config.min_frames
                and session.candidate_count >= self.config.debounce_results
            ):
                session.stable_state = candidate
            state = session.stable_state
        if valid_frames < self.config.min_frames:
            state = IDENTITY_UNCERTAIN
            reason = "collecting_identity_frames"
        elif state != candidate:
            reason = "identity_result_debouncing"
        else:
            reason = "identity_score_aggregated"
        return IdentityVerificationResult(state, aggregate, valid_frames, total_frames, reason, trigger)

    def request(
        self,
        observation: FaceObservation,
        *,
        trigger: str,
        track_id: Optional[int] = None,
        session_id: Optional[int] = None,
        force: bool = False,
    ) -> Optional[Future[IdentityVerificationResult]]:
        """Submit only event/heartbeat requests allowed by the trigger gate."""

        now = _timestamp_seconds(observation.timestamp)
        key = (trigger, track_id, session_id)
        with self._lock:
            if self._closed:
                raise RuntimeError("IdentityVerifier is closed")
            previous = self._last_trigger_at.get(key)
            interval = (
                self.config.heartbeat_seconds
                if trigger == TRIGGER_HEARTBEAT
                else self.config.min_event_interval_seconds
            )
            if not force and previous is not None and now - previous < interval:
                return None
            self._last_trigger_at[key] = now
        return self._executor.submit(
            self.verify,
            observation,
            trigger=trigger,
            track_id=track_id,
            session_id=session_id,
        )

    def submit(
        self,
        observation: FaceObservation,
        *,
        trigger: str = TRIGGER_EXPLICIT,
        track_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ) -> Future[IdentityVerificationResult]:
        with self._lock:
            if self._closed:
                raise RuntimeError("IdentityVerifier is closed")
        return self._executor.submit(
            self.verify,
            observation,
            trigger=trigger,
            track_id=track_id,
            session_id=session_id,
        )

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._template = None
            self._sessions.clear()
            self._last_trigger_at.clear()
        if self._owns_executor:
            self._executor.shutdown(wait=True, cancel_futures=True)
        if self._owns_embedder:
            close_embedder = getattr(self._embedder, "close", None)
            if callable(close_embedder):
                close_embedder()

    def _embed(self, observation: FaceObservation) -> Sequence[float]:
        embed = getattr(self._embedder, "embed", None)
        return embed(observation) if embed is not None else self._embedder(observation)

    def _new_session(self) -> _VerificationSession:
        return _VerificationSession(deque(maxlen=self.config.max_frames))

    def __enter__(self) -> "IdentityVerifier":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
