# EchoPosture GA-2.0.0

GA-2.0.0 remains a public, source-first release under the existing immutable `ga-2.0.0`
tag. This release now also provides a semi-portable graphical installer for Windows.

## Semi-portable graphical installer

The installer remains visible during download, verification, extraction, weight-script
execution, success, partial success, failure, and cancellation. It downloads the EchoPosture
program, embedded runtime, and all other distributable content only from the official
`NOVVLA/EchoPosture` GitHub Release. The program is never fetched through a third-party proxy.

The installer's selectable **model weight download source** applies only to the separately
downloaded YOLO pose weights. It selects one of the existing four scripts after the user
chooses language and tier:

| Language | Weight source | Script |
| --- | --- | --- |
| English | Official | `fetch_pose_models.ps1` |
| English | Mirror priority | `fetch_pose_models_mirror.ps1` |
| 中文 | 官方 | `fetch_pose_models_zh.ps1` |
| 中文 | 镜像优先 | `fetch_pose_models_mirror_zh.ps1` |

The installer requires explicit model-license consent before running a weight script. A mirror
is a third-party transport proxy; every downloaded file is still checked against the pinned
official SHA-256. Choosing Compatibility mode skips all weight scripts and leaves the installed
program runnable without additional YOLO weights.

CVLFace P5 weights are not bundled, mirrored, downloaded, or implied to be supplied. The
Professional Beta limitations remain in force. MediaPipe's dependency-owned `.tflite` runtime
resources are included because Compatibility mode requires them; they are not user-downloadable
YOLO/CVLFace weights.

## Published assets

- `EchoPosture-GA-2.0.0-semi-portable-setup.exe` — 52,224 bytes
- `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.001` — 1,000,000,000 bytes
- `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.002` — 1,000,000,000 bytes
- `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.003` — 313,314,546 bytes
- `EchoPosture-GA-2.0.0-semi-portable-manifest.json`
- `EchoPosture-GA-2.0.0-semi-portable-SHA256SUMS.txt`

The original semi-portable ZIP is retained locally as the fixed audit baseline: 2,313,314,546
bytes, SHA-256
`353a7880a07ec7885e1f1fe0d902e75f8c67a67754129586ea827c5579c262c1`. It is reconstructed from
the three official Release parts; it is not uploaded as a single over-2-GiB Release asset.

The installer embeds the trusted part manifest and checks each part before reconstruction,
then checks the complete ZIP before extraction. The public manifest records application source
commit `371fb71b2bc20834608f1edd59d1de4fd88b3126`, installer source commit
`3cfd5533a2b53dcf8711f4f2e6d79249bb9732bf`, and the `ga-2.0.0` release URL.

## Notices

The installer and existing EchoPosture executables are unsigned and may trigger Windows
SmartScreen. Verify the published SHA-256SUMS before running them. The source archive remains
available and unchanged; the `ga-2.0.0` tag was not moved. No `.pt`, `.safetensors`, or `.onnx`
weights are included in the semi-portable program package.
