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

from PyQt5.QtCore import QObject, QTimer

from debug_ui import PostureInterventionOverlay


class GpuBlurOverlayController(QObject):
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
        self._use_fallback = True

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
        if self._gpu_ready:
            return min(1.0, max(0.0, self._host_level))
        return 0.0

    @property
    def mode(self) -> str:
        return self._host_mode

    @property
    def fallback_reason(self) -> Optional[str]:
        return self._host_reason

    @property
    def _gpu_ready(self) -> bool:
        return self._host_mode == "gpu" and self._host_healthy and self._process_is_running()

    def set_warning_active(self, active: bool) -> None:
        self._target_active = active
        if self._process_is_running() and not self._use_fallback:
            self._send({"type": "set_target", "active": active})
            if self._gpu_ready:
                self._fallback.set_warning_active(False)
            return

        if self._process_is_running() and self._host_mode == "starting":
            self._send({"type": "set_target", "active": active})
            self._fallback.set_warning_active(False)
            return

        self._fallback.set_warning_active(active)

    def force_clear(self) -> None:
        self._target_active = False
        self._send({"type": "clear"})
        self._fallback.force_clear()

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

            if self._gpu_ready:
                self._use_fallback = False
                self._fallback.set_warning_active(False)
                self._send({"type": "set_target", "active": self._target_active})
            elif self._host_mode in {"dim_fallback", "disabled"}:
                self._use_fallback = True
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
        self._use_fallback = True
        self._fallback.set_warning_active(self._target_active)


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
