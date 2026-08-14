"""
EchoPosture 视觉工作线程。

把「摄像头读帧 + MediaPipe 推理 + 姿态评分」整体移出 GUI 主线程：
cv2 / MediaPipe 的 C 扩展在推理期间释放 GIL，普通 daemon 线程即可获得
真实并行。主线程（tray_app）以低频 QTimer 轮询「最新值信箱」取走最新
决策快照，UI 事件循环每帧只剩 <1ms 的轻活，动画不再被推理阻塞。

设计要点：
- 最新值信箱（单槽，写者覆盖、读者取最新）：天然丢弃过期帧，不会像
  信号队列那样堆积。干预判定是秒级语义（sustained>=12s、确认 3s），
  主线程 10Hz 消费完全足够。
- 线程归属铁律：VisionEngine（含两个 MediaPipe 模型）与 analyzer 的
  构造、全部调用、close() 只发生在工作线程；主线程只读 frozen
  dataclass 快照（VisionSample / PostureDecision）。
- 错误与校准结果是一次性回执（take_* 取走即清空），主线程在轮询里
  消费后走原有的提示/退出/恢复分支；工作线程绝不触碰任何 UI。
- 本模块不依赖 PyQt，可在无 GUI 环境用 FakeEngine 做逻辑层验证。
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable, List, Optional

from face_embedding import FaceEmbeddingPipeline, FaceEmbeddingUnavailable

from vision_test import (
    CameraPermissionError,
    PostureDecision,
    VisionSample,
    calibration_sample_is_complete,
    calibration_sample_missing_fields,
)
from vision_backend import VisionBackend, PostureFeatureExtractor, observation_from_sample
from identity_verifier import (
    FaceObservation,
    IdentityVerifier,
    IDENTITY_CONFIRMED,
    IDENTITY_MISMATCH,
    TRIGGER_EXPLICIT,
    TRIGGER_HEARTBEAT,
    TRIGGER_REACQUIRED,
)
from vision_tracking import TargetManager, TargetUpdate
from posture_science import (
    CALIBRATION_CONTAMINATION_REASONS,
    CalibrationAccumulator,
    CalibrationPlan,
    PREFERRED,
    RELAXED,
    TRANSITION,
    calibration_measurement_values,
    calibration_rejection_reason,
)

MODE_PAUSED = "paused"
MODE_MONITORING = "monitoring"
MODE_CALIBRATING = "calibrating"


def average_calibration_sample(
    samples: List[VisionSample],
    fallback: Optional[VisionSample] = None,
) -> Optional[VisionSample]:
    """Average only single-person, complete calibration samples."""
    eligible_samples = [sample for sample in samples if calibration_sample_is_complete(sample)]
    if not eligible_samples:
        return (
            fallback
            if fallback is not None and calibration_sample_is_complete(fallback)
            else None
        )
    if any(sample.face_count != 1 for sample in eligible_samples):
        return None

    def avg(name: str) -> Optional[float]:
        values = [getattr(sample, name) for sample in eligible_samples]
        usable = [value for value in values if value is not None]
        if not usable:
            return None
        return sum(usable) / len(usable)

    base = eligible_samples[-1]
    return replace(
        base,
        timestamp=datetime.now(),
        interpupillary_px=avg("interpupillary_px"),
        shoulder_diff_px=avg("shoulder_diff_px"),
        signed_shoulder_diff_px=avg("signed_shoulder_diff_px"),
        shoulder_width_px=avg("shoulder_width_px"),
        trunk_lean_deg=avg("trunk_lean_deg"),
        head_turn_ratio=avg("head_turn_ratio"),
        torso_height_px=avg("torso_height_px"),
        face_quality=avg("face_quality"),
        pose_quality=avg("pose_quality"),
        nose_confidence=avg("nose_confidence"),
        left_ear_confidence=avg("left_ear_confidence"),
        right_ear_confidence=avg("right_ear_confidence"),
        left_shoulder_confidence=avg("left_shoulder_confidence"),
        right_shoulder_confidence=avg("right_shoulder_confidence"),
        left_hip_confidence=avg("left_hip_confidence"),
        right_hip_confidence=avg("right_hip_confidence"),
        face_detected=all(sample.face_detected for sample in eligible_samples),
        pose_detected=all(sample.pose_detected for sample in eligible_samples),
        face_count=1,
    )


@dataclass(frozen=True)
class Snapshot:
    """最新监测快照。decision/sample 为 frozen dataclass，跨线程只读安全。"""

    seq: int = 0
    decision: Optional[PostureDecision] = None
    sample: Optional[VisionSample] = None
    target_update: Optional[TargetUpdate] = None


@dataclass(frozen=True)
class CalibrationResult:
    request_id: int
    ok: bool
    missing_fields: tuple[str, ...] = ()
    stage_counts: tuple[tuple[str, int], ...] = ()
    calibration_quality: float = 0.0
    failure_reason: Optional[str] = None


class VisionWorker:
    """拥有 VisionEngine 与 analyzer 的后台线程。

    主线程接口：start/stop、pause/resume、is_monitoring_active、
    latest（信箱）、take_error / take_calibration_result（一次性回执）、
    begin_calibration_sampling / complete_preferred_calibration /
    finalize_calibration、set/get_capture_fps。
    """

    CALIBRATION_INTERVAL_S = 0.18   # 与旧 calibration_timer 的 180ms 一致
    SAMPLE_CAP = 60                 # 与旧 calibration_samples 上限一致

    def __init__(
        self,
        engine_factory: Callable[[], VisionBackend],
        analyzer,
        target_fps: float = 30.0,
        target_manager: Optional[TargetManager] = None,
        identity_verifier: Optional[IdentityVerifier] = None,
        identity_embedding_pipeline: Optional[FaceEmbeddingPipeline] = None,
    ) -> None:
        self._engine_factory = engine_factory
        self.analyzer = analyzer
        self.target_manager = target_manager
        self.identity_verifier = identity_verifier
        self.identity_embedding_pipeline = identity_embedding_pipeline
        self._target_fps = max(1.0, float(target_fps))

        self._commands: "queue.Queue[tuple]" = queue.Queue()
        self._lock = threading.Lock()
        self._snapshot = Snapshot()
        self._error: Optional[Exception] = None
        self._calib_result: Optional[CalibrationResult] = None
        self._seq = 0

        # _mode 由主线程方法写、工作线程读（GIL 下 str 属性读写原子），
        # 这样 pause()/resume() 后 is_monitoring_active() 立即反映新状态。
        self._mode = MODE_PAUSED
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._started = threading.Event()
        self._start_error: Optional[Exception] = None
        self._thread: Optional[threading.Thread] = None

        # 仅工作线程触碰
        self._calib_samples: List[VisionSample] = []
        self._last_usable_sample: Optional[VisionSample] = None
        self._calibration_missing_fields: set[str] = set()
        self._calibration_plan = CalibrationPlan()
        self._calibration_accumulator: Optional[CalibrationAccumulator] = None
        self._dual_calibration_request: Optional[tuple[float, int]] = None
        self._preferred_cutoff_at = None
        self._calib_request_seq = 0
        self._identity_future = None
        self._identity_embedding_future = None
        self._identity_embedding_context: Optional[tuple[str, str, Optional[int]]] = None
        self._identity_enrollment_samples: list[FaceObservation] = []
        self._identity_enrollment_active = False
        self._last_identity_embedding_at: dict[tuple[str, Optional[int]], float] = {}
        self._last_identity_state: Optional[str] = None
        self._last_identity_track_id: Optional[int] = None

    # ============================================================
    # 主线程接口
    # ============================================================
    def start(self, timeout: float = 15.0) -> None:
        """启动工作线程并等待摄像头握手。

        工作线程内 engine.start() 抛出的异常会在这里重新抛给调用线程，
        保持 TrayMonitor.start() 原有的同步报错语义。这是启动期唯一一次
        有界阻塞。
        """
        thread = threading.Thread(target=self._run, name="VisionWorker", daemon=True)
        self._thread = thread
        thread.start()
        if not self._started.wait(timeout):
            self._stop_event.set()
            raise CameraPermissionError(
                f"Camera initialisation did not finish within {timeout:.0f}s."
            )
        if self._start_error is not None:
            raise self._start_error

    def stop(self, join_timeout: float = 2.0) -> None:
        self._stop_event.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(join_timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def is_monitoring_active(self) -> bool:
        return self._mode == MODE_MONITORING and self.is_alive()

    def resume(self) -> None:
        self._mode = MODE_MONITORING
        self._wake.set()

    def pause(self) -> None:
        self._mode = MODE_PAUSED

    def begin_calibration_sampling(self) -> None:
        """Begin the visible five-second preferred-posture stage."""
        self._preferred_cutoff_at = None
        self._mode = MODE_CALIBRATING
        self._commands.put(("begin_calib",))
        self._wake.set()

    def complete_preferred_calibration(self, distance_cm: float) -> int:
        """Close the preferred stage, pause, then silently collect relaxed data.

        The result is published asynchronously after the five-second relaxed
        target window, or after its bounded extension when more valid samples
        are needed. The caller must close the visible countdown before calling
        this method.
        """

        # Stop starting new reads before the UI tells the user to relax. The
        # worker command below installs the transition boundary and resumes
        # calibration on its next command drain.
        transition_started_at = datetime.now()
        self._preferred_cutoff_at = transition_started_at
        self._mode = MODE_PAUSED
        self._calib_request_seq += 1
        request_id = self._calib_request_seq
        self._commands.put(
            ("complete_preferred_calib", float(distance_cm), request_id, transition_started_at)
        )
        self._wake.set()
        return request_id

    def finalize_calibration(self, distance_cm: float, sample_count: int = 1) -> int:
        """Legacy debug/self-test baseline request.

        不足 sample_count 时先补采，平均后 set_baseline。生产科学校准必须走
        begin_calibration_sampling() + complete_preferred_calibration() 的双锚点路径。

        返回 request_id；结果经 take_calibration_result() 回执。
        完成后 worker 进入 paused，由主线程决定是否 resume。
        """
        self._calib_request_seq += 1
        request_id = self._calib_request_seq
        self._commands.put(("finalize_calib", float(distance_cm),
                            max(1, int(sample_count)), request_id))
        self._wake.set()
        return request_id

    def set_capture_fps(self, fps: float) -> None:
        if fps > 0:
            self._target_fps = float(fps)
            self._commands.put(("fps", float(fps)))
            self._wake.set()

    def get_capture_fps(self) -> float:
        return self._target_fps

    def latest(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def take_error(self) -> Optional[Exception]:
        with self._lock:
            error = self._error
            self._error = None
            return error

    def take_calibration_result(self) -> Optional[CalibrationResult]:
        with self._lock:
            result = self._calib_result
            self._calib_result = None
            return result

    # ============================================================
    # 工作线程
    # ============================================================
    def _run(self) -> None:
        engine = None
        try:
            try:
                engine = self._engine_factory()
                engine.start()
                engine.set_capture_fps(self._target_fps)
            except Exception as exc:
                self._start_error = exc
                return
            finally:
                self._started.set()
            self._loop(engine)
        finally:
            if engine is not None:
                try:
                    engine.close()
                except Exception:
                    pass

    def _loop(self, engine) -> None:
        frame_started = time.monotonic()
        while not self._stop_event.is_set():
            self._drain_commands(engine)
            mode = self._mode

            if mode == MODE_MONITORING:
                frame_started = time.monotonic()
                try:
                    sample, target_update = self._read_sample(engine)
                    decision = self.analyzer.evaluate(sample)
                    if target_update is not None:
                        if target_update.state == "IDENTITY_UNCERTAIN":
                            if decision.status == "PROFILE_MISMATCH":
                                self.target_manager.resolve_identity(False)
                            elif decision.status not in {
                                "IDENTITY_UNCERTAIN",
                                "TARGET_AMBIGUOUS",
                                "TARGET_OCCLUDED",
                                "TARGET_REACQUIRING",
                            }:
                                self.target_manager.resolve_identity(True)
                        decision = self._attach_target_context(decision, target_update)
                except Exception as exc:
                    self._publish_error(exc)
                    self._mode = MODE_PAUSED  # 停止产出，等主线程处置
                    continue
                self._publish_snapshot(decision, sample, target_update)
                self._throttle(frame_started)
            elif mode == MODE_CALIBRATING:
                try:
                    sample, _target_update = self._read_sample(engine)
                except Exception as exc:
                    self._publish_error(exc)
                    self._mode = MODE_PAUSED
                    continue
                self._collect_calibration_sample(sample)
                self._stop_event.wait(self.CALIBRATION_INTERVAL_S)
            else:  # paused
                self._wake.wait(0.2)
                self._wake.clear()

    def _drain_commands(self, engine) -> None:
        while True:
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                return

            kind = command[0]
            if kind == "fps":
                try:
                    engine.set_capture_fps(command[1])
                except Exception:
                    pass
            elif kind == "begin_calib":
                self._calib_samples = []
                self._last_usable_sample = None
                self._calibration_missing_fields = set()
                self._calibration_accumulator = CalibrationAccumulator(self._calibration_plan)
                self._dual_calibration_request = None
                self._identity_enrollment_samples = []
                self._identity_enrollment_active = self.identity_verifier is not None
                self._last_identity_embedding_at.clear()
                # A result from the previous session may still finish in the
                # embedding executor. Clear its context so it cannot enter the
                # new calibration template.
                self._identity_embedding_context = None
                if self.identity_verifier is not None:
                    self.identity_verifier.clear_template()
                if self.target_manager is not None:
                    self.target_manager.reset()
            elif kind == "complete_preferred_calib":
                _, distance_cm, request_id, transition_started_at = command
                accumulator = self._calibration_accumulator
                if accumulator is None:
                    self._mode = MODE_PAUSED
                    self._publish_calibration(
                        CalibrationResult(
                            request_id,
                            False,
                            ("calibration_not_started",),
                            failure_reason="calibration_not_started",
                        )
                    )
                    continue
                try:
                    accumulator.begin_transition(transition_started_at)
                except ValueError as exc:
                    self._mode = MODE_PAUSED
                    self._publish_calibration(
                        CalibrationResult(
                            request_id,
                            False,
                            (str(exc),),
                            failure_reason=str(exc),
                        )
                    )
                    continue
                self._dual_calibration_request = (distance_cm, request_id)
                self._mode = MODE_CALIBRATING
            elif kind == "finalize_calib":
                _, distance_cm, sample_count, request_id = command
                self._finalize_calibration(engine, distance_cm, sample_count, request_id)

    def _collect_calibration_sample(self, sample: VisionSample) -> None:
        if getattr(self.analyzer, "require_dual_anchor", False):
            accumulator = self._calibration_accumulator
            if accumulator is None:
                accumulator = CalibrationAccumulator(self._calibration_plan)
                self._calibration_accumulator = accumulator
            phase = accumulator.stage_at(sample.timestamp)
            cutoff = self._preferred_cutoff_at
            if phase == PREFERRED and cutoff is not None and sample.timestamp >= cutoff:
                return
            if phase == TRANSITION:
                return
            rejection = calibration_rejection_reason(sample, self._calibration_plan)
            if rejection is not None:
                if rejection in CALIBRATION_CONTAMINATION_REASONS:
                    accumulator.reject(sample.timestamp, rejection)
                    self._calib_samples = []
                    self._last_usable_sample = None
                    self._reset_identity_enrollment()
                else:
                    accumulator.skip(sample.timestamp, rejection)
                self._calibration_missing_fields.add(rejection)
                self._maybe_finish_dual_anchor(sample.timestamp)
                return
            accumulator.add(
                sample.timestamp,
                calibration_measurement_values(sample, self._calibration_plan),
            )
            self._last_usable_sample = sample
            self._calib_samples.append(sample)
            if len(self._calib_samples) > self.SAMPLE_CAP:
                self._calib_samples = self._calib_samples[-self.SAMPLE_CAP:]
            self._maybe_finish_dual_anchor(sample.timestamp)
            return

        missing_fields = calibration_sample_missing_fields(sample)
        multiple_people = sample.person_count is not None and sample.person_count != 1
        ambiguous_target = sample.target_state in {"MULTI_PRESENT", "TARGET_AMBIGUOUS"}
        if sample.face_count > 1 or multiple_people or ambiguous_target:
            # A second person invalidates the current calibration window. Do
            # not let later averaging hide that contamination.
            self._calib_samples = []
            self._last_usable_sample = None
            self._reset_identity_enrollment()
            missing_fields = tuple(sorted(set(missing_fields) | {"single_person"}))
        self._calibration_missing_fields.update(missing_fields)
        if not missing_fields:
            self._last_usable_sample = sample
            self._calib_samples.append(sample)
            if len(self._calib_samples) > self.SAMPLE_CAP:
                self._calib_samples = self._calib_samples[-self.SAMPLE_CAP:]

    def _maybe_finish_dual_anchor(self, timestamp) -> None:
        accumulator = self._calibration_accumulator
        request = self._dual_calibration_request
        if accumulator is None or request is None or accumulator.phase != RELAXED:
            return
        if not (
            accumulator.ready_to_finalize(timestamp)
            or accumulator.relaxed_deadline_reached(timestamp)
        ):
            return
        distance_cm, request_id = request
        self._finalize_dual_anchor_calibration(distance_cm, request_id)

    def _finalize_calibration(self, engine, distance_cm: float,
                              sample_count: int, request_id: int) -> None:
        if getattr(self.analyzer, "require_dual_anchor", False):
            self._finalize_dual_anchor_calibration(distance_cm, request_id)
            return

        # 样本不足先补采（recalibrate=18 帧；启动校准最少 1 帧、最多再试 8 次，
        # 与旧 _calibrate_from_camera 的 fallback 行为对应）
        attempts_left = max(8, sample_count * 2)
        while (len(self._calib_samples) < sample_count
               and attempts_left > 0
               and not self._stop_event.is_set()):
            attempts_left -= 1
            try:
                sample, _target_update = self._read_sample(engine)
            except Exception as exc:
                self._publish_error(exc)
                self._mode = MODE_PAUSED
                self._publish_calibration(CalibrationResult(request_id, False))
                return
            self._collect_calibration_sample(sample)
            self._stop_event.wait(self.CALIBRATION_INTERVAL_S / 2.0)

        averaged = average_calibration_sample(
            self._calib_samples, fallback=self._last_usable_sample
        )
        ok = False
        if averaged is not None:
            target_ok = (
                self.target_manager.lock_calibration_target()
                if self.target_manager is not None
                else True
            )
            if target_ok:
                try:
                    ok = bool(self.analyzer.set_baseline_from_sample(averaged, distance_cm))
                except Exception:
                    ok = False

        self._calib_samples = []
        self._mode = MODE_PAUSED  # 主线程拿到回执后决定是否 resume
        missing_fields: tuple[str, ...] = ()
        if not ok:
            missing_fields = tuple(sorted(self._calibration_missing_fields))
            if not missing_fields:
                missing_fields = ("complete_sample",)
        self._publish_calibration(CalibrationResult(request_id, ok, missing_fields))

    def _finalize_dual_anchor_calibration(
        self,
        distance_cm: float,
        request_id: int,
    ) -> None:
        accumulator = self._calibration_accumulator
        profile = None
        failure_reason = None
        if accumulator is None:
            failure_reason = "calibration_not_started"
        else:
            try:
                profile = accumulator.finalize()
            except ValueError as exc:
                failure_reason = str(exc)

        target_ok = True
        if profile is not None and self.target_manager is not None:
            target_ok = self.target_manager.lock_calibration_target()
            if not target_ok:
                failure_reason = "target_lock_failed"

        ok = False
        if profile is not None and target_ok:
            try:
                ok = bool(self.analyzer.set_calibration_profile(profile, distance_cm))
            except Exception as exc:
                failure_reason = f"profile_apply_failed:{exc}"

        stage_counts = tuple(
            sorted((accumulator.stage_counts if accumulator is not None else {}).items())
        )
        missing_fields: tuple[str, ...] = ()
        if not ok:
            fields = set(self._calibration_missing_fields)
            if accumulator is not None:
                fields.update(accumulator.failure_fields())
            if failure_reason:
                fields.add(failure_reason)
            missing_fields = tuple(sorted(fields or {"complete_sample"}))
            self._identity_enrollment_samples = []
            self._identity_enrollment_active = False

        self._calib_samples = []
        self._last_usable_sample = None
        self._calibration_accumulator = None
        self._dual_calibration_request = None
        self._preferred_cutoff_at = None
        self._mode = MODE_PAUSED
        self._publish_calibration(
            CalibrationResult(
                request_id=request_id,
                ok=ok,
                missing_fields=missing_fields,
                stage_counts=stage_counts,
                calibration_quality=(profile.calibration_quality if ok and profile else 0.0),
                failure_reason=failure_reason,
            )
        )

    def _throttle(self, frame_started: float) -> None:
        interval = 1.0 / self._target_fps
        elapsed = time.monotonic() - frame_started
        remaining = interval - elapsed
        if remaining > 0:
            self._stop_event.wait(remaining)

    # ---- 信箱写入 ----
    def _read_sample(self, engine) -> tuple[VisionSample, Optional[TargetUpdate]]:
        frame = None
        frame_reader = getattr(engine, "read_frame_sample", None)
        if self.identity_embedding_pipeline is not None and frame_reader is not None:
            frame, sample = frame_reader()
        else:
            sample = engine.read_sample()
        if self.target_manager is None:
            return sample, None
        self._apply_identity_embedding_result()
        self._apply_identity_result()
        provider = getattr(engine, "observations_for_last_sample", None)
        observations = provider() if provider is not None else observation_from_sample(sample)
        target_update = self.target_manager.update(observations, timestamp=sample.timestamp)
        identity_observation = target_update.target_observation
        if identity_observation is None and self._mode == MODE_CALIBRATING:
            eligible = tuple(
                observation
                for observation in observations
                if not observation.association_ambiguous
                and observation.face_bbox_xyxy is not None
            )
            identity_observation = eligible[0] if len(eligible) == 1 else None
        self._schedule_identity_embedding(frame, identity_observation, target_update)
        if target_update.target_observation is not None:
            sample = PostureFeatureExtractor.to_sample(target_update.target_observation)
        sample = replace(
            sample,
            target_track_id=target_update.target_track_id,
            target_state=target_update.state,
            target_observed=target_update.target_observation is not None,
            person_count=target_update.person_count,
            target_reason=target_update.reason,
            target_motion=target_update.target_motion,
            activity_state=target_update.activity_state,
        )
        return sample, target_update

    def _schedule_identity_embedding(
        self,
        frame,
        observation,
        target_update: TargetUpdate,
    ) -> None:
        pipeline = self.identity_embedding_pipeline
        verifier = self.identity_verifier
        if verifier is None or observation is None or observation.face_bbox_xyxy is None:
            self._last_identity_state = target_update.state
            self._last_identity_track_id = target_update.target_track_id
            return
        if observation.association_ambiguous:
            # A face that cannot be attributed to the target body must never
            # enter either enrollment or verification, including embeddings
            # supplied directly by a backend.
            if self._identity_enrollment_active:
                self._reset_identity_enrollment()
            self._last_identity_state = target_update.state
            self._last_identity_track_id = target_update.target_track_id
            return
        if observation.face_embedding is not None:
            self._submit_identity_observation(
                FaceObservation(
                    timestamp=observation.timestamp,
                    bbox_xyxy=observation.face_bbox_xyxy,
                    landmarks=observation.face_landmarks or (),
                    detector_quality=observation.face_quality or 0.0,
                    embedding=observation.face_embedding,
                ),
                target_update,
            )
            return
        if pipeline is None or frame is None or self._identity_embedding_future is not None:
            return

        if self._identity_enrollment_active:
            context = (TRIGGER_EXPLICIT, target_update.target_track_id)
            kind = "enroll"
            interval = 0.0
        else:
            reacquired = (
                self._last_identity_track_id != target_update.target_track_id
                or self._last_identity_state in {
                    "TARGET_REACQUIRING",
                    "AWAY",
                    "TARGET_OCCLUDED",
                }
            )
            trigger = TRIGGER_REACQUIRED if reacquired else TRIGGER_HEARTBEAT
            context = (trigger, target_update.target_track_id)
            kind = "verify"
            interval = (
                verifier.config.min_event_interval_seconds
                if reacquired
                else verifier.config.heartbeat_seconds
            )
        now = self._timestamp_seconds(observation.timestamp)
        previous = self._last_identity_embedding_at.get(context)
        if previous is not None and now - previous < interval:
            return
        try:
            self._identity_embedding_future = pipeline.request(frame, observation)
        except (FaceEmbeddingUnavailable, RuntimeError, ValueError):
            self._last_identity_state = target_update.state
            self._last_identity_track_id = target_update.target_track_id
            return
        self._last_identity_embedding_at[context] = now
        self._identity_embedding_context = (kind, context[0], context[1])
        self._last_identity_state = target_update.state
        self._last_identity_track_id = target_update.target_track_id

    def _submit_identity_observation(
        self,
        face_observation: FaceObservation,
        target_update: TargetUpdate,
    ) -> None:
        verifier = self.identity_verifier
        if verifier is None:
            return
        face_observation = FaceObservation(
            timestamp=face_observation.timestamp,
            bbox_xyxy=face_observation.bbox_xyxy,
            landmarks=face_observation.landmarks,
            detector_quality=face_observation.detector_quality,
            embedding=face_observation.embedding,
        )
        if self._identity_enrollment_active:
            self._identity_enrollment_samples.append(face_observation)
            self._identity_enrollment_samples = self._identity_enrollment_samples[
                -verifier.config.max_frames:
            ]
            if len(self._identity_enrollment_samples) >= verifier.config.min_frames:
                result = verifier.enroll(self._identity_enrollment_samples)
                if result.ok:
                    self._identity_enrollment_active = False
                    self._identity_enrollment_samples = []
            return
        reacquired = (
            self._last_identity_track_id != target_update.target_track_id
            or self._last_identity_state in {"TARGET_REACQUIRING", "AWAY", "TARGET_OCCLUDED"}
        )
        trigger = TRIGGER_REACQUIRED if reacquired else TRIGGER_HEARTBEAT
        future = verifier.request(
            face_observation,
            trigger=trigger,
            track_id=target_update.target_track_id,
        )
        if future is not None:
            self._identity_future = future
        self._last_identity_state = target_update.state
        self._last_identity_track_id = target_update.target_track_id

    def _apply_identity_embedding_result(self) -> None:
        future = self._identity_embedding_future
        if future is None or not future.done():
            return
        context = self._identity_embedding_context
        self._identity_embedding_future = None
        self._identity_embedding_context = None
        try:
            observation = future.result()
        except Exception:
            return
        if context is None:
            return
        kind, trigger, track_id = context
        verifier = self.identity_verifier
        if verifier is None:
            return
        if kind == "enroll":
            if not self._identity_enrollment_active:
                return
            self._identity_enrollment_samples.append(observation)
            self._identity_enrollment_samples = self._identity_enrollment_samples[
                -verifier.config.max_frames:
            ]
            if len(self._identity_enrollment_samples) >= verifier.config.min_frames:
                result = verifier.enroll(self._identity_enrollment_samples)
                if result.ok:
                    self._identity_enrollment_active = False
                    self._identity_enrollment_samples = []
            return
        future = verifier.request(
            observation,
            trigger=trigger,
            track_id=track_id,
            force=True,
        )
        if future is not None:
            self._identity_future = future

    @staticmethod
    def _timestamp_seconds(value) -> float:
        return value.timestamp() if isinstance(value, datetime) else float(value)

    def _reset_identity_enrollment(self) -> None:
        self._identity_enrollment_samples = []
        self._identity_embedding_context = None
        self._last_identity_embedding_at.clear()
        if self.identity_verifier is not None:
            self.identity_verifier.clear_template()

    def _apply_identity_result(self) -> None:
        if self.identity_verifier is None or self.target_manager is None:
            return
        future = self._identity_future
        if future is None or not future.done():
            return
        self._identity_future = None
        try:
            result = future.result()
        except Exception:
            self.target_manager.resolve_identity(None)
            return
        if result.state == IDENTITY_CONFIRMED:
            self.target_manager.resolve_identity(True)
        elif result.state == IDENTITY_MISMATCH:
            self.target_manager.resolve_identity(False)
        else:
            self.target_manager.resolve_identity(None)

    def _publish_snapshot(
        self,
        decision: PostureDecision,
        sample: VisionSample,
        target_update: Optional[TargetUpdate] = None,
    ) -> None:
        with self._lock:
            self._seq += 1
            self._snapshot = Snapshot(
                seq=self._seq,
                decision=decision,
                sample=sample,
                target_update=target_update,
            )

    @staticmethod
    def _attach_target_context(
        decision: PostureDecision,
        target_update: TargetUpdate,
    ) -> PostureDecision:
        """Add tracking metadata without overwriting a more specific reason."""

        return replace(
            decision,
            environment_state=decision.environment_state or target_update.state,
            target_track_id=target_update.target_track_id,
        )

    def _publish_error(self, exc: Exception) -> None:
        with self._lock:
            self._error = exc

    def _publish_calibration(self, result: CalibrationResult) -> None:
        with self._lock:
            self._calib_result = result
