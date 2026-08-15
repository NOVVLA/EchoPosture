"""Isolated local process adapter for the pinned CVLFace identity model."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np

from identity_model_adapters import (
    CvlFaceAutoModelAdapter,
    CvlFaceModelSpec,
    VIT_KPRPE_WEBFACE4M,
)
from identity_verifier import FaceObservation


class IdentityModelProcessError(RuntimeError):
    """Raised when the isolated identity model process cannot serve a request."""


class _IdentityModelProcessUnavailable(IdentityModelProcessError):
    """Raised for transport failures that can be recovered by restarting once."""


_STDERR_MAX_LINES = 100
_STDERR_MAX_LINE_CHARS = 4096


def find_identity_model_python(repository_root: Optional[Path] = None) -> Optional[Path]:
    """Find the dedicated P5 interpreter without mixing its Torch into the app."""

    configured = os.environ.get("ECHOPOSTURE_P5_PYTHON")
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_file() else None

    root = repository_root or Path(__file__).resolve().parent
    candidates = (
        root / "runtime" / "p5" / "python.exe",
        root / ".venv-p5" / "Scripts" / "python.exe",
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


class CvlFaceProcessAdapter:
    """Keep CVLFace's pinned dependencies in a persistent local subprocess."""

    def __init__(
        self,
        spec: CvlFaceModelSpec = VIT_KPRPE_WEBFACE4M,
        *,
        python_executable: Path,
        model_root: Optional[Path] = None,
        service_script: Optional[Path] = None,
        startup_timeout: float = 60.0,
        request_timeout: float = 30.0,
    ) -> None:
        self.spec = spec
        self.python_executable = Path(python_executable)
        self.model_root = model_root
        self.service_script = service_script or Path(__file__).with_name("identity_model_worker.py")
        self.startup_timeout = float(startup_timeout)
        self.request_timeout = float(request_timeout)
        self._process: Optional[subprocess.Popen[str]] = None
        self._responses: "queue.Queue[dict]" = queue.Queue()
        self._reader: Optional[threading.Thread] = None
        self._stderr_reader: Optional[threading.Thread] = None
        self._stderr_lines: deque[str] = deque(maxlen=_STDERR_MAX_LINES)
        self._lock = threading.Lock()
        self._next_request_id = 0

    @property
    def loaded(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def load(self) -> None:
        with self._lock:
            if self.loaded:
                return
            self._stop_process()
            if not self.python_executable.is_file():
                raise IdentityModelProcessError(
                    f"P5 Python interpreter not found: {self.python_executable}"
                )
            if not self.service_script.is_file():
                raise IdentityModelProcessError(
                    f"Identity model worker not found: {self.service_script}"
                )
            command = [
                str(self.python_executable),
                "-u",
                str(self.service_script),
                "--model",
                self.spec.name,
            ]
            if self.model_root is not None:
                command.extend(("--model-root", str(self.model_root)))
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            environment = os.environ.copy()
            environment["PYTHONNOUSERSITE"] = "1"
            repository_root = Path(__file__).resolve().parent
            existing_pythonpath = environment.get("PYTHONPATH")
            environment["PYTHONPATH"] = (
                str(repository_root)
                if not existing_pythonpath
                else os.pathsep.join((str(repository_root), existing_pythonpath))
            )
            self._responses = queue.Queue()
            self._stderr_lines = deque(maxlen=_STDERR_MAX_LINES)
            try:
                self._process = subprocess.Popen(
                    command,
                    cwd=str(repository_root),
                    env=environment,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=creationflags,
                )
            except OSError as exc:
                self._process = None
                raise IdentityModelProcessError(
                    f"Could not start identity model worker with {self.python_executable}: {exc}"
                ) from exc
            process = self._process
            responses = self._responses
            stderr_lines = self._stderr_lines
            self._reader = threading.Thread(
                target=self._read_responses,
                args=(process, responses),
                name="IdentityModelProtocol",
                daemon=True,
            )
            self._stderr_reader = threading.Thread(
                target=self._read_stderr,
                args=(process, stderr_lines),
                name="IdentityModelStderr",
                daemon=True,
            )
            self._reader.start()
            self._stderr_reader.start()
            response = self._wait_for_response(self.startup_timeout)
            if not response.get("ok") or response.get("event") != "ready":
                message = str(
                    response.get("error", "identity model worker did not become ready")
                )
                self._stop_process()
                error = self._with_stderr(message)
                raise IdentityModelProcessError(error)

    def embed_rgb_image(
        self,
        image_rgb: np.ndarray,
        keypoints: Optional[Tuple[Tuple[float, float], ...]] = None,
    ) -> Tuple[float, ...]:
        if image_rgb.shape != (112, 112, 3) or image_rgb.dtype != np.uint8:
            raise ValueError("CVLFace input must be a 112x112 uint8 RGB image")
        original_error: Optional[_IdentityModelProcessUnavailable] = None
        for _attempt in range(2):
            try:
                return self._embed_rgb_image_once(image_rgb, keypoints)
            except _IdentityModelProcessUnavailable as exc:
                if original_error is not None:
                    raise original_error from exc
                original_error = exc
                time.sleep(0.1)
                try:
                    self.load()
                except IdentityModelProcessError as retry_error:
                    raise original_error from retry_error
            except IdentityModelProcessError as exc:
                if original_error is not None:
                    raise original_error from exc
                raise
        raise original_error or IdentityModelProcessError("identity model request failed")

    def _embed_rgb_image_once(
        self,
        image_rgb: np.ndarray,
        keypoints: Optional[Tuple[Tuple[float, float], ...]],
    ) -> Tuple[float, ...]:
        with self._lock:
            if not self.loaded:
                raise _IdentityModelProcessUnavailable("identity model worker is not loaded")
            self._next_request_id += 1
            request_id = self._next_request_id
            payload = {
                "op": "embed",
                "request_id": request_id,
                "image": base64.b64encode(image_rgb.tobytes()).decode("ascii"),
                "keypoints": keypoints,
            }
            self._send(payload)
            response = self._wait_for_response(self.request_timeout)
            if response.get("request_id") != request_id:
                raise IdentityModelProcessError("identity model protocol response mismatch")
            if not response.get("ok"):
                raise IdentityModelProcessError(str(response.get("error", "embedding failed")))
            embedding = tuple(float(value) for value in response.get("embedding", ()))
            if not embedding:
                raise IdentityModelProcessError("identity model returned an empty embedding")
            return embedding

    def embed(self, observation: FaceObservation) -> Sequence[float]:
        if observation.embedding is None:
            raise ValueError("face observation has no precomputed embedding")
        return observation.embedding

    def close(self) -> None:
        with self._lock:
            process = self._process
            if process is None:
                return
            if process.poll() is None:
                try:
                    self._send({"op": "close"})
                    process.wait(timeout=5.0)
                except (IdentityModelProcessError, subprocess.TimeoutExpired):
                    pass
            self._stop_process()

    def _send(self, payload: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            self._stop_process()
            raise _IdentityModelProcessUnavailable(
                "identity model worker stdin is unavailable"
            )
        returncode = process.poll()
        if returncode is not None:
            self._stop_process()
            error = self._with_stderr(
                f"identity model worker crashed (exit code {returncode})"
            )
            raise _IdentityModelProcessUnavailable(error)
        try:
            process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            returncode = process.poll()
            self._stop_process()
            error = self._with_stderr(
                "identity model worker pipe failed"
                if returncode is None
                else f"identity model worker crashed (exit code {returncode})"
            )
            raise _IdentityModelProcessUnavailable(error) from exc

    @staticmethod
    def _read_responses(
        process: subprocess.Popen[str],
        responses: "queue.Queue[dict]",
    ) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            try:
                responses.put(json.loads(line))
            except json.JSONDecodeError:
                responses.put(
                    {
                        "event": "protocol_error",
                        "ok": False,
                        "error": "invalid identity model protocol output",
                    }
                )
        try:
            returncode = process.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            returncode = process.poll()
        responses.put(
            {
                "event": "exited",
                "ok": False,
                "returncode": returncode,
            }
        )

    @staticmethod
    def _read_stderr(
        process: subprocess.Popen[str],
        stderr_lines: deque[str],
    ) -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip("\r\n")[-_STDERR_MAX_LINE_CHARS:])

    def _wait_for_response(self, timeout: float) -> dict:
        try:
            response = self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            self._stop_process()
            error = self._with_stderr("identity model worker timed out")
            raise _IdentityModelProcessUnavailable(error) from exc
        if response.get("event") == "exited":
            returncode = response.get("returncode")
            self._stop_process()
            message = (
                "identity model worker closed its protocol output unexpectedly"
                if returncode is None
                else f"identity model worker crashed (exit code {returncode})"
            )
            error = self._with_stderr(message)
            raise _IdentityModelProcessUnavailable(error)
        if response.get("event") == "protocol_error":
            self._stop_process()
            error = self._with_stderr(str(response["error"]))
            raise IdentityModelProcessError(error)
        return response

    def _with_stderr(self, message: str) -> str:
        lines = [line for line in self._stderr_lines if line]
        if not lines:
            return message
        return message + "\nRecent worker stderr:\n" + "\n".join(lines)

    def _stop_process(self) -> None:
        process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        self._process = None
        current_thread = threading.current_thread()
        for thread in (self._reader, self._stderr_reader):
            if thread is not None and thread is not current_thread:
                thread.join(timeout=0.5)
        self._reader = None
        self._stderr_reader = None


def create_identity_model_adapter(
    spec: CvlFaceModelSpec = VIT_KPRPE_WEBFACE4M,
):
    """Prefer the isolated P5 runtime; require an opt-in for in-process code."""

    python_executable = find_identity_model_python()
    if python_executable is not None:
        return CvlFaceProcessAdapter(spec, python_executable=python_executable)
    if os.environ.get("ECHOPOSTURE_ALLOW_INPROCESS_MODEL") == "1":
        if importlib.util.find_spec("torch") is not None and importlib.util.find_spec("transformers") is not None:
            return CvlFaceAutoModelAdapter(spec)
        raise IdentityModelProcessError(
            "ECHOPOSTURE_ALLOW_INPROCESS_MODEL=1 is set, but torch and transformers "
            "are not available in the main application environment."
        )
    raise IdentityModelProcessError(
        "No isolated P5 Python interpreter is available. Configure ECHOPOSTURE_P5_PYTHON, "
        "package runtime/p5/python.exe, or explicitly allow main-process custom-code loading "
        "with ECHOPOSTURE_ALLOW_INPROCESS_MODEL=1."
    )


__all__ = [
    "CvlFaceProcessAdapter",
    "IdentityModelProcessError",
    "create_identity_model_adapter",
    "find_identity_model_python",
]
