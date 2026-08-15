# Professional mode Beta（CUDA 多人姿态）

Professional mode Beta 在 Standard mode 之上换掉两件事：推理跑在 NVIDIA CUDA 上，姿态权重在
`yolo26l-pose` 与 `yolo26x-pose` 之间**由本机实测决定**，而不是预先假定。除此之外它与 Standard mode
共用同一套统一观测、脸身归属、身份三态、双锚点校准和干预语义。

本档标记 Beta，因为跨设备性能、真人多人准确率与发行打包证据都尚未闭合。UI 必须始终显示实际生效的
后端与实测帧率，不得用 Standard 后端冒充本档。

## 与 Standard mode 的差异

| 项目 | Standard mode | Professional mode Beta |
| --- | --- | --- |
| 姿态后端 | Ultralytics YOLO26n-pose，`device="cpu"` | Ultralytics YOLO26l/x-pose，`device="cuda:0"` |
| 权重选择 | 固定 `yolo26n-pose.pt` | 首启实测 l 与 x，取满足延迟预算的最大者 |
| 硬件要求 | 较新的 CPU | CUDA 版 PyTorch + NVIDIA 驱动 + 独立显卡 |
| 启动耗时 | 约 4.6 s（导入 + 权重） | 首启含 CUDA 上下文与双权重基准，上限放宽到 90 s；命中缓存后显著缩短 |
| 失败回退 | 回退 Compatibility | 先降级 Standard，再回退 Compatibility，每一跳都可见 |
| 诊断信息 | 后端名 | 后端名 + 所选权重 + 实测 P50/P95 与 Hz |
| 人脸与身份 | 共用 CVLFace 链路 | 共用同一链路（双模型共识 EP-PRO-003 尚未实现） |

## 权重自动选型

首次选择本档时，后端在开摄像头**之前**用合成帧（640×480，固定种子，不触碰摄像头）为每个候选权重测量
3 帧预热 + 12 帧计时，取 nearest-rank P50/P95：

- `yolo26x-pose` 的 P95 ≤ 50 ms（即 ≥20 Hz 的单帧预算）→ 选 x；
- 否则 `yolo26l-pose` 的 P95 ≤ 50 ms → 选 l；
- 两者都不达标 → **拒绝启动**并给出实测数字，由回退链降级到 Standard。宁可降级，也不让本档挂着一个
  达不到宣称帧率的名字。

候选权重触发 CUDA OOM 时被跳过（x OOM 则试 l），全部 OOM 则拒绝启动。

结果缓存在 `%LOCALAPPDATA%\EchoPosture\professional_benchmark.json`，与 `settings.json` **分开存放**：
后者只保存用户偏好，不接纳性能遥测。指纹（权重大小、device、目标预算）变化或设置
`ECHOPOSTURE_PRO_REBENCH=1` 会强制重测。

设置 `ECHOPOSTURE_PROFESSIONAL_MODEL` 指向具体权重时跳过整个基准，直接采用该权重——这是刻意的显式选择，
不再二次猜测。

## 可用性探测

`vision_modes.detect_mode_availability()` 在**不导入 torch** 的前提下判断本档是否值得呈现，按顺序检查：

1. `torch` 的 spec 存在且有 `origin`；
2. `torch/lib/` 下存在 `torch_cuda*.dll`（CPU wheel 没有此文件）；
3. `%SystemRoot%\System32\nvml.dll` 存在（NVIDIA 驱动）；
4. `models\pose\` 下至少有一个 l/x 权重。

任一失败返回对应的细分原因键（`vision_mode_pro_unavailable_no_cuda_torch` /
`_no_driver` / `_no_weights`），UI 据此说明具体缺什么，而不是笼统地灰掉。

`torch.cuda.is_available()` 这类需要真正导入的深度校验推迟到 `start()`，失败经回退链可见地降级。
探测本身实测约 2 ms，满足 <50 ms 且零重导入的约束。

## 安全行为与限制

- 与 Standard 相同：只从显式本地路径加载，禁止自动下载；模型必须报告 `pose` 与 COCO `[17, 3]`。
- 后端是纯姿态后端，COCO 鼻/眼/耳只是人体关键点，不升格为人脸检测、模板或 embedding。
- `diagnostic_notice` 报告的帧率来自运行期最近 30 帧的实测滑动窗口，**不是**基准值，也不是理论值；
  测量帧不足时显示"正在采集实测帧率"而非编造数字。
- 回退必须可见：降级到 Standard 与降级到 Compatibility 使用不同文案，用户始终知道当前实际生效的档位。
- 只报告图像平面的个人内二维投影变化，不推断三维脊柱弯曲度，不作医疗诊断。

## 本地安装

产品运行时为裁剪过的 Python 3.11，不含 `pip`。在仓库根目录用 `uv` 把主运行时的 torch 换成 CUDA 构建。
PyTorch 官方 cu130 索引在本机实测只有约 24 KB/s（3 GB wheel 不可行），因此使用阿里云镜像
（实测约 370 KB/s）：

```powershell
uv pip install --python runtime\python311\python.exe `
  --index-url https://mirrors.aliyun.com/pytorch-wheels/cu130 `
  --extra-index-url http://pypi.tuna.tsinghua.edu.cn/simple `
  --trusted-host pypi.tuna.tsinghua.edu.cn --index-strategy unsafe-best-match `
  --no-python-downloads --reinstall-package torch --reinstall-package torchvision `
  torch==2.13.0 torchvision==0.28.0
```

网络条件允许时也可直接用官方索引：`--torch-backend cu130`（其余参数相同）。

选 **cu130** 而不是计划最初写的 cu128：cu130 索引上的 `torch==2.13.0` / `torchvision==0.28.0` 与 CPU 运行时
版本号完全一致，只换构建不降级；cu128 索引最高只到 torch 2.11.0，会把主运行时降级并波及 Standard mode。
CUDA 13.0 覆盖 RTX 5070 Ti 的 Blackwell（sm_120）。

CUDA 版 torch 是 CPU 推理的超集，`StandardPoseBackend` 仍显式传 `device="cpu"`，行为不变。代价是冷导入
变慢（实测 1.6 s → 4.47 s），CPU 推理速度基本不变。

验证安装：

```powershell
runtime\python311\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

把经过来源与许可证核验的 `yolo26l-pose.pt` / `yolo26x-pose.pt` 放到 `models\pose\`，或指定：

```powershell
runtime\python311\python.exe debug_ui.py --professional-model C:\path\to\yolo26x-pose.pt
```

## 证据等级

| 结论 | 等级 |
| --- | --- |
| 选型逻辑、OOM 降级、缓存失效、CUDA 缺失拒绝启动、回退链顺序 | **已取证**：`test_professional_pose_backend.py`（12 项）与 `test_startup_guards.py`（5 项）确定性测试，全部走注入点，不依赖真实 GPU |
| 可用性探测的四类失败原因与 <50 ms 预算 | **已取证**：`test_production_mode_onboarding.py`；真机实测 9.63 ms 且未导入 torch |
| Debug UI 专业档可切换、失败经 Standard 中间降级、标签显示真实后端名 | **已取证**：`test_debug_ui.py` |
| CUDA 运行时可用（torch 2.13.0+cu130、RTX 5070 Ti、sm_120、11.9 GB） | **已取证**：真机 `torch.cuda` 查询 |
| 本机选中 `yolo26x-pose`：P50 16.8 ms / P95 20.8 ms（约 59 Hz），远超 20 Hz 目标 | **已取证**：真机基准，见 `docs/vision-evidence/benchmark-professional-20260815.md` |
| Blackwell sm_120 推理数值正确：CUDA 与 CPU 关键点最大偏差 0.11 px、平均 0.01 px（门槛 <1 px） | **已取证**：真机同帧对照（Ultralytics 自带素材，未引入新人像资产） |
| 峰值显存 0.35 GB，本机 x 无 OOM 风险 | **已取证**：真机 `torch.cuda.max_memory_allocated` |
| 启动耗时：首启 14.5 s、缓存命中 3.3 s，90 s 预算余量充分 | **已取证**：真机计时 |
| 升级 CUDA torch 后 Standard mode 冷导入从 1.6 s 增至 4.47 s，CPU 推理 P50 基本不变（23→25 ms） | **已取证**：真机重测，见上述证据文件 |
| 真实摄像头会话下的端到端帧率（含采集与 UI 开销） | **未取证**：基准与一致性测试均为合成帧或静态图片 |
| 三条 UI 路径（浮窗选专业、轮盘运行期切换、失败降级到标准）的真机走查 | **未取证**：仅有离屏确定性测试 |
| 轮盘旋转动画的真机观感与动效时长 | **未取证**：离屏截图只能证明旋转时会重绘，不能证明手感 |
| 真人多人准确率、跨设备外部效度、医学或临床结论 | **不主张** |
