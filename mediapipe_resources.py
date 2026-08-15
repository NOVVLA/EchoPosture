"""Prepare an ASCII MediaPipe resource root for its Windows C++ loader."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType


class MediaPipeResourcePathError(RuntimeError):
    """Raised when MediaPipe resources cannot be exposed through an ASCII path."""


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return False
    return True


def _create_junction(link: Path, target: Path) -> None:
    command = (
        "& { param($link, $target) "
        "New-Item -ItemType Junction -Path $link -Target $target -ErrorAction Stop | Out-Null }"
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
            str(link),
            str(target),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    if completed.returncode != 0:
        detail = " ".join((completed.stderr or completed.stdout).split())
        raise OSError(detail or f"junction command exited {completed.returncode}")


def ensure_ascii_mediapipe_resource_path(mp_module: ModuleType) -> Path:
    """Return an ASCII package root and point solution_base at that root."""

    package_dir = Path(mp_module.__file__).resolve().parent
    if _is_ascii_path(package_dir):
        return package_dir

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    if not local_app_data or not _is_ascii_path(local_app_data):
        raise MediaPipeResourcePathError(
            "MediaPipe is installed under a non-ASCII path and LOCALAPPDATA does not provide "
            "an ASCII bridge location."
        )
    fingerprint = hashlib.sha256(str(package_dir).encode("utf-8")).hexdigest()[:12]
    bridge_parent = local_app_data / "EchoPosture" / "mediapipe-resources" / fingerprint
    bridge_site_packages = bridge_parent / "site-packages"
    bridged_package = bridge_site_packages / "mediapipe"
    expected_graph = (
        bridged_package
        / "modules"
        / "face_landmark"
        / "face_landmark_front_cpu.binarypb"
    )
    bridge_parent.mkdir(parents=True, exist_ok=True)

    errors = []
    if not expected_graph.is_file() and not bridge_site_packages.exists():
        try:
            _create_junction(bridge_site_packages, package_dir.parent)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"junction: {exc}")
    if not expected_graph.is_file():
        try:
            bridged_package.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(package_dir, bridged_package, dirs_exist_ok=True)
        except OSError as exc:
            errors.append(f"copy: {exc}")
    if not expected_graph.is_file():
        detail = "; ".join(errors) or "bridge did not expose the expected graph"
        raise MediaPipeResourcePathError(
            "MediaPipe resources exist, but its Windows C++ loader cannot read the non-ASCII "
            f"installation path and the ASCII bridge failed ({detail})."
        )

    from mediapipe.python import solution_base

    solution_base.__file__ = str(bridged_package / "python" / "solution_base.py")
    return bridged_package


__all__ = ["MediaPipeResourcePathError", "ensure_ascii_mediapipe_resource_path"]
