"""Offline-first CVLFace/AdaFace model adapters for P5.

The loading pattern follows the official CVLFace model card:
https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m
and https://github.com/mk-minchul/CVLface/blob/main/README_MODELS.md.
Weights are loaded only from a pinned local cache; this module never downloads
or persists camera images.
"""

from __future__ import annotations

import gc
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Tuple

from identity_verifier import FaceObservation


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


def default_model_root() -> Path:
    configured = os.environ.get("ECHOPOSTURE_P5_MODEL_ROOT")
    if configured:
        return Path(configured)
    repository_root = Path(__file__).resolve().parent / "models" / "p5"
    if repository_root.exists():
        return repository_root
    download_root = Path(r"D:\Download\EchoPosture-P5\models")
    if download_root.exists():
        return download_root
    return Path("runtime") / "models"


def model_path(spec: CvlFaceModelSpec, root: Optional[Path] = None) -> Path:
    return (root or default_model_root()) / spec.name


def missing_model_files(spec: CvlFaceModelSpec, root: Optional[Path] = None) -> Tuple[str, ...]:
    path = model_path(spec, root)
    return tuple(file for file in spec.required_files if not (path / file).is_file())


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
        missing = missing_model_files(self.spec, self.root)
        if missing:
            raise ModelCacheError(
                f"Pinned model cache is incomplete for {self.spec.name}: {', '.join(missing)}"
            )
        try:
            import torch
            from transformers import AutoModel
        except ImportError as exc:
            raise ModelDependencyError(
                "P5 model adapter needs optional torch and transformers dependencies."
            ) from exc
        local_path = model_path(self.spec, self.root)
        self._torch = torch
        model_path_text = str(local_path)
        previous_cwd = os.getcwd()
        sys.path.insert(0, model_path_text)
        try:
            # CVLFace's wrapper opens model.yaml with a relative path.
            # Keep the process-wide cwd change bounded to custom-code loading.
            os.chdir(local_path)
            self._model = AutoModel.from_pretrained(
                model_path_text,
                local_files_only=True,
                trust_remote_code=True,
            )
        finally:
            os.chdir(previous_cwd)
            sys.path.remove(model_path_text)
        self._model.to(self.device)
        self._model.eval()

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
]
