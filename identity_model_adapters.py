"""Offline-first CVLFace/AdaFace model adapters for P5.

The loading pattern follows the official CVLFace model card:
https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m
and https://github.com/mk-minchul/CVLface/blob/main/README_MODELS.md.
Weights are loaded only from a pinned local cache; this module never downloads
or persists camera images.
"""

from __future__ import annotations

import gc
import hashlib
import importlib
import json
import os
import stat
import subprocess
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from identity_verifier import FaceObservation
from windows_runtime_paths import RuntimePathBridgeError, prepare_package_dll_directory


class ModelDependencyError(RuntimeError):
    """Raised when optional Torch/Transformers dependencies are unavailable."""


class ModelCacheError(RuntimeError):
    """Raised when a pinned model cache is incomplete."""


@dataclass(frozen=True)
class CvlFaceModelSpec:
    name: str
    repo_id: str
    revision: str
    architecture: str
    training_data: str
    required_files: Tuple[str, ...]


VIT_KPRPE_WEBFACE4M = CvlFaceModelSpec(
    name="cvlface_adaface_vit_base_kprpe_webface4m",
    repo_id="minchul/cvlface_adaface_vit_base_kprpe_webface4m",
    revision="6530d73fb0af4d1d8287f31d559780c648ebd22a",
    architecture="ViT-Base KP-RPE + AdaFace",
    training_data="WebFace4M",
    required_files=(
        "config.json",
        "wrapper.py",
        "model.safetensors",
        "pretrained_model/model.pt",
        "pretrained_model/model.yaml",
    ),
)

IR101_WEBFACE4M = CvlFaceModelSpec(
    name="cvlface_adaface_ir101_webface4m",
    repo_id="minchul/cvlface_adaface_ir101_webface4m",
    revision="f2b38d9e24bfe301490d8dd081d8924b102333dd",
    architecture="IR101 + AdaFace",
    training_data="WebFace4M",
    required_files=(
        "config.json",
        "wrapper.py",
        "model.safetensors",
        "pretrained_model/model.pt",
        "pretrained_model/model.yaml",
    ),
)

REPOSITORY_MODEL_ROOT = Path(__file__).resolve().parent / "models" / "p5"
LEGACY_DOWNLOAD_MODEL_ROOT = Path(r"D:\Download\EchoPosture-P5\models")
USER_MODEL_ROOT = Path.home() / ".echoposture" / "models" / "p5"
VIT_KPRPE_MANIFEST_PATH = Path(__file__).resolve().parent / "tools" / "vit_kprpe_manifest.json"
_EXECUTABLE_MODEL_SUFFIXES = frozenset(
    (".py", ".pyc", ".pyo", ".pyd", ".so", ".pth", ".dll", ".dylib")
)
_REQUIRED_MANIFEST_FILES = frozenset(("pretrained_model/model.pt", "model.safetensors"))


def default_model_root() -> Path:
    configured = os.environ.get("ECHOPOSTURE_P5_MODEL_ROOT")
    if configured:
        return Path(configured)
    if REPOSITORY_MODEL_ROOT.exists():
        return REPOSITORY_MODEL_ROOT
    if LEGACY_DOWNLOAD_MODEL_ROOT.exists():
        return LEGACY_DOWNLOAD_MODEL_ROOT
    return USER_MODEL_ROOT


def model_path(spec: CvlFaceModelSpec, root: Optional[Path] = None) -> Path:
    return (root or default_model_root()) / spec.name


def missing_model_files(spec: CvlFaceModelSpec, root: Optional[Path] = None) -> Tuple[str, ...]:
    path = model_path(spec, root)
    return tuple(file for file in spec.required_files if not (path / file).is_file())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link_or_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_attribute = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(metadata.st_mode) or bool(file_attributes & reparse_attribute)


def _discover_model_executables(local_path: Path) -> set[str]:
    discovered: set[str] = set()

    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        if _is_link_or_reparse_point(local_path):
            raise ModelCacheError(
                f"Model cache root is a link or reparse point: {local_path}"
            )
        for current_root, directory_names, file_names in os.walk(
            local_path,
            topdown=True,
            onerror=raise_walk_error,
            followlinks=False,
        ):
            current_path = Path(current_root)
            for name in directory_names:
                candidate = current_path / name
                if _is_link_or_reparse_point(candidate):
                    relative_name = candidate.relative_to(local_path).as_posix()
                    raise ModelCacheError(
                        f"Model cache contains a link or reparse point: {relative_name}"
                    )
            for name in file_names:
                candidate = current_path / name
                relative_name = candidate.relative_to(local_path).as_posix()
                if _is_link_or_reparse_point(candidate):
                    raise ModelCacheError(
                        f"Model cache contains a link or reparse point: {relative_name}"
                    )
                if candidate.suffix.lower() in _EXECUTABLE_MODEL_SUFFIXES:
                    discovered.add(relative_name)
    except ModelCacheError:
        raise
    except OSError as exc:
        raise ModelCacheError(f"Cannot safely scan model cache {local_path}: {exc}") from exc
    return discovered


def verify_model_code_integrity(spec: CvlFaceModelSpec, local_path: Path) -> None:
    """Reject model caches without a complete trusted code and weight manifest."""

    if spec != VIT_KPRPE_WEBFACE4M:
        raise ModelCacheError(
            f"No trusted integrity manifest is available for {spec.name}; refusing to load it."
        )
    manifest_path = VIT_KPRPE_MANIFEST_PATH
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelCacheError(
            f"Cannot read trusted ViT KP-RPE manifest: {manifest_path} ({exc})"
        ) from exc
    if (
        manifest.get("schema_version") != 1
        or manifest.get("model") != spec.name
        or manifest.get("model_revision") != spec.revision
        or manifest.get("source_repository") != "mk-minchul/CVLface"
        or manifest.get("source_revision") != "308142aa50adf2e187711354f7524635d3414f1e"
    ):
        raise ModelCacheError(
            f"Trusted ViT KP-RPE manifest metadata is invalid: {manifest_path}"
        )
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise ModelCacheError(
            f"Trusted ViT KP-RPE manifest has no file hashes: {manifest_path}"
        )
    missing_manifest_files = sorted(_REQUIRED_MANIFEST_FILES - files.keys())
    if missing_manifest_files:
        raise ModelCacheError(
            "Trusted ViT KP-RPE manifest does not cover required unsafe-load files: "
            + ", ".join(missing_manifest_files)
        )

    approved_executables: set[str] = set()
    for relative_name, expected_hash in files.items():
        if (
            not isinstance(relative_name, str)
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
        ):
            raise ModelCacheError(
                f"Trusted ViT KP-RPE manifest contains an invalid entry: {relative_name!r}"
            )
        relative_path = Path(relative_name)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ModelCacheError(
                f"Trusted ViT KP-RPE manifest contains an unsafe path: {relative_name}"
            )
        target = local_path / relative_path
        if not target.is_file():
            raise ModelCacheError(f"Trusted model code file is missing: {relative_name}")
        actual_hash = _sha256_file(target)
        if actual_hash != expected_hash.lower():
            raise ModelCacheError(
                f"SHA-256 mismatch for model code '{relative_name}': "
                f"expected {expected_hash.lower()}, actual {actual_hash}"
            )
        normalized_name = relative_path.as_posix()
        if target.suffix.lower() in _EXECUTABLE_MODEL_SUFFIXES:
            approved_executables.add(normalized_name)

    discovered_executables = _discover_model_executables(local_path)
    unapproved_executables = sorted(discovered_executables - approved_executables)
    if unapproved_executables:
        raise ModelCacheError(
            "Unapproved executable files are present in the model cache: "
            + ", ".join(unapproved_executables)
        )


class CvlFaceAutoModelAdapter:
    """Lazy local adapter for a pinned CVLFace repository snapshot."""

    def __init__(
        self,
        spec: CvlFaceModelSpec,
        root: Optional[Path] = None,
        device: str = "cpu",
    ) -> None:
        self.spec = spec
        self.root = root or default_model_root()
        self.device = device
        self._torch: Any = None
        self._model: Any = None

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        local_path = model_path(self.spec, self.root)
        verify_model_code_integrity(self.spec, local_path)
        missing = missing_model_files(self.spec, self.root)
        if missing:
            raise ModelCacheError(
                f"Pinned model cache is incomplete for {self.spec.name}: {', '.join(missing)}"
            )
        try:
            prepare_package_dll_directory("torch")
            import torch
            from transformers import AutoModel
        except (ImportError, OSError, RuntimePathBridgeError) as exc:
            raise ModelDependencyError(
                "P5 model adapter needs optional torch and transformers dependencies with "
                f"loadable native DLLs ({exc})."
            ) from exc
        self._torch = torch
        model_path_text = str(local_path)
        previous_cwd = os.getcwd()
        previous_dont_write_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.path.insert(0, model_path_text)
        try:
            # CVLFace's wrapper opens model.yaml with a relative path.
            # Keep the process-wide cwd change bounded to custom-code loading.
            os.chdir(local_path)
            if "KP-RPE" in self.spec.architecture:
                self._preload_kprpe(local_path)
            self._model = AutoModel.from_pretrained(
                model_path_text,
                local_files_only=True,
                trust_remote_code=True,
            )
        finally:
            os.chdir(previous_cwd)
            sys.path.remove(model_path_text)
            sys.dont_write_bytecode = previous_dont_write_bytecode
        self._model.to(self.device)
        self._model.eval()

    @staticmethod
    def _preload_kprpe(local_path: Path) -> None:
        """Import RPE without letting upstream mutate the user environment."""

        original_check_call = subprocess.check_call

        def reject_upstream_install(command: Any, *_args: Any, **_kwargs: Any) -> None:
            raise subprocess.CalledProcessError(1, command)

        try:
            # The upstream package runs ``setup.py install --user`` during an
            # import when its optional accelerator is absent. Inference has a
            # pure-Python fallback, so product startup must not attempt that
            # process-wide installation.
            subprocess.check_call = reject_upstream_install
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"(?s).*Failed to install `rpe_ops`.*",
                    category=UserWarning,
                )
                importlib.import_module("models.vit_kprpe.RPE")
        except SystemExit as exc:
            raise ModelDependencyError(
                "CVLFace KP-RPE attempted to install a local extension and requested a restart."
            ) from exc
        finally:
            subprocess.check_call = original_check_call
            os.chdir(local_path)

    def embed_tensor(
        self,
        image_tensor: Any,
        keypoints: Optional[Any] = None,
    ) -> Tuple[float, ...]:
        """Run one transient normalized RGB tensor through the local model."""

        if self._model is None or self._torch is None:
            raise RuntimeError("CvlFaceAutoModelAdapter.load() must be called first")
        with self._torch.inference_mode():
            output = self._model(image_tensor, keypoints) if keypoints is not None else self._model(image_tensor)
        if isinstance(output, (tuple, list)):
            output = output[0]
        if hasattr(output, "pooler_output"):
            output = output.pooler_output
        elif hasattr(output, "last_hidden_state"):
            output = output.last_hidden_state[:, 0]
        if getattr(output, "ndim", 1) > 2:
            output = output.flatten(start_dim=1)
        if getattr(output, "ndim", 1) == 1:
            output = output.unsqueeze(0)
        return tuple(float(value) for value in output[0].detach().cpu().flatten().tolist())

    def embed_rgb_image(
        self,
        image_rgb: Any,
        keypoints: Optional[Tuple[Tuple[float, float], ...]] = None,
    ) -> Tuple[float, ...]:
        """Convert one transient 112x112 RGB array using the model's test transform."""

        if self._model is None or self._torch is None:
            raise RuntimeError("CvlFaceAutoModelAdapter.load() must be called first")
        if getattr(image_rgb, "shape", None) != (112, 112, 3):
            raise ValueError("CVLFace input must be a 112x112 RGB image")
        image_tensor = self._torch.as_tensor(image_rgb.copy(), device=self.device)
        image_tensor = image_tensor.permute(2, 0, 1).unsqueeze(0).float()
        image_tensor = image_tensor.div(255.0).sub(0.5).div(0.5)

        keypoint_tensor = None
        needs_keypoints = "KP-RPE" in self.spec.architecture
        if needs_keypoints:
            if keypoints is None or len(keypoints) != 5:
                raise ValueError("CVLFace KP-RPE input requires five face keypoints")
            keypoint_tensor = self._torch.tensor(
                keypoints,
                dtype=image_tensor.dtype,
                device=self.device,
            ).unsqueeze(0)
        return self.embed_tensor(image_tensor, keypoint_tensor)

    def embed(self, observation: FaceObservation) -> Sequence[float]:
        """IdentityVerifier hook for backends that already computed a vector."""

        if observation.embedding is None:
            raise ValueError(
                "raw image tensors are intentionally not stored in FaceObservation; "
                "call embed_tensor() while the crop is transient"
            )
        return observation.embedding

    def close(self) -> None:
        self._model = None
        self._torch = None
        gc.collect()


__all__ = [
    "CvlFaceAutoModelAdapter",
    "CvlFaceModelSpec",
    "IR101_WEBFACE4M",
    "ModelCacheError",
    "ModelDependencyError",
    "VIT_KPRPE_WEBFACE4M",
    "default_model_root",
    "missing_model_files",
    "model_path",
    "verify_model_code_integrity",
]
