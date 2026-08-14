"""Windows runtime path bridges for native Python dependencies."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import os
import subprocess
from pathlib import Path
from typing import Optional


class RuntimePathBridgeError(RuntimeError):
    """Raised when a native dependency cannot be exposed through an ASCII path."""


_DLL_DIRECTORY_HANDLES: list[object] = []
_PRELOADED_DLL_HANDLES: list[object] = []


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
    try:
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
    except subprocess.SubprocessError as exc:
        raise OSError(str(exc)) from exc
    if completed.returncode != 0:
        detail = " ".join((completed.stderr or completed.stdout).split())
        raise OSError(detail or f"junction command exited {completed.returncode}")


def ensure_ascii_directory_bridge(directory: Path, namespace: str) -> Path:
    """Return *directory* or a stable ASCII junction to it on Windows."""

    target = directory.resolve()
    if os.name != "nt" or _is_ascii_path(target):
        return target

    local_app_data_text = os.environ.get("LOCALAPPDATA", "")
    local_app_data = Path(local_app_data_text)
    if not local_app_data_text or not _is_ascii_path(local_app_data):
        raise RuntimePathBridgeError(
            "LOCALAPPDATA does not provide an ASCII location for native DLL loading."
        )

    fingerprint = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:12]
    bridge_parent = local_app_data / "EchoPosture" / "runtime-paths" / namespace / fingerprint
    bridge = bridge_parent / "current"
    bridge_parent.mkdir(parents=True, exist_ok=True)
    if not bridge.is_dir():
        try:
            _create_junction(bridge, target)
        except OSError as exc:
            raise RuntimePathBridgeError(
                f"Could not create an ASCII DLL path bridge for {target}: {exc}"
            ) from exc
    if not bridge.is_dir():
        raise RuntimePathBridgeError(
            f"ASCII DLL path bridge does not expose the expected directory: {bridge}"
        )
    return bridge


def prepare_package_dll_directory(
    package_name: str,
    relative_directory: str = "lib",
) -> Optional[Path]:
    """Register an ASCII DLL search directory without importing the package."""

    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return None
    spec = importlib.util.find_spec(package_name)
    locations = tuple(spec.submodule_search_locations or ()) if spec is not None else ()
    if not locations:
        raise RuntimePathBridgeError(f"Python package {package_name!r} is not installed.")
    dll_directory = Path(locations[0]) / relative_directory
    if not dll_directory.is_dir():
        raise RuntimePathBridgeError(
            f"Native DLL directory is missing for {package_name!r}: {dll_directory}"
        )
    search_directory = ensure_ascii_directory_bridge(
        dll_directory,
        f"{package_name}-dlls",
    )
    try:
        handle = os.add_dll_directory(str(search_directory))
    except OSError as exc:
        raise RuntimePathBridgeError(
            f"Windows rejected DLL directory {search_directory}: {exc}"
        ) from exc
    _DLL_DIRECTORY_HANDLES.append(handle)
    return search_directory


def preload_package_dll(
    package_name: str,
    dll_name: str,
    relative_directory: str = "lib",
) -> Optional[Path]:
    """Load one DLL early, before another native GUI stack claims its dependencies."""

    search_directory = prepare_package_dll_directory(package_name, relative_directory)
    if search_directory is None:
        return None
    dll_path = search_directory / dll_name
    if not dll_path.is_file():
        raise RuntimePathBridgeError(f"Native DLL is missing: {dll_path}")
    try:
        handle = ctypes.WinDLL(str(dll_path))
    except OSError as exc:
        raise RuntimePathBridgeError(f"Could not preload native DLL {dll_path}: {exc}") from exc
    _PRELOADED_DLL_HANDLES.append(handle)
    return dll_path


__all__ = [
    "RuntimePathBridgeError",
    "ensure_ascii_directory_bridge",
    "preload_package_dll",
    "prepare_package_dll_directory",
]
