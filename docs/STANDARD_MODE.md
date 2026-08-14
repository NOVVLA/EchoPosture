# Standard mode（Debug UI 多人姿态原型）

Standard mode 当前只接入源码 `debug_ui.py`，正式托盘/启动器 EXE 仍固定使用 Compatibility mode。它使用
Ultralytics YOLO26n-pose 在 CPU 上检测多人，为每个人分别输出人体框和 COCO 17 点骨架，再把肩、髋、鼻、
耳等关键点转换为项目统一的 `PersonObservation` 和个人双锚点姿态量。

## 与 Compatibility mode 的当前差异

| 项目 | Compatibility mode | Standard mode |
| --- | --- | --- |
| 姿态后端 | MediaPipe BlazePose Lite | Ultralytics YOLO26n-pose CPU |
| 人体输出 | 单副骨架 | 每位检测人物各自的人体框、17 点骨架和置信度 |
| 多人场景 | 可发现多脸并拒绝错配，但单骨架被闯入者占用后无法继续看到原目标骨架 | 多副骨架保持独立，再由 `TargetManager` 选择并跟踪校准目标 |
| 人脸与身份 | 共用 `FaceEnhancedBackend` 和本地 CVLFace 链路 | 共用同一增强、归属和身份链路 |
| 产品入口 | Debug UI 和正式托盘/EXE | 仅源码 Debug UI |
| 额外依赖 | 当前 MediaPipe 产品运行时 | 本地权重、固定版 Ultralytics 和 CPU PyTorch |

两种模式在后端之后共用同一个 `TargetManager`、目标状态、身份三态、双锚点校准、姿态评分和干预语义。
因此 Standard mode 当前增加的是“多人姿态观测能力”，不是另一套风险阈值，也不绕过目标锁定或身份保护。

## 当前人脸与身份边界

`StandardPoseBackend` 本身是纯姿态后端：YOLO 的鼻、眼、耳只是 COCO 人体姿态关键点，不是人脸检测或
身份数据。正常 Debug UI 会在外层为所有已注册模式套用 `FaceEnhancedBackend`：

- BlazeFace 检测人脸框并统计场景人数；
- 脸与人体框通过统一归属算法做一对一关联，近似匹配或无法确认时保持歧义，不猜测；
- 只对已归属的人脸裁剪运行 FaceMesh，提取双眼、鼻尖和嘴角五点；
- 本地 CVLFace 可在校准注册、长时离开后重捕获等事件中异步复核身份；
- 肩宽、瞳距、脸身比例和姿态比例不能确认或拒绝身份，只用于归属、跟踪或姿态测量；
- 人脸帧、裁剪、会话模板和 embedding 不由该链路写入磁盘。

CVLFace 运行时与姿态后端是两项独立能力。身份模型不可用时，不应把几何相似当成身份确认；Standard 姿态
后端是否可启动也不能证明身份运行时或正式发行包已经具备。

## 安全行为与限制

- 模型只从显式本地路径加载，禁止自动下载。
- 模型必须报告 `pose` 任务和 COCO `[17, 3]` 关键点布局，否则拒绝启动。
- 多人关联超过观测数、轨迹数或状态预算时进入 `TARGET_AMBIGUOUS/association_budget_exceeded`，不改变已有轨迹。
- 目标显著丢失后，只有当前候选的 CVLFace 结果可以重新绑定；低质量、歧义、过期或错误轨迹的异步结果被拒绝。
- 模式切换会取消进行中的校准，清空目标、身份会话和科学校准配置，因此切换成功后必须重新完成双锚点校准。
- 初始化失败时，Debug UI 关闭失败后端、恢复先前后端（通常是 Compatibility）并显示真实原因。
- 只报告摄像头图像平面的个人内二维投影变化，不推断三维脊柱弯曲度，也不作医疗诊断。

Standard mode 的结构优势是多人体框和多骨架，而不是已经证明的整体准确率提升。当前没有足够的真人多人、
真实摄像头、跨设备、长期误接受/误拒绝或正式发行包证据，不能把本地单元测试和空帧基准解释成这些结论。

## 本地安装

产品运行时为裁剪过的 Python 3.11，不包含 `pip` 或 `ensurepip`。本机已验证的安装方式是在仓库根目录使用
`uv`，明确指定现有运行时和 CPU 版 PyTorch：

```powershell
uv pip install --python runtime\python311\python.exe --torch-backend cpu --no-python-downloads `
  -r requirements-standard.txt
```

将经过来源和许可证核验的 `yolo26n-pose.pt` 放到
`models\pose\yolo26n-pose.pt`，或设置 `ECHOPOSTURE_STANDARD_MODEL`，也可以向 Debug UI 传入：

```powershell
runtime\python311\python.exe debug_ui.py --standard-model C:\path\to\yolo26n-pose.pt
```

启动 Debug UI 后在模式下拉框选择“标准模式”。依赖缺失、权重缺失、模型初始化失败、原生 DLL 无法加载或
摄像头打开失败时，界面会恢复到先前后端并显示真实原因。

身份复核需要单独的 P5 解释器。发现顺序为 `ECHOPOSTURE_P5_PYTHON`、打包候选
`runtime\p5\python.exe`、本地开发 `.venv-p5\Scripts\python.exe`。当前 GA 包不承诺包含该解释器或模型资产。

## 固定依赖与本地证据

- `ultralytics==8.4.120`
- 本机解析结果：`torch==2.13.0+cpu`、`torchvision==0.28.0+cpu`
- 本地开发权重大小：`7,878,574` 字节
- 本地开发权重 SHA256：`EB3BB8268828AEAF515CEC23A4BFAFD793944A86FE9AF94BA7823609C14522A9`
- 权重状态：本地未跟踪开发输入，不得随源码、CI 或发行包上传

2026-08-14 的无摄像头真实权重验证确认模型任务为 `pose`、关键点形状为 `[17, 3]`。在当前机器上，对
12 个 640x480 合成空帧去掉前 2 次预热后，推理 P50 为 `22.94 ms`、P95 为 `31.25 ms`。这只证明本地
权重/API/CPU 路径可执行；空帧不包含人体，不能替代真人、多人数、真实摄像头、跨设备或 416/480 输入实验。

共享人脸/身份边界已有确定性测试，并曾用本地隔离运行时完成一次 512 维 CVLFace embedding 冒烟测试；这仍
不等于真实身份准确率、跨人群阈值、隐私验收或打包可移植性已经完成。

项目许可证为 `AGPL-3.0-only`。这不替代对具体权重和训练数据再分发权限的独立审计，详见
[许可证决策](decisions/ADR-0003-agpl-license-acceptance.md) 和
[模型许可证审计](vision-evidence/license-audit.md)。

## 官方依据

- Ultralytics Pose：https://docs.ultralytics.com/tasks/pose/
- Ultralytics 许可：https://www.ultralytics.com/license
- GNU AGPLv3：https://www.gnu.org/licenses/agpl-3.0.txt
