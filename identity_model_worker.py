"""Line-delimited local protocol worker for CVLFace inference."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path


def _write(protocol, payload: dict) -> None:
    protocol.write(json.dumps(payload, separators=(",", ":")) + "\n")
    protocol.flush()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-root")
    args = parser.parse_args()

    # Upstream CVLFace prints model diagnostics to stdout. Reserve the original
    # stream for the protocol and redirect library output away from it.
    protocol = sys.stdout
    sys.stdout = sys.stderr

    try:
        import numpy as np

        from identity_model_adapters import (
            CvlFaceAutoModelAdapter,
            IR101_WEBFACE4M,
            VIT_KPRPE_WEBFACE4M,
        )

        specs = {
            VIT_KPRPE_WEBFACE4M.name: VIT_KPRPE_WEBFACE4M,
            IR101_WEBFACE4M.name: IR101_WEBFACE4M,
        }
        spec = specs[args.model]
        model = CvlFaceAutoModelAdapter(
            spec,
            root=Path(args.model_root) if args.model_root else None,
        )
        model.load()
    except Exception as exc:
        _write(protocol, {"event": "ready", "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    _write(protocol, {"event": "ready", "ok": True, "model": spec.name})
    try:
        for line in sys.stdin:
            request = json.loads(line)
            if request.get("op") == "close":
                break
            request_id = request.get("request_id")
            image = None
            try:
                raw = base64.b64decode(request["image"], validate=True)
                image = np.frombuffer(raw, dtype=np.uint8).copy().reshape((112, 112, 3))
                keypoints = request.get("keypoints")
                points = (
                    tuple((float(x), float(y)) for x, y in keypoints)
                    if keypoints is not None
                    else None
                )
                embedding = model.embed_rgb_image(image, points)
                _write(
                    protocol,
                    {
                        "request_id": request_id,
                        "ok": True,
                        "embedding": embedding,
                    },
                )
            except Exception as exc:
                _write(
                    protocol,
                    {
                        "request_id": request_id,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            finally:
                if image is not None:
                    image.fill(0)
    finally:
        model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
