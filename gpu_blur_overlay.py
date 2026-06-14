"""
GPU blur overlay controller.

The native host owns capture and rendering. This Python layer only controls
the target state and keeps the existing PyQt dim overlay as a fallback.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from debug_ui import PostureInterventionOverlay


class GpuBlurOverlayController(QObject):
    screen_capture_warning = pyqtSignal(str)

    def __init__(self, enabled: bool = True) -> None:
        super().__init__()
        self._fallback = PostureInterventionOverlay()
        self._target_active = False
        self._closed = False
        self._status_queue: "queue.Queue[str]" = queue.Queue()
        self._process: Optional[subprocess.Popen[str]] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._host_started_at = 0.0
        self._last_status_at = 0.0
        self._last_heartbeat_at = 0.0
        self._host_mode = "disabled"
        self._host_healthy = False
        self._host_reason: Optional[str] = None
        self._host_level = 0.0
        self._host_fps = 0.0
        self._host_blur_available = False
        self._use_fallback = True
        self._screen_capture_warning_reason: Optional[str] = None
        self._max_dim_alpha = 0.32
        self._blur_scale = 1.0
        # IPC 去重：set_warning_active 现在被主循环周期性调用，只有目标
        # 状态/配置真正变化时才写管道，避免无意义的高频 IPC。
        self._last_sent_target: Optional[bool] = None
        self._config_dirty = True
        self._fallback.set_visual_config(self._max_dim_alpha, self._blur_scale)

        if enabled:
            self._start_host()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_host)
        self._timer.start(250)

    @property
    def dim_level(self) -> float:
        if self._gpu_ready:
            return min(1.0, max(0.0, self._host_level))
        return self._fallback.dim_level

    @property
    def blur_level(self) -> float:
        if self._gpu_ready and self._host_blur_available:
            return min(1.0, max(0.0, self._host_level * self._blur_scale))
        return self._fallback.blur_level

    @property
    def mode(self) -> str:
        return self._host_mode

    @property
    def fallback_reason(self) -> Optional[str]:
        return self._host_reason

    @property
    def screen_capture_warning_reason(self) -> Optional[str]:
        return self._screen_capture_warning_reason

    @property
    def _gpu_ready(self) -> bool:
        return self._host_mode == "gpu" and self._host_healthy and self._process_is_running()

    def set_warning_active(self, active: bool) -> None:
        self._target_active = active
        if self._process_is_running() and not self._use_fallback:
            self._send_visual_config()
            self._send_target(active)
            if self._gpu_ready:
                self._fallback.force_clear()
            return

        if self._process_is_running() and self._host_mode == "starting":
            self._send_target(active)
            self._fallback.force_clear()
            return

        self._fallback.set_warning_active(active)

    def _send_target(self, active: bool) -> None:
        if self._last_sent_target == active:
            return
        self._last_sent_target = active
        self._send({"type": "set_target", "active": active})

    def set_visual_config(self, max_dim_alpha: float, blur_scale: float) -> None:
        self._max_dim_alpha = min(0.85, max(0.0, float(max_dim_alpha)))
        self._blur_scale = min(1.0, max(0.0, float(blur_scale)))
        self._config_dirty = True
        self._fallback.set_visual_config(self._max_dim_alpha, self._blur_scale)
        self._send_visual_config()

    @property
    def max_dim_alpha(self) -> float:
        return self._max_dim_alpha

    @property
    def blur_scale(self) -> float:
        return self._blur_scale

    def force_clear(self) -> None:
        self._target_active = False
        self._last_sent_target = False  # clear 即目标关闭；下次开启必须重发
        self._send({"type": "clear"})
        self._fallback.force_clear()

    def trigger_max_effect(self) -> None:
        self._target_active = True
        self._last_sent_target = True   # boost 即目标开启；下次关闭必须重发
        if self._process_is_running() and not self._use_fallback:
            self._send_visual_config()
            self._send({"type": "boost"})
            if self._gpu_ready:
                self._fallback.force_clear()
            return
        if self._process_is_running() and self._host_mode == "starting":
            self._send_visual_config()
            self._send({"type": "boost"})
            self._fallback.force_clear()
            return

        self._fallback.trigger_max_effect()

    def close(self) -> None:
        self._closed = True
        self.force_clear()
        self._send({"type": "shutdown"})
        self._fallback.close()

        process = self._process
        self._process = None
        if process is None:
            return

        try:
            process.wait(timeout=0.8)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    def _start_host(self) -> None:
        host_path = self._find_host_path()
        if host_path is None:
            self._host_mode = "dim_fallback"
            self._host_reason = "BlurOverlayHost.exe was not found"
            self._use_fallback = True
            return

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._process = subprocess.Popen(
                [str(host_path), "--parent-pid", str(os.getpid())],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=creationflags,
            )
        except OSError as exc:
            self._host_mode = "dim_fallback"
            self._host_reason = f"BlurOverlayHost.exe failed to start: {exc}"
            self._use_fallback = True
            return

        self._host_started_at = time.monotonic()
        self._last_status_at = 0.0
        self._last_heartbeat_at = 0.0
        self._host_mode = "starting"
        self._host_healthy = False
        self._host_reason = None
        self._use_fallback = False

        self._reader_thread = threading.Thread(target=self._read_host_stdout, daemon=True)
        self._reader_thread.start()

    def _find_host_path(self) -> Optional[Path]:
        candidates = [
            Path.cwd() / "BlurOverlayHost.exe",
            Path(__file__).resolve().parent / "BlurOverlayHost.exe",
            Path(__file__).resolve().parent / "native" / "BlurOverlayHost.exe",
        ]
        for path in candidates:
            if path.exists():
                return path
        return None

    def _read_host_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return

        try:
            for line in process.stdout:
                if line:
                    self._status_queue.put(line.strip())
        finally:
            self._status_queue.put("__host_eof__")

    def _poll_host(self) -> None:
        if self._closed:
            return

        self._drain_status_queue()
        self._refresh_process_state()
        self._send_heartbeat()

    def _drain_status_queue(self) -> None:
        while True:
            try:
                line = self._status_queue.get_nowait()
            except queue.Empty:
                break

            if line == "__host_eof__":
                if not self._closed:
                    self._enter_fallback("BlurOverlayHost.exe exited")
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue

            if message.get("type") != "status":
                continue

            self._last_status_at = time.monotonic()
            self._host_mode = str(message.get("mode", "disabled"))
            self._host_healthy = bool(message.get("healthy", False))
            self._host_reason = message.get("reason")
            self._host_level = float(message.get("level") or 0.0)
            self._host_fps = float(message.get("fps") or 0.0)
            self._host_blur_available = bool(message.get("blur_available", False))

            if self._gpu_ready:
                self._use_fallback = False
                self._fallback.force_clear()
                # 主机恢复/首次就绪：强制重发配置与目标状态
                self._config_dirty = True
                self._last_sent_target = None
                self._send_visual_config()
                self._send_target(self._target_active)
            elif self._host_mode in {"dim_fallback", "disabled"}:
                self._use_fallback = True
                if self._host_reason:
                    self._maybe_report_screen_capture_warning(str(self._host_reason))
                self._fallback.set_warning_active(self._target_active)

    def _refresh_process_state(self) -> None:
        if not self._process_is_running():
            if self._process is not None and not self._closed:
                self._enter_fallback("BlurOverlayHost.exe stopped")
            return

        now = time.monotonic()
        if self._host_mode == "starting" and now - self._host_started_at > 3.0:
            self._shutdown_host()
            self._enter_fallback("BlurOverlayHost.exe did not report healthy status")

    def _send_heartbeat(self) -> None:
        if not self._process_is_running() or self._use_fallback:
            return

        now = time.monotonic()
        if now - self._last_heartbeat_at < 0.5:
            return

        self._last_heartbeat_at = now
        self._send({"type": "heartbeat"})

    def _send_visual_config(self) -> None:
        if not self._process_is_running() or self._use_fallback:
            return
        if not self._config_dirty:
            return
        self._config_dirty = False
        self._send(
            {
                "type": "set_config",
                "max_dim": self._max_dim_alpha,
                "blur": self._blur_scale,
            }
        )

    def _send(self, message: dict) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            return

        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except Exception as exc:
            if not self._closed:
                self._enter_fallback(f"BlurOverlayHost.exe pipe failed: {exc}")

    def _process_is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _shutdown_host(self) -> None:
        process = self._process
        if process is None:
            return

        self._send({"type": "shutdown"})
        try:
            process.wait(timeout=0.5)
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
        self._process = None

    def _enter_fallback(self, reason: str) -> None:
        self._host_mode = "dim_fallback"
        self._host_healthy = False
        self._host_reason = reason
        self._host_level = 0.0
        self._host_blur_available = False
        self._use_fallback = True
        self._maybe_report_screen_capture_warning(reason)
        self._fallback.set_warning_active(self._target_active)

    def _maybe_report_screen_capture_warning(self, reason: str) -> None:
        if self._screen_capture_warning_reason is not None:
            return
        if not self._looks_like_screen_capture_failure(reason):
            return
        self._screen_capture_warning_reason = reason
        self.screen_capture_warning.emit(reason)

    @staticmethod
    def _looks_like_screen_capture_failure(reason: str) -> bool:
        lowered = reason.lower()
        capture_terms = (
            "desktop capture",
            "desktop duplication",
            "duplicateoutput",
            "gdi capture",
            "bitblt",
            "self-capture",
            "acquirenextframe",
            "acquireframe",
            "capture fallback",
        )
        return any(term in lowered for term in capture_terms)


def run_host_self_test(timeout_seconds: float = 8.0) -> tuple[bool, str]:
    host = _find_host_path_static()
    if host is None:
        return False, "BlurOverlayHost.exe was not found"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            [str(host), "--self-test"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            creationflags=creationflags,
        )
    except Exception as exc:
        return False, str(exc)

    output = (result.stdout or "").strip()
    if result.stderr:
        output = (output + "\n" + result.stderr.strip()).strip()
    return result.returncode == 0, output


def _find_host_path_static() -> Optional[Path]:
    candidates = [
        Path.cwd() / "BlurOverlayHost.exe",
        Path(__file__).resolve().parent / "BlurOverlayHost.exe",
        Path(__file__).resolve().parent / "native" / "BlurOverlayHost.exe",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None
