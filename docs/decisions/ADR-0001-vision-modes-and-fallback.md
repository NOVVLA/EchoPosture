# ADR-0001：视觉模式、回退顺序与证据门槛

- 状态：Accepted for implementation; release adoption pending P2 evidence gates
- 日期：2026-08-10
- 关联计划：`docs/plans/EchoPosture_vision_identity_upgrade_plan.md`
- 关联任务：EP-VISION-001

## 背景

EchoPosture 需要在不破坏当前 MediaPipe 兼容路径的前提下增加标准模式和专业模式 Beta。模式之间必须共享目标管理、身份状态和风险语义；模型选择不能绕过录像回放、性能和许可证证据。

## 决策

### 模式职责

| 模式 | 姿态后端 | 人脸处理 | 目标设备 | 状态 |
| --- | --- | --- | --- | --- |
| 兼容模式 | 当前 MediaPipe BlazePose Lite | 当前 Face Mesh；事件时可做身份复核 | CPU、无可用 GPU | 现有可运行基线 |
| 标准模式 | YOLO26n-pose；首版使用 Ultralytics PyTorch CPU | 本轮不运行任何人脸、身份模板或 embedding 功能 | 普通 Windows CPU | Debug UI 姿态后端已实现；真实设备与正式 EXE 尚未接入 |
| 专业模式 Beta | YOLO26l/x-pose；优先 TensorRT FP16 | 高质量目标对齐；可选双模型/视频聚合 | RTX 级 GPU | P2 后进入许可和性能验证 |

当前实现边界：正式托盘路径仍使用“兼容模式”（MediaPipe BlazePose Lite + FaceMesh）。Debug UI 已接入
标准姿态后端，专业模式仍仅保留受能力门控的入口；没有对应后端或标准模式依赖/本地权重时，界面会显示
真实原因并恢复兼容后端，不会把兼容后端冒充标准或专业模式。本轮标准模式明确不加载或调用任何人脸验证、
身份模板或 embedding 链路。项目已接受 AGPLv3；真实设备性能和权重再分发证据仍须分别关闭。

模式名是产品契约。当前标准原型固定 `ultralytics==8.4.120` 和本地
`yolo26n-pose.pt` 哈希，但模型文件仍不是获准上传或发行的资产。

### 回退顺序

启动或运行时能力探测按以下顺序执行：

1. 用户选择专业模式且 TensorRT FP16 初始化、显存和短时基准均通过时，使用专业模式。
2. 专业模式不可用时，回退标准模式，并记录机器可读原因（例如 `TENSORRT_UNAVAILABLE`、`MODEL_INIT_FAILED`、`OOM`）。
3. 标准模式不可用时，回退兼容模式，并向用户显示回退原因。
4. 兼容模式也不可用时，安全停止视觉干预并报告摄像头/模型错误；不得把旁人提升为目标。

回退只能降低能力，不能改变 `TargetManager`、身份三态结果或风险状态的语义。回退不得自动下载专业模型。

### 证据门槛

实现或发布任何新模式前必须具备：

- ADR 与实际配置一致；
- `docs/vision-evidence/recording_manifest.csv` 中的录像具有参与者同意、场景标签、保存期限和 SHA-256；
- 指标按 `docs/vision-evidence/metrics-baseline.md` 的协议采集，并同时报告 P50/P95；
- `docs/vision-evidence/license-audit.md` 对代码、精确权重和训练数据分别给出 `verified`、`conditional` 或 `blocked`；
- P1 的远端审核、真实摄像头和打包自检缺口不得被本 ADR 视为已关闭。

## 不在本 ADR 范围内

- 本轮只在 Debug UI 集成 YOLO26n-pose 标准姿态后端；不接入正式 EXE；
- 不集成 AdaFace、CAFace、FaceMesh 裁剪、身份模板或任何 embedding；
- 不实现 TensorRT 专业后端，也不把本地权重纳入发行包；
- 不提交真实人脸录像、原图、裁剪、模板或向量；
- 不把候选模型的仓库许可证解释为其权重或训练数据许可证。

## 后续变更要求

改变模式职责、回退顺序、默认模式或许可证门槛时，必须更新本 ADR、指标基线和开发日志，并提供对应回放/性能/许可证据。
