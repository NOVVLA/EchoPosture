# ADR-0005：GA-2.0.0 追加发布不含模型权重的半便携包

- 状态：已接受
- 日期：2026-08-16（Asia/Shanghai）
- 范围：在 `ga-2.0.0` 同一标签下追加第二个发行资产；`docs/RELEASE.md` §4b 的解除条件

## 决策

在已发布的 `ga-2.0.0` 标签下，追加第二个发行资产
`EchoPosture-GA-2.0.0-portable-win-x64.zip`（"半便携包"）。它与 §4a 的纯源码包并存，
不新建标签、不覆盖已发布的源码资产。

半便携包包含：

- 内嵌的 CPython 3.11 运行时（`runtime/python311`），已含 PyQt5、OpenCV、MediaPipe、
  Ultralytics、以及 Professional Beta 所需的 CUDA `torch`/`torchvision`；
- 三个编译后的可执行文件：`EchoPosture.exe`、`EchoPostureSelfTest.exe`、
  `BlurOverlayHost.exe`；
- 全部应用层 `*.py` 模块，包括此前被 §4b 排除在外的 `standard_pose_backend.py`、
  `professional_pose_backend.py` 及其支持模块（`face_body_association.py`、
  `identity_model_adapters.py` 等）；
- `tools/fetch_pose_models/` 四个脚本，供用户在安装后自行获取权重；
- `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md`、`GA_BUILD.txt`、`README_GA.md`、`logo.png`。

半便携包**不包含用户需另行获取的模型**：

- Ultralytics YOLO 姿态权重（`*.pt`）或 CVLFace P5 身份权重（`*.safetensors`）；
- `models/` 目录、CVLFace P5 相关任何内容；
- `.git/`、构建脚本、测试文件、开发文档以外的内部资料。

为保证兼容模式解压即用，运行时仍包含 MediaPipe 包自身要求的 `.tflite` 资源；这些是
第三方运行时组成部分，不是本项目要求用户下载的 YOLO/CVLFace 权重。

用户拿到半便携包后，仍需运行 `tools/fetch_pose_models/` 中的一个脚本获取姿态权重，
才能使用标准模式或专业 Beta 模式；兼容模式无需下载即可使用。这与 §4a 纯源码包对
权重的处理方式完全一致——差异仅在于运行时与可执行文件是否预先内嵌。

## 依据

### 为什么现在可以纳入标准模式与专业 Beta 模式

`docs/RELEASE.md` §4b 原文写明："Before a future package enables Standard mode,
separately approve and add `standard_pose_backend.py`, its tested runtime
dependencies, model provenance/hash, redistribution decision, and notices to
the allowlist。" 本 ADR 即完成这一单独批准：

- 运行时依赖（`ultralytics`、CUDA `torch`/`torchvision`）已实际安装在本机
  `runtime/python311` 中，版本可在其 `dist-info` 目录核实
  （`ultralytics-8.4.120`、`torch-2.13.0+cu130`、`torchvision-0.28.0+cu130`）；
  这与 `docs/vision-evidence/benchmark-professional-20260815.md` 记录的实测基准
  一致。
- 模型来源与哈希已在 ADR-0004 与 `docs/vision-evidence/license-audit.md` 中批准
  （Ultralytics YOLO26n/l/x-pose，`approved`）。
- 再分发决策：本包**不分发**用户需另行获取的 YOLO/CVLFace 权重本身，只分发获取
  YOLO 权重所需的应用代码与校验脚本；因此不产生 ADR-0004 第 1 条所述"内嵌权重"
  的合规缺口。MediaPipe 的运行时资源仅随其依赖一起提供，以保留兼容模式的直接运行能力。
- Notice：`NOTICE`、`THIRD_PARTY_NOTICES.md` 已覆盖 Ultralytics（AGPL-3.0）、
  MediaPipe/OpenCV（Apache-2.0）、PyQt5（GPL-3.0）；本次追加确认这些通知条款
  同样适用于半便携包内嵌的运行时副本。

### 为什么不新建标签

用户明确要求"在同标签下发行"。半便携包与已发布的纯源码包描述的是同一个
`GA-2.0.0` 版本的两种交付形态，而不是两个不同版本；GitHub Release 支持一个
标签下挂载多个资产，因此复用 `ga-2.0.0` 标签、只追加资产，是准确且符合用户
指示的做法。

### 为什么半便携包记录了比标签更新的源码提交

追加半便携包前，本仓库还需要两处不影响已标记版本行为的修正：

1. `launcher/EchoPostureLauncher.cs` 的 ASCII 路径桥标签从遗留的
   `EchoPostureGA121` 改为 `EchoPostureGA200`，避免与仍在分发的 GA-1.2.1 便携包
   共用同一个 `%LOCALAPPDATA%` 目录发生冲突；自检报告标题同步更新为
   `GA-2.0.0 self-test`。
2. `README_EXE.md`、`docs/RELEASE.md` §4b 的文字说明更新，以反映标准模式和
   专业 Beta 模式现已获批进入便携发行的事实。

这些是发布延续性修正，不改变已标记提交 `371fb71` 对应的源码包内容。因此
`ga-2.0.0` 标签继续精确指向 `371fb71`（源码包所对应的提交），而半便携包自身
的 `GA_BUILD.txt` 如实记录其实际构建所依据的、稍晚的提交哈希。两个资产各自
的 `GA_BUILD.txt` 都可独立验证，不需要移动已发布的标签。

## 已核实事实与证据等级

- **已取证**：本机 `runtime/python311` 目录实际内容（`Lib/site-packages` 下
  PyQt5、cv2、mediapipe、ultralytics、torch、torchvision 的 `dist-info` 版本号，
  直接文件系统检查）；目录总大小约 3.9 GB。
- **已取证**：`launcher/EchoPostureLauncher.cs` 中旧标签 `EchoPostureGA121`
  与自检标题 `GA-1.2.1` 的准确出现位置（直接读取源码）。
- **二手证据**：CUDA `torch`/`torchvision` 版本与 Professional Beta 基准测试的
  对应关系依据 `docs/vision-evidence/benchmark-professional-20260815.md` 既有
  记录，本次未重新跑基准复核。

## 待办

1. 若未来 CVLFace P5 阻断解除，需另行评估是否、以何种方式纳入半便携包——本 ADR
   的批准范围**不**扩展到 P5。
2. 若便携包需要独立于源码包升级（例如仅修复运行时问题），应参照本 ADR 的方式
   如实记录该资产自身的构建提交，而不是移动 `ga-2.0.0` 标签。
