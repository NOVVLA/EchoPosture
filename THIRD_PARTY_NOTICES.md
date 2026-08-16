# Third-Party Notices

EchoPosture is licensed under the GNU Affero General Public License, version 3
(AGPL-3.0-only). See [LICENSE](LICENSE). This file lists the third-party
software EchoPosture depends on, their licenses, and the attribution each
license requires. It applies to every distribution channel; where a
requirement is specific to a channel (source-only vs. portable), that is
noted explicitly.

None of the entries below are modified by EchoPosture; they are used as
published by their respective authors.

## Ultralytics YOLO26 (pose weights)

- **Component**: `yolo26n-pose.pt`, `yolo26l-pose.pt`, `yolo26x-pose.pt`
- **Source**: <https://github.com/ultralytics/ultralytics> /
  <https://github.com/ultralytics/assets>
- **License**: AGPL-3.0 (per Ultralytics' licensing guidance,
  <https://www.ultralytics.com/license>, pretrained model weights are
  covered by the same AGPL-3.0 terms as the code that produced them)
- **How EchoPosture uses it**: EchoPosture does not bundle these weights.
  `tools/fetch_pose_models/` contains scripts that fetch them, on request,
  directly from the official GitHub release (or a pass-through mirror that
  serves byte-identical content), and verify each file's SHA-256 before
  accepting it. Because EchoPosture's own code is AGPL-3.0-only (see
  [ADR-0003](docs/decisions/ADR-0003-agpl-license-acceptance.md)), running
  these weights inside EchoPosture does not create a licensing conflict.
- **Corresponding source**: this repository, at the commit recorded in
  `GA_BUILD.txt`, is the complete corresponding source for the EchoPosture
  code that loads and runs these weights.

## MediaPipe

- **Source**: <https://github.com/google-ai-edge/mediapipe>
- **License**: Apache License, Version 2.0
- **Copyright**: The MediaPipe Authors
- **How EchoPosture uses it**: installed as the `mediapipe` PyPI package
  declared in `requirements.txt`; not modified or re-published by this
  project. The upstream project does not ship a separate NOTICE file to
  propagate. A future portable channel that bundles the MediaPipe binary
  runtime must include the exact upstream LICENSE file inside the bundled
  copy, per Apache-2.0 §4.

## OpenCV

- **Source**: <https://github.com/opencv/opencv>
- **License**: Apache License, Version 2.0 (as of OpenCV 4.5+)
- **Copyright** (from OpenCV's `COPYRIGHT` file): Intel Corporation
  (2000-2022); Willow Garage Inc. (2009-2011); NVIDIA Corporation
  (2009-2016); Advanced Micro Devices, Inc. (2010-2013); OpenCV Foundation
  (2015-2023); Itseez Inc. (2008-2016); Xperience AI (2019-2023); Shenzhen
  Institute of Artificial Intelligence and Robotics for Society
  (2019-2022); Southern University of Science And Technology (2022-2023);
  OpenCV AI (2023-2025). Third-party copyrights within OpenCV remain the
  property of their respective owners.
- **How EchoPosture uses it**: installed as the `opencv-python` PyPI
  package declared in `requirements.txt`; not modified or re-published by
  this project. The upstream project does not ship a separate NOTICE file
  to propagate. A future portable channel that bundles the OpenCV binary
  runtime must include the exact upstream LICENSE/COPYRIGHT files inside
  the bundled copy, per Apache-2.0 §4.

## PyQt5

- **Source**: <https://www.riverbankcomputing.com/software/pyqt/>
- **License**: GNU General Public License, version 3 (Riverbank Computing
  offers a commercial license as an alternative; EchoPosture does not hold
  one, so PyQt5 is used here under GPLv3)
- **How EchoPosture uses it**: installed as the `PyQt5` PyPI package
  declared in `requirements.txt` to build the tray console UI; not
  modified or re-published by this project. GPLv3 is compatible with
  EchoPosture's own AGPL-3.0-only licensing.

## CVLFace AdaFace models (P5 face-identity) — explicitly NOT distributed

- **Source**: <https://huggingface.co/minchul/cvlface_adaface_ir101_webface4m>,
  <https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m>
- **Status**: **blocked from every EchoPosture distribution channel.** Their
  code is MIT-licensed, but the model cards require downstream users to
  separately comply with the training dataset's (WebFace4M) license, which
  restricts use to academic research and forbids redistribution without
  permission. EchoPosture does not hold such permission, so it does not
  download, mirror, bundle, or provide a fetch script for these weights.
  See [ADR-0004](docs/decisions/ADR-0004-ga-2-0-source-only-distribution.md)
  for the full reasoning. Users who want face-identity features must obtain
  these models themselves, directly from the links above, at their own
  legal risk and responsibility.
