# ADR-0006: GA-2.0 半便携图形安装器与权重来源选择

- 状态：Accepted
- 日期：2026-08-17
- 适用版本：GA-2.0.0
- 关联：[ADR-0005](ADR-0005-ga-2-0-portable-standard-professional.md)

## 决策

GA-2.0.0 半便携包通过一个始终显示的 Windows Forms 安装器交付。安装器下载、校验、
重组并解压项目官方 GitHub Release 中的三个程序分片。程序、运行时和所有可分发内容只有
这一个项目官方来源；不通过 GitHub 代理、第三方镜像或权重镜像传输。

安装器中的“模型权重下载来源”选择**仅影响用户主动获取的 Ultralytics YOLO 姿态权重**。
安装器在用户选择语言、权重范围和官方/镜像来源并确认许可说明后，调用已有的对应脚本：

| 语言 | 权重来源 | 脚本 |
|---|---|---|
| English | 官方 | `fetch_pose_models.ps1` |
| English | 镜像优先 | `fetch_pose_models_mirror.ps1` |
| 中文 | 官方 | `fetch_pose_models_zh.ps1` |
| 中文 | 镜像优先 | `fetch_pose_models_mirror_zh.ps1` |

安装器传入 `-Yes -Tier <Standard|Professional|All> -DestinationRoot <安装目录\models\pose>`。
`-Yes` 只在安装器本身已展示说明并取得用户确认后使用。脚本退出码是成功与否的事实来源；
安装器不根据输出文本提前判定成功。

CVLFace 权重继续受 ADR-0005 的禁止条款约束：本安装器不下载、不镜像、不分发。

## 传输与可审计性

已验证的 `EchoPosture-GA-2.0.0-portable-win-x64.zip` 按 `1,000,000,000` 字节切分为三个 Release 资产。
安装器内嵌可信清单，固定项目官方 URL、每个分片的大小和 SHA-256，以及重组 ZIP 的
SHA-256。网络上的 JSON 清单只供公开审计，不取代安装器内嵌的信任根。

安装器源码可以在已发布标签之后追加到 `main`，但不得移动已公布的 `ga-2.0.0` 标签。
公开清单分别记录应用源码标签提交与安装器源码提交。

## 用户可见行为

- 安装器不需要管理员权限，默认安装到当前用户目录，不写入系统卸载注册项。
- 下载、校验、解压和权重脚本输出始终显示在界面中。
- 成功、失败或取消后都不自动退出；只有用户主动点击才关闭。
- 权重下载失败不回滚已校验的程序安装；界面明确告知 Compatibility 模式仍可运行。
- 安装器与现有启动 EXE 均未代码签名，公开文档需提示 SmartScreen 并公布完整摘要。

## 已发布资产证据

`ga-2.0.0` Release 现已追加以下六个资产；程序分片均为官方 GitHub Release 下载，权重来源选择不适用于
它们：

| 资产 | 大小 | SHA-256 |
|---|---:|---|
| `EchoPosture-GA-2.0.0-semi-portable-setup.exe` | 52,224 | `fc5de97df3fbd31c337fb6775947c21968beba7be3ad553b9a23a6292940975e` |
| `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.001` | 1,000,000,000 | `3a76ed1e17787f6f188aded0b26deecea7659d41c41a9c52845033a59e801994` |
| `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.002` | 1,000,000,000 | `9354260cbc18c3ed01113adcb9252b3d7cc04088601a717da7548af7c3cdaf63` |
| `EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.003` | 313,314,546 | `cecea0f3ea30a480ae51057fdfd95195292e088aab19dd79db7d30f9871c9d2b` |
| `EchoPosture-GA-2.0.0-semi-portable-manifest.json` | 1,641 | `e1a384313e32af41780c9167f5836000ca5a95bc356002f6d1808dbb9ac1d77e` |
| `EchoPosture-GA-2.0.0-semi-portable-SHA256SUMS.txt` | 582 | `fbbd52357f7c174699a22b588c92491cbba56655abb29904e8f5b5c6e706429b` |

The reconstructed program ZIP remains `2,313,314,546` bytes with SHA-256
`353a7880a07ec7885e1f1fe0d902e75f8c67a67754129586ea827c5579c262c1`. The installer embeds the same manifest as the
public JSON, and the PE certificate table is absent (unsigned). The installed package contains no `.pt`,
`.safetensors`, or `.onnx` files; MediaPipe runtime `.tflite` resources are the only model-format runtime assets.

Because some supported hosts expose a minimal Windows PowerShell without `Get-FileHash`, the installer invokes the
selected existing weight script through a hidden process-local .NET compatibility wrapper. It does not modify the
script, change the source mapping, or make the program download path indirect.
