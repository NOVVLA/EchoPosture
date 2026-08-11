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
    TRIGGER_HEARTBEAT,
    TRIGGER_REACQUIRED,
)
from vision_tracking import TargetManager, TargetUpdate

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


class VisionWorker:
    """拥有 VisionEngine 与 analyzer 的后台线程。

    主线程接口：start/stop、pause/resume、is_monitoring_active、
    latest（信箱）、take_error / take_calibration_result（一次性回执）、
    begin_calibration_sampling / finalize_calibration、set/get_capture_fps。
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
    ) -> None:
        self._engine_factory = engine_factory
        self.analyzer = analyzer
        self.target_manager = target_manager
        self.identity_verifier = identity_verifier
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
        self._calib_request_seq = 0
        self._identity_future = None
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
        """进入校准采样模式（清空旧样本，按 180ms 间隔在后台累积）。"""
        self._mode = MODE_CALIBRATING
        self._commands.put(("begin_calib",))
        self._wake.set()

    def finalize_calibration(self, distance_cm: float, sample_count: int = 1) -> int:
        """请求定基线：不足 sample_count 时先补采，平均后 set_baseline。

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
                        decision = replace(
                            decision,
                            environment_state=target_update.state,
                            target_track_id=target_update.target_track_id,
                        )
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
                if self.target_manager is not None:
                    self.target_manager.reset()
            elif kind == "finalize_calib":
                _, distance_cm, sample_count, request_id = command
                self._finalize_calibration(engine, distance_cm, sample_count, request_id)

    def _collect_calibration_sample(self, sample: VisionSample) -> None:
        missing_fields = calibration_sample_missing_fields(sample)
        multiple_people = sample.person_count is not None and sample.person_count != 1
        ambiguous_target = sample.target_state in {"MULTI_PRESENT", "TARGET_AMBIGUOUS"}
        if sample.face_count > 1 or multiple_people or ambiguous_target:
            # A second person invalidates the current calibration window. Do
            # not let later averaging hide that contamination.
            self._calib_samples = []
            self._last_usable_sample = None
            missing_fields = tuple(sorted(set(missing_fields) | {"single_person"}))
        self._calibration_missing_fields.update(missing_fields)
        if not missing_fields:
            self._last_usable_sample = sample
            self._calib_samples.append(sample)
            if len(self._calib_samples) > self.SAMPLE_CAP:
                self._calib_samples = self._calib_samples[-self.SAMPLE_CAP:]

    def _finalize_calibration(self, engine, distance_cm: float,
                              sample_count: int, request_id: int) -> None:
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

    def _throttle(self, frame_started: float) -> None:
        interval = 1.0 / self._target_fps
        elapsed = time.monotonic() - frame_started
        remaining = interval - elapsed
        if remaining > 0:
            self._stop_event.wait(remaining)

    # ---- 信箱写入 ----
    def _read_sample(self, engine) -> tuple[VisionSample, Optional[TargetUpdate]]:
        sample = engine.read_sample()
        if self.target_manager is None:
            return sample, None
        self._apply_identity_result()
        provider = getattr(engine, "observations_for_last_sample", None)
        observations = provider() if provider is not None else observation_from_sample(sample)
        target_update = self.target_manager.update(observations, timestamp=sample.timestamp)
        self._request_identity_check(target_update)
        if target_update.target_observation is not None:
            sample = PostureFeatureExtractor.to_sample(target_update.target_observation)
        sample = replace(
            sample,
            target_track_id=target_update.target_track_id,
            target_state=target_update.state,
            target_observed=target_update.target_observation is not None,
            person_count=target_update.person_count,
            target_reason=target_update.reason,
        )
        return sample, target_update

    def _request_identity_check(self, target_update: TargetUpdate) -> None:
        verifier = self.identity_verifier
        observation = target_update.target_observation
        if verifier is None or observation is None or observation.face_bbox_xyxy is None:
            self._last_identity_state = target_update.state
            self._last_identity_track_id = target_update.target_track_id
            return
        face_observation = FaceObservation(
            timestamp=observation.timestamp,
            bbox_xyxy=observation.face_bbox_xyxy,
            landmarks=observation.face_landmarks or (),
            detector_quality=observation.face_quality or 0.0,
            embedding=observation.face_embedding,
        )
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

    def _publish_error(self, exc: Exception) -> None:
        with self._lock:
            self._error = exc

    def _publish_calibration(self, result: CalibrationResult) -> None:
        with self._lock:
            self._calib_result = result
