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
            self._process = subprocess.Popen(
                command,
                cwd=str(Path(__file__).resolve().parent),
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=creationflags,
            )
            self._responses = queue.Queue()
            self._reader = threading.Thread(
                target=self._read_responses,
                name="IdentityModelProtocol",
                daemon=True,
            )
            self._reader.start()
            response = self._wait_for_response(self.startup_timeout)
            if not response.get("ok") or response.get("event") != "ready":
                error = response.get("error", "identity model worker did not become ready")
                self._stop_process()
                raise IdentityModelProcessError(str(error))

    def embed_rgb_image(
        self,
        image_rgb: np.ndarray,
        keypoints: Optional[Tuple[Tuple[float, float], ...]] = None,
    ) -> Tuple[float, ...]:
        if image_rgb.shape != (112, 112, 3) or image_rgb.dtype != np.uint8:
            raise ValueError("CVLFace input must be a 112x112 uint8 RGB image")
        with self._lock:
            if not self.loaded:
                raise IdentityModelProcessError("identity model worker is not loaded")
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
                except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                    process.terminate()
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=2.0)
            self._process = None
            self._reader = None

    def _send(self, payload: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise IdentityModelProcessError("identity model worker stdin is unavailable")
        process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def _read_responses(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            try:
                self._responses.put(json.loads(line))
            except json.JSONDecodeError:
                self._responses.put({"ok": False, "error": "invalid identity model protocol output"})
        self._responses.put(
            {
                "ok": False,
                "error": f"identity model worker exited ({process.poll()})",
            }
        )

    def _wait_for_response(self, timeout: float) -> dict:
        try:
            return self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            self._stop_process()
            raise IdentityModelProcessError("identity model worker timed out") from exc

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
        self._reader = None


def create_identity_model_adapter(
    spec: CvlFaceModelSpec = VIT_KPRPE_WEBFACE4M,
):
    """Prefer the isolated configured P5 runtime, then use local dependencies."""

    python_executable = find_identity_model_python()
    if python_executable is not None:
        return CvlFaceProcessAdapter(spec, python_executable=python_executable)
    if importlib.util.find_spec("torch") is not None and importlib.util.find_spec("transformers") is not None:
        return CvlFaceAutoModelAdapter(spec)
    raise IdentityModelProcessError(
        "No usable identity model runtime. Configure ECHOPOSTURE_P5_PYTHON or package runtime/p5/python.exe."
    )


__all__ = [
    "CvlFaceProcessAdapter",
    "IdentityModelProcessError",
    "create_identity_model_adapter",
    "find_identity_model_python",
]
