# Standard mode（Debug UI 原型）

Standard mode 当前只接入 `debug_ui.py`，正式托盘/启动器 EXE 尚未接入。它使用
Ultralytics YOLO26n-pose 在 CPU 上检测多人和 COCO 17 点人体骨架，然后把肩、髋、鼻、耳转换为现有的个人双锚点姿态量。

## 当前边界

- 不运行 FaceMesh、Face Landmarker、人脸裁剪、身份模型、模板或 embedding。
- YOLO 的鼻、眼、耳只作为人体姿态关键点，不声明为人脸检测或身份数据。
- 只报告摄像头图像平面中的二维投影关系；不声称推断三维脊椎弯曲度或医疗诊断角度。
- 模型只从显式本地路径加载，禁止自动下载。
- 多人关联超过安全预算时进入 `TARGET_AMBIGUOUS` 并暂停选择，不静默切换到旁人。
- 目标显著丢失后，在没有用户稍后提供的人脸方案之前会保持身份不确定或要求重新校准。

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

启动 Debug UI 后在模式下拉框选择“标准模式”。依赖缺失、权重缺失、模型初始化失败或摄像头打开失败时，界面会恢复到先前后端并显示真实原因。

## 固定依赖与本地证据

- `ultralytics==8.4.120`
- 本机解析结果：`torch==2.13.0+cpu`、`torchvision==0.28.0+cpu`
- 本地开发权重大小：`7,878,574` 字节
- 本地开发权重 SHA256：`EB3BB8268828AEAF515CEC23A4BFAFD793944A86FE9AF94BA7823609C14522A9`
- 权重状态：本地未跟踪开发输入，不得随源码、CI 或发行包上传

2026-08-14 的无摄像头真实权重验证确认模型任务为 `pose`、关键点形状为 `[17, 3]`。在当前机器上，对
12 个 640×480 合成空帧去掉前 2 次预热后，推理 P50 为 `22.94 ms`、P95 为 `31.25 ms`。这只证明本地
权重/API/CPU 路径可执行；空帧不包含人体，不能替代真人、多人数、真实摄像头、跨设备或 416/480 输入实验。

项目许可证为 `AGPL-3.0-only`。这不替代对具体权重和训练数据再分发权限的独立审计，详见 [许可证决策](decisions/ADR-0003-agpl-license-acceptance.md) 和 [模型许可证审计](vision-evidence/license-audit.md)。

## 官方依据

- Ultralytics Pose：https://docs.ultralytics.com/tasks/pose/
- Ultralytics 许可：https://www.ultralytics.com/license
- GNU AGPLv3：https://www.gnu.org/licenses/agpl-3.0.txt
