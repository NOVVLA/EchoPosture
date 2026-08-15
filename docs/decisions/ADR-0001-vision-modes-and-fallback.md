# ADR-0001：视觉模式、回退顺序与证据门槛

- 状态：Accepted for implementation; source Standard prototype implemented; release adoption pending evidence gates
- 日期：2026-08-10
- 更新：2026-08-14（同步跨模式人脸/身份边界与 Standard 源码原型）
- 关联计划：`docs/plans/EchoPosture_vision_identity_upgrade_plan.md`
- 关联任务：EP-VISION-001

## 背景

EchoPosture 需要在不破坏当前 MediaPipe 兼容路径的前提下增加标准模式和专业模式 Beta。模式之间必须共享目标管理、身份状态和风险语义；模型选择不能绕过录像回放、性能和许可证证据。

## 决策

### 模式职责

| 模式 | 姿态后端 | 人脸处理 | 目标设备 | 状态 |
| --- | --- | --- | --- | --- |
| 兼容模式 | 当前 MediaPipe BlazePose Lite（单骨架） | 共用 BlazeFace、脸身归属、目标 FaceMesh 五点和事件触发 CVLFace 复核 | CPU、无可用 GPU | 正式托盘/EXE 的现有基线；错配时安全暂停，不提供真正的多人骨架连续追踪 |
| 标准模式 | YOLO26n-pose；首版使用 Ultralytics PyTorch CPU | 原始姿态输出经相同 `FaceEnhancedBackend` 和 CVLFace 身份边界增强 | 普通 Windows CPU | Debug UI 多人姿态原型已实现；真实设备与正式 EXE 尚未接入 |
| 专业模式 Beta | YOLO26l/x-pose；优先 TensorRT FP16 | 高质量目标对齐；可选双模型/视频聚合 | RTX 级 GPU | P2 后进入许可和性能验证 |

当前实现边界：正式托盘路径仍固定使用“兼容模式”，源码 Debug UI 已接入 Standard 多人姿态后端。
BlazeFace 提供真实人脸框、检测分数和场景人数；脸与人体必须通过统一的一对一归属边界，归属不明确时进入
安全暂停。兼容模式仍不能为每位入镜者分别输出骨架：若 BlazePose 改为追踪闯入者，它只能拒绝把该观测
当成原目标，不能继续追踪已被挤出单骨架结果的用户。Standard 为每位检测人物分别输出人体框、17 点骨架、
置信度和姿态特征，再由同一个 `TargetManager` 选择校准目标。

Debug UI 为 Compatibility 和 Standard 的原始姿态后端统一套用 `FaceEnhancedBackend`。该边界执行 BlazeFace、
脸身归属和目标 FaceMesh 五点提取，并在本地隔离运行时可用时向 CVLFace 提交事件触发的异步身份复核。
几何量只决定归属与轨迹关联，只有 CVLFace 结果可以确认或拒绝身份。帧、裁剪、会话模板和 embedding 不由
该链路写入磁盘。专业模式仍仅保留受能力门控的入口；没有对应后端或 Standard 依赖/本地权重时，界面会
显示真实原因并恢复先前后端，不会把 Compatibility 冒充 Standard 或 Professional。项目已接受 AGPLv3；
真实设备性能、身份阈值、打包可移植性和权重再分发证据仍须分别关闭。

模式名是产品契约。当前标准原型固定 `ultralytics==8.4.120` 和本地
`yolo26n-pose.pt` 哈希，但模型文件仍不是获准上传或发行的资产。

### 回退顺序

启动或运行时能力探测按以下顺序执行：

1. 用户选择专业模式且 TensorRT FP16 初始化、显存和短时基准均通过时，使用专业模式。
2. 专业模式后端实现后，如不可用则回退标准模式，并记录机器可读原因（例如 `TENSORRT_UNAVAILABLE`、`MODEL_INIT_FAILED`、`OOM`）。当前 Professional 入口不注册后端，因此只显示不可用原因并保持当前模式。
3. 标准模式切换失败时，恢复先前已工作的后端（正常默认是兼容模式），并向用户显示实际异常原因。
4. 兼容模式也不可用时，安全停止视觉干预并报告摄像头/模型错误；不得把旁人提升为目标。

回退只能降低能力，不能改变 `TargetManager`、身份三态结果或风险状态的语义。回退不得自动下载任何模型。
成功切换姿态后端会清空目标、身份会话和科学校准配置，用户必须在新后端上重新完成双锚点校准。

### 证据门槛

实现或发布任何新模式前必须具备：

- ADR 与实际配置一致；
- `docs/vision-evidence/recording_manifest.csv` 中的录像具有参与者同意、场景标签、保存期限和 SHA-256；
- 指标按 `docs/vision-evidence/metrics-baseline.md` 的协议采集，并同时报告 P50/P95；
- `docs/vision-evidence/license-audit.md` 对代码、精确权重和训练数据分别给出 `verified`、`conditional` 或 `blocked`；
- P1 的远端审核、真实摄像头和打包自检缺口不得被本 ADR 视为已关闭。

## 不在本 ADR 范围内

- 本轮只在 Debug UI 集成 YOLO26n-pose 标准姿态后端；不接入正式 EXE；
- 不持久化人脸帧、裁剪、身份模板或 embedding；不把几何比例作为身份结论；
- 不把共享 CVLFace 原型的本地冒烟测试解释成身份准确率、跨设备阈值、隐私验收或发行包可用性；
- 不实现 TensorRT 专业后端，也不把本地权重纳入发行包；
- 不提交真实人脸录像、原图、裁剪、模板或向量；
- 不把候选模型的仓库许可证解释为其权重或训练数据许可证。

## 后续变更要求

改变模式职责、回退顺序、默认模式或许可证门槛时，必须更新本 ADR、指标基线和开发日志，并提供对应回放/性能/许可证据。
