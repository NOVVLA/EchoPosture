"""Camera-free checks for the optional CVLFace model adapters."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np

import identity_model_adapters
import identity_model_process
from identity_model_adapters import (
    CvlFaceAutoModelAdapter,
    IR101_WEBFACE4M,
    ModelCacheError,
    VIT_KPRPE_WEBFACE4M,
    default_model_root,
    missing_model_files,
    model_path,
    verify_model_code_integrity,
)
from identity_model_process import (
    CvlFaceProcessAdapter,
    IdentityModelProcessError,
    create_identity_model_adapter,
    find_identity_model_python,
)
from identity_verifier import FaceObservation


def test_pinned_specs_and_cache_paths() -> None:
    assert len(VIT_KPRPE_WEBFACE4M.revision) == 40
    assert len(IR101_WEBFACE4M.revision) == 40
    root = Path("temporary-p5-models")
    assert model_path(VIT_KPRPE_WEBFACE4M, root) == root / VIT_KPRPE_WEBFACE4M.name
    assert "model.safetensors" in missing_model_files(VIT_KPRPE_WEBFACE4M, root)


def test_default_model_root_fallback_is_absolute_and_cwd_independent() -> None:
    original_environment = os.environ.pop("ECHOPOSTURE_P5_MODEL_ROOT", None)
    original_repository_root = identity_model_adapters.REPOSITORY_MODEL_ROOT
    original_download_root = identity_model_adapters.LEGACY_DOWNLOAD_MODEL_ROOT
    with tempfile.TemporaryDirectory() as temporary_directory:
        missing_root = Path(temporary_directory) / "missing"
        try:
            identity_model_adapters.REPOSITORY_MODEL_ROOT = missing_root / "repository"
            identity_model_adapters.LEGACY_DOWNLOAD_MODEL_ROOT = missing_root / "download"
            expected = identity_model_adapters.USER_MODEL_ROOT
            assert default_model_root() == expected
            assert default_model_root().is_absolute()
        finally:
            identity_model_adapters.REPOSITORY_MODEL_ROOT = original_repository_root
            identity_model_adapters.LEGACY_DOWNLOAD_MODEL_ROOT = original_download_root
            if original_environment is not None:
                os.environ["ECHOPOSTURE_P5_MODEL_ROOT"] = original_environment


def test_vit_integrity_rejects_tampering_and_unapproved_executables() -> None:
    original_manifest_path = identity_model_adapters.VIT_KPRPE_MANIFEST_PATH
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        wrapper = root / "wrapper.py"
        approved = root / "models" / "vit_kprpe" / "approved.py"
        weight = root / "pretrained_model" / "model.pt"
        safetensors = root / "model.safetensors"
        approved.parent.mkdir(parents=True)
        weight.parent.mkdir(parents=True)
        wrapper.write_text("trusted wrapper\n", encoding="utf-8")
        approved.write_text("trusted module\n", encoding="utf-8")
        weight.write_bytes(b"trusted pickle weight fixture")
        safetensors.write_bytes(b"trusted safetensors weight fixture")
        manifest = {
            "schema_version": 1,
            "model": VIT_KPRPE_WEBFACE4M.name,
            "model_revision": VIT_KPRPE_WEBFACE4M.revision,
            "source_repository": "mk-minchul/CVLface",
            "source_revision": "308142aa50adf2e187711354f7524635d3414f1e",
            "files": {
                "wrapper.py": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
                "models/vit_kprpe/approved.py": hashlib.sha256(
                    approved.read_bytes()
                ).hexdigest(),
                "pretrained_model/model.pt": hashlib.sha256(
                    weight.read_bytes()
                ).hexdigest(),
                "model.safetensors": hashlib.sha256(
                    safetensors.read_bytes()
                ).hexdigest(),
            },
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        identity_model_adapters.VIT_KPRPE_MANIFEST_PATH = manifest_path
        try:
            verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)

            approved.write_text("tampered module\n", encoding="utf-8")
            try:
                verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)
            except ModelCacheError as exc:
                assert "SHA-256 mismatch" in str(exc)
                assert "models/vit_kprpe/approved.py" in str(exc)
            else:
                raise AssertionError("tampered custom code must be rejected")

            approved.write_text("trusted module\n", encoding="utf-8")
            weight.write_bytes(b"tampered pickle weight fixture")
            try:
                verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)
            except ModelCacheError as exc:
                assert "SHA-256 mismatch" in str(exc)
                assert "pretrained_model/model.pt" in str(exc)
            else:
                raise AssertionError("tampered pickle weights must be rejected")

            weight.write_bytes(b"trusted pickle weight fixture")
            executable_suffixes = (".py", ".pyc", ".pyo", ".pyd", ".so", ".pth", ".dll")
            for suffix in executable_suffixes:
                rogue = root / f"yaml{suffix}"
                rogue.write_bytes(b"unapproved executable content")
                try:
                    verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)
                except ModelCacheError as exc:
                    assert "Unapproved" in str(exc)
                    assert rogue.name in str(exc)
                else:
                    raise AssertionError(f"unapproved {suffix} file must be rejected")
                rogue.unlink()

            external = root.parent / f"{root.name}-external.py"
            linked = root / "linked.py"
            external.write_text("raise RuntimeError\n", encoding="utf-8")
            try:
                linked.symlink_to(external)
            except OSError:
                pass
            else:
                try:
                    verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)
                except ModelCacheError as exc:
                    assert "link or reparse point" in str(exc)
                    assert "linked.py" in str(exc)
                else:
                    raise AssertionError("model-cache links must be rejected")
            finally:
                external.unlink(missing_ok=True)
        finally:
            identity_model_adapters.VIT_KPRPE_MANIFEST_PATH = original_manifest_path


def test_vit_manifest_must_cover_pickle_weight() -> None:
    original_manifest_path = identity_model_adapters.VIT_KPRPE_MANIFEST_PATH
    with tempfile.TemporaryDirectory() as temporary_directory:
        root = Path(temporary_directory)
        wrapper = root / "wrapper.py"
        wrapper.write_text("trusted wrapper\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "model": VIT_KPRPE_WEBFACE4M.name,
            "model_revision": VIT_KPRPE_WEBFACE4M.revision,
            "source_repository": "mk-minchul/CVLface",
            "source_revision": "308142aa50adf2e187711354f7524635d3414f1e",
            "files": {
                "wrapper.py": hashlib.sha256(wrapper.read_bytes()).hexdigest(),
            },
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        identity_model_adapters.VIT_KPRPE_MANIFEST_PATH = manifest_path
        try:
            try:
                verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, root)
            except ModelCacheError as exc:
                assert "pretrained_model/model.pt" in str(exc)
                assert "manifest" in str(exc)
            else:
                raise AssertionError("pickle weights must be covered by the manifest")
        finally:
            identity_model_adapters.VIT_KPRPE_MANIFEST_PATH = original_manifest_path


def test_ir101_without_trusted_manifest_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        try:
            verify_model_code_integrity(IR101_WEBFACE4M, Path(temporary_directory))
        except ModelCacheError as exc:
            assert IR101_WEBFACE4M.name in str(exc)
            assert "No trusted integrity manifest" in str(exc)
        else:
            raise AssertionError("IR101 must fail closed without a trusted manifest")


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


def test_identity_model_python_discovery_honors_explicit_runtime() -> None:
    original = os.environ.get("ECHOPOSTURE_P5_PYTHON")
    try:
        os.environ["ECHOPOSTURE_P5_PYTHON"] = sys.executable
        assert find_identity_model_python() == Path(sys.executable)
    finally:
        if original is None:
            os.environ.pop("ECHOPOSTURE_P5_PYTHON", None)
        else:
            os.environ["ECHOPOSTURE_P5_PYTHON"] = original


def test_inprocess_model_fallback_requires_explicit_opt_in() -> None:
    original_allow = os.environ.pop("ECHOPOSTURE_ALLOW_INPROCESS_MODEL", None)
    original_find_python = identity_model_process.find_identity_model_python
    original_find_spec = identity_model_process.importlib.util.find_spec
    identity_model_process.find_identity_model_python = lambda: None
    identity_model_process.importlib.util.find_spec = lambda _name: object()
    try:
        try:
            create_identity_model_adapter()
        except IdentityModelProcessError as exc:
            assert "No isolated P5 Python interpreter" in str(exc)
            assert "ECHOPOSTURE_ALLOW_INPROCESS_MODEL=1" in str(exc)
        else:
            raise AssertionError("in-process model loading must be disabled by default")

        os.environ["ECHOPOSTURE_ALLOW_INPROCESS_MODEL"] = "1"
        assert isinstance(create_identity_model_adapter(), CvlFaceAutoModelAdapter)
    finally:
        identity_model_process.find_identity_model_python = original_find_python
        identity_model_process.importlib.util.find_spec = original_find_spec
        if original_allow is None:
            os.environ.pop("ECHOPOSTURE_ALLOW_INPROCESS_MODEL", None)
        else:
            os.environ["ECHOPOSTURE_ALLOW_INPROCESS_MODEL"] = original_allow


def test_isolated_process_protocol_returns_embedding_and_closes() -> None:
    service_source = """
import json
import os
import sys
from pathlib import Path

repository_root = str(Path.cwd())
pythonpath_entries = os.environ.get("PYTHONPATH", "").split(os.pathsep)
ready = repository_root in pythonpath_entries
print(json.dumps({"event": "ready", "ok": ready, "error": "missing repository PYTHONPATH"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("op") == "close":
        break
    print(json.dumps({
        "request_id": request["request_id"],
        "ok": True,
        "embedding": [3.0, 4.0],
    }), flush=True)
"""
    with tempfile.TemporaryDirectory() as temporary_directory:
        service_script = Path(temporary_directory) / "fake_identity_worker.py"
        service_script.write_text(service_source, encoding="utf-8")
        adapter = CvlFaceProcessAdapter(
            VIT_KPRPE_WEBFACE4M,
            python_executable=Path(sys.executable),
            service_script=service_script,
            startup_timeout=5.0,
            request_timeout=5.0,
        )
        adapter.load()
        assert adapter.loaded
        embedding = adapter.embed_rgb_image(
            np.zeros((112, 112, 3), dtype=np.uint8),
            tuple((0.1 * index, 0.2 * index) for index in range(5)),
        )
        assert embedding == (3.0, 4.0)
        adapter.close()
        assert not adapter.loaded


def test_send_rejects_exited_worker_before_writing() -> None:
    class DeadProcess:
        stdin = object()

        @staticmethod
        def poll():
            return 23

    adapter = CvlFaceProcessAdapter(python_executable=Path(sys.executable))
    adapter._process = DeadProcess()
    try:
        adapter._send({"op": "embed"})
    except IdentityModelProcessError as exc:
        assert "worker crashed (exit code 23)" in str(exc)
        assert adapter._process is None
    else:
        raise AssertionError("an exited worker must be rejected before writing")


def test_isolated_process_recovers_once_after_worker_crash() -> None:
    service_source = """
import json
import os
import sys
from pathlib import Path

marker = Path(__file__).with_suffix(".marker")
print(json.dumps({"event": "ready", "ok": True}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("op") == "close":
        break
    if not marker.exists():
        marker.write_text("crashed", encoding="utf-8")
        print("Traceback: simulated first worker crash", file=sys.stderr, flush=True)
        os._exit(7)
    print(json.dumps({
        "request_id": request["request_id"],
        "ok": True,
        "embedding": [5.0, 12.0],
    }), flush=True)
"""
    with tempfile.TemporaryDirectory() as temporary_directory:
        service_script = Path(temporary_directory) / "recovering_identity_worker.py"
        service_script.write_text(service_source, encoding="utf-8")
        adapter = CvlFaceProcessAdapter(
            python_executable=Path(sys.executable),
            service_script=service_script,
            startup_timeout=5.0,
            request_timeout=5.0,
        )
        try:
            adapter.load()
            embedding = adapter.embed_rgb_image(
                np.zeros((112, 112, 3), dtype=np.uint8),
            )
            assert embedding == (5.0, 12.0)
            assert adapter.loaded
        finally:
            adapter.close()


def test_worker_crash_reports_exit_code_and_recent_stderr() -> None:
    service_source = """
import json
import os
import sys

print(json.dumps({"event": "ready", "ok": True}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("op") == "close":
        break
    print("Traceback: simulated permanent worker crash", file=sys.stderr, flush=True)
    os._exit(7)
"""
    with tempfile.TemporaryDirectory() as temporary_directory:
        service_script = Path(temporary_directory) / "crashing_identity_worker.py"
        service_script.write_text(service_source, encoding="utf-8")
        adapter = CvlFaceProcessAdapter(
            python_executable=Path(sys.executable),
            service_script=service_script,
            startup_timeout=5.0,
            request_timeout=5.0,
        )
        try:
            adapter.load()
            try:
                adapter.embed_rgb_image(np.zeros((112, 112, 3), dtype=np.uint8))
            except IdentityModelProcessError as exc:
                message = str(exc)
                assert "worker crashed (exit code 7)" in message
                assert "Traceback: simulated permanent worker crash" in message
                assert "protocol response mismatch" not in message
            else:
                raise AssertionError("worker crash must fail the request")
        finally:
            adapter.close()


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_") and callable(test):
            test()
    print("ALL TESTS PASSED")
