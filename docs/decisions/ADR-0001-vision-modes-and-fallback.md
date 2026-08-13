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
| 标准模式 | YOLO26n-pose ONNX Runtime CPU（候选） | 只对锁定目标的脸部裁剪运行 Face Mesh/Face Landmarker | 普通 Windows CPU | P2 后进入原型验证 |
| 专业模式 Beta | YOLO26l/x-pose；优先 TensorRT FP16 | 高质量目标对齐；可选双模型/视频聚合 | RTX 级 GPU | P2 后进入许可和性能验证 |

当前实现边界：正式托盘路径仍使用“兼容模式”（MediaPipe BlazePose Lite + FaceMesh）。标准/专业模式在
Debug UI 中已预留并受能力门控；没有对应姿态后端时，选择会显示不可用原因，不会静默把兼容后端冒充标准
或专业模式。标准模式的人脸验证接线已支持官方 CVLFace 112x112 RGB 输入、ArcFace 五点对齐和内存
embedding，但标准姿态后端、真实权重运行、性能和许可证证据仍未关闭。

模式名是产品契约。候选模型名不是已批准的依赖，直到精确版本、权重和许可证记录齐全。

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

- 不集成 YOLO、AdaFace、CAFace 或任何新模型；
- 不实现 YOLO/TensorRT 姿态后端、真实摄像头性能证据或发行许可审计；
- 不提交真实人脸录像、原图、裁剪、模板或向量；
- 不把候选模型的仓库许可证解释为其权重或训练数据许可证。

## 后续变更要求

改变模式职责、回退顺序、默认模式或许可证门槛时，必须更新本 ADR、指标基线和开发日志，并提供对应回放/性能/许可证据。
