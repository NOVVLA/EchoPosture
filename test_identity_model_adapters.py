"""Camera-free checks for the optional CVLFace model adapters."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np

import identity_model_adapters
from identity_model_adapters import (
    CvlFaceAutoModelAdapter,
    IR101_WEBFACE4M,
    VIT_KPRPE_WEBFACE4M,
    missing_model_files,
    model_path,
)
from identity_verifier import FaceObservation


def test_pinned_specs_and_cache_paths() -> None:
    assert len(VIT_KPRPE_WEBFACE4M.revision) == 40
    assert len(IR101_WEBFACE4M.revision) == 40
    root = Path("temporary-p5-models")
    assert model_path(VIT_KPRPE_WEBFACE4M, root) == root / VIT_KPRPE_WEBFACE4M.name
    assert "model.safetensors" in missing_model_files(VIT_KPRPE_WEBFACE4M, root)


def test_adapter_does_not_require_raw_image_storage() -> None:
    adapter = CvlFaceAutoModelAdapter(VIT_KPRPE_WEBFACE4M, Path("temporary-p5-models"))
    observation = FaceObservation(
        timestamp=0.0,
        bbox_xyxy=(0.0, 0.0, 100.0, 100.0),
        embedding=(1.0, 0.0),
    )
    assert tuple(adapter.embed(observation)) == (1.0, 0.0)
    adapter.close()
    assert not adapter.loaded


class _FakeTensor:
    dtype = "float32"

    def permute(self, *_axes):
        return self

    def unsqueeze(self, _axis):
        return self

    def float(self):
        return self

    def div(self, _value):
        return self

    def sub(self, _value):
        return self


class _FakeTorch:
    def __init__(self) -> None:
        self.keypoints = None

    def as_tensor(self, _value, device=None):
        assert device == "cpu"
        return _FakeTensor()

    def tensor(self, value, dtype=None, device=None):
        assert dtype == "float32"
        assert device == "cpu"
        self.keypoints = value
        return _FakeTensor()


def test_rgb_adapter_requires_real_five_points_only_for_kprpe() -> None:
    image = np.zeros((112, 112, 3), dtype=np.uint8)
    points = tuple((0.1 * index, 0.2 * index) for index in range(5))

    vit = CvlFaceAutoModelAdapter(VIT_KPRPE_WEBFACE4M, Path("temporary-p5-models"))
    vit._model = object()
    vit._torch = _FakeTorch()
    captured = {}

    def fake_embed_tensor(image_tensor, keypoints=None):
        captured["image"] = image_tensor
        captured["keypoints"] = keypoints
        return (1.0, 0.0)

    vit.embed_tensor = fake_embed_tensor
    assert vit.embed_rgb_image(image, points) == (1.0, 0.0)
    assert captured["keypoints"] is not None
    try:
        vit.embed_rgb_image(image, points[:3])
    except ValueError as exc:
        assert "five face keypoints" in str(exc)
    else:
        raise AssertionError("KP-RPE must reject incomplete keypoints")

    ir101 = CvlFaceAutoModelAdapter(IR101_WEBFACE4M, Path("temporary-p5-models"))
    ir101._model = object()
    ir101._torch = _FakeTorch()
    ir101.embed_tensor = fake_embed_tensor
    assert ir101.embed_rgb_image(image, None) == (1.0, 0.0)
    assert captured["keypoints"] is None


def test_kprpe_preload_restores_model_root_after_upstream_chdir() -> None:
    model_root = Path.cwd()
    original_import_module = identity_model_adapters.importlib.import_module
    original_check_call = identity_model_adapters.subprocess.check_call
    install_blocked = False

    def fake_import_module(name: str):
        nonlocal install_blocked
        assert name == "models.vit_kprpe.RPE"
        os.chdir(model_root.parent)
        try:
            identity_model_adapters.subprocess.check_call(["setup.py", "install", "--user"])
        except identity_model_adapters.subprocess.CalledProcessError:
            install_blocked = True
        else:
            raise AssertionError("KP-RPE preload must block upstream user-site installation")
        return object()

    identity_model_adapters.importlib.import_module = fake_import_module
    try:
        CvlFaceAutoModelAdapter._preload_kprpe(model_root)
        assert Path.cwd() == model_root
        assert install_blocked
        assert identity_model_adapters.subprocess.check_call is original_check_call
    finally:
        identity_model_adapters.importlib.import_module = original_import_module
        os.chdir(model_root)


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("ALL TESTS PASSED")
