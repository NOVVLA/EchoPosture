"""Camera-free checks for the optional CVLFace model adapters."""

from __future__ import annotations

from pathlib import Path

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


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("ALL TESTS PASSED")
