# ADR-0004：GA-2.0 采用不含模型权重的源码发行

- 状态：已接受
- 日期：2026-08-15（Asia/Shanghai）
- 范围：GA-2.0 发行形态、模型权重获取方式、`models/` 的版本控制策略

## 决策

GA-2.0 以**不含模型权重的源码压缩包**发布，不提供便携包（portable package）。

发行包内提供四个一键脚本，由用户在本机自行获取 Ultralytics YOLO26 姿态权重，均放在
`tools/fetch_pose_models/` 目录下：

- `fetch_pose_models.ps1` —— 官方源（GitHub `ultralytics/assets` release `v8.4.0`），英文界面
- `fetch_pose_models_mirror.ps1` —— 镜像源，供官方源不可达的网络使用，英文界面
- `fetch_pose_models_zh.ps1` —— 官方源的中文本地化版本，行为与英文版一致
- `fetch_pose_models_mirror_zh.ps1` —— 镜像源的中文本地化版本，行为与英文版一致

四个脚本对同一份 SHA-256 做校验，镜像只改变传输路径，语言只改变界面文字，均不改变信任根。

## 依据

### 为什么不发便携包

便携包必然内嵌 `runtime/`，而要让标准模式开箱可用就必须一并内嵌 `yolo26n-pose.pt`。
Ultralytics 许可页明确：其训练所得模型默认受 AGPL-3.0 覆盖，分发衍生作品时需公开
"the complete corresponding source code for the entire derivative work"，并明确包含
"where applicable, model weights"。

ADR-0003 已接受 AGPL-3.0-only，因此**再分发 YOLO 权重本身在许可上是可行的**。不发便携包
不是因为 YOLO 不允许，而是：

1. `docs/RELEASE.md` 既有的便携包流程尚未完成 §4b 要求的权重来源批准、NOTICE 装配与
   相应源码交付验证；在这些补齐前发布内嵌权重的包会造成实际的合规缺口。
2. 由用户自取权重可以让发行包与训练数据条款争议完全脱钩，边界更干净。

因此这是**当前阶段的保守选择**，不是永久结论。补齐 §4b 后可以重新评估便携包。

### 为什么 CVLFace P5 权重被完全阻断

`models/p5/` 下两个 CVLFace AdaFace 模型（IR101 与 ViT KP-RPE）代码与权重标称 MIT，但模型卡
要求使用者遵守训练数据集许可证。其训练集 WebFace4M 是 WebFace260M 的子集，条款为：仅限学术
研究、禁止商业用途、未经许可禁止以任何方式转发或分发、需签署协议并由固定编制责任人签字。

权重是否继承数据集限制在法律上尚无定论，但模型卡那句要求把该不确定性明确转嫁给了下游使用者。
结论：

- 不进入任何发行渠道；
- **也不提供获取脚本**——项目不应帮助用户获取自身无权再分发的权重；
- 现有的 `tools/download_p5_models.ps1` 与 `tools/hydrate_p5_model_code.ps1` 仅作为本地开发
  工具保留，不进入发行包。

要解除阻断只有两条路：向 face-benchmark.org 取得书面再分发许可，或改用训练数据可再分发的
人脸模型。补文档无法解决。

## 版本控制策略

`models/` 已加入 `.gitignore`。此前 `.gitattributes` 中为 `models/p5/**` 配置的 Git LFS 规则
已移除——该规则会在一次 `git add -f` 后把 1.4 GB 受限权重推上公开仓库，且 LFS 历史极难彻底
清除。不得在没有新的许可决策前重新引入。

## 已核实事实与证据等级

- **已取证**：Ultralytics 许可页原文（直接抓取）；`ultralytics/assets` release `v8.4.0` 的
  资产大小与下载地址（GitHub API）；本地三个 pose 权重的 SHA-256 与官方资产大小一致；
  三个 pose 权重（n/l/x）均经 ghfast.top 完整下载并校验，SHA-256 与官方逐字节一致，
  `yolo26n-pose.pt` 另经 gh-proxy.com 复验一致。
- **二手证据**：CVLFace 模型卡与 WebFace4M 条款原文在本机网络下无法直接访问
  （huggingface.co 连接被拒），结论依据搜索结果与本项目既有的
  `docs/vision-evidence/license-audit.md`。法律签字前应复核原文。

## 待办

1. 创建 `NOTICE` 与 `THIRD_PARTY_NOTICES.md`（Ultralytics AGPL-3.0、MediaPipe/OpenCV
   Apache-2.0 及其 NOTICE 转录、PyQt5 GPL-3.0）。既有便携包已发行版本可能缺失 Apache-2.0
   第 4 条要求的 NOTICE 传递，需一并复核。
2. 判断应用是否触发 AGPLv3 第 13 条（网络交互远程用户），若触发需在界面显著提供源码入口。
3. 更新 `docs/vision-evidence/license-audit.md`：YOLO 转为 `approved`（限定文件与哈希），
   CVLFace 维持 `blocked` 并写明阻断理由为训练数据条款。
