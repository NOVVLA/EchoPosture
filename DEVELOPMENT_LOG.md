# DEVELOPMENT_LOG（Development Log，开发日志）

## 2026-08-15 (Asia/Shanghai) - Professional mode Beta: real-hardware benchmark closes the CUDA/Blackwell risks

- Source: 上一条的 Phase 0 真机验证。上一条提交时 CUDA torch 尚在下载，全部 GPU 相关结论都还是"未取证"。
- Git: 紧随 `8d6ab94` 的验证提交，branch `codex/pr2-phase1-calibration-safety`。
- Install note: PyTorch 官方 cu130 索引在本机实测约 **24 KB/s**，3 GB wheel 不可行（初次尝试 40 分钟只落盘
  5.5 MB）。改用阿里云 `mirrors.aliyun.com/pytorch-wheels/cu130`（约 370 KB/s）完成安装。清华的
  `pytorch-wheels` 路径已 404，不可用。`requirements-professional.txt` 与 `docs/PROFESSIONAL_MODE.md`
  已记录可用的完整命令。
- Verified on hardware（RTX 5070 Ti Laptop、sm_120、11.9 GB、驱动 610.74、torch 2.13.0+cu130）：
  - **CUDA 可用**：`torch.cuda.is_available()` 为 True，设备与计算能力均正确识别。
  - **选型基准**：l 与 x 的 P50 均为 16.8 ms；x 的 P95 20.8 ms 满足 50 ms 预算，因此选中 `yolo26x-pose`，
    约 59 Hz，远超 20 Hz 目标。l 与 x 的 P50 相同说明本机瓶颈不在算力，选最大权重不付出吞吐代价——但这是
    本设备结论，其他 GPU 必须重跑，这正是自动选型存在的理由。
  - **Blackwell 数值正确性**：同权重同帧在 `cuda:0` 与 `cpu` 上推理，`bus.jpg`（4 人）与 `zidane.jpg`（2 人）
    检出人数一致，关键点最大偏差 **0.11 px**、平均 0.01 px，远低于计划设的 1 px 门槛。使用 Ultralytics 自带
    素材，未引入任何新的人像资产。
  - **显存**：峰值 0.35 GB，本机 x 的 OOM 风险可排除（降级链保留给显存更小的设备）。
  - **启动耗时**：首启（含 CUDA 上下文 + 双权重加载 + 双基准）14.5 s，缓存命中 3.3 s。90 s 预算余量充分，
    暂不收紧。
  - **可用性探测**：三档均判定可用，耗时 9.63 ms（预算 50 ms），且 `'torch' in sys.modules` 为 False，
    确认零重导入约束成立。
  - **Standard mode 回归**：CUDA 构建让冷导入从 1.6 s 增至 **4.47 s**（原生库更大的直接代价），CPU 单帧
    推理 P50 基本不变（23 → 25 ms）。本次权重加载只用 0.11 s，但那是文件系统缓存命中，与旧记录的 3.0 s
    不同条件，**不能**据此声称升级让启动更快。`STANDARD_MODE.md` 已更正引用。
- Evidence file: `docs/vision-evidence/benchmark-professional-20260815.md`（只含指标，无图像/人脸/身份数据）。
- Verification: 全部测试在 CUDA runtime 上重跑通过——`test_professional_pose_backend`、
  `test_production_mode_onboarding`、`test_startup_guards`、`test_standard_pose_backend`、
  `test_vision_worker`、`test_debug_ui`。
- Remaining risk: 真实摄像头会话下的端到端帧率（本轮全部数字为合成帧或静态图片，不含采集与 UI 开销）；
  三条 UI 路径（浮窗选专业、轮盘运行期切换、失败降级到标准）的真机走查；轮盘旋转动画的真机观感与动效
  时长；真人多人准确率；EXE 重打包自检。医学/临床/跨设备外部效度**不主张**。

## 2026-08-15 (Asia/Shanghai) - Professional mode Beta: CUDA pose backend, measured l/x selection, real availability probe, and a genuinely rotating mode wheel

- Source: `docs/plans/EchoPosture_production_mode_onboarding_plan.md` 的后续。摸底发现该计划的 TASK-1~11 已在
  `a2cdb44` / `3aeacaa` 全部落地（文档头部的"未开始编码"已过时），因此本轮的实际范围收敛为：实现专业档的
  后端本体、把硬编码的"不可用"换成真实探测，外加用户当面提出的轮盘 UI 重做。
  用户拍板的四项：两者都做（后端 + 浮窗接真）、GPU 路径先走 CUDA PyTorch（TensorRT 留作后续）、
  l/x 实测后自动选、身份双模型共识（EP-PRO-003）本轮不做。
- Git: commit `8d6ab94`, branch `codex/pr2-phase1-calibration-safety`.
- Scope:
  - **CUDA 运行时**（`requirements-professional.txt` 新建）：主 runtime 的 torch 换为 CUDA 构建。
    **选 cu130 而非计划最初写的 cu128**——`uv --dry-run` 实测 cu130 索引提供 `torch==2.13.0+cu130` /
    `torchvision==0.28.0+cu130`，与现有 CPU 版号完全一致，只换构建不降级；cu128 索引最高只到 torch 2.11.0，
    会连累共用同一 runtime 的 Standard mode。CUDA 13.0 覆盖本机 RTX 5070 Ti 的 Blackwell（sm_120）。
  - **可用性探测接真**（`vision_modes.py`）：`detect_mode_availability` 的专业档从硬编码 `False` 改为四项
    零导入检查（复用同一次 `find_spec("torch")` → `torch/lib/torch_cuda*.dll` glob → `System32/nvml.dll`
    → l/x 权重存在性），各自映射到细分原因键；新增 `probe_professional_support` 与
    `professional_model_paths`。`intended_backend` 从 `yolo26-pose-tensorrt` 改为
    `ultralytics-yolo26-pose-cuda`。深度校验（`torch.cuda.is_available()`）推迟到 `start()`，失败走可见回退。
  - **专业后端**（`professional_pose_backend.py` 新建，约 370 行）：`ProfessionalPoseBackend` 继承
    `StandardPoseBackend`，复用其观测转换、姿态特征、黑帧检测与 COCO-17 契约校验。覆写：`device="cuda:0"`、
    实例级 `capabilities`（选型后用 `dataclasses.replace` 更新为实际权重名）、CUDA 前置校验（可注入
    `cuda_ready`）、CUDA OOM 识别与逐级跳过、`diagnostic_notice`（运行期最近 30 帧实测滑窗，帧数不足时
    显示"正在采集"而不编造数字）。
  - **权重自动选型**：`select_professional_model` 纯函数 + 合成帧基准（3 帧预热 + 12 帧计时，固定种子，
    不开摄像头），nearest-rank P50/P95，x 的 P95 ≤ 50 ms 选 x，否则 l，都不达标则拒绝启动并给出实测数字。
    结果缓存到 `%LOCALAPPDATA%\EchoPosture\professional_benchmark.json`——**刻意与 `settings.json` 分开**，
    后者的隐私最小化契约（测试断言 payload 恰为三键）不应被性能遥测污染。指纹变化或
    `ECHOPOSTURE_PRO_REBENCH=1` 触发重测；`ECHOPOSTURE_PROFESSIONAL_MODEL` 显式指定则跳过整个基准。
  - **capabilities 读穿**（`face_observation_enhancer.py`）：`FaceEnhancedBackend.capabilities` 从 `__init__`
    时的一次性拷贝改为 `@property` 动态读内层。否则专业档在 `start()` 里完成选型后，外层仍报告选型前的
    占位名，Debug UI 会显示过期后端——违反"必须显示实际生效后端"的诚实性契约。
  - **多级回退链**（`tray_app.py`）：`_begin_mode_initialization` 的单级回退改为候选列表循环，新增
    `_fallback_chain`（professional → standard → previous → compatibility，去重）与 `_mode_start_timeout`
    （专业档 90 s，其余保持 25 s；首启含 CUDA 上下文 + 两次权重加载 + 双基准，25 s 必然不够）。
    `fallback` 信号增加第三个参数携带实际回退目标，`onboarding_toast.show_mode_failure` 据此选择
    "已回退到标准模式"或"已回退到兼容模式"文案——回退到哪一档必须说清，不能一律说成兼容。
  - **Debug UI**（`debug_ui.py`）：注册延迟导入的专业工厂、新增 `--professional-model`、多人框绘制条件
    纳入专业档、`_switch_vision_mode` 改为沿降级链逐跳尝试并累积展示每一跳的失败原因。
  - **轮盘重做**（`mode_wheel_selector.py`）：用户指出原实现"只能叫弧形选择器"——三个选项固定排布、
    切换时只做整体平移，盘体本身没有任何旋转证据。改为真正的转盘：9 个循环槽位（3 档 × 3 轮）填满整圆、
    以绝对角度 `_wheel_angle` 驱动、刻度与辐条随盘旋转（速度越快越亮）、选项沿切线倾斜而非始终水平、
    顶部固定指针不动、`OutBack` 过冲缓动模拟机械咬合。同时修掉两侧的硬边光晕（改用 destination-in
    擦除 alpha）、收紧顶部辉光到圆盘裁剪内、缩小卡片让相邻档露出更多。
  - **i18n**（`i18n.py`，zh + en 同步）：新增 `vision_mode_pro_unavailable_no_cuda_torch` / `_no_driver` /
    `_no_weights`、`vision_pro_active_notice` / `_active_warmup` / `_fallback_perf` / `_fallback_oom`、
    `onb_mode_benchmarking`、`onb_mode_failed_fallback_standard`；改写 `vision_mode_professional_unavailable`
    （去掉已不成立的"尚未提供 TensorRT 后端"措辞）。
  - **文档**：新建 `docs/PROFESSIONAL_MODE.md`（差异表、选型规则、探测顺序、安装命令、证据等级声明）；
    `docs/STANDARD_MODE.md` 加注主 runtime 可能已是 CUDA 构建、标准档仍强制 CPU、冷导入数字需重测。
- Verification: `ruff check` 全过。确定性测试（均不依赖真实 GPU / 摄像头，CUDA 路径全走注入点）：
  `test_professional_pose_backend.py` 新建 12 项全绿（cuda:0 device 契约、选型三分支、OOM 逐级降级与全 OOM
  拒启、缓存命中/失效、env 覆写跳过基准、观测契约与标准一致、包装器跟随选型后的后端名）；
  `test_startup_guards.py` 17 项（新增 5 项回退链与超时预算）；`test_production_mode_onboarding.py`
  （新增探测四类失败原因、专业档可用时两个选择器均可选、轮盘旋转会重绘的断言）；
  `test_debug_ui.py` 12 项（新增专业档可切换 + 失败经 Standard 中间降级，并更新了断言 "TensorRT" 字样的
  过时用例）；`test_standard_pose_backend.py` / `test_vision_worker.py` / `test_feature_toggles.py` /
  `test_compatibility_face_detection.py` / `test_tray_flyout.py` 回归全绿。
- Remaining risk（均已写入 `docs/PROFESSIONAL_MODE.md` 的证据等级表）：cu130 wheel 的实际落盘与
  `torch.cuda.is_available()` 真机确认；Blackwell sm_120 上 Ultralytics 推理的数值正确性（需同帧 CPU vs CUDA
  关键点对照）；l/x 在本机的真实 P50/P95 与最终选型；90 s 启动预算需真机计时后收紧；12 GB 显存下 x 的峰值
  占用；升级 CUDA torch 后 Standard mode 冷导入耗时的变化；轮盘旋转动画的真机观感与动效时长仍待人工确认
  （离屏截图只能证明"旋转时会重绘"，不能证明手感）。EXE 重打包自测未做。

## 2026-08-15 (Asia/Shanghai) - Fix adopted PR-review items: identity toggle symmetry, UI language-refresh gaps, calibration feedback, and CVLFace model-cache integrity

- Source: organized PR-comment feedback from closed-as-not-planned GitHub issues (#25-#29). Each accusation was
  verified against current source before any fix; the user then gave explicit per-item accept/reject decisions.
  Rejected and out of scope: #25-2 (exposure decay), #25-3 (forced identity re-check on reacquisition), #25-4
  (runtime black-frame auto-fallback), #27-M3 (startup calibration cancel window), #28-A/B (multi-person pipeline
  architecture changes), #28-D (motion-innovation-triggered identity re-check). #25-1 and #26-1 required no code
  change (both were fabricated/incorrect accusations, refuted against source). #29 (package size reduction) was
  never explicitly adopted and has no corresponding packaging script in this repo; still open, not addressed here.
  The user's governing instruction for this delivery: fix the remaining adopted items directly, delegating
  reasonably to a Codex agent for the larger security-sensitive batch to control cost rather than doing everything
  personally.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`.
- Scope:
  - **#27-M1/M2 identity-toggle symmetry** (`vision_worker.py`, `vision_test.py`): `_identity_enrollment_active` now
    also checks `analyzer.identity_check_enabled`; the `PROFILE_MISMATCH` decision branch in `vision_test.py` now
    mirrors the existing `IDENTITY_UNCERTAIN` guard so a disabled identity toggle is honored symmetrically across
    every decision branch that references identity state.
  - **#27-L1-L7 UI language-refresh and control gaps**: `onboarding_toast.py` and `tray_flyout.py` now refresh the
    eye-slide switch's accessible name on language change; `tray_flyout.py` no longer double-registers its language
    listener; `posture_console.py`'s language-change handler no longer hardcodes a paused-state label and instead
    calls `refresh()` so the state text reflects real monitoring state; `debug_ui.py`'s language-change handler
    re-renders status/reason text from the live sample instead of resetting to init placeholders, and the
    high-performance-FPS checkbox is now disabled during calibration and guarded against toggling mid-calibration,
    matching the existing high-precision checkbox behavior; `tray_app.py` removed a dead, never-instantiated
    `StatusPanel` class (~90 lines) and its unused imports, and worker/mode-failure error text shown in tray
    notifications is now compressed to a single-line, length-bounded summary (`_short_error_text`) while the full
    technical error is still printed to stderr.
  - **#27-M4 relaxed-extension progress feedback** (`vision_worker.py`, `tray_app.py`, `i18n.py`): the production
    dual-anchor calibration flow's background relaxed stage can silently extend up to `relaxed_max_extension_seconds`
    (2s) beyond its nominal 5s window when samples are still insufficient, with no prior user feedback beyond the
    initial "relax now" toast. `VisionWorker` now exposes a one-shot `take_calibration_extension_pending()` poll,
    set once by `_maybe_finish_dual_anchor` when the nominal relaxed window has elapsed but `ready_to_finalize` is
    still false and the bounded deadline has not yet been reached; `tray_app.py`'s existing 10Hz `_tick()` poll
    surfaces this as a new tray toast (`tm_calib_extending`, zh/en) so the user knows collection is still active
    rather than appearing stuck. Originally attempted via Codex delegation; two consecutive delegation attempts
    failed on an unrelated Codex-session environment fault (`CreateProcessAsUserW failed: 1312`, Windows login
    session error, zero files touched either time), so this item was implemented directly instead of retrying a
    third time.
  - **#26 CVLFace identity-model security/subprocess-robustness batch** (`identity_model_adapters.py`,
    `identity_model_process.py`, `identity_verifier.py`, `tools/hydrate_p5_model_code.ps1`,
    `tools/download_p5_models.ps1`, `tools/vit_kprpe_manifest.json`): delegated to a Codex agent given the
    security-sensitive surface (`trust_remote_code=True` model loading, subprocess isolation, hash whitelisting).
    Because self-reported "done, tests pass" summaries are not sufficient evidence for security-critical code, the
    resulting diff was independently audited by a `code-reviewer` subagent before being trusted; that audit found 3
    High-severity gaps and a related Medium finding, which were routed back to the same Codex thread for targeted
    fixes, then re-audited:
    - Hash-whitelist scan scope was widened from only the `models/vit_kprpe/` subtree to the entire model-cache root
      (matching where the root is inserted at `sys.path[0]`), closing a path-shadowing bypass (e.g. a planted
      `<model_root>/yaml.py` that would otherwise import ahead of the real `yaml` package); covered suffixes were
      extended to `.py/.pyc/.pyo/.pyd/.so/.pth/.dll/.dylib`; symlinks and Windows reparse points (including
      junctions, verified via `FILE_ATTRIBUTE_REPARSE_POINT` rather than the narrower `S_ISLNK`) are now rejected;
      `sys.dont_write_bytecode` is set for the duration of the load to stop new unwhitelisted `.pyc` from being
      generated.
    - `pretrained_model/model.pt` (loaded via `torch.load`, i.e. pickle deserialization) is now a required,
      hash-verified manifest entry; the hash check runs before `torch`/`transformers` are imported and before
      `AutoModel.from_pretrained` executes any model code.
    - Any model spec without a trusted manifest (currently the IR101 path) now fails closed with `ModelCacheError`
      instead of silently skipping verification; the current production default (ViT/KP-RPE, confirmed via
      `tray_app.py`, `debug_ui.py`, `identity_model_process.py`) is unaffected because it is fully covered by the
      manifest.
    - `IdentityVerifier.close()` no longer unconditionally closes a shared embedder via duck-typing; a new
      `owns_embedder: bool = False` constructor parameter (default preserves existing shared-embedder behavior at
      both production call sites) gates the cascade, matching the existing ownership convention already used by
      `FaceEmbeddingPipeline`/`debug_ui.py`.
  - **Post-re-audit follow-up, fixed directly (not re-delegated, small and well-scoped)**: the re-audit surfaced two
    further items neither original pass had caught:
    - `model.safetensors` — the file that actually initializes the model's weights at load time (loaded *after*
      `model.pt`, overwriting its state dict) — was completely absent from the trusted manifest and therefore
      unverified, meaning the `model.pt` hash protection could be bypassed by replacing the safetensors file to make
      the identity check accept an attacker-chosen face. Added its SHA-256 to `tools/vit_kprpe_manifest.json` and to
      `identity_model_adapters.py`'s `_REQUIRED_MANIFEST_FILES`, so the manifest cannot omit it. Updated
      `test_identity_model_adapters.py`'s tampering-fixture to include and hash this file so the fail-closed test
      still exercises the real required-file set.
    - The repository's actual local model cache under `models/p5/cvlface_adaface_vit_base_kprpe_webface4m/` still
      contained 11 stale `__pycache__/*.pyc` files from before the whitelist-widening fix existed. Under the new,
      correctly-widened scan these are unapproved executables, so the real production model directory would have
      failed `verify_model_code_integrity` and silently disabled identity checking (confirmed by reproducing the
      failure locally before cleanup). Removed the stale `__pycache__` directories and added a cleanup step to
      `tools/hydrate_p5_model_code.ps1` (after hydration, recursively remove `__pycache__` under both model roots) so
      this cannot recur from a future hydration run.
- Risk: the identity-model integrity changes are fail-closed by construction — a manifest gap, hash mismatch,
  unapproved executable, or untrusted model spec now raises `ModelCacheError` and blocks loading rather than
  degrading silently; this is a deliberate behavior change from the previous silent-skip posture and is the whole
  point of the fix, not a regression. `IdentityVerifier.close()`'s new default preserves prior behavior at both
  production call sites (`tray_app.py`, `debug_ui.py`), so no embedder-lifecycle change ships from this entry.
  Calibration-flow and UI changes are additive (a new toast, corrected label refresh) or dead-code removal; no
  decision-branch, threshold, or intervention-timing logic changed.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目` (bundled `runtime\python311\python.exe`, this repo's
  actual convention — pytest is not installed anywhere on this machine):
  - `test_vision_worker.py` (26 tests, including `test_dual_anchor_worker_uses_bounded_relaxed_extension`),
    `test_feature_toggles.py`, `test_debug_ui.py` (11 tests), `test_tray_flyout.py` (updated `_Switch` test double
    to add the new `setAccessibleName` no-op it now needs) all passed with no regressions.
  - `test_identity_model_adapters.py` and `test_identity_verifier.py` passed after both the Codex-delegated H1/H2/H3
    fixes and the follow-up `model.safetensors`/fixture updates.
  - Independently re-ran `verify_model_code_integrity(VIT_KPRPE_WEBFACE4M, model_path(...))` against the real local
    model cache directory after cleanup: passes end-to-end with the updated manifest.
  - `i18n._TEXTS['zh']`/`['en']` key sets compared programmatically: no gaps, `tm_calib_extending` present in both.
  - `python -c "import tray_app"` succeeded after removing the dead `StatusPanel` class and its imports.
  - `tools/hydrate_p5_model_code.ps1` re-parsed successfully via
    `[System.Management.Automation.Language.Parser]::ParseFile` after the cleanup-step edit.
  - Two independent adversarial reviews (`code-reviewer` subagent) were run against the #26 batch: the first
    verdict was "needs changes before merge" (3 High, 5 Medium, 4 Low findings); after remediation the second
    verdict confirmed H1/H2/H3/M1 fully fixed and flagged the two items above as the remaining blockers, both of
    which are now fixed and independently re-verified in this entry.
- Artifacts and privacy: no camera frame, face crop, embedding, or model weight was downloaded, generated, or
  altered by this work beyond removing stale interpreter bytecode cache files (`__pycache__/*.pyc`, regenerable,
  not source) under the untracked, per-machine `models/` directory, which remains outside version control. No
  package, installer, or release artifact was built.
- Gaps: the re-audit's remaining Medium/Low findings are deliberately deferred, not silently dropped:
  - Windows reparse-point rejection currently uses the coarse `FILE_ATTRIBUTE_REPARSE_POINT` bit, which would also
    reject OneDrive Files-On-Demand placeholder files if the model cache ever lived under an OneDrive-synced
    folder; checked this machine directly (`fsutil reparsepoint query` on both `Documents` and `models/`) and
    confirmed neither is a reparse point here, so this is not a live issue on this machine, but remains a
    portability caveat for other deployments.
  - The repository's symlink-rejection test silently no-ops on Windows without Developer Mode enabled (`OSError`
    from `symlink_to` is caught and the assertion block never runs); the reparse-point/junction path is covered by
    manual reasoning about `os.lstat`/`FILE_ATTRIBUTE_REPARSE_POINT` semantics, not by an executed test.
  - `tools/hydrate_p5_model_code.ps1` still hydrates the IR101 code tree even though `identity_model_adapters.py`
    now unconditionally rejects IR101 for lack of a trusted manifest; the script has no comment explaining this, so
    a future maintainer could reasonably assume IR101 is loadable when it currently is not.
  - No packaged EXE rebuild, self-test, live camera trial, or cross-machine hydration rerun was performed.
  - #29 (package size reduction) remains unaddressed and unscoped; flagged to the user as an open question rather
    than silently dropped.
- Conclusion: all explicitly adopted PR-review items are implemented, independently re-verified past their
  first-pass review findings, and ready to commit and push on the current branch; #29 and the deferred Medium/Low
  hardening items above should be raised with the user as follow-up, not treated as resolved.

## 2026-08-14 (Asia/Shanghai) - Synchronize vision-mode documentation with current source

- Source: user request to correct documentation after the recent Standard-mode, shared face-observation, CVLFace,
  candidate-session, ownership, abstention, and intervention fixes. The canonical docs still described Standard as a
  pose-only path with no face or identity processing and the tracked upgrade plan still marked resumed identity work
  as paused.
- Git: commit `60f8ef0`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Scope:
  - `README.md`, `README_EXE.md`, `docs/README.md`, and `docs/STANDARD_MODE.md` now distinguish the packaged
    Compatibility-only posture path from the source Debug UI Standard prototype and describe Standard's per-person
    boxes, COCO 17-keypoint observations, local-weight gate, shared face/identity boundary, and evidence limits.
  - `docs/ARCHITECTURE.md`, `docs/TROUBLESHOOTING.md`, and ADR-0001 now describe
    `FaceEnhancedBackend(CompatibilityBackend(...))`, `StandardPoseBackend`, mode-independent BlazeFace/FaceMesh
    enrichment, CVLFace-only identity decisions, candidate-scoped stale-result guards, actual switch/reset behavior,
    and the current Professional unavailable entry.
  - The tracked vision/identity plan now records the implemented ViT KP-RPE and optional IR101 adapters, resumed P5
    status, Standard shared face enhancement, and the fact that current mode switching clears target, identity, and
    scientific calibration state instead of performing the previously planned quick recalibration/template reuse.
- Risk: documentation could overstate source capability as packaged availability or deterministic tests as live
  accuracy. Every updated entry keeps Standard out of the current GA package, separates the raw pose-only backend from
  the Debug UI face decorator, and leaves real-camera, identity-threshold, privacy, packaging, and redistribution
  evidence explicitly open. No runtime behavior, dependency, model, or release artifact changed.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe test_standard_pose_backend.py`: passed all pose-only raw-backend, multi-person,
    shared-face, no-download, DLL-preload, and model-contract checks.
  - `runtime\python311\python.exe test_debug_ui.py`: passed all tests, including three-mode availability and fallback;
    emitted the existing bundled Qt missing-font-directory and offscreen plugin warnings.
  - `runtime\python311\python.exe test_identity_model_adapters.py`: passed.
  - `runtime\python311\python.exe test_vision_tracking.py`: passed, including multi-person continuation, no silent
    promotion, candidate identity, association-budget, and worker target-selection cases; the bounded 10x10 matrix
    measured P50 `5.82 ms` and P95 `7.32 ms` in this run.
  - Local Markdown link check passed for all eight updated documentation files before this log entry.
  - `git diff --check`: passed; Git emitted only existing working-copy LF-to-CRLF conversion warnings.
- Artifacts and privacy: no package, release, model, runtime, frame, face crop, embedding, recording, or generated
  document was created or staged. Existing unrelated untracked workspace files remain untouched.
- Gaps: no live camera, consented multi-person scene, deliberate leave/re-enter identity trial, cross-device test,
  packaged EXE rebuild/self-test, model redistribution audit, remote CI, or medical/external validation was performed.
- Conclusion: the canonical mode documentation and tracked implementation plan now match the current source contracts
  and preserve the remaining evidence boundaries; ready for reviewed documentation commit and push on the current
  branch.

## 2026-08-14 (Asia/Shanghai) - Repair intervention trigger sensitivity and timing

- Source: urgent user request and `docs/plans/EchoPosture_intervention_trigger_defects.md`; the report's synthetic
  dual-anchor scenario A reproduced as exactly `0.0` deviation before the fix, with ratio/angle acceptance margins
  of `0.075` and `5.5 degrees` masking meaningful changes.
- Git: code commit `9d29078`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; local integration commit
  `eb569d0` preserves the remote identity-parity history, while delivery remains the existing PR
  branch and includes the branch's one previously local commit.
- Root causes: runtime acceptance added a fixed movement deadband to measurement noise, unsupported single channels
  were discarded, the shared shoulder denominator guard could suppress changes backed by real raw geometry, severe
  excursions bypassed the existing posture-change confirmation, and exposure accumulated only after ALERT. This
  created both false negatives and a hard WATCH/ALERT cliff.
- Scope and fix: `posture_science.py` now accepts the larger of runtime noise and a personal-span movement allowance
  capped by the absolute policy limit; ratio/angle defaults are `0.010`/`1.0 degree` noise floors, `0.075`/`5.0
  degree` movement caps, and `0.07`/`6.0 degree` response scales. Lone supported channels contribute discounted
  evidence, while shoulder-width-only denominator drift still abstains unless a raw head or torso numerator supports
  the change. `vision_test.py` requires the two-second confirmation for every new body-posture excursion, integrates
  WATCH at a lower bounded weight, can reach BAD from sustained WATCH exposure, and labels nonzero sub-WATCH results
  as minor posture variation. The reliability collection tool reports the same production formula and policy fields.
- Policy safety: `PosturePolicy` now rejects `watch_enter >= alert_enter`, preventing a zero or negative WATCH
  interpolation span. Moderate head-direction change remains scoreable below `0.35`; changes at or above that
  observation threshold still abstain according to the head-turn policy.
- Superseded audit claims: this entry replaces the 2026-08-13 statements that a severe eligible posture becomes
  WATCH on its first qualifying frame and that WATCH never accumulates exposure. All new body-posture episodes now
  require the existing two-second confirmation, and sustained WATCH evidence accumulates more slowly than ALERT.
- Risk: intervention sensitivity changes within the calibrated scientific analyzer, but target identity, presence,
  movement, quality, camera/reference, cooldown, and tray intervention gates remain in place. The new thresholds are
  adjustable product interaction and measurement-reliability policy, not anatomical, physiological, or medical
  standards.
- Verification from the repository root:
  - `runtime\python311\python.exe test_posture_science.py`, `test_feature_toggles.py`, and
    `test_vision_worker.py` passed. Regressions cover report scenarios A/B/C/D, accepted anchors, sustained sub-ALERT
    WATCH reaching BAD, brief severe actions remaining behind confirmation, shoulder-width-only drift abstention,
    real forward/lateral alerts, and the head-turn boundary.
  - `runtime\python311\python.exe test_vision_tracking.py`, `test_vision_replay.py`, `test_startup_guards.py`, and
    `test_tray_flyout.py` passed.
  - Bundled-Python `py_compile` passed for all six changed Python files; global `ruff check` passed for those files;
    `git diff --check` passed with only Git's existing LF-to-CRLF working-copy warnings.
- Artifacts and privacy: tests use synthetic numeric geometry. No frame, image, video, face crop, identity data,
  reliability report, model, package, or release artifact was created or staged. The user-owned defect report and all
  unrelated untracked workspace files remain unstaged.
- Gaps: physical-camera comfort, false-positive/false-negative rates, cross-camera reliability, external validity,
  and medical validation remain unverified and unclaimed. Live-camera behavior still requires user retest after
  delivery.
- Conclusion: the reported trigger defects are fixed at the deterministic policy and timing layers, guarded by core
  and cross-module regressions, and ready to commit and push on the current branch.

## 2026-08-14 - Recover camera frames and Standard mode after native-frame failures

- Source: user feedback screenshot and live Debug UI report: startup raised `Reference mode is unavailable if
  'data' is not c_contiguous`; after dismissing the dialog the camera preview stayed blank, and changing vision
  modes appeared to do nothing.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; delivery remains PR `#23`.
- Root causes: the selected RGB face crop inherited a non-C-contiguous NumPy view that MediaPipe FaceMesh rejects;
  the Debug UI permanently stopped its frame timer after any unexpected one-frame exception; and, on this Chinese
  workspace path, importing PyQt before Torch could make Windows fail to initialize Torch `c10.dll` with
  `WinError 1114`, causing Standard mode startup to fall back to Compatibility mode.
- Fix: face crops are copied to C-contiguous read-only arrays before FaceMesh; unexpected frame errors are shown
  once per consecutive error and frame polling resumes after the dialog closes; selecting the current or an
  unavailable mode also restores a stopped timer. A Windows-only helper now exposes native package DLL directories
  through a stable ASCII junction under `%LOCALAPPDATA%\EchoPosture\runtime-paths`, registers the directory, and
  preloads Torch `c10.dll` before PyQt in both Debug UI and tray entry points. Standard-pose and identity adapters
  prepare the same DLL path before optional Torch-backed model imports and retain explicit dependency errors.
- Risk: the recovery timer may retry a persistent unexpected backend failure, but duplicate modal dialogs remain
  suppressed until a successful frame. Permission and black-frame errors retain their existing dedicated stop and
  recovery flows. Compatibility mode remains available when Torch is absent. The helper stores only a filesystem
  junction derived from the local package path and no camera, face, identity, or posture data.
- Verification from the repository root:
  - Real MediaPipe received a read-only selected-face crop and returned `READ_ONLY_FACE_CROP_OK`.
  - A bundled-Python offscreen live-camera harness read Compatibility, Standard, and Compatibility-again frames:
    `COMPAT_FRAME True True []`, `STANDARD_FRAME standard True True []`, and
    `COMPAT_RETURN_FRAME compatibility True True []`.
  - `runtime\python311\python.exe -c "import tray_app; import torch; ..."` returned
    `TRAY_THEN_TORCH_OK 2.13.0+cpu`, proving the production Qt-then-Torch import order loads successfully.
  - `test_debug_ui.py`, `test_compatibility_face_detection.py`, `test_standard_pose_backend.py`,
    `test_identity_model_adapters.py`, `test_vision_worker.py`, `test_startup_guards.py`, and
    `test_tray_flyout.py` passed with the bundled Python runtime.
  - Bundled-Python `py_compile` for all changed Python modules, `ruff check .`, and `git diff --check` passed.
- Artifacts and privacy: no frames, face crops, identity templates, logs, models, screenshots, PDFs, runtime files,
  or generated packages are included. Existing untracked local materials remain unstaged.
- Backup: `git stash create` captured the complete staged pre-commit state, including the new runtime helper, at
  object `db174b4477acfb3560fccdffb359f68bcd578624` without changing the working tree.
- Gaps: the bundled Qt build still reports its existing missing font-directory warning under the Chinese workspace
  path; it did not prevent imports, frame reads, mode changes, or tests. Final interactive display behavior on the
  user's exact screen remains a post-delivery retest; no release package was built or changed.
- Conclusion: the reported exception, frozen-preview path, and Standard-mode native DLL failure are reproduced at
  their component boundaries, fixed at their causes, covered by regressions, and ready for the existing PR.

## 2026-08-13 - Surface pronounced posture configurations without bypassing intervention timing

- Source: user live-camera report that an approximately 90-degree sustained head turn and a pronounced frontal
  shoulder-shrug/neck-contraction posture could remain `GOOD` or move only through inconsistent observation states.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; delivery remains the existing PR
  `#23`, with no additional PR.
- Root cause: all head turns were treated only as invalid forward-geometry measurements, so even a stable extreme
  direction could never become explicit posture-change evidence. Forward scoring also required two independent
  ratio channels at every magnitude; a real frontal shrug or neck protraction that strongly changed only one
  head/shoulder or torso/shoulder channel was therefore discarded as inconclusive.
- Fix: normalized head-direction delta now has three explicit product-policy regions: below `0.25` uses normal body
  scoring, `0.25-0.45` remains measurement observation, and a high-quality stable delta from `0.45` upward becomes
  a continuous `0.70-1.00` direction-deviation signal. A single forward channel may stand alone only at deviation
  `0.85` or above and only when its own raw numerator leaves the calibrated repeatability band; denominator-only
  shoulder-width drift still abstains. These values are interaction and measurement-reliability policies, not
  anatomical, physiological, or medical thresholds.
- Timing and safety: an eligible severe body configuration or extreme head direction becomes visible as `WATCH` on
  its first qualifying static frame, while its exposure clock is explicitly anchored at that frame and starts at
  zero. `BAD` and `CRITICAL` still require 12 and 30 equivalent exposure seconds. Movement, low face/pose quality,
  target uncertainty, camera/reference instability, and post-calibration validation pause exposure. The production
  tray still requires `BAD`/`CRITICAL`, at least 12 exposure seconds, an additional three-second confirmation, and
  the existing 60-second cooldown before intervention.
- Regression boundaries: ordinary short reaching still enters `ADJUSTING` for the two-second confirmation window;
  natural midrange lean remains `GOOD`; moderate head turn remains `OBSERVING`; uniform distance change, high-FPS
  jitter, and shoulder-width-only drift cannot open `WATCH` or accumulate exposure. Pronounced frontal shrug,
  genuine forward geometry, extreme static head direction, and pronounced pelvis-relative side recline now enter
  `WATCH` immediately without preloading exposure.
- Verification from the repository root:
  - `runtime\python311\python.exe test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`,
    `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, `test_vision_replay.py`, and
    `test_tray_flyout.py` passed.
  - `runtime\python311\python.exe -m py_compile posture_science.py vision_test.py debug_ui.py i18n.py
    test_posture_science.py test_feature_toggles.py`, `ruff check .`, and `git diff --check` passed.
  - Debug UI emitted the existing bundled Qt missing-font-directory warning; all assertions and its exit code passed.
- Privacy and artifacts: all added regressions use synthetic numeric features. No image, video, frame, face crop,
  identity vector/template, or reliability report was created or saved. Unrelated local screenshots, review folders,
  model files, PDFs, `uv.lock`, and other untracked paths remain unstaged.
- Backup: `git stash create` captured the tracked pre-commit state at object
  `0e2c24a1107c1c2795dcc7f3a3539be5b64dc6ee`; it did not alter the working tree or include untracked local files.
- Gaps: the original physical-camera scenarios still require user retest after delivery. Cross-camera head-direction
  reliability, consented recording, measured false-positive/false-negative rates, external validity, and medical
  validation remain unverified and unclaimed.
- Conclusion: deterministic logic, UI compatibility, worker, tracking, replay, startup, tray, lint, and syntax checks
  passed. The change is ready for split code/tests and audit commits on the existing PR; incident closure remains
  contingent on live-camera retest.

## 2026-08-13 - Preserve real side-recline evidence and bound static-hold support

- Source: field report that a sustained side-recline could remain `GOOD` because the shoulder line stayed parallel,
  and request for a limited contribution from holding an already poor posture for too long.
- Root cause: lateral scoring required shoulder asymmetry and trunk lean to corroborate each other, so a genuine
  pelvis-relative torso lean was discarded when shoulder asymmetry was near zero.
- Fix: `posture_science.py` now admits pronounced `trunk_lean_deg` as a lateral evidence channel at the explicit
  `lone_trunk_lean_deviation` product gate while retaining two-feature corroboration for ordinary lateral changes.
  `vision_test.py` integrates `StaticHoldAccumulator` only after posture confirmation, with a 60-180 second ramp and
  a maximum `0.12` add-on. Normal posture, movement, low quality, recovery, and observation gaps cannot earn it.
- Verification: `test_posture_science.py` and `test_feature_toggles.py` pass, including lone-trunk side-recline and
  normal-posture static-hold regressions. Real-camera comfort and external validity remain unverified.

## 2026-08-13 - Separate normal movement from unknown measurements and debounce posture changes

- Source: user field feedback that normal movement, leaning/reaching, shoulder-width change, and camera-distance
  change were immediately shown as unrecognized or observation states, effectively requiring the user to remain
  motionless and too close to a single calibrated position.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; delivery remains the existing PR
  `#23`, with no additional PR.
- Root cause: the scientific analyzer used `UNKNOWN` as a generic synonym for every paused exposure frame. Runtime
  score hysteresis also admitted a corroborated excursion on its first frame, while activity tracking measured only
  target-box centre translation and missed centre-stable forward/backward movement. A correlated raw-scale guard then
  permanently abstained after an otherwise valid user changed distance.
- State fix: `MOVING` now means measured target activity, `ADJUSTING` means a new reach/lean/posture change is inside
  a two-second product confirmation window, and `OBSERVING` means the target is known but that observation is not
  exposure-eligible. `UNKNOWN` remains for genuinely unavailable posture features or unresolved target/identity
  conditions. All non-intervention states keep zero current deviation and cannot trigger the tray overlay.
- Noise and time fix: the single-observation measurement band now uses the largest of MDC, `3.0 ×` within-anchor
  standard deviation, a `0.025` normalized-ratio floor, and a `2.5°` angle floor. A separate natural-movement
  deadband adds `0.05` for normalized ratios and `3°` for angle features, so ordinary reaching, breathing, and seat
  adjustment do not immediately change the user-visible state. Small uncorroborated changes remain normal variation.
  A corroborated deviation must stay beyond the personal range for about two seconds before WATCH; the
  confirmation interval is never backfilled into static exposure. These are adjustable product reliability and
  interaction parameters, not medical or physiological thresholds.
- Movement and scale fix: target activity combines smoothed centre translation with signed relative bounding-box
  scale velocity, detecting forward/backward movement while cancelling alternating one-pixel scale jitter. Uniform
  whole-person scale changes preserve normalized features and continue to score at the new distance. Shoulder-span
  change abstains only when it creates ratio evidence without matching changes in raw face/torso/ear numerators.
- UI and compatibility: Debug UI, tray/console status translation, numeric replay, and worker decisions understand
  `MOVING`, `ADJUSTING`, and `OBSERVING`. Worker snapshots preserve the analyzer's environment reason instead of
  overwriting it with the target-lock state. Existing `GOOD`, `WATCH`, `BAD`, `CRITICAL`, and target states remain.
- Verification from the repository root:
  - `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`,
    `test_startup_guards.py`, `test_debug_ui.py`, and `test_vision_replay.py` passed during development. New regressions
    cover brief reach recovery, sustained confirmation, uniform distance scale, forward/backward activity, and
    high-FPS box-scale jitter.
  - Final `runtime\\python311\\python.exe -m py_compile ...`, `ruff check .`, `test_posture_science.py`,
    `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`, `test_startup_guards.py`,
    `test_debug_ui.py`, `test_vision_replay.py`, and `git diff --check` all passed from the repository root.
    Debug UI emitted only the existing bundled Qt missing-font-directory warning; assertions passed.
- Privacy and artifacts: all new evidence is synthetic numeric geometry. No image, frame, video, face crop, identity
  vector/template, or reliability report was saved.
- Gaps: physical-camera comfort and false-observation frequency still require user retest. Cross-device reliability,
  consented recording, external validity, and medical validation remain unverified and unclaimed.
- Conclusion: implementation behavior is locally guarded and ready for split commit/push; physical-camera comfort and
  false-observation frequency remain explicit user-retest gaps.

## 2026-08-13 - Treat two anchors as a normal range without a separation gate

- Source: user field report and product correction that preferred and naturally relaxed postures exist only to define
  a personal accepted range; users must not be rejected or encouraged to slump because the two anchors look similar.
- Git: runtime/UI commit `864d25d`, documentation/audit commit `c47dde6`, branch
  `codex/pr2-phase1-calibration-safety`, tag `none`; delivery target remains existing PR `#23`, with no new PR.
- Reproduction: two five-sample stable stages with identical values, and two naturally close stages whose mean delta
  stayed below the runtime noise band, both raised `no_feature_separates_above_mdc`. The score also used anchor span
  and calibrated direction, so a narrow span amplified jitter and the opposite range boundary was ignored.
- Fix: ordered anchor means now define the accepted range. Identical, close, and wide anchors all calibrate when at
  least one posture feature has five valid values in both stages. Each boundary is extended by the larger of MDC,
  `1.96 × std`, and the small feature floor; excursion beyond either side uses fixed product response scales of
  `0.10` for normalized ratios and `10°` for angles, independent of anchor spacing. The old separation failure and
  feature-disabling branch were removed.
- UI and audit: Debug UI uses the same full production two-anchor path, removes the obsolete anchor-separation reason,
  and places the concrete failure plus preferred/relaxed valid counts directly in the red stage card. The numeric
  reliability report keeps anchor delta as descriptive evidence and states that it never gates calibration.
- Risk: this changes calibration acceptance and bidirectional deviation magnitude. Existing multi-feature support,
  confidence abstention, target/camera guards, hysteresis, exposure thresholds, and legacy-labelled single-frame path
  remain in place. All numeric floors and response scales are product policies, not medical or physiological values.
- Verification from the repository root:
  - Bundled `py_compile` passed for the posture, worker, analyzer, Debug UI, localization, reliability tool, and
    affected tests.
  - `ruff check .` passed.
  - `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`,
    `test_startup_guards.py`, `test_debug_ui.py`, and `test_vision_replay.py` passed. New production-worker and Debug
    UI regressions both complete a 5+5 identical-anchor profile successfully.
  - `tools\collect_posture_reliability.py --help` passed; no `--output` report was requested or saved.
  - `git diff --check` passed. Debug UI emitted the existing bundled Qt missing-font-directory warning; deterministic
    strings and behavior passed, but packaged font fidelity is not claimed.
- Privacy and artifacts: tests and report-schema checks use only synthetic numeric data. No frame, image, video, face
  crop, identity template/vector, or reliability report was saved.
- Gaps: the user's physical-camera calibration must be retested after delivery. Cross-device SEM/MDC, consented
  recording, user comfort, external validity, and medical validation remain unverified and unclaimed.
- Backup: `git stash create` captured all tracked changes before staging at object
  `52d8ab5b67cd327becb2caf416378fa8e2c09806`; unrelated untracked local artifacts were not included.
- Conclusion: deterministic and static verification passed; ready to split code/tests and documentation into
  reviewable commits and push both to the existing PR.

## 2026-08-13 - Make lateral posture evidence invariant to camera roll

- Source: completion audit of the unchanged-upright-posture false alert after the preceding shared-shoulder-scale
  fixes. The audit enumerated every production writer of `camera_drift` and found that no current backend ever sets
  it to true, so the existing camera-drift abstention branch did not protect the live pipeline.
- Git: commit `9b7acba5c453d68c4d2b5435aefb37069c21241c`, branch
  `codex/pr2-phase1-calibration-safety`, tag `none`; delivery target remains the existing PR `#23`, with no new PR.
- Reproduction: a deterministic rigid transform rotated the same eye, ear, shoulder, hip, and torso geometry by
  eight degrees without changing any body-segment length. Before this fix the image-axis shoulder and trunk angles
  corroborated each other, entered `WATCH` immediately, and reached `BAD` after 12 equivalent seconds. This is a
  coordinate-frame failure, not evidence that the user's posture changed.
- Fix: when hip landmarks pass their own quality gate, shoulder asymmetry is now the shoulder-line angle relative to
  the pelvis line, and trunk lean is the torso line relative to that same pelvis reference. These measurements remain
  unchanged under a rigid image/camera roll. With no usable hips, the prior shoulder-only fallback is retained as
  diagnostic evidence and cannot open `WATCH` alone.
- Abstention: calibration records numeric eye-line, shoulder-line, and hip-line angles. If the independent eye and
  pelvis references both move in the same direction beyond their calibrated repeatability ranges and remain within
  three degrees of each other, the runtime returns `UNKNOWN`/`camera_roll_measurement_abstained` and pauses exposure.
  The 3-degree floor/agreement are adjustable measurement-reliability product parameters, not anatomical or medical
  standards.
- Negative evidence: the unchanged skeleton remained free of `WATCH`, `BAD`, and `CRITICAL` under translation,
  uniform scale, rigid roll, and their combined transform. Translation remained `GOOD`; scale and roll explicitly
  abstained with zero exposure. A 30-second rigid-roll sequence accumulated zero exposure.
- Positive evidence: two geometry-consistent posture sequences still intervene. A real forward change retains the
  existing `WATCH` to `BAD` behavior, and a pelvis-relative lateral change from calibrated 0/5-degree shoulder and
  0/7-degree torso anchors to 18/24 degrees also reaches `BAD` after the configured equivalent-exposure interval.
- Verification from the repository root:
  - Bundled Python `py_compile` passed for the changed posture, analyzer, UI, localization, and test modules.
  - `ruff check .` passed.
  - `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`,
    `test_startup_guards.py`, `test_debug_ui.py`, and `test_vision_replay.py` all passed sequentially.
  - `git diff --check` passed. Debug UI emitted only the existing bundled Qt font-directory warning.
- UI evidence: the same `test_debug_ui.py` run revalidated the green `1/2` preferred stage, orange no-sample
  transition, purple `2/2` silent relaxed stage, large camera banner, stage rail, and post-calibration validation
  state. The frozen `ui/index.html` reference is unchanged.
- Documentation correction: `docs/ARCHITECTURE.md` now names the pelvis-relative lateral features and supported
  numeric camera-failure signatures. `docs/TROUBLESHOOTING.md` no longer implies that the compatibility backend has a
  universal camera-motion detector; unsupported camera moves still require manual recalibration.
- Privacy and artifacts: all new evidence is pure numeric/synthetic geometry. No frame, image, video, face crop,
  identity template/vector, or user biometric data was created or saved.
- Gaps: the current camera view still has no detectable person, so a same-person live-camera dual calibration and
  multi-minute unchanged-posture hold remains an external evidence gate. Cross-device reliability, consented
  recording, user feedback, external validity, and medical validation remain unclaimed.
- Conclusion: the reproducible camera-roll false-alert path is fixed and guarded by negative and positive numerical
  evidence. Ready to update the existing PR; physical-camera incident closure still requires a live user retest.

## 2026-08-13 - Require raw forward evidence before ratio-based exposure

- Source: continued investigation of the field report that an unchanged upright posture entered `WATCH` and later
  triggered static-exposure intervention. The preceding shared-scale fix stopped the original 200-to-160 px replay,
  but completion remained unproven without auditing the guard boundary.
- Git: commit `2411be8dae11760837475516fbb3a4e500fa4e48`, branch `codex/pr2-phase1-calibration-safety`, tag `none`;
  delivery target remains the existing
  PR `#23`, with no new PR.
- Remaining root cause: with preferred/relaxed shoulder spans of 200/185 px, the coarse guard allowed another 5% of
  product reliability margin. At 175 px the face/shoulder, torso/shoulder, and ear/shoulder ratios could therefore
  reach deviation about `0.77` before the guard rejected the frame, even while their raw face width, torso height,
  and ear-to-shoulder pixel distance were unchanged. This was a credible slow-drift path to the delayed field alarm.
- Fix: calibration now records the numeric mean ear-to-shoulder pixel offset alongside the existing face width,
  torso height, and shoulder span. A forward ratio group is allowed to accumulate exposure only when both of its
  independent channels are supported by their own raw numerator leaving the calibrated repeatability band. Stable
  raw numerators with changing ratios are treated as one shared-denominator measurement failure and return
  `UNKNOWN`/`shared_shoulder_scale_measurement_abstained` with exposure paused.
- Quality chain: the new raw ear offset is removed together with its normalized ratio when either ear or shoulder
  confidence is below its landmark gate. Low face quality also removes raw interpupillary support. Missing or weak
  numerator evidence abstains rather than granting permission to intervene.
- Positive behavior: two deterministic forward-change replays retain intervention ability. One keeps shoulder width
  fixed; the other moves shoulder width within its accepted calibration range while independently changing the raw
  head and torso geometry. Both enter `WATCH` and reach `BAD` after the configured equivalent-exposure threshold.
  These are product interaction and reliability rules, not medical or physiological standards.
- Verification from the repository root:
  - A five-minute, 1,800-observation 185-to-175 px shoulder-drift replay kept all raw forward numerators fixed,
    explicitly abstained before intervention, and produced no `WATCH`, `BAD`, `CRITICAL`, deviation, or exposure.
  - `test_posture_science.py` and `test_feature_toggles.py` passed, including partial raw support, landmark-quality,
    gradual-drift, and positive-intervention cases.
  - `test_vision_worker.py`, `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, and
    `test_vision_replay.py` passed. Debug UI emitted only the existing bundled Qt font-directory warning.
  - Modified-file Ruff, bundled `py_compile`, and `git diff --check` passed before the final full-suite pass.
- Live camera evidence: a temporary, local-only ASCII junction was used to run current source without changing the
  release bridge. MediaPipe initialized successfully and camera 0 opened, correcting the older assumption that the
  model resource itself was currently missing. A first read hit the intended near-black-frame guard; a subsequent
  30-frame read completed, but detected zero faces and zero poses and returned no posture features. Cameras 1-3 did
  not open. No live human posture decision was therefore obtained, and no frame was displayed or saved.
- Privacy and artifacts: camera probes printed only aggregate/numeric status and immediately released each device.
  No image, video, face crop, identity data, template/vector, or reliability report was saved. The temporary ASCII
  junction is removed after verification and is not part of Git.
- Gaps: the current camera view contains no detectable person, so same-person real-camera calibration and a
  multi-minute unchanged-posture hold remain an external evidence gate. Cross-device SEM/MDC, consented recording,
  user feedback, external validity, and medical validation also remain unclaimed.
- Conclusion: the additional slow shared-denominator path is reproduced and fixed with negative and positive
  deterministic evidence. Ready to update the existing PR after the full local suite; live-user confirmation remains
  required before claiming that the original physical-camera incident is fully closed.

## 2026-08-13 - Abstain when a shared shoulder scale drifts and clarify calibration actions

- Source: field report that an unchanged posture could remain in `WATCH` and later trigger static-exposure
  intervention, plus a request to make the preferred, transition, and relaxed Debug UI stages unmistakable.
- Git: commit `40ec8e70d3f1ef17c5feb1ff02575960b8d70fe4`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; delivery target is the existing PR
  `#23`, with no new PR.
- Numeric root cause: a deterministic replay held face size, torso height, ear height, shoulder slope, and trunk lean
  fixed while the detected `shoulder_width_px` drifted from 200 px to 160 px. Because face/shoulder,
  torso/shoulder, and ear/shoulder all used that width as a denominator, the same detector drift moved three ratios
  together. The old grouping counted those correlated changes as corroboration, reached deviation `1.0`, and reached
  `CRITICAL` after about 300 equivalent high-deviation seconds even though the represented posture was unchanged.
- Scoring fix: face/shoulder and ear/shoulder are now one head/shoulder evidence channel rather than two votes. The
  head/shoulder channel needs independent torso support before the forward group can open `WATCH`; a face and ear
  excursion alone remains numeric diagnostic evidence but abstains from intervention.
- Reliability gate: runtime scoring compares the current numeric shoulder span with both calibrated anchor ranges.
  When it leaves the anchor range by more than the largest of MDC, `1.96 × std`, or a 5% scale allowance, the
  analyzer returns `UNKNOWN` with `shared_shoulder_scale_measurement_abstained`, zero current deviation and
  confidence, and pauses exposure. The 5% allowance is an adjustable product reliability parameter, not an
  anatomical, physiological, or medical threshold.
- Positive protection: a separate deterministic replay keeps shoulder width at the calibrated 200 px while face and
  torso geometry jointly move beyond the relaxed anchor. It still enters `WATCH` immediately and reaches `BAD` after
  the configured 12-second equivalent-exposure threshold, proving the reliability gate does not suppress every
  measurable forward-posture change.
- Debug UI: the preferred, non-sampling transition, and silent relaxed stages now use green, orange, and purple
  12-pixel camera borders; large action-first camera banners; and a bottom two-stage rail showing which posture is
  active. The full dual-anchor flow and the labelled legacy single-frame comparison both remain available. An initial
  offscreen screenshot pass found the rail text vertically cropped; rail padding was corrected and a font-metric
  regression assertion was added.
- Verification from the repository root:
  - Bundled `py_compile` passed for the runtime, UI, localization, and affected test modules.
  - `ruff check .` passed.
  - `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`,
    `test_startup_guards.py`, `test_debug_ui.py`, and `test_vision_replay.py` passed.
  - The unchanged-posture replay covered 1,800 observations over five minutes, encountered the new explicit
    shoulder-scale abstention, and never produced `WATCH`, `BAD`, `CRITICAL`, non-zero deviation, or exposure.
  - Three 1020×700 offscreen Debug UI views were re-rendered with the local Microsoft YaHei system font after the
    crop fix. The stage banner and bottom rail text were complete in preferred, transition, and relaxed views; the
    temporary images contain only the fake test skeleton/UI and remain outside the repository.
  - `git diff --check` passed; the only diagnostic noise was the existing bundled Qt missing-font-directory warning.
- Privacy and artifacts: no camera frame, face crop, video, identity template/vector, reliability report, package,
  release asset, or tag was created. The temporary fake-data UI screenshots are local-only and are not staged.
- Gaps: no live-camera or packaged-display run is claimed. MediaPipe initialization from this non-ASCII workspace
  path remains a separate environment evidence gap, as do cross-device SEM/MDC, consented recording, user feedback,
  external validity, and medical validation.
- Conclusion: the field false-positive mechanism is reproduced and guarded by deterministic negative and positive
  tests; the offscreen Debug UI action states are visually verified. Ready to push to the existing PR, subject to its
  remote checks and the named live-camera gap.

## 2026-08-13 - Validate the calibrated normal range before enabling exposure

- Git: commit `53f416c0333678c04f10c58faf2c92c9a293aaa9`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; delivery target is the existing PR
  `#23`, with no new PR.
- Source: continued field report that the full five-second preferred stage still failed with `preferred_samples` and
  `pose_quality_low`, and that an unchanged upright posture could enter `WATCH` after a successful calibration.
- Calibration root cause: before the preceding follow-up, the MediaPipe extraction floor was `0.50`; the first fix
  lowered both extraction and calibration shoulder-quality floors to `0.40`. Field behavior showed that when either
  shoulder stayed at visibility `0.30-0.39`, the backend still discarded every frame before the five-second
  repeatability window could assess it, so the stage necessarily ended with zero valid samples.
- Calibration fix: shoulder landmarks at or above `0.30` now reach the calibration accumulator. The strict runtime
  intervention confidence floor remains `0.65`; anchor repeatability, noise floors, multi-person rejection, and
  per-feature confidence gates still disable evidence that is not reliable enough. Hip-dependent features retain
  their independent `0.50` landmark floor.
- False-exposure root cause and fix: calibration samples and target-locked monitoring samples cross an adapter/target
  replacement boundary. The analyzer now requires about two stable seconds in the calibrated personal normal band
  after target lock before exposure is enabled. During this validation it returns `UNKNOWN`, reports zero posture
  deviation, and pauses exposure. Uncertain target, motion, camera drift/scale jump, head turn, missing features, and
  low confidence reset the validation window. A posture outside the normal band cannot satisfy the gate.
- Debug UI: preferred, transition, and silent relaxed collection retain their persistent green/orange/purple camera
  banners. After both anchors are collected, a distinct blue `复验` state remains visible until the same production
  normal-range gate activates monitoring; the legacy single-frame comparison remains separate.
- CI: the Windows `python-quality` job now compiles and runs the posture-science, feature-toggle, tracking, Debug UI,
  and numeric replay suites in addition to `test_vision_worker.py`, so these production contracts are enforced on the
  existing PR instead of relying only on local checks.
- Evidence: deterministic tests cover stable shoulder visibility `0.35/0.38`, a complete worker target-adapter
  calibration path, post-calibration validation, and five minutes of unchanged target-replaced posture with no
  `WATCH`, non-zero deviation, or exposure. These values are product reliability parameters, not medical standards.
- Verification from the repository root:
  - Bundled `py_compile` passed for the changed runtime, UI, localization, and test modules.
  - `ruff check .` passed.
  - `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`,
    `test_startup_guards.py`, `test_debug_ui.py`, and `test_vision_replay.py` passed.
  - `git diff --check` passed. The Debug UI test emitted only the existing bundled Qt missing-font-directory warning.
- Artifacts: no package, release asset, tag, image, video, or numeric reliability report was created or saved.
- Remaining evidence gate: the MediaPipe asset exists on disk, but FaceMesh initialization still reports
  `FileNotFoundError` for that exact resource under the non-ASCII workspace path. The live camera chain therefore was
  not run; no real-camera or external-validity pass is claimed.
- Conclusion: deterministic and offscreen checks pass; ready to push to the existing PR, subject to remote CI and the
  named real-camera evidence gap.

## 2026-08-13 - Filter detector jitter from production activity gating

- Source: production-path replay reproduced a serious false-positive path: an unchanged upright posture became `WATCH` because 72 FPS detector/landmark jitter was classified as `MOVING`.
- Root cause: `TargetManager` used instantaneous frame-to-frame bbox velocity for both association prediction and activity classification. About one pixel of ordinary jitter therefore became a high normalized pixels-per-second value.
- Scope: association keeps the raw velocity predictor, while activity classification now uses a configurable 0.20-second low-pass velocity (`motion_smoothing_seconds`). Genuine sustained translation remains above the existing `MOVING` product threshold.
- Debug UI: the camera-visible calibration banner is now nearly full-width with stronger border, font, and phase-specific accessible name; the preferred and relaxed stages remain a single dual-anchor flow with only the preferred countdown.
- Verification: `runtime\\python311\\python.exe test_vision_tracking.py`, `test_feature_toggles.py`, `test_debug_ui.py`, `test_vision_replay.py`, and modified-file `py_compile` passed. A 2,000-frame production-chain replay at 72 FPS with fixed-seed one-pixel Gaussian landmark jitter produced `GOOD=2000`, maximum normalized motion `0.0709`, posture deviation `0`, and exposure `0`.
- Gaps (corrected 2026-08-14): this run attributed the failure to a missing bundled
  `face_landmark_front_cpu.binarypb`; later direct inspection confirmed the file existed and the actual failure was
  MediaPipe's Windows C++ loader resolving the non-ASCII workspace path incorrectly. Real-camera and packaged-rendering
  validation was still not performed in this historical run. No medical or hardware-level validation is claimed.

## 2026-08-13 - Harden normal-posture exposure and clarify Debug UI stages

- Source: follow-up reports that a fixed comfortable posture could enter `WATCH` and later accumulate static exposure, and that the two Debug UI calibration stages were visually too easy to confuse.
- Git: commit `f420ed6f3ce437a0a1ba0aad7ae50441de948037` on branch `codex/pr2-phase1-calibration-safety`, pushed to the existing PR `#23`; no new PR is created.
- Root cause: a single noisy runtime ratio or angle could open a posture group even when the other independent features stayed stable. The scientific profile also needed an explicit abstention state for that incomplete evidence.
- Scope: posture groups now require a second independent feature to reach the product support floor before contributing to posture deviation. A lone excursion is reported as `UNKNOWN` with `posture_evidence_inconclusive`, pauses exposure, and cannot enter `BAD` or `CRITICAL`. Head-turn and moving states remain visible as `WATCH`/observation states but pause exposure and carry zero posture deviation.
- Debug UI: preferred collection retains the full visible 5-second countdown; the approximately 1-second transition explicitly prompts relaxation; relaxed collection runs for its approximately 5-second bounded window with a persistent purple stage banner and indeterminate progress bar, without a second countdown. Stage title, badge, colors, and camera banner are distinct for preferred, transition, relaxed, active, and failed states.
- Verification: `runtime\\python311\\python.exe test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`, `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, `test_vision_replay.py`, bundled `py_compile`, `ruff check` on modified files, and `git diff --check` all passed. Debug UI emitted only the existing bundled Qt missing-font-directory warning.
- Gaps (corrected 2026-08-14): this run attributed the failure to a missing bundled
  `face_landmark_front_cpu.binarypb`; the artifact existed, and the actual failure was non-ASCII Windows path handling
  in MediaPipe's C++ loader. Real-camera calibration, packaged font fidelity, cross-device SEM/MDC, consented recording,
  and external-validity evidence remained unverified in this historical run. Synthetic tests do not replace those gates.
- Conclusion: deterministic protections and stage affordances are ready to deliver through PR `#23`; only the named tracked files for this fix will be staged.

## 2026-08-12 - Correct dual-anchor normal-band semantics and calibration guidance

- Source: user-reported production behavior: unchanged posture entered `WATCH` after dual-anchor calibration and later accumulated static exposure; Debug UI also made the two collection stages too easy to confuse.
- Git: commits `0eb9208`, `3a14995`, and `5035f0a`, branch `codex/pr2-phase1-calibration-safety`, existing PR `#23`, tag `none`.
- Root cause: the previous scoring contract treated `preferred` as deviation `0.0` and the explicitly requested `relaxed` anchor as deviation `1.0`. With `alert_enter=0.70`, the user's valid relaxed calibration posture was immediately classified as a risky posture. A two-second preferred re-entry gate only delayed the incorrect classification.
- Scope: `posture_science.py` now treats both anchors and the interval between them as a personal normal posture band; only excursion beyond the relaxed boundary and runtime noise band has non-zero deviation. `ExposureAccumulator` ignores observation gaps over two seconds instead of backfilling missing time, and the analyzer/replay report `GOOD` once the current posture leaves the watch hysteresis even when old exposure is decaying. `vision_test.py`, `vision_replay.py`, and deterministic tests cover the production scoring path.
- User-visible guidance: `debug_ui.py` keeps distinct colored camera banners for upright, transition, and natural-relaxation phases, then enters active monitoring directly. Tray and localized documentation now say that background relaxed sampling is still active and that monitoring starts immediately after successful calibration; stale re-entry labels and messages were removed. Public architecture, troubleshooting, and ADR text now describe the normal-band contract.
- Risk: this changes the meaning of the relaxed anchor and therefore the product's intervention timing. Exposure thresholds, noise floors, and the two-second observation-gap limit remain adjustable product policy, not medical or physiological standards.
- Verification:
  - `runtime\\python311\\python.exe test_posture_science.py`: passed, including preferred/midpoint/relaxed zero-deviation, continuous over-boundary exposure, decay, and long-gap no-backfill regressions.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed, including multi-minute relaxed and midpoint holds staying `GOOD` with zero exposure.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed, including sparse replay and recovery-to-`GOOD` cases.
  - `runtime\\python311\\python.exe test_debug_ui.py`: passed, including persistent stage banners, geometry containment, and direct active state.
  - `runtime\\python311\\python.exe test_vision_worker.py`, `test_vision_tracking.py`, `test_startup_guards.py`, `test_tray_flyout.py`, `test_identity_model_adapters.py`, `test_identity_verifier.py`, `test_ai_pr_review_guards.py`, and `test_ai_maintainer_manual_flows.py`: passed.
  - `ruff check .`, bundled `py_compile`, and `git diff --check`: passed. Qt emitted the existing bundled-font-directory warning during Debug UI tests; it does not indicate a test failure.
- Gaps: no real-camera run, packaged font-fidelity review, cross-device SEM/MDC study, consented recording, external-validity or medical validation is claimed. The excluded local `README.local.md` was updated for maintainer consistency but is not uploaded.
- Conclusion: deterministic root-cause fix and user guidance are ready for delivery through PR `#23`; remote CI must be rechecked against the final pushed SHA.

## 2026-07-25 - Strengthen PR Review Escalation Guidance Without Weakening Close Gates

- Source: user request to make the PR reviewer more willing to identify present, easily minimized defects and to
  investigate allowed close conditions assertively, while preserving every existing close gate.
- Git: implementation delivered as remote commit `783f771e8f6ebd39dfaf84aea85f5bbffe325937`
  (`feat(review): strengthen PR escalation guidance`), branch `main`, pushed to `origin/main`.
- Scope: updated the PR review prompt to reject "easy to fix" as a reason to ignore a proven problem, require explicit
  findings for evidence-backed defects, and direct the model to test every close gate when it considers closure. Added
  a pure-logic regression test and included it in the remote quality gate.
- Risk: prompt guidance may produce more review findings and more primary close candidates. It does not expand the five
  hard close-rule categories, lower the primary `0.95` confidence threshold, bypass the independent reviewer, or
  permit merging.
- Verification:
  - Command: `runtime\python311\python.exe test_ai_pr_review_guards.py`.
  - Result: passed. Verifies that second-review disagreement, insufficient primary confidence, and missing hard-rule
    evidence all prevent closure.
  - Command: existing AI maintainer, startup, tray flyout, and vision worker logic tests; plus Python compilation and
    `git diff --check`.
  - Result: passed.
  - Command: remote quality-gate run `30155762398` and CodeQL run `30155762406`.
  - Result: passed. Quality gate completed Ruff, Python compilation, the complete logic suite including the new PR
    review guard test, and Windows build; CodeQL completed native build and analysis.
- Gaps: none for the prompt and guard implementation.
- Conclusion: implemented and validated. The model is more assertive about raising defects, but ordinary defects remain
  request-changes cases and automated closure still requires all existing independent gates.

## 2026-07-25 - Replace AI Release Notes Draft with Strict Post-Publication Audit

- Source: user request to audit every formally published GitHub Release, strictly identify missing release information,
  and create a follow-up Issue when the published information needs completion.
- Git: implementation commits `ff5a3b7317709e5989757660f1525c372d718f78`
  (`feat(workflows): audit published releases`) and `625978df0750a852a6eb85bba60da122808d789c`
  (`fix(workflows): enforce strict release findings`), branch `main`, pushed to `origin/main`.
- Scope: replaced `ai-release-notes` with `ai-release-audit`. It runs on `release.published` and supports a manual tag
  re-audit. The flow runs trusted default-branch code, reads only bounded Release metadata, applies deterministic
  naming/body/asset/digest checks, and accepts only allowlisted AI finding categories with evidence and confidence at
  least `0.70`.
- Risk: this flow can create one public Issue for a published Release. It has only `contents: read` and `issues: write`;
  it cannot edit or withdraw a Release, change tags or assets, alter repository files, merge, or change settings. Open
  audit Issues are deduplicated by a stable tag marker.
- Verification:
  - Command: `runtime\python311\python.exe test_ai_maintainer_manual_flows.py`.
  - Result: passed. Covers clean-release no-op, missing required information planning exactly one Issue, and rejection of
    AI finding categories outside the allowlist.
  - Command: `runtime\python311\python.exe test_startup_guards.py`, `test_tray_flyout.py`, and
    `test_vision_worker.py`.
  - Result: passed; existing logic suites remained green.
  - Command: `runtime\python311\python.exe -m py_compile .github\ai-flows\branch_preflight.py`
    `.github\ai-flows\release_audit.py test_ai_maintainer_manual_flows.py`, and `git diff --check`.
  - Result: passed.
  - Command: local Ruff check.
  - Result: skipped; Ruff is not installed in the local runtime. The updated remote quality gate installs
    `requirements-dev.txt` and is the clean-environment authority.
  - Command: remote quality-gate runs `30152308106` and `30152392639`, plus CodeQL runs `30152308116` and
    `30152392641`.
  - Result: all passed. Each quality gate completed Ruff, Python compilation, the logic suite, and the Windows build;
    each CodeQL run completed native build and analysis.
  - Command: manual dry-run `ai-release-audit` run `30152400507` against published `ga-1.2.1`.
  - Result: passed. The model identified four allowlisted, evidenced follow-ups and produced
    `outcome=issue_planned`; `dry_run=true` prevented creation of the proposed Issue.
- Gaps: none for the implemented trigger and dry-run path. The next real `release.published` event will create its
  deduplicated Issue when the deterministic or strict allowlisted finding gate is met.
- Conclusion: implemented, pushed, and exercised against the configured provider. The workflow can only create a
  follow-up Issue; it cannot edit or withdraw a Release or otherwise modify release assets, tags, or repository files.

## 2026-07-25 - Implement Read-Only AI Branch Preflight and Release Notes Drafts

- Source: user request to complete the two lowest-risk AI maintainer workflow frameworks and push them to the canonical remote.
- Git: implementation commit `260e49757b0a6e4469d87ffac3a9665c62c92509`
  (`feat(workflows): implement AI branch and release drafts`), branch `main`, pushed to `origin/main`.
- Scope: replaced the placeholder implementations for ai-branch-preflight and ai-release-notes with flow-specific
  context collection, OpenAI-compatible JSON analysis, guarded read-only results, structured Actions summaries, workflow
  inputs, prompts, and deterministic mock tests. Updated the quality gate to lint, compile, and run those tests.
- Risk: the workflows receive repository metadata and configured AI service Secrets at runtime. They must remain
  read-only: no comments, labels, reviews, merges, tags, releases, asset uploads, repository-file edits, or audit-log
  edits are permitted by either flow.
- Verification:
  - Command: runtime/python311/python.exe test_ai_maintainer_manual_flows.py
  - Result: passed; mock branch and release executions produced step summaries and cleared every requested write effect.
  - Command: runtime/python311/python.exe test_startup_guards.py, test_tray_flyout.py, and test_vision_worker.py
  - Result: passed; existing logic suite remained green in the project runtime.
  - Command: runtime/python311/python.exe -m py_compile on both new flow modules and the new test
  - Result: passed.
  - Command: local branch and release context collection against main..HEAD and ga-1.2.1..HEAD
  - Result: passed; branch comparison returned the expected empty baseline and release collection returned 16 commits.
  - Command: git diff --check and changed-file line-length scan
  - Result: passed.
  - Command: Ruff local check
  - Result: skipped; neither system Python nor runtime/python311 has the Ruff module. The updated remote quality gate installs
    requirements-dev.txt and will provide the authoritative clean-environment Ruff result.
  - Command: remote quality gate run `30149698916` and CodeQL run `30149698902` on the implementation commit
    `260e497`.
  - Result: passed. `python-quality` installed the development requirements, ran Ruff, compiled the Python sources, and
    passed the logic tests; `windows-build` passed; CodeQL `analyze` passed after building the launcher and native host.
  - Command: manual remote `ai-branch-preflight` run `30149717871` with `base_ref=main`, `target_ref=HEAD`, and
    `dry_run=true`.
  - Result: passed. The configured model returned structured JSON with `action=ignore`, confidence `0.90`, and correctly
    reported that both refs resolve to the same commit; no repository write was attempted.
  - Command: manual remote `ai-release-notes` run `30149718787` with `from_ref=ga-1.2.1`, `to_ref=HEAD`,
    `version=0.0.0-validation`, `channel=GA`, and `dry_run=true`.
  - Result: passed. The configured model returned a human-review draft, flagged the validation version as a placeholder,
    and explicitly reported that no tag, release, asset, checksum, or repository file was created or modified.
- Gaps: none for this L1 read-only implementation. The two remaining framework-only flows still require their own
  context collection and separately reviewed action policies before they can be implemented.
- Conclusion: implemented, pushed, and exercised against the configured provider. Both flows remain read-only regardless
  of requested model output and are advisory only; they are not merge gates.

## 2026-07-18 - Add Maintainer Architecture, Release, Troubleshooting, and Contribution Guides

- Source: user request to complete the first-round documentation set and verify that each document is operationally useful.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: added `CONTRIBUTING.md` and `docs/README.md`, `docs/ARCHITECTURE.md`, `docs/RELEASE.md`, and
  `docs/TROUBLESHOOTING.md`; linked the new documentation index and contribution guide from the public README.
- Risk: documentation-only change. Incorrect architecture, package, or diagnostic claims could misdirect contributors
  or release maintainers, so critical assertions were checked against source, CI, the GA-1.2.1 package, and the live
  GitHub release.
- Verification:
  - Command: local Markdown link resolver over `CONTRIBUTING.md`, `README.md`, and `docs/*.md`.
  - Result: passed; 32 local links resolved to existing files.
  - Command: source assertion check against `launcher/EchoPostureLauncher.cs`, `tray_app.py`, `vision_worker.py`,
    `gpu_blur_overlay.py`, `native/BlurOverlayHost.cpp`, and `build_launcher.cmd`.
  - Result: passed; all 28 checked launcher, timing, intervention, IPC, hotkey, and build assertions matched source.
  - Command: compare the documented release allowlist with `dist/EchoPosture-GA-1.2.1-win-x64`.
  - Result: passed; all 17 required top-level entries were present, there were no extra entries, and no forbidden
    top-level repository, audit, backup, or log directories were present.
  - Command: `Get-FileHash -Algorithm SHA256 dist\EchoPosture-GA-1.2.1-win-x64.zip` and live
    `gh release view ga-1.2.1` metadata comparison.
  - Result: passed; local ZIP and uploaded asset both reported
    `7d8f6142eb760ad456155f327b7c4550ee222a85bb24a3a6964318ca5267b618`; live asset name, uploaded state,
    release/tag, draft/prerelease state, and target commit also matched the guide's current baseline.
  - Command: stale version and personal workspace path scan over the new documentation.
  - Result: passed; no GA-1.0.0, `EchoPostureGA100`, or personal absolute workspace path was present.
  - Command: `git diff --check`.
  - Result: passed, exit 0.
- Gaps: no application runtime, camera, overlay, or package build test was run because executable behavior did not
  change. Markdown rendering was checked structurally rather than through a browser preview.
- Conclusion: ready to commit and push; the first-round documentation set has navigable entry points, source-grounded
  architecture, an auditable release checklist, symptom-driven diagnostics, and a contributor workflow tied to CI.

## 2026-07-17 - Align Maintainer Documentation with GA-1.2.1

- Source: user request to correct stale GA-1.0.0 references and unify the current version information.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: updated `README_EXE.md` and the local-only `README.local.md` to identify GA-1.2.1, its `EchoPostureGA121` ASCII bridge, and the `EchoPosture-GA-1.2.1-win-x64` package directory.
- Risk: documentation-only change; no launcher, runtime, package, or release artifact was modified.
- Verification:
  - Command: `rg -n "GA-1.0.0|EchoPostureGA100" README.md README.local.md README_EXE.md`
  - Result: passed; no stale GA-1.0.0 or `EchoPostureGA100` references remain in the current README files.
  - Command: compare the documented bridge and package directory with `launcher/EchoPostureLauncher.cs` and local `dist` contents.
  - Result: passed; the launcher uses `EchoPostureGA121`, and `dist/EchoPosture-GA-1.2.1-win-x64` exists.
  - Command: `git diff --check`
  - Result: passed, exit 0.
- Gaps: no runtime test was run because the change only corrects documentation version labels.
- Conclusion: ready to commit and push; current README version information is aligned with GA-1.2.1.

## 2026-07-16 - Clarify AI Workflow Names and Repository Document Labels

- Source: user request to make the AI issue-triage and PR-review workflow entries easier to discover and to clarify repository document names for maintainers.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: changed only the display names of `ai-issue-triage` and `ai-pr-review` (including their jobs) to show their respective `@ai-issue` and `@ai-review` comment entry points. Added bilingual filename labels and links in `CHANGELOG.md`, `README_EXE.md`, `DEVELOPMENT_LOG.md`, `PROCESS_AUDIT.md`, and `ROE.md`.
- Risk: GitHub Actions checks will display longer Unicode names. Workflow triggers, permissions, job steps, conditions, and implementation code are unchanged.
- Verification:
  - Command: `git diff --check`
  - Result: passed, exit 0.
  - Command: `git diff --word-diff=porcelain -- .github/workflows/ai-issue-triage.yml .github/workflows/ai-pr-review.yml`
  - Result: passed; review confirmed that only the two workflow and job `name` scalar values changed in each file.
- Gaps: no remote Actions run has executed for this display-name-only change. The local environment lacks both PowerShell `ConvertFrom-Yaml` and Python `PyYAML`, so a local YAML parser was unavailable.
- Conclusion: ready to commit and push to `main`; no runtime or workflow-logic behavior changed.

## 2026-07-11 - Keep Open Python Dependency Ranges Stable

- Source: user request after review of Dependabot PRs #16 and #17, which only raised open `>=` lower bounds despite CI already resolving the newer releases.
- Git: commit `pending`, branch `chore/dependabot-open-range-policy`, target `origin/main`.
- Scope: set the root `pip` Dependabot entry to `versioning-strategy: increase-if-necessary`. Existing compatible open requirements, such as `opencv-python>=4.8.0` and `PyQt5>=5.15.9`, will no longer be mechanically raised for routine version updates.
- Risk: Dependabot will not create a version-update PR when the current open requirement already permits the available version. A maintainer must deliberately change a minimum version when dropping older-runtime compatibility is intended. Security updates remain enabled separately through GitHub Dependabot alerts and security updates.
- Verification:
  - Source: GitHub Dependabot options reference confirms that `pip` supports `versioning-strategy`; its `increase-if-necessary` example preserves an already-compatible requirement for a minor update.
  - Command: `git diff --check`
  - Result: passed, exit 0.
- Gaps: GitHub validates the Dependabot configuration after the PR is opened; no local Dependabot runner is configured.
- Conclusion: pending review and GitHub configuration validation.

## 2026-07-10 - GA-1.2.0 Maintainer Intelligence Package and Release

- Source: user request to package the current remote `main` as GA-1.2.0 and publish a new downloadable GitHub Release with an OpenAI-style feature name.
- Git: release source commit `4b102be87b99a44b903cb140cf8190e156d0c322`, branch `main`, tag `ga-1.2.0`.
- Scope: changed launcher release labeling to GA-1.2.0, moved the ASCII bridge to `%LOCALAPPDATA%\EchoPostureGA120`, rebuilt all Windows executables, assembled a minimal current-main portable runtime, removed local logs/internal work files, and named the release `EchoPosture GA-1.2.0 - Maintainer Intelligence`.
- Verification:
  - `runtime\python311\python.exe -m py_compile ...`: passed.
  - `runtime\python311\python.exe test_vision_worker.py`: passed; output ended with `ALL TESTS PASSED`.
  - `runtime\python311\python.exe test_feature_toggles.py`: passed; output ended with `ALL TESTS PASSED`.
  - `.\build_launcher.cmd`: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - First package self-test: environment-only calibration failure because no usable face/shoulder sample was captured; GPU, UI, and vision stages exited 0.
  - Second package self-test: passed; run root `%LOCALAPPDATA%\EchoPostureGA120\current`, all four stages exited 0, `startup_calibrated=True`, and `baseline=True`.
  - Sanitized package verification: GPU host, Debug UI, and Vision stages exited 0; the tray stage could not capture a face/shoulder calibration sample in two attempts, matching the known environment-sensitive calibration condition rather than a missing-file failure.
  - ZIP structure audit: required EXEs, embedded Python, runtime modules, `LICENSE`, and GA build metadata were present; forbidden entries count was 0.
  - Sensitive-content audit: no local user paths, API keys, token-like values, logs, internal process documents, build scripts, test files, or repository metadata were present outside the embedded third-party runtime.
- Artifacts:
  - Package: `dist\EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64`
  - ZIP: `dist\EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64.zip`
  - ZIP size: `301525653` bytes
  - SHA256: `AE0A615B45CFC57829C00523F40DDE05BD245011877CEE8C1C5EDF14E5798EC7`
- Release focus: current desktop mainline, bilingual UI, runtime console controls, AI Maintainer PR/Issue automation, and Claude-route backup failover.
- Remaining gap: long-running camera/overlay behavior and everyday tray interaction still require normal user-side desktop use beyond the packaged self-test.

本日志从 Git 历史和当前仓库文件还原，作为后续过程审计的起点。2026-06-09 以前的条目不是完整实时开发记录；它们只记录 Git 能证明的事实和已经识别出的证据缺口。后续提交必须按 [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md) 补充验证、风险和产物证据。

## 2026-07-07 - Wire Console Feature Toggles to Analyzer Flags

- Source: user request to push the local feature-toggle changes and merge them to the remote main branch.
- Git: commit `pending`, branch `codex/console-feature-toggles`, target `origin/main`.
- Scope:
  - `vision_test.py` `HighPrecisionPostureAnalyzer`: added default-on runtime flags for precision scoring, presence checks, and identity checks.
  - `posture_console.py`: changed the PRECISION, PRESENCE, and IDENTITY vertebrae from disabled placeholders to real toggles wired to the analyzer flags.
  - `test_feature_toggles.py`: added headless checks for defaults, off/on behavior, presence suppression, identity suppression, and basic-mode fallback scoring.
  - `README.md`: documented the console window and the seven tray-console feature controls.
- Risk: turning precision off uses the older threshold-based scoring path with a fixed BAD risk score for intervention compatibility; turning presence off allows multi-face frames to continue through normal scoring; the toggle values are runtime-only and reset to default-on after restart.
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile posture_console.py vision_test.py test_feature_toggles.py`
  - Result: passed, exit 0.
  - Command: `runtime\python311\python.exe test_feature_toggles.py`
  - Result: passed, output ended with `ALL TESTS PASSED`, exit 0.
- Gaps: no live click-through test of the console vertebrae was run on the desktop UI in this pass.
- Conclusion: ready to finish cherry-pick, verify, and push to `main`.

## 2026-06-16 - Public README Rewrite

- Source: user request to keep the local maintainer README for internal use while replacing the remote-facing README with a guide public users can follow.
- Git: commit `d9a4e3917a3d49470b3d8ab86a37a3aeb390fa5c`, branch `main`, tag `none`.
- Scope: rewrote [README.md](README.md) as a public GitHub landing page; removed local machine paths, local `dist/` and `runtime/` assumptions, and debug-first instructions; added release download, SHA256, first-run steps, tray controls, self-test guidance, source/developer entry points, and current limitations. Preserved the prior local README as untracked `README.local.md`.
- Risk:
  - Public users must be directed to the GitHub release ZIP rather than source-tree-only or local-package paths.
  - The root README is the GitHub landing page and must not require knowledge of this local workspace.
  - The local maintainer README must remain untracked so it is not uploaded as public guidance.
- Verification:
  - Command: `gh release view ga-1.0.0 --repo NOVVLA/EchoPosture --json tagName,name,isPrerelease,isDraft,url,targetCommitish,assets`
  - Result: passed; release `EchoPosture GA-1.0.0` is not draft or prerelease, asset `EchoPosture-GA-1.0.0-win-x64.zip` exists with digest `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`.
  - Command: `gh repo view NOVVLA/EchoPosture --json nameWithOwner,url,visibility,isPrivate,defaultBranchRef`
  - Result: passed; repository is `NOVVLA/EchoPosture`, `visibility=PUBLIC`, `isPrivate=false`, default branch `main`.
  - Command: `git fetch origin main`
  - Result: failed because Git HTTPS could not connect to `github.com:443`; GitHub API checks remained available.
- Artifacts: public README update for `https://github.com/NOVVLA/EchoPosture`.
- Gaps: remote update may need the GitHub API path if ordinary Git push remains unavailable in this environment.
- Conclusion: ready to publish after diff review.

## 2026-06-15 - Repository Rename and Public Visibility

- Source: user request to stop using `ICC` as the remote repository name, use the Markdown project name, and keep the repository public.
- Git: commit `50443e71808f11057caadaddeef731006b6be974`, branch `main`, tag `none`.
- Scope: renamed the GitHub repository from `NOVVLA/ICC` to `NOVVLA/EchoPosture`; updated local `origin` to `https://github.com/NOVVLA/EchoPosture.git`; updated process rules so the canonical repository and visibility checks match the public `EchoPosture` repository.
- Risk:
  - Release, push, and audit commands must use the renamed repository.
  - Old `NOVVLA/ICC` links remain as historical release evidence only and must not be treated as the current canonical repository.
  - Documentation that still says the repository should be private would conflict with the current public release posture.
- Verification:
  - Command: `gh repo view NOVVLA/ICC --json name,nameWithOwner,url,isPrivate,visibility,defaultBranchRef`
  - Result: passed before rename; repository reported `nameWithOwner=NOVVLA/ICC`, `visibility=PUBLIC`, and `isPrivate=false`.
  - Command: `gh repo view NOVVLA/EchoPosture --json nameWithOwner,url,visibility,isPrivate`
  - Result: failed before rename because `NOVVLA/EchoPosture` did not yet exist.
  - Command: `gh repo rename -R NOVVLA/ICC EchoPosture --yes`
  - Result: passed.
  - Command: `gh repo view NOVVLA/EchoPosture --json name,nameWithOwner,url,isPrivate,visibility,defaultBranchRef`
  - Result: passed after rename; repository reported `nameWithOwner=NOVVLA/EchoPosture`, `url=https://github.com/NOVVLA/EchoPosture`, `visibility=PUBLIC`, `isPrivate=false`, and default branch `main`.
  - Command: `git remote set-url origin https://github.com/NOVVLA/EchoPosture.git`
  - Result: passed.
  - Command: `git remote -v`
  - Result: passed; fetch and push now point to `https://github.com/NOVVLA/EchoPosture.git`.
- Artifacts: GitHub repository URL `https://github.com/NOVVLA/EchoPosture`.
- Gaps: historical release URLs that were created under `NOVVLA/ICC` are retained as old evidence; GitHub should redirect them, but new commands and rules must use `NOVVLA/EchoPosture`.
- Conclusion: repository name now matches the Markdown project name `EchoPosture`, and the target repository visibility is public.

## 2026-06-13 - GA-1.0.0 Package and Release

- Source: user request to use the latest `main`, set the version to `GA-1.0.0`, build a release package, push to remote, and create a GitHub release.
- Git: release source commit `197fbb092a7b7fbd61626c5c5df709aed01d103c`, branch `main`, tag `ga-1.0.0`; post-release audit commit `pending`.
- Scope: changed package/release labeling to `GA-1.0.0`; changed launcher ASCII bridge from `%LOCALAPPDATA%\EchoPostureTeamAlpha` to `%LOCALAPPDATA%\EchoPostureGA100`; changed self-test title to `EchoPosture GA-1.0.0 self-test`; updated release docs and audit rules; built and packaged a portable Windows x64 folder.
- Risk:
  - Launcher bridge path affects MediaPipe resource loading when the package is under the current Chinese workspace path.
  - Release package must not reuse the old TEAM_ALPHA package, path, bridge label, or release tag.
  - Package verification needs LocalAppData write access; sandboxed execution cannot create the ASCII bridge.
- Verification:
  - Command: `git fetch origin`
  - Result: passed; local `main` matched `origin/main` before release work.
  - Command: `runtime\python311\python.exe -m py_compile tray_app.py vision_worker.py gpu_blur_overlay.py onboarding_toast.py tray_flyout.py posture_console.py debug_ui.py vision_test.py`
  - Result: passed (exit 0).
  - Command: `.\build_launcher.cmd`
  - Result: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - Command: `dist\EchoPosture-GA-1.0.0-win-x64\EchoPostureSelfTest.exe`
  - Result: failed under sandbox because `%LOCALAPPDATA%\EchoPostureGA100` could not be created; MediaPipe then ran from the Chinese path and missed bundled resources.
  - Command: `dist\EchoPosture-GA-1.0.0-win-x64\EchoPostureSelfTest.exe` with approved unsandboxed execution.
  - Result: passed; report showed run root `C:\Users\aaabb\AppData\Local\EchoPostureGA100\current`, GPU host exit code 0, Debug UI exit code 0, Vision exit code 0, Tray monitor exit code 0.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: passed; repository reported `visibility=PUBLIC` and `isPrivate=false`.
  - Command: `gh release create ga-1.0.0 dist\EchoPosture-GA-1.0.0-win-x64.zip --repo NOVVLA/ICC --target 197fbb092a7b7fbd61626c5c5df709aed01d103c --title "EchoPosture GA-1.0.0"`
  - Result: passed; release URL `https://github.com/NOVVLA/ICC/releases/tag/ga-1.0.0`.
  - Command: `gh release view ga-1.0.0 --repo NOVVLA/ICC --json tagName,name,isPrerelease,isDraft,url,targetCommitish,createdAt,publishedAt,assets`
  - Result: passed; tag `ga-1.0.0`, target commit `197fbb092a7b7fbd61626c5c5df709aed01d103c`, `isDraft=false`, `isPrerelease=false`, asset state `uploaded`, size `305721523`, digest `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`.
  - Command: `git ls-remote --tags origin ga-1.0.0`
  - Result: passed; remote tag exists at `639d1dde2f18faf98b8b000ec406941af791ccef`.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: passed after release; repository still reported `visibility=PUBLIC` and `isPrivate=false`.
- Artifacts:
  - Package: `dist\EchoPosture-GA-1.0.0-win-x64`
  - Zip: `dist\EchoPosture-GA-1.0.0-win-x64.zip`
  - Zip size: `305721523` bytes
  - SHA256: `345B9F9E06CA058AF77197EE741B9C87E60D59FCE27B7357728F9C8576CFF5F4`
  - Release URL: `https://github.com/NOVVLA/ICC/releases/tag/ga-1.0.0`
  - GitHub asset digest: `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`
- Gaps: GUI animation smoothness, tray flyout interaction, and long-running camera/overlay behavior still require user-side real desktop validation beyond self-test.
- Conclusion: GA-1.0.0 package was released and post-release checks passed.

## 2026-06-09 - Audit Baseline

- Source: maintenance audit request.
- Git: `6ba14c73bce0a7bca2e11eafe4ac229a79a54d44`, branch `main`.
- Scope: no code change in this baseline; reviewed Git history, tag, ignored directories, docs, logs, backups and package presence.
- Evidence from Git:
  - Current tracked files are source and docs only; `logs/`, `dist/`, `runtime/`, `_backups/` are ignored.
  - Only tag is `dev-20260607-144042`, pointing to `7fa5b6970d20409a310c1837f2abd0c0fa202be2`.
  - Later working-tree review showed separate TEAM_ALPHA-related edits in existing files; this baseline does not validate those edits unless a later log entry explicitly records their verification.
- Gaps:
  - Existing logs do not prove current DEV package verification.
  - Release/package hash and GitHub release回查结果 are not recorded in tracked docs.
  - Early backup `EchoPosture-source-backup-20260530-194638` lacks `BACKUP_MANIFEST.txt`.
- Conclusion: Git can reconstruct the change sequence, but future process credibility requires tracked development logs.

## 2026-06-09 - Process Audit Documentation

- Source: user request to make future development logs credible and readable from Git.
- Git: commit `pending`, branch `main`.
- Scope: added [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md), added this [DEVELOPMENT_LOG.md（Development Log，开发日志）](DEVELOPMENT_LOG.md), and linked both from [README.md](README.md) and [ROE.md（Rules of Engagement，项目协作与操作规则）](ROE.md).
- Risk:
  - Documentation rules now affect future commit and release workflow.
  - Existing working-tree changes in `CHANGELOG.md`, `README_EXE.md`, `launcher/EchoPostureLauncher.cs`, and TEAM_ALPHA edits in existing docs were present during this documentation pass and are not validated by this entry unless separately logged.
- Verification:
  - Command: `git log --reverse --date=iso --pretty=format:'%h %H %ad %an %s'`
  - Result: passed; used to reconstruct historical commit sequence.
  - Command: `git status --short`
  - Result: passed; used to identify current tracked and untracked changes.
  - Command: `git diff -- README.md ROE.md PROCESS_AUDIT.md DEVELOPMENT_LOG.md`
  - Result: passed for tracked README/ROE diff; new untracked audit files were reviewed by direct content inspection.
- Artifacts: no release artifact.
- Gaps: no runtime or UI verification was needed because this entry only changes process documentation.
- Conclusion: ready for review; commit SHA should be filled after commit.

## 2026-06-09 - TEAM_ALPHA Package and Release

- Source: user request to package the current project and create a GitHub release using TEAM_ALPHA labels instead of DEV labels.
- Git: release source commit `db37ea6a88a7958de54f67f3d06c269c6acb6d23`, branch `main`, tag `team-alpha-20260609-154821`; post-release audit commit `pending`.
- Scope: changed package/release naming rules and docs from `DEV` / `dev-...` to `TEAM_ALPHA` / `team-alpha-...`; changed launcher ASCII bridge from `%LOCALAPPDATA%\EchoPostureDev` to `%LOCALAPPDATA%\EchoPostureTeamAlpha`; changed self-test title to `EchoPosture TEAM_ALPHA self-test`; built and packaged a portable Windows x64 folder.
- Risk:
  - Launcher bridge path affects MediaPipe resource loading when the package is under the current Chinese workspace path.
  - Release package must not use the old DEV package or release tag.
  - Package verification needs LocalAppData write access; sandboxed execution cannot create the ASCII bridge.
- Verification:
  - Command: `.\build_launcher.cmd`
  - Result: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - Command: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64\EchoPostureSelfTest.exe`
  - Result: failed under sandbox because `%LOCALAPPDATA%\EchoPostureTeamAlpha` could not be created; MediaPipe then ran from the Chinese path and missed bundled resources.
  - Command: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64\EchoPostureSelfTest.exe` with approved unsandboxed execution.
  - Result: passed; report showed run root `C:\Users\aaabb\AppData\Local\EchoPostureTeamAlpha\current`, GPU host exit code 0, Debug UI exit code 0, Vision exit code 0, Tray monitor exit code 0.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: historical pre-public-state check; superseded by the 2026-06-15 public visibility record above.
  - Command: `gh release create team-alpha-20260609-154821 dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64.zip --repo NOVVLA/ICC --target db37ea6a88a7958de54f67f3d06c269c6acb6d23 --title "EchoPosture TEAM_ALPHA 20260609-154821" --prerelease`
  - Result: passed; release URL `https://github.com/NOVVLA/ICC/releases/tag/team-alpha-20260609-154821`.
  - Command: `gh release view team-alpha-20260609-154821 --repo NOVVLA/ICC --json tagName,name,isPrerelease,url,targetCommitish,createdAt,publishedAt,assets`
  - Result: passed; tag `team-alpha-20260609-154821`, target commit `db37ea6a88a7958de54f67f3d06c269c6acb6d23`, `isPrerelease=true`, asset state `uploaded`, size `305875036`, digest `sha256:7a0018e09a0c5a7a4f3b0ce350a27cb43c94cd01b0c19f42da2078c46f891fd3`.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: historical pre-public-state check; superseded by the 2026-06-15 public visibility record above.
  - Command: `git ls-remote --tags origin team-alpha-20260609-154821`
  - Result: failed; network connection timed out after 300 seconds.
  - Command: `git fetch origin tag team-alpha-20260609-154821`
  - Result: passed; fetched the new tag into the local repository.
- Artifacts:
  - Package: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64`
  - Zip: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64.zip`
  - Zip size: `305875036` bytes
  - SHA256: `7A0018E09A0C5A7A4F3B0CE350A27CB43C94CD01B0C19F42DA2078C46F891FD3`
  - Release URL: `https://github.com/NOVVLA/ICC/releases/tag/team-alpha-20260609-154821`
  - GitHub asset digest: `sha256:7a0018e09a0c5a7a4f3b0ce350a27cb43c94cd01b0c19f42da2078c46f891fd3`
- Gaps: the first `git ls-remote` tag check timed out, but `gh release view` and `git fetch origin tag team-alpha-20260609-154821` confirmed the release tag.
- Conclusion: TEAM_ALPHA package was released and post-release checks passed.

## 2026-05-30 - Initial EchoPosture MVP

- Source: reconstructed from Git.
- Git: `1c4a619a58b2da9701e6aaea7038cf43f2eaeb02`.
- Scope: added the initial README, debug UI, overlay test, vision test, requirements and run scripts.
- Files: `.gitignore`, `README.md`, `debug_ui.py`, `overlay_test.py`, `requirements.txt`, `run_debug_ui.cmd`, `run_overlay_test.cmd`, `run_vision_test.cmd`, `vision_test.py`.
- Git evidence: 9 files changed, 1180 insertions.
- Missing audit content:
  - No recorded user requirement, acceptance criteria or design rationale.
  - No tracked verification command output.
  - No dependency snapshot beyond `requirements.txt`.
  - No known camera/MediaPipe/overlay environment notes.
- Conclusion: source introduction is clear; runtime verification is not auditable from Git alone.

## 2026-06-02 - Tray Runtime, Launcher and GPU Overlay

- Source: reconstructed from Git.
- Git: `692f339e43eeaf5199685787962772ffa97dfdbf`.
- Scope: introduced production-style tray runtime, EXE launcher docs and sources, GPU blur controller, native D3D11/DXGI host, build scripts and expanded high-precision posture analysis.
- Files: `.gitignore`, `CHANGELOG.md`, `README.md`, `README_EXE.md`, `build_blur_overlay_host.cmd`, `build_launcher.cmd`, `debug_ui.py`, `gpu_blur_overlay.py`, `launcher/EchoPostureLauncher.cs`, `native/BlurOverlayHost.cpp`, `tray_app.py`, `vision_test.py`.
- Git evidence: 12 files changed, 3840 insertions, 74 deletions.
- Missing audit content:
  - No split log for tray, launcher, GPU host, posture scoring and docs.
  - No tracked build output for `EchoPosture.exe`, `EchoPostureSelfTest.exe` or `BlurOverlayHost.exe`.
  - No tracked self-test summary proving camera, UI, vision and tray checks passed.
  - No risk record for overlay cleanup, camera release, DXGI failure, compositor fallback or UI blocking.
- Conclusion: implementation scope is well evidenced by Git; verification and risk closure are not.

## 2026-06-07 - DEV UI Prototype and Blur Fallback Controls

- Source: reconstructed from Git.
- Git: `7fa5b6970d20409a310c1837f2abd0c0fa202be2`.
- Tag: `dev-20260607-144042`.
- Scope: added frozen offline UI reference, expanded blur fallback behavior and controls, updated DEV package metadata and docs.
- Files: `CHANGELOG.md`, `README.md`, `README_EXE.md`, `build_blur_overlay_host.cmd`, `debug_ui.py`, `gpu_blur_overlay.py`, `launcher/EchoPostureLauncher.cs`, `native/BlurOverlayHost.cpp`, `tray_app.py`, `ui/index.html`, `vision_test.py`.
- Git evidence: 11 files changed, 1585 insertions, 49 deletions.
- Local artifact evidence: `dist/EchoPosture-DEV-20260607-144042-win-x64` exists and includes `DEV_BUILD.txt`.
- Missing audit content:
  - No tracked SHA256 for the DEV package or key EXE files.
  - No tracked build transcript or release回查结果.
  - Package `logs` directory has no current self-test output.
  - UI prototype has no tracked screenshot or visual comparison note.
  - Existing tag proves source point, not package integrity.
- Conclusion: source tag and package directory exist; package verification remains underdocumented.

## 2026-06-07 - Restore Frozen UI Reference

- Source: reconstructed from Git.
- Git: `9ce2a99c0e85dde7222b4594551d2b483c923569`.
- Scope: restored `ui/index.html` as a frozen visual reference and updated docs.
- Files: `CHANGELOG.md`, `README.md`, `README_EXE.md`, `ui/index.html`.
- Git evidence: 4 files changed, 9 insertions, 30 deletions.
- Missing audit content:
  - No record explaining what was changed before restore and why restore was required.
  - No visual before/after evidence.
  - No explicit frozen-file exception note tied to the commit.
- Conclusion: restore action is visible in Git; rationale and validation need future documentation discipline.

## 2026-06-07 - Project Editing Rules

- Source: reconstructed from Git.
- Git: `94ca210e149a01dd59dc2c3a53e5e9f1d221cf47`.
- Scope: added `ROE.md` and linked project rules from README.
- Files: `README.md`, `ROE.md`.
- Git evidence: 2 files changed, 73 insertions.
- Missing audit content:
  - Rule effective date is visible, but prior commits were not created under these rules.
  - No explicit migration note for older process gaps until this development log.
- Conclusion: rules became tracked here; earlier history remains partially reconstructed.

## 2026-06-08 - OCULI/VERTEBRA Console Integration

- Source: reconstructed from Git.
- Git: `9c448b77ffdfdc4df2ab9c107b580af341e962ef`.
- Scope: added `posture_console.py`, connected console to tray double-click and added supporting vision/tray changes.
- Files: `posture_console.py`, `tray_app.py`, `vision_test.py`.
- Git evidence: 3 files changed, 965 insertions, 9 deletions.
- Missing audit content:
  - No UI screenshot or viewport verification.
  - No manual interaction checklist for tray double-click, console open/close, state readout or failure behavior.
  - No performance note for the new console path.
- Conclusion: integration is clear in Git; UI behavior needs tracked verification.

## 2026-06-08 - Console Polish

- Source: reconstructed from Git.
- Git: `edc61914396e9be97b144c020f7a73d954be3f66`.
- Scope: polished console performance, labeled switches and fused frameless UI.
- Files: `posture_console.py`.
- Git evidence: 1 file changed, 335 insertions, 107 deletions.
- Missing audit content:
  - No visual regression note.
  - No performance measurement or interaction checklist.
  - No accessibility or scaling note.
- Conclusion: code change is localized; user-facing verification is missing.

## 2026-06-09 - Process Rule Tightening

- Source: reconstructed from Git.
- Git:
  - `ff4e1cb0dc40698f73afc5e72335e4dd288db95b` - document merge branch policy.
  - `437e0aaee0ed1d3eef9a2d91f8d1a684191390da` - document canonical repository remote.
  - `6ba14c73bce0a7bca2e11eafe4ac229a79a54d44` - tighten commit push requirement.
- Scope: clarified branch, remote and commit/push rules in `ROE.md`.
- Missing audit content:
  - Rules were updated, but no separate process audit file existed before this change.
  - No release verification template existed before this change.
- Conclusion: these commits improve process rules but need this log and [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md) to make future records auditable.

## 2026-06-09 - Tray Icon Logo Asset

- Source: reconstructed from Git.
- Git: `a4a8eb8e2f0e311143abf5141c56782f929b296f`.
- Scope: added `logo.png` and updated tray icon usage.
- Files: `logo.png`, `tray_app.py`.
- Git evidence: 2 files changed, 6 insertions.
- Missing audit content:
  - No image provenance note.
  - No tray icon visual check in notification area.
  - No fallback behavior note if the asset cannot load.
- Conclusion: change is small and visible; asset provenance and UI verification should be tracked going forward.

## 2026-06-13 - Onboarding Toast, Tray Flyout, Decorative Eye, Console Geometry

- Source: user request（统一 UI 至 ui/onboarding.html 演示：开场弹窗开关、托盘浮窗替代右键菜单、眼睛改纯装饰、控制台黄金分割居中+入场动画）。
- Git: commit `pending`, branch `main`.
- Scope:
  - 新增 `ui/onboarding.html`（开场流程演示参考，用户提供）。
  - 新增 `onboarding_toast.py`：右下角开场弹窗 + 苹果式眼睛滑条开关（单条时间轴驱动；玻璃卡片+logo 衬底预渲染为 pixmap；入场/谢幕只动 windowOpacity/位置）。共享 `render_glass_card()`；`EyeSlideSwitch` 支持 one_shot 与双向两种模式。
  - 新增 `tray_flyout.py`：托盘右键玻璃浮窗（监测开关 + 重新校准/最深效果/红色退出按钮 + 左上齿轮开控制台），Qt.Popup 点外自动收起。
  - `tray_app.py`：启动流程改为 开场弹窗→校准倒计时；移除 QMenu 托盘菜单，右键→浮窗；新增 open_console()；stop() 收口弹窗/浮窗。另含此前在途的高 DPI 属性改动（AA_EnableHighDpiScaling/AA_UseHighDpiPixmaps）。
  - `posture_console.py`：眼睛改纯装饰（常闭、点击穿透、删除 set_open/clicked），监测启停职责移交托盘浮窗；新增眼下 ECHOPOSTURE 字样；窗口尺寸=可用高度×0.618（保持 880:600）自动居中；每次显示播放 420ms 淡入+上浮入场动画；另含此前在途的 UI_SCALE=1.17 缩放改动。
- Risk: 启动流程新增用户确认环节（不拨开关则不进入校准）；托盘右键不再有原生菜单（退出入口移至浮窗红色按钮）；README 中"托盘菜单"描述已过时（待后续文档更新）；UI_SCALE/高 DPI 在途改动与本任务同提交（用户已确认提交当前文件状态）。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile onboarding_toast.py tray_flyout.py tray_app.py posture_console.py`
  - Result: passed (exit 0)。
  - Command: 静态接线断言脚本（导入四模块；断言 EyeSlideSwitch one_shot/set_on/toggled、TrayFlyout 按钮与 popup_bottom_right、EyeItem 无 clicked/set_open、tray_app 无 QMenu()/QAction(/setContextMenu、Context→flyout 接线）
  - Result: passed（临时脚本已按 ROE 清理，不入库）。
- Gaps: 本机 shell 环境 Qt GUI 层无法初始化（QGuiApplication 构造挂起，QCoreApplication 正常），开场弹窗动画、浮窗交互、控制台入场动画均未实机目检，待用户验证；README 托盘菜单章节未更新。
- Artifacts: 备份 `_backups/pre-vision-worker-20260613-000411/`（含 BACKUP_MANIFEST.txt，HEAD ef3ebc1）。
- Conclusion: local only; 待用户实机验证 UI 行为。

## 2026-06-13 - Move Vision Pipeline Off the GUI Thread

- Source: user request（UI 明显卡顿）。根因：TrayMonitor 以 72Hz QTimer 在 GUI 主线程同步执行 摄像头读帧 + MediaPipe FaceMesh/Pose 推理 + 评分（单次 50-150ms >> 14ms 周期），事件循环饱和导致全部动画掉帧；重新校准同步连采 18 帧另卡死主线程约 3 秒。
- Git: commit `pending`, branch `main`.
- Scope:
  - 新增 `vision_worker.py`：VisionWorker daemon 线程持有 VisionEngine+analyzer（构造/调用/close 全在工作线程），最新值信箱 + 一次性错误/校准回执；`average_calibration_sample`/`sample_is_usable` 从 tray_app 迁出为纯函数。
  - `tray_app.py`：监测主循环改为 10Hz 轻量 `_tick`（只取信箱、驱动 overlay、消费回执，<1ms/帧）；启动校准与 recalibrate_now 全部后台化（采样/平均/定基线在工作线程，结果回执后按原分支提示与恢复）；`--self-test` 保留完全同步本地路径不经 worker；`stop()` 收口 `worker.stop(join_timeout=2)`；`_EngineProxy` 保持 `monitor.engine.set/get_capture_fps` 接口，posture_console 零改动。TrayMonitor 公开接口无变化。
- Risk: 校准状态机（startup/recal × 成功/失败/进行中暂停退出）是最大回归面；worker join 超时（驱动卡死）时摄像头灯可能延迟熄灭；校准提示从同步变为约 1-3 秒后回执。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile vision_worker.py tray_app.py posture_console.py gpu_blur_overlay.py onboarding_toast.py tray_flyout.py`
  - Result: passed (exit 0)。
  - Command: `runtime\python311\python.exe test_vision_worker.py`（FakeEngine + 真 analyzer 逻辑层测试：线程归属、信箱覆盖、校准平均与旧语义一致、失败回执、错误一次性传播、出错自暂停、start 失败同步抛出、fps 往返、stop join、close 在工作线程）
  - Result: passed，输出 `ALL TESTS PASSED`，exit 0。测试入库为 `test_vision_worker.py`。
  - Command: tray_app/gpu_blur_overlay/posture_console 接线静态断言（无 calibration_timer、tick=100ms、worker.stop、self-test 同步路径、公开接口齐全）
  - Result: passed（临时脚本已清理）。
- Gaps: 本机无法初始化 Qt GUI 层，未实机验证：动画流畅度（核心验收）、启动校准/重校准 toast、摄像头拔出错误路径、退出后摄像头灯熄灭、`--self-test` 实跑。待用户按清单验证。
- Artifacts: 回退点 commit 861ad1a + `_backups/pre-vision-worker-20260613-000411/`。
- Conclusion: local only; 待用户实机验证。

## 2026-06-13 - Console Hide Hibernation and Overlay IPC Dedup

- Source: 同上卡顿任务的次要优化项。
- Git: commit `pending`, branch `main`.
- Scope:
  - `posture_console.py`：hideEvent 停 250ms refresh_timer 并停所有椎骨呼吸辉光动画（控制台"关闭"按钮实为 hide，此前隐藏后仍持续重绘）；showEvent 恢复。
  - `gpu_blur_overlay.py`：set_target/set_config IPC 去重（仅状态/配置变化时写管道）；gpu_ready 恢复时强制重发；force_clear/boost 同步缓存。
- Risk: 去重缓存与宿主实际状态不一致会导致命令漏发——已在 gpu 恢复、clear、boost 路径强制重置缓存。
- Verification: 同上一条目的 py_compile 与接线断言（hideEvent/_last_sent_target/_config_dirty 存在）；GPU 宿主实际行为待用户实机验证（压暗/模糊触发与解除、最深效果测试）。
- Conclusion: local only; 待用户实机验证。

## 2026-06-13 - Restyle Startup Calibration Dialog to Glass-Card Language

- Source: user request（把校准提示框统一成与开场弹窗/托盘浮窗一致的风格：logo 半透明打底、无边框、布局好看、配色合理）。
- Git: commit `99d8146`, branch `main`.
- Scope:
  - `tray_app.py` `StartupCalibrationDialog`：由浅色（`#f7f9fc`）带 1px 边框、居中的 `QDialog`，改造为同族视觉语言——`FramelessWindowHint` + `WA_TranslucentBackground` 无边框透明窗；复用 `onboarding_toast.render_glass_card()`（深色玻璃渐变 + 右侧 logo 蓝图衬底向左渐隐 + 1px 高光描边）；三段静态文字（小标题 `ECHOPOSTURE · 启动校准` / 主标题 `请坐直，保持舒适姿态` / 两行说明）沿用 toast 做法一次性画进缓存 pixmap，银白/银灰分级、左对齐垂直居中。
  - 新增 `_CountdownRing` 自绘控件替代旧的大号数字：淡白底环 + 银白→品牌红渐变进度弧（12 点顺时针递减）+ 居中数字，作为右侧焦点，与左侧文字构成左文右环布局；动态部分作为子控件自绘，文字进卡片（与 toast 开关/文字分工一致）。
  - `showEvent` 入场 240ms `windowOpacity` 0→1 淡入；`_center_on_screen` 主屏居中。
  - 对外接口不变：`StartupCalibrationDialog(seconds)` → `step()` → `_refresh()` 全保留，`_countdown_step`/`finalize_calibration` 驱动逻辑零改动。导入相应补充（QEasingCurve/QPointF/QPropertyAnimation/QRectF、QBrush/QLinearGradient/QPen、render_glass_card/_font/SILVER_*/RED_SOFT）。
- Risk: 无边框窗失去原生标题栏/关闭按钮（弹窗本就倒计时结束自动关闭，无影响）；窗口标志由 `Qt.Dialog|Customize|Title|StayOnTop` 改为 `Qt.Dialog|Frameless|StayOnTop`；视觉为纯样式改动，不触碰校准状态机。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile tray_app.py`
  - Result: passed (exit 0)。
  - Command: 离屏冒烟（QT_QPA_PLATFORM=offscreen 构造对话框 + repaint + 连续 step()）
  - Result: passed；圆环定位 (422,60)、尺寸 580×248，倒计时 5→4→3→2→1→0 且归零时 `step()` 返回 True、`_CountdownRing` 数值随之更新；玻璃卡/ logo 衬底/圆环弧等矢量部分渲染正常（临时预览脚本已清理，不入库）。
- Gaps: 本机 offscreen 沙箱 Qt 字体子系统不可用（`QFontDatabase().families()` 直接令进程崩溃），所有 `drawText` 静默不出字，故无法在本环境截出带文字成品图——左侧三段文字与圆环内数字的实际排版需用户在真机/真实显示下目检。
- Conclusion: local only; 矢量布局与倒计时行为已验证，文字渲染待用户实机目检。

## 2026-07-11 - Security Policy and Dependency Update Automation

- Source: user request to add the highest-priority repository health and security files.
- Git: commit `pending`, branch `docs/security-maintenance`, tag `none`.
- Scope:
  - Added `SECURITY.md` with supported-version boundaries, a private reporting route, response targets, coordinated
    disclosure guidance, dependency triage expectations, privacy precautions, and safe-harbor language.
  - Added `.github/dependabot.yml` for weekly root-level `pip` and GitHub Actions version checks with bounded open pull
    request counts.
  - Enabled and verified repository settings for Dependabot alerts, Dependabot security updates, and private
    vulnerability reporting as part of the same maintenance task.
- Risk:
  - The response targets create ongoing maintainer expectations and must be revisited if maintainer capacity changes.
  - Dependabot pull requests can expose compatibility regressions in MediaPipe, OpenCV, PyQt, packaging, launcher, or
    native build paths; automated updates still require normal review and verification.
  - The existing HTTP Python package index configuration remains outside this file-addition task and is a follow-up
    supply-chain risk.
- Verification:
  - Command: `git diff --check`.
  - Result: passed (exit 0); no whitespace errors.
  - Command: line-length review for `SECURITY.md` and `.github/dependabot.yml`.
  - Result: passed; no line exceeded 120 characters.
  - Command: manual schema review against GitHub's official Dependabot options reference.
  - Result: passed; configuration uses version 2 with required ecosystem, directory, and schedule fields for root-level
    `pip` and `github-actions` manifests.
  - Command: local YAML parser checks through Python PyYAML and Ruby YAML.
  - Result: skipped; neither PyYAML nor Ruby is installed in the available environment. The configuration remains
    subject to GitHub's server-side processing after merge.
  - Command: GitHub REST API enablement and status checks for vulnerability alerts, automated security fixes, and
    private vulnerability reporting.
  - Result: passed; enablement calls returned HTTP 204, private vulnerability reporting returned `enabled: true`, and
    automated security fixes returned `enabled: true` with `paused: false`.
- Artifacts: documentation and repository configuration only; no release or binary artifacts.
- Gaps: Dependabot's first scheduled job and generated pull request cannot be verified before the configuration reaches
  the default branch.
- Conclusion: file-level validation passed; ready for remote pull-request verification.

## 2026-08-09 - Phase 1 Calibration Safety and Multi-user Debounce

- Source: user request to implement the first priority from `docs/plans/EchoPosture_vision_identity_upgrade_plan.md`.
- Git: implementation commit `329c537`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - `vision_test.py`: require a single person, both face and pose observations, and complete core posture metrics before automatic calibration; debounce multi-user state for 0.3 seconds.
  - `vision_worker.py`: reuse the shared calibration predicate, filter averaged samples, and reset the calibration window when a second person appears.
  - `test_feature_toggles.py`, `test_vision_worker.py`: add deterministic coverage for incomplete/multi-person calibration samples, calibration-window reset, and multi-user debounce.
  - Plan reference: `docs/plans/EchoPosture_vision_identity_upgrade_plan.md` was already present at the canonical path in the PR base (`origin/main`, commit `3691e8d`); no plan-file move is included in this PR.
- Risk: stricter calibration may reject short-lived partial camera observations and require the user to remain visible with complete face and pose metrics; multi-user status now waits 0.3 seconds before suppression.
- Verification:
  - Command: `runtime\\python311\\python.exe -m py_compile vision_test.py vision_worker.py test_feature_toggles.py test_vision_worker.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed, exit 0.
  - Command: `runtime\\python311\\python.exe test_feature_toggles.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; `ALL TESTS PASSED`, exit 0.
  - Command: `runtime\\python311\\python.exe test_vision_worker.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; `ALL TESTS PASSED`, exit 0.
  - Command: `runtime\\python311\\python.exe test_startup_guards.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; 8 tests, exit 0.
  - Command: `git diff --check`.
  - Result: passed; only the repository's existing LF/CRLF conversion warnings were reported.
- Gaps: Ruff was not run because the `ruff` command is unavailable in the current environment; no real-camera or packaged Windows self-test was run; the PR and remote merge were not yet completed at log-entry creation time.
- Artifacts: no release or binary artifacts.
- Conclusion: local implementation validated for logic tests; ready for PR review after commit and push.

## 2026-08-09 - PR22 AI Review Follow-up

- Source: GitHub Actions AI review comment `5231950418` on PR #22.
- Git: implementation commit `30906d6`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - Clear the multi-user debounce anchor when presence checking is disabled, preventing stale timestamps from bypassing the confirmation window after re-enabling the feature.
  - Derive averaged observation flags from eligible samples instead of force-stamping them.
  - Use `calibration_sample_is_complete` as the single canonical calibration predicate across `vision_test.py`, `vision_worker.py`, and `tray_app.py`.
  - Add regression coverage for an ineligible fallback and the presence-toggle debounce path.
  - Surface missing calibration conditions when no complete sample is available, so calibration failure is diagnosable from the tray message.
- Risk: the same-frame completeness invariant remains intentionally conservative; real-camera co-occurrence of face and pose metrics is still unverified and must be checked before merge.
- Verification:
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed, 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe -m py_compile tray_app.py vision_test.py vision_worker.py test_feature_toggles.py test_vision_worker.py`: passed.
- Gaps: Ruff remains unavailable in the environment; no real-camera or packaged Windows self-test was run.
- Artifacts: no release or binary artifacts.
- Conclusion: AI review findings addressed where confirmed; PR requires CI rerun and real-camera review of the conservative calibration condition.

## 2026-08-10 - Vision Plan Priority Handoff Register

- Source: user request to record the remaining 2.0 implementation priorities for handoff and later audit.
- Git: implementation commit `98bc4ba`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope: added an execution register to `docs/plans/EchoPosture_vision_identity_upgrade_plan.md` covering P1 review gates and the ordered P2-P8 work, with task IDs, dependencies, status definitions, and completion evidence.
- Current state: P1 remains in review in PR #22; P2 is the next executable priority after P1 approval and evidence completion. No P2-P8 implementation has started.
- Verification: `git diff --check` passed; no source or runtime behavior changed.
- Gaps: the register intentionally preserves the known real-camera, packaged self-test, licensing, and release-validation gates.

## 2026-08-10 - Phase 2 Evidence Assets and Architecture Decision

- Source: user instruction to begin P2 after the P1 implementation work.
- Git: local branch `codex/pr2-phase1-calibration-safety`; PR #22 was checked through the GitHub API and remains open and unmerged (`merged: false`, `state: open`).
- Scope:
  - Added `docs/decisions/ADR-0001-vision-modes-and-fallback.md` to freeze the three mode responsibilities, fallback order, safety semantics, and evidence gates.
  - Added `docs/vision-evidence/README.md`, empty `recording_manifest.csv`, and empty `deletion_log.csv` with consent, retention, deletion, and no-media-in-Git rules.
  - Added `docs/vision-evidence/metrics-baseline.md` with timing boundaries, P50/P95 metrics, scenario matrix, and initial performance gates.
  - Added `docs/vision-evidence/license-audit.md` with source-linked, field-separated audits for Ultralytics YOLO26 candidates, CVLFace AdaFace ViT, AdaFace IR101, and CAFace.
  - Linked the new evidence documents from `docs/README.md` and marked P2 `IN_PROGRESS` in the plan register.
- Verification:
  - Playwright extension session opened the official Ultralytics license page, CVLFace model/repository, AdaFace repository, and CAFace repository; observed source text and repository license metadata.
  - GitHub API returned repository license metadata: Ultralytics `AGPL-3.0`; CVLFace, AdaFace, and CAFace `MIT`.
  - No candidate weights were downloaded; exact weight license, revision, SHA-256, and training-data redistribution terms remain explicitly unverified.
- Gaps: no consented recordings or benchmark values exist yet; P1 remote merge, real-camera evidence, and packaged self-test remain open. P2 does not authorize model integration or P3-P8 implementation.
- Conclusion: P2 evidence framework and architecture decision are in progress; release-facing license approval is blocked until exact artifacts and data terms are audited.

## 2026-08-10 - Phase 3/4 Unified Backend and Target State Machine

- Source: user instruction to implement P3 and P4 together after the P2 evidence documents.
- Git: local branch `codex/pr2-phase1-calibration-safety`; no commit or remote push was requested in this turn.
- Scope:
  - Added `vision_backend.py` with `PersonObservation`, `Keypoint`, `VisionCapabilities`, `VisionBackend`, and `CompatibilityBackend`.
  - Added `vision_tracking.py` with deterministic bounding-box/velocity association, track lifecycle, calibration target lock, occlusion, away, reacquisition, identity-uncertain, multi-present, and target-ambiguous states.
  - Wired `TrayMonitor` and `VisionWorker` through the compatibility backend and target manager while preserving the existing synchronous packaged self-test path.
  - Extended immutable samples/snapshots with target state and track metadata; `MULTI_PRESENT` continues posture scoring when the target observation remains separate, while ambiguous face/body association is safety-suppressed.
  - Added target-specific `PostureFeatures` extraction so the analyzer consumes the locked target observation instead of an arbitrary frame-level sample from a multi-person backend.
  - Added localized labels for new target states and `test_vision_tracking.py` covering backend conversion, crossing, multi-person continuation, occlusion/reacquisition, no silent promotion, ambiguity, analyzer gating, and worker integration.
  - Added `vision_replay.py`, `test_vision_replay.py`, and the metrics-only `benchmark-synthetic-p3-p4.jsonl` replay matrix covering multi-person entry/exit, target departure/return, crossing, and away transitions.
  - Updated `docs/ARCHITECTURE.md` and the vision plan checklist/status for EP-VISION-010/011 and EP-TRACK-001 through EP-TRACK-005.
- Verification:
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py`: passed.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py`: passed.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all P3/P4 deterministic tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed.
  - `git diff --check`: passed; only the repository's existing LF/CRLF conversion warnings were reported.
- Gaps: no real-camera run, consented recording replay, packaged Windows self-test, or multi-person pose backend was executed in this environment. Compatibility mode intentionally emits `TARGET_AMBIGUOUS` when its single pose cannot be paired with one of multiple faces; full `MULTI_PRESENT` continuation requires a backend that emits separate person observations.
- Conclusion: P3/P4 implementation and deterministic integration are complete locally; hardware/replay/package evidence remains required before changing their priority status to release-complete.

## 2026-08-10 - Phase 3/4 Completion Audit Hardening

- Scope:
  - Added `PostureFeatures` and `PostureFeatureExtractor`; the worker now scores the locked target's observation, not a frame-level bystander sample.
  - Limited ambiguous-face suppression to ambiguous target association; a clear target remains scoreable while an ambiguous bystander is tracked separately.
  - Added one-second multi-person exit stabilization, timestamp-scaled velocity prediction, non-target pruning coverage, numeric timestamp support, and presence/identity toggle coverage.
  - Added the metrics-only JSONL replay CLI and synthetic 18-frame matrix; no camera frames or identity data are stored.
- Verification:
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 expected state frames.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; target-specific scoring, ambiguous bystander, exit stabilization, numeric timestamp, and all prior P3/P4 cases.
  - Ruff and startup guard checks passed after the hardening changes.
- Remaining external evidence is unchanged: real camera, consented recording replay, and packaged Windows self-test are not run in this environment.

## 2026-08-10 - P4 Cross-frame Association Hardening

- Source: deterministic regression exposed a silent target swap when two people crossed and the backend supplied no stable detection IDs.
- Scope:
  - `vision_tracking.py`: replaced observation-order greedy association with global one-to-one frame matching; motion prediction now carries more weight than stale-frame IoU, exact detection IDs remain authoritative, and near-tied geometry enters `TARGET_AMBIGUOUS`.
  - `test_vision_tracking.py`: added regression coverage for the no-ID crossing case and a symmetric geometry tie that must not silently switch the locked target.
- Verification:
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all tracking, worker integration, target-specific scoring, crossing, occlusion, and ambiguity tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed; `ALL TESTS PASSED`.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_replay.py vision_replay.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_replay.py vision_replay.py`: passed.
  - `git diff --check`: passed; only existing LF/CRLF conversion warnings were reported.
- Gaps: P2 evidence assets still have no consented recordings, measured camera baselines, or exact candidate-weight license/SHA-256 audit; real-camera, packaged self-test, and remote P1 merge remain unverified. P3/P4 therefore remain `IN_PROGRESS` in the plan register.
- Conclusion: deterministic association safety is hardened locally; this does not close the external P2/P4 evidence gates.

## 2026-08-10 - P3/P4 Local Implementation Completion Audit

- Source: user instruction to proceed with P3 and P4 together after the P2 architecture/evidence work.
- Scope:
  - P3: completed the model-independent observation/capability contract, compatibility MediaPipe adapter, target-specific posture feature extraction, and Worker integration while preserving the legacy sample path.
  - P4: completed target lock, global one-to-one association, velocity prediction, track lifecycle, multi-person continuation, occlusion/away/reacquisition states, face-body ambiguity handling, and no-silent-promotion safeguards.
  - Hardened compatibility association so a missing face anchor is ambiguous, and hardened calibration completeness so normalized target samples still reject `person_count != 1`, `MULTI_PRESENT`, and `TARGET_AMBIGUOUS` frames.
  - Extended `benchmark-synthetic-p3-p4.jsonl` to 24 metrics-only frames covering stable-ID crossing, no-ID crossing, geometry ties, multi-person entry/exit, target departure/return, and away transitions.
- Verification:
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all P3/P4 state, association, target-specific scoring, and Worker integration tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 24 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`, including target-manager presence calibration reset.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed; `ALL TESTS PASSED`.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_worker.py test_vision_replay.py vision_replay.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_worker.py test_vision_replay.py vision_replay.py`: passed.
  - `git diff --check`: passed; only existing LF/CRLF conversion warnings were reported.
- Remaining gates: real camera and consented recording replay, packaged Windows self-test, P1 remote merge, measured P2 baselines, and exact candidate-weight/data-license evidence remain unverified. The plan register therefore keeps P2/P3/P4 at `IN_PROGRESS` rather than release-complete.
- Conclusion: P3/P4 implementation and deterministic evidence are complete locally; external validation is still required before release sign-off.

## 2026-08-10 - Debug UI Target Panel Verification

- Source: user request to make the existing CMD test panel show the latest P2/P3/P4 changes in a directly verifiable page.
- Scope:
  - `debug_ui.py`: added an injectable backend factory for deterministic panel tests; the production path remains `CompatibilityBackend + TargetManager`.
  - `test_debug_ui.py`: added an offscreen, camera-free test using a fixed frame plus the real target manager and posture analyzer. It verifies `ACQUIRING`, calibration, `TARGET_LOCKED`, track `1`, and people count `1`.
  - `run_debug_ui.cmd`: keeps `--target-panel` enabled and forwards caller arguments such as `--camera 1`.
  - `docs/README.md` and `docs/TROUBLESHOOTING.md`: documented live-panel and camera-free verification commands, expected states, and evidence limits.
- Verification:
  - `runtime\python311\python.exe -m py_compile debug_ui.py vision_backend.py test_debug_ui.py`: passed.
  - `ruff check debug_ui.py vision_backend.py i18n.py test_debug_ui.py`: passed.
  - `runtime\python311\python.exe test_debug_ui.py`: passed; `ACQUIRING` -> `TARGET_LOCKED`, track `1`, people `1`.
  - `runtime\python311\python.exe test_vision_tracking.py`: passed; all tests.
  - `runtime\python311\python.exe test_vision_worker.py`: passed; all tests.
  - `runtime\python311\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\python311\python.exe vision_replay.py docs\vision-evidence\benchmark-synthetic-p3-p4.jsonl`: passed; 24 frames.
- Evidence limits: this validates panel wiring and state presentation without hardware. Real camera landmark quality, display behavior, and packaged self-test still need user-side execution.

## 2026-08-10 - P5 Model-independent identity verifier foundation

- Scope:
  - Added `identity_verifier.py` with the `IdentityVerifier` contract, three-state results (`IDENTITY_CONFIRMED`, `IDENTITY_UNCERTAIN`, `IDENTITY_MISMATCH`), quality scoring, normalized landmark alignment, configurable 8-20 frame aggregation, and debounced decisions.
  - Added asynchronous submit/request APIs with reacquisition and heartbeat trigger gates.
  - Kept raw frames, face crops, and temporary bystander vectors outside the data model; `clear_template()` and `close()` release the in-memory template, score window, and trigger state.
  - Added `test_identity_verifier.py` covering quality rejection, enrollment, aggregation, mismatch safety, async trigger throttling, and cleanup.
- Verification:
  - `runtime\\python311\\python.exe test_identity_verifier.py`: passed; `ALL TESTS PASSED`.
  - `ruff check identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; `ALL TESTS PASSED`.
- Remaining gates:
  - CVLFace AdaFace ViT-Base KP-RPE and AdaFace IR101 adapters are not integrated because exact weights, SHA-256, training-data terms, and distribution permissions remain blocked in `docs/vision-evidence/license-audit.md`.
  - No real-camera, consented-recording, false-accept/false-reject, or packaged privacy audit has been run.
- Conclusion: P5 model-independent foundation is implemented locally; P5 is not release-complete.

## 2026-08-10 - P5 pinned CVLFace adapters and offline cache preparation

- Scope:
  - Added `identity_model_adapters.py` with pinned CVLFace specs for ViT-Base KP-RPE/WebFace4M revision `6530d73fb0af4d1d8287f31d559780c648ebd22a` and IR101/WebFace4M revision `f2b38d9e24bfe301490d8dd081d8924b102333dd`.
  - Added `requirements-p5-models.txt` as a separate optional environment definition (`torch`, `torchvision`, `transformers`, `huggingface-hub`, `safetensors`, `Pillow`); the desktop runtime was not modified.
  - Added `tools/download_p5_models.ps1`, which downloads only the pinned files and writes a SHA-256 manifest outside Git.
- Official sources checked:
  - CVLFace model card quick start: `https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m`.
  - CVLFace model download guidance: `https://github.com/mk-minchul/CVLface/blob/main/README_MODELS.md`.
- Verification:
  - `ruff check identity_model_adapters.py test_identity_model_adapters.py identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile identity_model_adapters.py test_identity_model_adapters.py identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_identity_model_adapters.py`: passed; `ALL TESTS PASSED`.
  - Identity, Worker, and target-tracking tests all passed.
- Download status:
  - PowerShell direct download failed with `无法连接到远程服务器`.
  - Edge downloaded ViT `model.safetensors` (460344344 bytes, SHA-256 `3c6d37ea874c2f38ffc9a7f0e9247efc994c3fb5c12d044759ac294e19d127f7`) and IR101 `model.safetensors` (260980552 bytes, SHA-256 `21adb6220e8799a0e658f16946df9649c7269f432fe9810a7b9c4ad1241080a8`) into `D:\\Download\\EchoPosture-P5\\models`.
  - Edge downloaded ViT `pretrained_model/model.pt` (460381841 bytes, SHA-256 `b8d5adde0a00f6482b5e866b6e37eeaa947302a40d9af31c211af72f34d38afb`) and IR101 `pretrained_model/model.pt` (261111273 bytes, SHA-256 `7a3341c3afc507fd6f50345638d2f3ef2f0e931d5b4f5aba60e15709853fcf5e`).
  - Official CVLFace custom code, config, wrapper, and model YAML files were hydrated from the GitHub repository into both caches; `missing_model_files()` now returns empty tuples for both specs.
- Conclusion: both pinned model caches are locally complete for the adapter's core file gate; Torch/Transformers installation and actual model inference remain unverified, and no weight is licensed for distribution.

## 2026-08-10 - P5 isolated model environment

- Created `D:\\Download\\EchoPosture-P5\\venv` with `uv` and Python 3.11.9.
- Installed the optional model stack from `requirements-p5-models.txt`: Torch 2.1.2, torchvision 0.16.2, Transformers 4.33.0, huggingface-hub, safetensors, Pillow, OmegaConf, PyYAML, and their dependencies.
- The first local ViT load reached Transformers custom-code loading and exposed two issues: NumPy 2.x is incompatible with the Torch 2.1.2 wheel, and the local model directory must be temporarily added to `sys.path`. The adapter now handles the latter and the requirements pin `numpy<2` for the former.
- The follow-up NumPy install and smoke command were blocked by the execution approval service overload; no successful model inference result is claimed.
- `tools\\hydrate_p5_model_code.ps1` now pins CVLFace GitHub commit `308142aa50adf2e187711354f7524635d3414f1e`; rerunning that pinned refresh was also blocked by the same transient approval-service overload.
- Final `ruff check identity_model_adapters.py test_identity_model_adapters.py` and `git diff --check`: passed (only existing LF/CRLF conversion warnings remain).

## 2026-08-10 - P5 repository-bundled weights and startup wiring

- Copied the complete pinned ViT-KP-RPE and IR101 CVLFace model directories,
  including custom model code and configuration, into `models/p5/`.
- Added `.gitattributes` rules so `.safetensors` and `.pt` files use Git LFS.
- Changed `identity_model_adapters.default_model_root()` to prefer the
  repository-bundled `models/p5/` path; the D-drive cache remains a fallback.
- Updated `TrayMonitor` to load the bundled ViT adapter during normal startup,
  create an `IdentityVerifier`, inject it into `VisionWorker`, and release both
  verifier and model on shutdown. Missing dependencies or a damaged cache
  disable only the identity gate and leave posture monitoring running.
- No-camera inference smoke test and license/distribution approval remain open.
- The smoke test reached the bundled CVLFace custom code and exposed a missing
  `timm` dependency; `requirements-p5-models.txt` now pins `timm==0.9.12`, but
  installation timed out before a second load attempt.

## 2026-08-11 - Posture science core refactor v1

- Source: user-approved posture science refactor plan; implementation of the accepted ADR-0002 decision.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope: added `posture_science.py` and metrics-only `tools/collect_posture_reliability.py`; extended
  `VisionSample`, `PostureFeatures`, `Keypoint`, target motion/activity output, and `PostureDecision`; switched the
  production tray analyzer and both startup/manual recalibration flows to a two-anchor profile; the original timing
  interpretation was later corrected in the 2026-08-12 entry below; retained `set_baseline_from_sample()` only for
  explicit legacy debug/self-test; updated tray intervention,
  i18n, debug metrics, README/docs, ADR-0002, replay, and focused tests.
- Product policy: watch enter/exit `0.50/0.40`, alert enter/exit `0.70/0.55`, severe deviation `0.85`, equivalent
  exposure `12s/30s`, confirmation `3s`, cooldown `60s`. These values are interaction policy parameters, not medical
  or physiological standards.
- Data boundary: runtime monitoring does not save frames, video, face crops, identity templates, or vectors. The
  reliability command writes a numeric JSON report only when `--output` is explicitly supplied.
- Recovery: created `_backups/posture-science-v1-preedit-20260811-170304/` before edits; the worktree already contained
  unrelated identity/model and documentation changes, which were preserved.
- Verification passed:
  - `runtime\\python311\\python.exe -m py_compile posture_science.py vision_test.py vision_backend.py vision_tracking.py vision_worker.py tray_app.py debug_ui.py i18n.py`
  - `runtime\\python311\\python.exe test_posture_science.py`
  - `runtime\\python311\\python.exe test_feature_toggles.py`
  - `runtime\\python311\\python.exe test_vision_worker.py`
  - `runtime\\python311\\python.exe test_vision_tracking.py`
  - `runtime\\python311\\python.exe test_vision_replay.py`
  - `runtime\\python311\\python.exe test_startup_guards.py`
  - `runtime\\python311\\python.exe test_debug_ui.py` (offscreen; Qt emitted existing missing-font-directory warnings)
  - `runtime\\python311\\python.exe tools\\collect_posture_reliability.py --help`
- Additional verification passed: `ruff check .`; `git diff --check` (only existing LF/CRLF conversion warnings).
- Not run: real camera reliability collection, `--output` report generation, SEM/MDC cross-device repeatability,
  external clinical validity, user comfort feedback, package build, and GUI/manual overlay observation.
- Conclusion: local implementation ready for static verification; real-camera and external-validity evidence remain open.

## 2026-08-12 - Debug UI full two-anchor calibration

- Source: user report that the diagnostic UI exposed only the legacy single-frame calibration after the production
  path had moved to the two-anchor posture model.
- Git: core behavior commit `bac3c33`, UI/docs in this commit, branch
  `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - Made the Debug UI primary calibration action run the production-equivalent explicit phase flow: a full visible
    five-second preferred-posture stage, an approximately one-second ignored transition, then a silent approximately
    five-second relaxed-posture stage with at most two seconds of bounded extension.
  - Reused `CalibrationPlan`, `CalibrationAccumulator`, `calibration_rejection_reason()`,
    `calibration_measurement_values()`, and `HighPrecisionPostureAnalyzer.set_calibration_profile()` so stage counts,
    quality gates, MDC feature disabling, and failure semantics match the production decision layer.
  - Added live preferred/relaxed sample counts, rejection details, cancellation, failure, and successful profile
    summary in both Chinese and English.
  - Preserved the legacy single-frame path as a visually secondary, explicitly labelled comparison button. The fast
    packaged `debug_ui.py --self-test` contract still uses that explicit legacy comparison and reports its mode.
  - Extended the offscreen Debug UI test to cover a complete 5+5-sample profile and the separate legacy path.
- Evidence boundary: deterministic UI tests use timestamped numeric samples and do not prove real-camera repeatability
  or cross-device SEM/MDC. Those external evidence gates remain open.

## 2026-08-12 - Correct dual-anchor production timing

- Source: user-reported severe production bug. The initial implementation incorrectly split the existing visible
  five-second countdown into 2 seconds preferred plus 3 seconds relaxed, even though the user had not yet been told to
  relax. This shortened both anchors and caused frequent valid-sample failures.
- Root-cause fix:
  - Kept the visible countdown at five seconds and assigned every sample in it only to the preferred anchor.
  - Added an explicit preferred/transition/relaxed state machine. The countdown closes before the tray says the user
    may relax; transition samples are ignored for about one second and cannot count or reset either anchor.
  - Added a silent approximately five-second relaxed window. If it has fewer than five valid samples at the nominal
    target, collection may extend by at most two seconds before reporting failure.
  - Routed startup calibration, manual recalibration, and the Debug UI primary calibration through the same phase
    semantics. The labelled legacy single-frame Debug UI and self-test paths remain separate.
- Policy boundary: 5-second preferred, about 1-second transition, about 5-second relaxed, and 2-second maximum
  extension are adjustable product interaction timings, not medical or physiological standards.
- Evidence boundary: deterministic tests verify phase ownership, ignored transition samples, bounded extension,
  timeout failure, dialog-before-relax ordering, and legacy separation. Real-camera timing and repeatability remain an
  independent evidence gate.

## 2026-08-12 - Fix calibration quality dropout amplification

- Source: user reported production calibration still failed with both `preferred_samples` and `pose_quality_low` even
  during the full five-second preferred stage.
- Root cause:
  - Every rejected frame cleared all previously accepted samples in the active anchor, so one transient quality or
    motion dropout near the end converted an otherwise valid five-second window into a sample shortage.
  - Aggregate `pose_quality` used the minimum visibility across shoulders and hips. A partly cropped or lower-quality
    hip therefore rejected otherwise reliable face/shoulder evidence, despite hip-dependent features being optional.
  - The calibration layer added an unvalidated `0.65` pose cutoff above the backend's own `0.50` usable-landmark
    threshold, discarding otherwise measurable `0.50-0.64` shoulder observations before SEM/MDC could assess them.
- Fix:
  - Multiple-person and ambiguous-target observations still reset the active anchor because they can contaminate
    identity. Zero-person dropouts, low quality, motion, missing keypoints, and temporary uncertainty now abstain for
    one frame and are counted for audit without erasing accepted samples. Previously, `face_count == 0` was mistakenly
    grouped with multiple-person contamination and could still clear the full preferred window.
  - Aggregate pose quality now represents the required shoulder pair. Landmark-level gates remove hip-dependent torso
    features when hip visibility is low while retaining reliable face/shoulder, shoulder-asymmetry, and ear/shoulder
    evidence.
  - The calibration pose floor now matches the backend's `0.50` usability floor. Feature repeatability statistics and
    MDC, rather than an unsupported stricter whole-frame threshold, decide whether a feature has usable evidence.
- Evidence: deterministic regressions prove that four valid samples survive an intervening low-quality frame and reach
  five on the next valid frame, and that `0.55/0.58` hip visibility does not reject high-confidence shoulder evidence.
- Remaining evidence gate: a real-camera production calibration must still be rerun to confirm the observed hardware
  no longer fails; deterministic tests do not establish the user's live camera result.

## 2026-08-13 - Narrow calibration validity to posture evidence

- Source: continued investigation of the user-reported startup failure reporting both a preferred-stage sample
  shortage and body-keypoint quality failure.
- Root cause found in the calibration boundary: `CalibrationAccumulator.add()` counted any finite calibration value,
  including environment-only distance/scale values. A frame could therefore increase the valid-sample counter even
  after all posture features had been removed by face, shoulder, hip, or ear quality gates. Finalization then reported
  a generic feature/quality failure that did not describe the frame-level evidence.
- Fix:
  - Stage counters now advance only when at least one posture feature is usable; environment-only values are audited as
    `no_posture_features` and do not satisfy the five-sample requirement.
  - Low face quality removes only the face-derived ratio. Independent shoulder/lateral/torso evidence can still be
    collected when its own landmarks meet the quality floor.
  - Added localized diagnostics for `no_posture_features` in Chinese and English.
- Verification: `runtime\\python311\\python.exe test_posture_science.py`, `test_vision_worker.py`, and
  `test_vision_tracking.py` all pass; source compiles and `git diff --check` passes.
- Evidence boundary (corrected 2026-08-14): this run reported
  `mediapipe/modules/face_landmark/face_landmark_front_cpu.binarypb` as missing. Later byte-level inspection confirmed
  the artifact existed; MediaPipe's Windows C++ loader was failing on the non-ASCII workspace path. A real-camera
  rerun was not performed in this historical run and is not retroactively claimed as complete.

## 2026-08-12 - Prevent relaxed-anchor startup exposure and noise amplification

- Source: user observed that the Debug UI did not clearly distinguish the two anchor stages and that monitoring entered
  `WATCH` immediately after calibration even though the ending posture had not changed.
- Deterministic root cause:
  - The calibration necessarily ended at the relaxed anchor, which is defined as deviation `1.0`; monitoring began on
    the next frame, so holding the expected ending posture immediately opened WATCH and accumulated exposure.
  - Runtime scoring used SEM-derived MDC as if it were the complete single-frame noise band. Because SEM shrinks with
    sample count, a marginal anchor span could leave a near-zero denominator and amplify ordinary frame jitter.
- Fix:
  - Added a post-calibration preferred-posture re-entry gate. The relaxed ending posture and all re-entry frames pause
    exposure; monitoring activates only after the preferred range is held for about two stable seconds.
  - Runtime tolerance now uses the larger of MDC and `1.96 ×` within-anchor standard deviation. Anchor features that do
    not clear this single-observation repeatability floor with a minimum signal margin are disabled before group
    scoring.
  - Added a high-contrast Debug UI stage card: green preferred, orange transition, purple silent relaxed, blue re-entry,
    plus distinct active and failed states. The card now sits directly above the camera area at the same width, rather
    than being buried in the metrics panel. The legacy single-frame control remains separately labelled.
- Policy boundary: the `1.96` repeatability multiplier, minimum signal margin, and two-second re-entry stability are
  adjustable product parameters, not medical or physiological standards.
- Evidence:
  - Deterministic regressions cover 60 seconds at the relaxed ending posture with zero exposure, preferred re-entry
    activation, preferred-range runtime jitter, rejection of an all-noise near-identical anchor profile, marginal
    feature disabling, and distinct Debug UI states.
  - A separate long-hold regression activates monitoring after preferred re-entry, then holds the preferred posture for
    five minutes; every decision remains `GOOD`, `posture_deviation` remains `0`, and exposure remains `0`.
  - The offscreen Qt geometry check at a 1020 x 700 Debug UI reports a 678 x 86 stage card above a 678 x 576 camera
    area, with equal widths and no overlap. Offscreen preferred/relaxed screenshots confirmed the green/purple stage
    styling, camera placement, and control hierarchy. Qt emitted its existing bundled-runtime missing-font-directory
    warning and rendered system UI text blank in those screenshots, so they are not treated as Chinese text or font
    fidelity evidence.
- Verification passed from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe -m py_compile posture_science.py vision_test.py vision_worker.py tray_app.py debug_ui.py tools\collect_posture_reliability.py test_posture_science.py test_feature_toggles.py test_vision_worker.py test_vision_tracking.py test_startup_guards.py test_debug_ui.py test_vision_replay.py`
  - `ruff check .`
  - `runtime\python311\python.exe test_posture_science.py`
  - `runtime\python311\python.exe test_feature_toggles.py`
  - `runtime\python311\python.exe test_vision_worker.py`
  - `runtime\python311\python.exe test_vision_tracking.py`
  - `runtime\python311\python.exe test_startup_guards.py`
  - `runtime\python311\python.exe test_debug_ui.py`
  - `runtime\python311\python.exe test_vision_replay.py`
  - `git diff --check`
- Verification note: `runtime\python311\python.exe -m ruff check .` was unavailable because the bundled interpreter
  does not include the `ruff` module; the repository's installed `ruff check .` executable passed instead.
- Backup: before staging, `git stash create` captured all 18 tracked modifications at object
  `388fd230704151915bcc5a057d12a587e5d95859` from source HEAD
  `9ad26519e9ed5d0f049696652d15f0cb3bd71d78`; no untracked local artifacts were included.
- Gaps: a real-camera production calibration must still be rerun under the user's camera, framing, lighting, normal
  movement, and lens-drift conditions. No live-camera pass, successful screenshot-based text/font review, consented
  recording, or external-validity result is claimed.

## 2026-08-12 - Harden runtime posture evidence and debug calibration cues

- Source: continued investigation after the user reported calibration failures and unclear dual-anchor stage changes;
  manual follow-up to the incomplete PR review.
- Git: runtime commit `dcbcf20`, Debug UI commit `eedadfe`, branch
  `codex/pr2-phase1-calibration-safety`, existing PR `#23`, tag `none`.
- Runtime root causes and fixes:
  - Production scoring called unfiltered `measurement_values()`, so a hip pair at confidence `0.20` could still let a
    noisy `torso_shoulder_ratio` drive `WATCH`, `BAD`, and `CRITICAL` while aggregate shoulder quality remained `0.95`.
    Runtime extraction now applies the same feature-local shoulder/hip/ear gates as calibration, and decision
    confidence is computed only from the features that actually reached scoring. Low-quality hip-dependent evidence
    now abstains and cannot accumulate exposure.
  - A normalized anchor span of `0.020` with a `0.015` runtime noise floor left only a `0.005` scoring denominator.
    The product reliability margin now requires anchor separation of at least `2.0` runtime-noise bands; narrower
    features are disabled instead of amplifying frame jitter.
  - `ExposureAccumulator` previously integrated throughout WATCH hysteresis, so deviation `0.60` could preload minutes
    of exposure below the `0.70` alert threshold. Integration now occurs only while alert hysteresis is active; WATCH
    remains an observation state and recovery still decays existing exposure exponentially.
- Debug UI behavior:
  - The full production-equivalent dual-anchor control remains the primary action; the legacy single-frame comparison
    remains secondary and explicitly labelled.
  - The stage area is now a 136px-or-taller full-color card with localized `1/2`, relax, `2/2`, return, active, and retry
    badges plus a stable progress bar. When the preferred five-second stage ends, a high-contrast one-second prompt is
    overlaid in the center of the camera area before silent relaxed sampling starts.
- Verification passed from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe -m py_compile posture_science.py vision_test.py debug_ui.py i18n.py tools\collect_posture_reliability.py test_posture_science.py test_feature_toggles.py test_debug_ui.py test_vision_replay.py`
  - `ruff check .`
  - All tracked root logic scripts: `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`,
    `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, `test_vision_replay.py`,
    `test_tray_flyout.py`, `test_identity_model_adapters.py`, `test_identity_verifier.py`,
    `test_ai_pr_review_guards.py`, and `test_ai_maintainer_manual_flows.py`.
  - `runtime\python311\python.exe tools\collect_posture_reliability.py --help`.
  - `git diff --check` passed with only the repository's existing LF/CRLF conversion warnings.
  - Offscreen Qt validation at `1020 x 700`: stage card `678 x 141`, camera `678 x 521`, centered prompt
    `598 x 150` fully inside the camera area, phase badge `放松`, progress `50`, and nonblank window render.
- Verification note: the bundled Qt runtime continues to report its existing missing-font-directory warning. The
  deterministic tests verify localized strings and geometry, but do not establish packaged font rendering fidelity.
- Backup: `git stash create` captured all tracked changes at object
  `84dac123f71cce8bf3d8eeb6767251af4c65c300`; untracked models, review folders, posters, and local artifacts were not
  included or staged.
- Gaps: real-camera calibration, cross-device SEM/MDC, user-visible packaged UI, consented recording, and external
  validity remain independent evidence gates. No medical or hardware-level validation is claimed.
- Conclusion: runtime false-exposure paths and Debug UI stage visibility are covered by deterministic regression tests;
  ready for delivery to the existing PR branch.

## 2026-08-11 - AI review findings routed into the vision plan

- Source: user request after manual audit of the AI review posted on PR #23.
- Git: plan commit `5e8953626609ed4ea50ec4cfc1fbad2f5cecc0a6`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Facts corrected:
  - PR #23 changes `.gitattributes`, model adapter code, and local download/hydration tooling, but its 42 changed files and remote head tree contain no tracked `models/p5/` weight files.
  - The earlier "repository-bundled weights" entry described a local, untracked worktree copy. It did not establish that weights were committed, uploaded, or distributed through the PR.
  - Exact weight and training-data license approval remains a future integration/release gate; it is not evidence that this PR currently redistributes weights.
- Scope:
  - Added `EP-TRACK-006` to bound global association work and require a safe ambiguity fallback plus adversarial-count latency evidence before a real multi-person backend is connected.
  - Added `EP-ID-008` so disabling identity verification prevents model loading, verifier injection, verification requests, and embedding processing, then clears in-memory state.
  - Linked `EP-UI-002` to the runtime gate and updated the P4/P5 priority register and completion evidence.
- Risk: this change records follow-up work only; the current recursive matcher and identity runtime behavior are not fixed by this documentation commit.
- Verification:
  - `git diff --check`: passed.
  - Targeted `rg` review confirmed `EP-TRACK-006` and `EP-ID-008` appear in their phase lists, priority rows, and handoff status text.
  - GitHub API confirmed PR #23 remote head `bcd4bfb17d39916055439462a89058fd1f725307`; changed files matching `models/p5/*`: `0`; head-tree paths matching `models/p5/*`: `0`.
  - Pushed plan commit `5e8953626609ed4ea50ec4cfc1fbad2f5cecc0a6` to the PR branch; GitHub then reported the same SHA as PR #23 head and still reported `0` changed files matching `models/p5/*`.
  - Posted the corrective `@ai-review` request at `https://github.com/NOVVLA/EchoPosture/pull/23#issuecomment-5255309355`.
  - AI review run `31507828605` completed successfully, but the model output failed JSON parsing and the workflow safely downgraded to a confidence-0 comment at `https://github.com/NOVVLA/EchoPosture/pull/23#issuecomment-5255324440`; it did not issue a substantive corrected review.
- Gaps: implementation, unit tests, real-camera behavior, latency measurements, privacy audit, and license approval remain open under the new and existing plan tasks.
- Conclusion: plan update and corrective comment delivered; the AI route executed safely but did not produce a substantive correction, so the earlier `CHANGES_REQUESTED` review remains for manual handling.

## 2026-08-11 - AI PR Review Timeout Recovery

- Source: repeated GitHub Actions failures in `ai-pr-review` runs #69 and #70; both ended with an uncaught `TimeoutError` after the 60-second client deadline.
- Git: implementation commit `97c34a1`, branch `fix/ai-review-timeout-recovery`, tag `none`.
- Scope:
  - `.github/ai-flows/common_ai_client.py`: classify socket/read timeouts as `AIClientTimeoutError`, keeping them inside the existing safe AI error contract.
  - `.github/ai-flows/pr_review.py`: use a configurable `AI_PR_REVIEW_TIMEOUT_SECONDS` value with a 300-second default for primary and secondary review calls, while tolerating invalid or non-positive configuration.
  - `.github/workflows/ai-pr-review.yml`: expose the timeout override through the repository variable `AI_PR_REVIEW_TIMEOUT_SECONDS`.
  - `.github/workflows/quality-gate.yml`, `test_ai_client_timeout.py`: run lint, compile, and regression checks for the shared client and timeout fallback.
- Risk: a longer request deadline can keep the review job waiting longer, but remains below the workflow's 20-minute job limit and leaves room for a slow non-streaming response such as the observed 73 seconds; timeout failures now produce an auditable safe comment/label instead of crashing the job.
- Verification:
  - `runtime\\python311\\python.exe test_ai_client_timeout.py`: passed on Python 3.11.9; timeout wrapping, the 300-second PR review default, and safe fallback all passed.
  - `runtime\\python311\\python.exe test_ai_pr_review_guards.py`: passed.
  - `runtime\\python311\\python.exe test_ai_maintainer_manual_flows.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile .github/ai-flows/common_ai_client.py .github/ai-flows/pr_review.py test_ai_client_timeout.py`: passed.
  - `ruff check .github/ai-flows/common_ai_client.py .github/ai-flows/pr_review.py test_ai_client_timeout.py`: passed.
  - `git diff --check`: passed; only existing LF-to-CRLF checkout warnings were emitted.
- Gaps: no local provider credentials are available, so a real AI response and post-fix GitHub run require remote verification after publication. `actionlint`, PyYAML, and Ruby YAML were unavailable locally, so workflow YAML parsing is deferred to GitHub Actions.
- Artifacts: no release or binary artifacts.
- Conclusion: local regression validation passed; ready for remote branch CI and pull-request review.

## 2026-08-12 - PR23 main integration and final delivery audit

- Source: user request to continue delivery of the dual-anchor calibration and runtime evidence fixes through the
  existing PR without creating another feature PR.
- Git: integration commit `b6a331f5a3e9bd31c0eb6353cebaba75859a715d`, branch
  `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Integration:
  - Created backup branch `backup/pr23-before-main-merge-20260812` at
    `eedadfeca421177fad26b7a3568a08922ae8ed8f` before changing branch history.
  - Fetched `origin/main` at `8a9c6cd2f802b3275270373c2f7dd8246b8ddf5b` and merged it into the PR branch.
  - The only content conflict was `DEVELOPMENT_LOG.md`. The resolution preserved both the posture-science history and
    main's AI-review timeout recovery entry; main's source/workflow/test changes merged without manual code edits.
  - Updated the runtime and Debug UI delivery record with their pushed commits: `dcbcf20` and `eedadfe`.
- Local verification after the merge:
  - `ruff check .`: passed.
  - Bundled Python `py_compile`: passed for posture science, analyzer, backend, tracking, worker, tray, Debug UI,
    reliability CLI, AI client/review code, and the corresponding focused test scripts.
  - Passed: `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`,
    `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, `test_vision_replay.py`,
    `test_tray_flyout.py`, `test_identity_model_adapters.py`, `test_identity_verifier.py`,
    `test_ai_client_timeout.py`, `test_ai_pr_review_guards.py`, and `test_ai_maintainer_manual_flows.py`.
  - `tools\collect_posture_reliability.py --help`: passed without writing a report.
  - `git diff --check` and staged diff checks: passed. Debug UI tests emitted only the existing bundled Qt missing-font
    directory warning.
- Remote evidence for integration head `b6a331f`:
  - Push and pull-request quality-gate runs `31608381489` and `31608386942`: `python-quality` and `windows-build`
    completed successfully in both runs.
  - Push and pull-request CodeQL runs `31608381405` and `31608386887`: `analyze` completed successfully in both runs;
    the resulting `CodeQL` check also completed successfully.
  - AI review workflow run `31608386895` completed successfully.
  - GitHub reported `mergeable: MERGEABLE`; the prior source conflict is resolved.
- Review disposition:
  - Review `4907534781` on old commit `bcd4bfb` was dismissed as stale and factually incorrect after GitHub's PR files
    API confirmed there are zero changed paths under `models/p5/`. The review had treated LFS path rules as proof that
    model weights were committed.
  - After dismissal, GitHub reports `reviewDecision: REVIEW_REQUIRED`. Ruleset `Protect main branch` requires one
    approving review, so PR `#23` remains `BLOCKED` pending normal human approval even though the required status checks
    pass and the branch is technically mergeable.
- Remote state: PR `#23` remains the delivery PR at
  `https://github.com/NOVVLA/EchoPosture/pull/23`; no second feature PR was created. The repository remains public with
  `main` as its default branch.
- Gaps: no real-camera calibration, cross-device SEM/MDC study, packaged font-fidelity check, consented recording,
  privacy review, model-weight redistribution approval, adversarial multi-person latency evidence, or external
  medical validity is claimed. These remain independent evidence or follow-up gates.
- Conclusion: code integration, deterministic validation, remote CI, conflict resolution, and stale-review cleanup are
  complete for the integration head. PR `#23` awaits the repository's required human approval.

## 2026-08-13 - Fixed-posture abstention and dual-anchor quality-floor follow-up

- Source: field report that a fixed upright posture could remain visibly `WATCH`, and that the five-second preferred
  stage could fail with insufficient body-keypoint quality.
- Root cause: scientific-mode uncertainty branches used `WATCH` for moving/head-turn/low-quality frames; head-turn
  detection also reused raw interpupillary pixel scale, which changes with camera distance. The pose extractor rejected
  both shoulders below 0.50 before the calibration repeatability layer could collect five samples.
- Changes:
  - Measurement uncertainty now returns `UNKNOWN` and pauses exposure; it cannot be interpreted as posture deviation or
    open an intervention episode.
  - Scientific head-turn gating uses only normalized nose/eye ratio. Raw interpupillary scale remains environment data.
  - Calibration accepts stable shoulder observations down to the explicit 0.40 extraction floor, while hip-dependent
    torso features keep a separate 0.50 landmark floor. Runtime intervention quality remains 0.65.
- Verification:
  - Passed `test_feature_toggles.py`, including distance-scale replay and no-exposure head-turn/movement abstention.
  - Passed `test_posture_science.py`, `test_vision_worker.py`, and `test_debug_ui.py`; the worker test now covers stable
    borderline pose quality completing both anchors.
  - Correction added 2026-08-14: the bundled face-landmark artifact existed; this historical run was blocked by
    MediaPipe's non-ASCII Windows resource-path handling. No live-camera success was claimed for this run.
- Gaps: external camera/device repeatability and user-facing status wording for `UNKNOWN` remain evidence/follow-up work.

## 2026-08-13 - Compatibility identity recovery and three-mode debug contract

- Source: user field report that a steep side recline was reported as occlusion and that a recovered upright target
  remained stuck in candidate state; follow-up request to expose compatibility/standard/professional modes and wire
  the local face model without relabeling the backend.
- Git: code commit `650c0b5`, documentation commit `pending`, branch
  `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Scope:
  - `vision_tracking.py`: high-quality short-gap face continuity repairs a compatibility torso-box jump for the
    already locked target; independent rebinds remain `IDENTITY_UNCERTAIN`; ambiguous, low-quality, timed-out, and
    multiple similar candidates abstain. State text now says landmarks are temporarily unavailable/rematching.
  - `vision_modes.py`, `debug_ui.py`, `i18n.py`: add the three-mode selector and explicit backend availability;
    current production/debug default remains `CompatibilityBackend` and unavailable standard/professional choices
    report their missing posture backend instead of silently falling back.
  - `vision_test.py`, `vision_backend.py`: propagate FaceMesh five-point numeric landmarks (eyes, nose, mouth corners).
  - `face_embedding.py`, `identity_model_adapters.py`, `vision_worker.py`, `tray_app.py`: add transient 112x112 RGB
    face crop, official ArcFace five-point similarity alignment, CVLFace tensor input, asynchronous embedding,
    session-only enrollment and verification, and cleanup on cancellation/contamination/shutdown. No frame, crop,
    image, or vector is persisted by this path.
  - Tests cover the new tracking safety states, three-mode UI, crop privacy, KP-RPE five-point contract, asynchronous
    template enrollment, late-result rejection, and contamination clearing.
- Risk: real CVLFace/Torch weight loading and standard YOLO26n-pose/TensorRT posture backends were not run in this
  environment; installing a face model alone does not make standard posture mode available. No medical, clinical,
  cross-device, or external-validity claim is made.
- Verification:
  - `runtime\\python311\\python.exe test_face_embedding.py`: passed.
  - `runtime\\python311\\python.exe test_identity_model_adapters.py`: passed.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed, including session template and cleanup cases.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed, including side-recline and rebind safety.
  - `runtime\\python311\\python.exe test_debug_ui.py`: passed; emitted only the existing offscreen Qt missing-font
    directory warning.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed.
  - `runtime\\python311\\python.exe test_posture_science.py`: passed.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed after updating the synthetic candidate-present
    contract from `TARGET_OCCLUDED` to `TARGET_REACQUIRING`.
  - `runtime\\python311\\python.exe test_identity_verifier.py`: passed.
  - Target-module `py_compile`: passed.
  - `ruff check ...`: passed for all changed code/tests; `git diff --check`: passed.
- Gaps: real-camera behavior, actual Torch/CVLFace inference on the user's installed environment, standard posture
  backend integration, model license/weight redistribution, packaged UI font fidelity, and remote CI remain separate
  evidence gates.
- Conclusion: deterministic code and safety contract ready for the existing PR branch; real-model and standard-mode
  claims remain pending explicit runtime evidence.

## 2026-08-13 - Extreme seated-posture visibility and low-track-activity risk context

- Source: user report that deliberately extreme head tilt and pelvis-relative upper-body translation could be shown as
  `GOOD`, `ADJUSTING`, or `OBSERVING`; follow-up request to fix Debug UI wording first, then the production analyzer
  path, reuse target tracking for prolonged low activity, add an honest calibrated 2D projection reference, and
  re-audit the scientific and plan claims about isolated variables.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Scope and order:
  - `debug_ui.py`, `i18n.py`: completed the requested diagnostic-first change. The panel always identifies the actual
    active mode/backend and separates any unavailable/failure notice; returning to Compatibility clears stale
    Standard/Professional text. It exposes target motion/activity, projected trunk axis, 2D head-trunk angle, posture
    deviation, combined risk, exposure, and confidence. `WATCH` is now “posture deviation detected”.
  - `posture_science.py`, `vision_test.py`: the production scientific analyzer now retains extreme, quality-valid
    single-channel posture evidence instead of labelling it as normal or inconclusive. Ordinary isolated drift still
    requires support. Trunk lean and head-trunk angle share one shoulder-hip projection channel and cannot corroborate
    themselves; shoulder-pelvis asymmetry remains independent. Extreme changes enter `WATCH` immediately but start at
    zero exposure and cannot skip the 12/30-second dose gates.
  - `vision_tracking.py` was already wired through `TargetManager` into Debug UI and `VisionWorker`. The current
    activity proxy uses normalized body-box centre translation plus relative scale velocity. Reliable uninterrupted
    low track activity starts a combined-risk add-on at 60 seconds, reaches its `0.12` cap at 180 seconds, and cannot
    by itself change posture deviation, leave `GOOD`, create posture exposure, or trigger an alert. Movement,
    uncertainty, low quality, or an observation gap resets it. It is not proof that the user did not move.
  - The calibrated 2D contract uses the shoulder-centre-to-hip-centre image-plane axis and the nose-to-shoulder versus
    shoulder-to-hip projected angle. These are within-user camera projections only, not CVA, Cobb angle, 3D spine
    curvature, or clinical spine inclination.
  - `docs/decisions/ADR-0002-posture-detection-scientific-improvements.md` and
    `docs/plans/EchoPosture_vision_identity_upgrade_plan.md` now record that boundary, the severe standalone-evidence
    exception, shared scoring semantics for all planned modes, and the remaining real-evidence gates.
- Plan audit:
  - Under-recorded: `EP-VISION-012`, `EP-VISION-013`, `EP-ID-001`, `EP-ID-002`, and `EP-ID-006` have deterministic
    implementation/tests and are now checked. GitHub API confirmed PR #22 was merged on 2026-08-11, so its old
    “waiting for approval” status was stale.
  - Ahead of plan but incomplete as full tasks: Debug UI already has the three-mode selector and this round of
    localization, but formal product settings and real Standard/Professional posture backends do not exist; therefore
    `EP-UI-001` and `EP-UI-003` remain unchecked.
  - Not complete: `EP-ID-007` has session cleanup code but lacks formal runtime/privacy evidence. `EP-TRACK-006`, real
    model inference and licenses, consented recordings, real-camera/cross-device evidence, performance budgets, and
    Standard/Professional implementation remain open.
- Scientific source:
  - OSHA, “Computer Workstations eTool: Good Working Positions”:
    https://www.osha.gov/etools/computer-workstations/positions . The page describes the head as generally in line with
    the torso and recommends frequent posture changes even when working posture is good. It supports the product
    direction, but supplies neither EchoPosture's thresholds nor a clinical validation of monocular projection values.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - Passed: `test_debug_ui.py`, `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`,
    `test_vision_tracking.py`, `test_vision_replay.py`, `test_identity_verifier.py`,
    `test_identity_model_adapters.py`, `test_startup_guards.py`, and `test_tray_flyout.py`.
  - The Worker regression preserves target `nose_point`, `shoulder_center`, and `hip_center`, then proves the same
    extreme head-tilt sample reaches `WATCH` through the production Worker/analyzer chain.
  - `runtime\python311\python.exe -m py_compile debug_ui.py i18n.py posture_science.py vision_test.py vision_worker.py
    vision_tracking.py identity_verifier.py`: passed.
  - The bundled Python has no `ruff` module (`No module named ruff`); the existing system `ruff.exe` was used instead
    and the changed-file check passed. Full-repository Ruff and final diff checks also passed.
  - A dedicated low-track-activity lifecycle regression accumulates more than 60 seconds, injects a low-quality frame,
    and proves the next reliable frame restarts at zero seconds with zero add-on. The existing
    `_reset_post_calibration_validation_window()` helper already performed the required reset; the gap was explicit
    contract coverage rather than a missing production reset call.
  - Several sandboxed command launches failed before execution with Windows error 1312 (“the specified logon session
    does not exist”); identical approved retries ran and passed. Debug UI tests emitted the existing bundled Qt
    missing-font-directory warning but exited 0.
- Risk and privacy: no image, video, face crop, identity vector, or historical movement path is added to persistence.
  Existing internal `static_hold_*` field names remain for compatibility, while user-visible text says “low track
  activity” to match the actual sensor capability.
- Gaps: no real-camera posture trial, deliberate-pose human scenario matrix, cross-device repeatability, camera-roll
  study, consented recording, packaged EXE rebuild/self-test, Standard/Professional backend, model-license approval,
  clinical gold-standard comparison, or external validity is claimed. Thresholds remain product reliability and
  interaction parameters, not biological or medical standards.
- Conclusion: deterministic Debug UI and Compatibility production paths implement the requested semantics and retain
  explicit scientific limits; real-world and packaged-runtime evidence remains follow-up work.

## 2026-08-14 - AGPLv3 acceptance and pose-only Standard mode Debug UI

- Source: user request to replace the project license with a strict license, record explicit acceptance, implement
  Standard mode in the Debug UI before the formal EXE path, and defer all face-related work to a separate user plan.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Scope:
  - `LICENSE`, `README.md`, `README_EXE.md`, and `docs/`: switch project-owned code to GNU AGPLv3 only
    (`AGPL-3.0-only`), record acceptance of source/network obligations, and keep third-party model weights and training
    data behind a separate redistribution audit.
  - `standard_pose_backend.py`, `requirements-standard.txt`, `debug_ui.py`, and vision contracts: add an explicitly
    local, CPU-only Ultralytics YOLO26n-pose Debug UI backend with COCO 17-point per-person observations, pose-only
    calibration, lazy optional-backend import, no automatic model download, and Compatibility fallback on failure.
  - `vision_tracking.py`: replace unbounded recursive association with bounded bit-mask dynamic programming; crowded
    frames over budget abstain as `TARGET_AMBIGUOUS/association_budget_exceeded` without mutating existing tracks.
  - Face crops, FaceMesh, identity models, templates, and embeddings are not loaded or processed by Standard mode.
    The production tray/EXE path remains Compatibility-only in the requested diagnostic-first sequence.
- Risk:
  - The local pose weight is not ignored by Git and is not approved for redistribution. It remained untracked and was
    not staged. Standard dependencies were installed only into ignored `runtime/python311` for local verification.
  - Real camera/person accuracy, multiple-person replay, 416/480 input comparisons, cross-device behavior, packaged
    EXE integration, and weight/training-data redistribution remain open evidence gates.
  - A first Ultralytics import created a 607-byte default settings file outside the project because of its Unicode-path
    fallback. The exact generated file and empty directory were immediately removed; no image or user data was saved.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `uv pip check --python runtime\python311\python.exe`: passed; Python 3.11.9 environment is consistent with
    `ultralytics==8.4.120`, `torch==2.13.0+cpu`, and `torchvision==0.28.0+cpu`; CUDA is unavailable/unused.
  - Real local weight: 7,878,574 bytes; SHA256
    `EB3BB8268828AEAF515CEC23A4BFAFD793944A86FE9AF94BA7823609C14522A9`; model reports task `pose` and keypoint shape
    `[17, 3]`. Twelve synthetic 640x480 blank frames, excluding two warmups, measured P50 `22.94 ms` and P95
    `31.25 ms`. This verifies API/runtime execution only, not human-scene accuracy.
  - Passed `test_standard_pose_backend.py`, `test_debug_ui.py`, `test_vision_tracking.py`, `test_posture_science.py`,
    `test_vision_worker.py`, `test_feature_toggles.py`, `test_vision_replay.py`, `test_startup_guards.py`, and
    `test_tray_flyout.py`. The 10x10 association test measured P50 `5.87 ms`, P95 `6.59 ms` in the final run.
  - Target-module `py_compile`, changed-file `ruff check`, and `git diff --check`: passed. Debug UI tests emitted the
    existing bundled Qt missing-font-directory warning; exit code remained 0.
- Artifacts: no package, release, model, image, recording, or runtime dependency was staged. Local model and installed
  optional dependencies remain development-only inputs.
- Gaps: live camera/UI operation, real seated-person and deliberate-extreme-posture trials, consented multi-person
  recordings, packaged self-test, remote CI, formal tray/EXE mode selection, ONNX comparison, and model redistribution
  approval were not performed and are not claimed complete.
- Conclusion: AGPLv3 acceptance and the pose-only Standard mode Debug UI implementation are locally verified and ready
  for source review; production adoption and real-world evidence require follow-up.

## 2026-08-14 - Compatibility face ownership safety and identity-loader repair

- Source: the user clarified that the next work from
  `docs/plans/EchoPosture_identity_tracking_detail_plan.md` was specifically the face-recognition path and
  face-to-body ownership validation, with Debug UI diagnostics changed before the production Compatibility path.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Root causes:
  - The old Compatibility adapter accepted a face inside a body box expanded upward by `1.25 * body_height`. For a
    seated body this envelope could extend hundreds of pixels above the frame, so a standing intruder's face could be
    combined with the seated user's BlazePose landmarks.
  - `face_count` came from FaceMesh and was capped at two; the selected face box was reconstructed from five points;
    `face_quality` was effectively a Boolean `1.0`; and the short-gap continuity rescue could clear an ownership
    ambiguity without checking the locked user's face/body scale or a sufficiently strict face-centre displacement.
  - MediaPipe's face graph existed in the bundled runtime. Its Windows C++ resource loader failed on the non-ASCII
    repository path, which earlier development-log entries incorrectly diagnosed as a missing artifact.
  - CVLFace KP-RPE changes the process cwd if its optional extension import fails, then attempts
    `setup.py install --user`. This broke the wrapper's relative `pretrained_model/model.pt` lookup and introduced an
    unacceptable startup-time environment mutation.
  - Follow-up audit found that a target observation newly marked `association_ambiguous` could still reach the formal
    Worker embedding path. During enrollment that could mix a face with unproven body ownership into the session
    template even though TargetManager had already abstained from posture ownership.
- Changes, in the requested order:
  - Debug UI now reads the active backend's diagnostic notice after startup and every mode transition. If BlazeFace
    initialization fails, it explicitly reports the FaceMesh fallback and the real exception; returning to
    Compatibility refreshes the current notice instead of retaining stale Standard/Professional text.
  - Added an ASCII MediaPipe resource bridge under
    `%LOCALAPPDATA%\\EchoPosture\\mediapipe-resources\\<fingerprint>` and corrected the historical log entries without
    retroactively claiming that their live-camera checks succeeded.
  - Compatibility mode now runs BlazeFace full-range detection for real face boxes, detector scores, six anchors, and
    uncapped face counts. It selects a face only when shoulder-relative vertical/horizontal position, eye/shoulder
    scale, and cross-model nose or ear anchors agree; only that selected crop is sent to FaceMesh for five-point iris
    geometry. Detector confidence, face size, five-point geometry, brightness, and contrast form a continuous
    `[0, 1]` quality value.
  - TargetManager stores the locked user's face/body scale, rejects drift outside `+/-35%`, and requires both that
    scale consistency and a stricter `0.45` face-centre displacement limit before short-gap continuity may rescue an
    ownership ambiguity. BlazeFace scene counts propagate separately from the single BlazePose track, so additional
    faces remain visible as `MULTI_PRESENT` without silently replacing the target.
  - VisionWorker now refuses both backend-supplied embeddings and asynchronous crop requests whenever
    `association_ambiguous=True`; active enrollment samples are cleared immediately. This closes the ownership-to-ID
    gap and prevents a geometrically unowned face from contaminating the session template.
  - KP-RPE is preloaded while cwd restoration is bounded to the model root. The adapter blocks the upstream user-site
    install attempt and retains the pure-Python fallback instead of compiling or installing code during app startup.
  - ADR-0001 records the honest Compatibility limit: one BlazePose skeleton can reject a mismatched observation but
    cannot continuously track every person when the detector changes subjects. CI now compiles, lints, and runs the
    new face-ownership, Compatibility detection, identity-adapter, tracking, and Worker guards.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - Passed `test_face_body_association.py`, `test_compatibility_face_detection.py`,
    `test_identity_model_adapters.py`, `test_vision_tracking.py`, and `test_vision_worker.py`. Coverage includes a high
    standing intruder, a same-height lateral face, an intruder-only detection, uncapped three-face counting, selected
    crop-only FaceMesh, normal single-user ownership, locked-scale drift, strict continuity rescue, continuous quality
    rejection, and zero identity requests for ambiguous ownership.
  - Passed `test_debug_ui.py`, `test_feature_toggles.py`, `test_posture_science.py`,
    `test_standard_pose_backend.py`, `test_startup_guards.py`, `test_tray_flyout.py`, and `test_vision_replay.py`.
  - From the Chinese repository path, bundled-runtime initialization reported BlazeFace, FaceMesh, and BlazePose all
    available with no fallback reason. MediaPipe emitted only its normal TFLite/feedback-manager diagnostics.
  - The real local ViT KP-RPE model loaded, returned a finite 512-dimensional embedding, and no longer launched an
    extension build or user-site install. The measured run took 6.793 seconds to load and 0.162 seconds to embed; the
    optional CUDA/C++ RPE accelerator remained unavailable and the pure-Python path was used.
  - Changed-file Ruff, target-module `py_compile`, and `git diff --check` passed before this final audit entry; they are
    rerun after the entry as the delivery gate.
- Privacy and evidence boundary: no frame, face crop, embedding, template, or movement history is persisted by these
  changes. No real-person camera recording, consented multi-person trial, cross-device validation, medical/clinical
  claim, packaged EXE rebuild, or model-weight redistribution approval is claimed.
- Remaining identity deployment gap: the production packaged runtime still lacks Torch/Transformers and ONNX Runtime
  identity dependencies. EP-ID-010 (Torch package versus ONNX versus a separate process), real-model A/B evidence,
  threshold validation, and the plan's graded identity fallback remain open; this change repairs the loader and the
  ownership safety boundary but does not claim that production face recognition is deployed.
- Conclusion: P0 Compatibility ownership safety and the EP-ID-009 KP-RPE loader repair are implemented with
  deterministic and real local model evidence. The untracked user-authored detail plan remains a read-only input and
  is not part of the staged delivery set.

## 2026-08-14 - Standard mode person boxes and honest reacquisition status

- Source: user report that Standard mode did not draw the person box emitted by the pose model, incorrectly displayed
  a Compatibility-mode reacquisition message, and did not recover after the user's face became unrecognisable.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Root causes and scope:
  - `StandardPoseBackend` already populated each `PersonObservation.bbox_xyxy`, but `DebugWindow._show_frame()` only
    drew selected posture landmarks and never consumed the model's person boxes.
  - The shared `TARGET_REACQUIRING` translation was hard-coded as a Compatibility-mode message even when the active
    backend was Standard.
  - Standard mode is deliberately pose-only: it sets `supports_face_bbox=False` and emits no face box, landmarks,
    quality, or embedding. Debug UI constructs a `TargetManager` but no `IdentityVerifier` or
    `FaceEmbeddingPipeline`. Once geometry association breaks and a new body track appears, the required identity
    confirmation therefore cannot complete. This is an implementation gap, not evidence that face recognition ran
    and failed.
  - `debug_ui.py` now reads observations once per frame, passes the same immutable set to tracking and drawing, and
    draws visible Standard-mode person boxes. The locked target uses a green `TARGET #id` frame; other people use
    yellow `PERSON #id` frames. Invalid, non-finite, or out-of-frame boxes are rejected or clipped.
  - `i18n.py` now describes `TARGET_REACQUIRING` generically as rematching the body track. Standard mode explicitly
    says face identity confirmation is not connected when that confirmation is required.
- Risk: the fix does not loosen target ownership or silently promote a new body track. Full Standard-mode face and
  identity integration remains deferred to the dedicated identity plan; this change only makes the current limitation
  visible and corrects the two requested UI defects.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe test_debug_ui.py`: passed, including assertions that the Standard observation box
    reaches `cv2.rectangle`, uses the expected coordinates, and no reacquisition text claims Compatibility mode.
  - `runtime\python311\python.exe test_standard_pose_backend.py`: passed; confirms the pose-only observation contract.
  - `runtime\python311\python.exe test_vision_tracking.py`: passed, including no-silent-promotion and identity-required
    reacquisition guards.
  - `runtime\python311\python.exe test_vision_worker.py`: passed, including identity enrollment and ambiguous-ownership
    rejection tests.
  - `ruff check .`, target-file `py_compile`, and `git diff --check`: passed. `git diff --check` emitted only the
    repository's existing LF-to-CRLF conversion warnings.
  - Real camera/model probe: the bundled runtime opened camera 0 and completed one single-frame plus one ten-frame
    Standard YOLO run without saving images. All sampled frames returned zero person observations, so the probe proves
    capture/inference execution but cannot prove a visible real-person box. The deterministic UI test is the current
    drawing evidence.
- Artifacts and privacy: no image, recording, face crop, embedding, model, package, or runtime dependency was staged or
  saved by this work.
- Gaps: a seated person must be present and detected for live visual box confirmation. Standard-mode head-region face
  detection, FaceMesh ownership geometry, session identity enrollment/verification, reacquisition recovery, packaged
  EXE integration, and remote CI remain follow-up gates.
- Conclusion: the two requested Debug UI defects are fixed and locally regression-tested. The third report is
  confirmed as a missing Standard-mode identity integration; it is investigated and disclosed, not implemented here.

## 2026-08-14 - CVLFace-only identity decisions and cross-mode observation boundary

- Source: user request to remove shoulder-width/face-scale identity decisions, deploy the already configured face
  model through the real Debug UI and tray paths, make leave/re-enter recovery usable, and re-verify that all three
  planned modes share one normalized model-output contract.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Scope and root causes:
  - Identity was still coupled to geometry-era assumptions and Standard mode had no shared face enrichment. A target
    that returned as a new body track therefore could remain in identity uncertainty without a model-capable path.
  - `FaceEnhancedBackend` now decorates every registered mode and synchronizes `read_frame_sample()`,
    `PersonObservation`, face boxes, five-point landmarks, scene counts, and posture samples before TargetManager sees
    them. Compatibility and Standard use this boundary now; the Professional reservation is covered by the same
    factory contract and cannot introduce a different observation shape when its backend is registered.
  - Shoulder width, pupil distance, face/body scale, and posture ratios no longer make identity conclusions. Geometry
    remains limited to face/body ownership and track association. Only a CVLFace verifier result may confirm or reject
    an identity candidate; candidate track IDs are preserved across asynchronous embedding and verification results.
  - Long absence may submit one clear, face-capable candidate for verification, but ambiguous, low-quality, stale, or
    wrong-track results cannot rebind the calibrated target. Embedding failures remain retryable instead of silently
    promoting a track. UI reasons now say face identity mismatch and the dead face/shoulder profile-mismatch text was
    removed.
  - `identity_model_process.py` and `identity_model_worker.py` keep the pinned ViT KP-RPE environment isolated from the
    main pose runtime. Discovery prefers `ECHOPOSTURE_P5_PYTHON`, packaged `runtime/p5/python.exe`, then local
    `.venv-p5`; face crops and embeddings are sent only through a local in-memory protocol and are not persisted.
  - Debug UI was changed before the production path. It now draws body and face boxes and uses the shared identity
    pipeline in Compatibility and Standard. The tray Compatibility backend and `VisionWorker` use the same enhancer,
    TargetManager, enrollment, and verification contracts.
- Risk:
  - The source path is operational with local `.venv-p5`, but a packaged build must include a compatible
    `runtime/p5/python.exe` environment or configure `ECHOPOSTURE_P5_PYTHON`. No packaged EXE portability is claimed.
  - `PROFILE_MISMATCH` remains the stable external status identifier for compatibility, but its only producer is now
    TargetManager after a face-verifier rejection; its diagnostic reason explicitly identifies face identity.
  - No model weights, runtime environment, face images, embeddings, recordings, or user-authored plan files are part
    of this commit.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - Passed: `test_face_body_association.py`, `test_face_embedding.py`, `test_identity_model_adapters.py`,
    `test_identity_verifier.py`, `test_vision_tracking.py`, `test_vision_worker.py`,
    `test_standard_pose_backend.py`, `test_compatibility_face_detection.py`, `test_debug_ui.py`,
    `test_feature_toggles.py`, `test_posture_science.py`, `test_startup_guards.py`, `test_vision_replay.py`, and
    `test_tray_flyout.py`.
  - Regression coverage proves that large face-scale and pupil-distance changes do not decide identity, long absence
    still produces a verifiable candidate, an identity mismatch cannot rebind it, stale candidate results are ignored,
    and all three reserved mode factories emit the same enriched `PersonObservation` boundary.
  - Real product-adapter smoke test: `CvlFaceProcessAdapter` loaded from the configured isolated runtime, returned a
    finite 512-dimensional embedding (`norm=13.491850733858788`), and closed cleanly (`loaded=False`).
  - `ruff check .`, targeted `py_compile`, and `git diff --check`: passed. Debug UI tests emitted the existing bundled
    Qt missing-font-directory warning but exited 0.
  - A broad loop over every root `test_*.py` was not executed because the safety reviewer rejected running unrelated
    AI-maintainer/manual-flow scripts without prior side-effect inspection. Those scripts are outside this visual
    identity change; all directly relevant tests were run explicitly.
- Artifacts and privacy: no package or release was built. Face crops are transient local process inputs; no frame,
  crop, embedding, identity template, or trajectory is written to disk by this change.
- Gaps: no live seated-person camera exercise, deliberate leave/re-enter visual trial, consented multi-person trial,
  cross-device threshold validation, packaged EXE rebuild/self-test, or remote CI result is claimed yet. The live UI
  camera scenario remains a manual verification gate after source delivery.
- Conclusion: source runtime identity is now CVLFace-only, recovery and stale-result guards are deterministic, and the
  shared observation interface is verified for Compatibility, Standard, and the Professional reservation. The change
  is ready for commit, push, PR review, and remote CI; packaged identity-runtime assembly remains follow-up work.

## 2026-08-14 - Candidate-scoped face identity verification sessions

- Source: user requirement to fix discovered identity defects before further feature work and make CVLFace a reliable
  primary selector for which person's posture observations may enter processing.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Root cause and preserved evidence:
  - `IdentityVerifier.request()` throttled by `(trigger, track_id)`, but `verify()` accumulated every candidate into
    one global score deque, valid-frame count, debounce candidate, and stable state.
  - After the enrolled user had produced a confirmed heartbeat history, the first frame of a new intruder candidate
    returned `IDENTITY_CONFIRMED`, `score=1.0`, `valid_frames=9`, reason `identity_score_aggregated`. The score was the
    old user's median rather than evidence from the new candidate.
  - Worker and Debug UI carried candidate track IDs with futures, but no verification-session token. A late embedding
    or verifier future could therefore finish after reacquisition or candidate replacement without proving that it
    still belonged to the active evidence window.
- Changes:
  - `IdentityVerifier` now owns independent score, frame-count, debounce, and stable-state data keyed by candidate
    track and a monotonically increasing session ID. Starting a session clears the abandoned active window and its
    trigger gate while retaining the enrolled user template.
  - `verify()`, `request()`, and `submit()` accept the normalized `track_id` and `session_id` context. Trigger
    throttling also includes the session ID, so reacquiring the same track starts immediately instead of inheriting a
    prior event interval.
  - VisionWorker and Debug UI start a fresh session when the candidate track changes or the same track newly enters
    `IDENTITY_UNCERTAIN`. The same candidate continues accumulating across frames, while normal heartbeats stay in the
    current session.
  - Embedding and verification future contexts now include the active session ID. Candidate/session changes cancel
    what can be cancelled, discard all old contexts, and refuse to apply a completed result unless both track and
    session still match. Calibration reset also clears both asynchronous stages and session state.
  - Regression tests cover owner heartbeats followed by an intruder, same-track reacquisition, late old-session
    evidence, same-candidate accumulation, event-gate reset, and Worker session rotation across candidate and state
    transitions. The Debug UI verifier test double implements the same session interface.
- Risk and privacy:
  - The change is fail-closed: every new or reacquired candidate must independently collect the configured minimum
    number of valid CVLFace samples before confirmation. It may add the intended reacquisition delay but removes the
    unsafe first-frame confirmation path.
  - Only numeric transient scores and embeddings remain in memory. No frame, face crop, embedding, template, score,
    or trajectory is written to disk or added to logs.
- Verification from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe test_identity_verifier.py`: passed; the new intruder's first result is uncertain
    with one valid frame, and old-session evidence does not change the new session's frame count.
  - `runtime\python311\python.exe test_vision_worker.py`: passed, including candidate change, same-track
    reacquisition, continuous same-candidate accumulation, ambiguous ownership, and cancelled enrollment guards.
  - `runtime\python311\python.exe test_debug_ui.py`: passed. The bundled Qt missing-font-directory warning remains,
    but the process exited 0 and all Debug UI assertions passed.
  - `test_identity_model_adapters.py`, `test_face_embedding.py`, `test_face_body_association.py`,
    `test_vision_tracking.py`, and `test_compatibility_face_detection.py`: passed.
  - `ruff check identity_verifier.py vision_worker.py debug_ui.py test_identity_verifier.py test_vision_worker.py
    test_debug_ui.py`: passed.
  - `runtime\python311\python.exe -m py_compile identity_verifier.py vision_worker.py debug_ui.py
    test_identity_verifier.py test_vision_worker.py test_debug_ui.py`: passed.
- Artifacts: no package, release, model, runtime, screenshot, recording, or user-authored plan file is included.
- Gaps: no live seated-person leave/re-enter trial, consented multi-person swap trial, cross-device threshold study,
  packaged `runtime/p5` build, packaged EXE self-test, or remote CI result is claimed in this entry. Those remain
  production evidence gates even though the deterministic state-contamination defect is fixed.
- Conclusion: the known cross-candidate confirmation defect is fixed at the verifier and both asynchronous runtime
  entry points. The source change is ready for final static checks, commit, push, and PR CI.

## 2026-08-14 - Face ownership debounce and measured abstention guards

- Source: `docs/plans/EchoPosture_abstention_oversensitivity_plan.md`, based on field reports of occasional false
  `TARGET_AMBIGUOUS` frames and frequent shoulder-scale `OBSERVING` abstentions.
- Git: commit `c6144d1`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Face/body ownership changes:
  - Association results now distinguish `clear`, `unconfirmed`, and `ambiguous`. A single face/body pair whose
    cross-model ear or nose anchors disagree is treated as an unconfirmed measurement, not immediate multi-person
    ambiguity. Its face box, landmarks, quality, and face-derived posture values are removed before tracking or
    identity processing; body posture evidence remains available.
  - BlazeFace ear anchors are compared with BlazePose ear anchors when both are available, avoiding the prior
    eye-centre-versus-ear-centre mismatch. Position mismatches, competing faces/bodies, and score ties remain
    fail-closed.
  - TargetManager requires 0.4 seconds of continuous face/body ambiguity before surfacing `TARGET_AMBIGUOUS`.
    Transient ambiguity keeps the existing body track but cannot submit the stripped face for identity work.
- Shoulder-scale and abstention changes:
  - The fixed 5% shoulder-width floor was replaced by the calibrated preferred/relaxed MDC and standard-deviation
    repeatability band, with a 2 px absolute measurement floor. Uniform whole-person distance scaling remains
    measurable, while isolated unstable width changes still abstain.
  - Temporary `OBSERVING` decisions retain the last reliable posture-deviation display without adding exposure.
    A gap longer than `maximum_observation_gap_seconds` clears that retained display, preventing stale values.
- Deliberate exclusions: no unmeasured torso-yaw compensation, adaptive association threshold, or camera-roll
  increase was introduced. `MIN_SELECTION_MARGIN=0.12` and the 3 degree roll guards remain unchanged pending real
  camera data; the plan's suggested 6-8 degree roll range is not treated as validated.
- Verification from `C:\Temp\ep_repo`, using the real bundled interpreter at
  `C:\Users\aaabb\Documents\ICC驼背项目\runtime\python311\python.exe`:
  - Passed all 12 required suites: `test_face_body_association.py`, `test_compatibility_face_detection.py`,
    `test_vision_tracking.py`, `test_vision_worker.py`, `test_identity_verifier.py`,
    `test_identity_model_adapters.py`, `test_standard_pose_backend.py`, `test_posture_science.py`,
    `test_feature_toggles.py`, `test_debug_ui.py`, `test_vision_replay.py`, and `test_startup_guards.py`.
  - `ruff check .`, targeted `py_compile`, and `git diff --check`: passed. `test_startup_guards.py` emitted the
    existing Qt missing-font-directory warning but exited 0; `git diff --check` emitted only LF-to-CRLF warnings.
  - The `C:\Temp\ep_rt\python.exe` junction does not resolve the bundled `_pth` imports, so tests used the real
    interpreter path while keeping the repository working directory ASCII-only.
- Artifacts and privacy: no plan document, frame, face crop, embedding, model, package, runtime, or generated asset
  is included. Existing unrelated tracked and untracked work remains outside the delivery set.
- Gaps: no live seated-person camera session, multi-person visual trial, packaged EXE rebuild/self-test, or
  cross-device threshold calibration was performed. Remote CI will be checked after push and reported separately.
- Conclusion: both documented defects are fixed in source with deterministic regression coverage, while unvalidated
  P2 threshold changes remain deferred instead of being guessed.

## 2026-08-14 - Shoulder-scale abstention decision priority follow-up

- Source: user field report that leaning toward the display or changing projected shoulder width still repeatedly
  froze posture processing in `OBSERVING`, despite the earlier measured-abstention improvement.
- Git: feature commit `efc7161`, branch `codex/pr2-phase1-calibration-safety`, PR `#23`, tag `none`.
- Root cause and reproduced evidence:
  - `shared_scale_measurement_unstable()` treated every positive forward deviation without raw numerator support as a
    global frame veto. It did not consider whether that deviation could reach the first intervention threshold, or
    whether the same frame already contained independent intervention-level lateral posture evidence.
  - A synthetic calibrated shoulder-width change from 200 px to 208 px produced forward deviation `0.045`, far below
    `watch_enter=0.50`, but the guard returned true and the analyzer emitted
    `shared_shoulder_scale_measurement_abstained` instead of continuing a normal measurement.
  - A 220 px shoulder width combined with strong projected head lean produced overall deviation `1.0` and lateral
    deviation `1.5`, but the same guard still returned true and suppressed the expected intervention flow.
- Changes:
  - Sub-WATCH forward evidence now bypasses the shared-scale abstention guard because it cannot open intervention or
    accumulate exposure. No new numeric threshold was introduced; the existing audited `watch_enter` policy is used.
  - Lateral evidence that already reaches WATCH takes priority over the shoulder-scale guard, allowing genuine
    projected trunk/head posture evidence to continue through `ADJUSTING`, `WATCH`, and later exposure states.
  - High forward scores caused only by an unsupported shoulder-width denominator still abstain, preserving the
    original landmark-instability protection.
  - Regression expectations now distinguish low-risk measurable drift from actionable denominator drift: low-risk
    values may remain visible below WATCH but must never accumulate exposure.
- Risk:
  - This changes only guard priority after the posture score is already available. Calibration bands, raw-numerator
    repeatability, intervention thresholds, exposure timing, identity, target ownership, and camera-roll policy are
    unchanged.
  - Independent lateral evidence can now continue when shoulder width is also suspect. Existing roll, quality,
    target, and exposure guards remain earlier or downstream in the analyzer pipeline.
- Verification from `C:\Temp\ep_repo`, using
  `C:\Users\aaabb\Documents\ICC驼背项目\runtime\python311\python.exe`:
  - Before the implementation change, the new regressions failed with `OBSERVING` and
    `shared_shoulder_scale_measurement_abstained` for the 208 px case, proving the reported behavior.
  - Passed all 12 required suites: `test_face_body_association.py`, `test_compatibility_face_detection.py`,
    `test_vision_tracking.py`, `test_vision_worker.py`, `test_identity_verifier.py`,
    `test_identity_model_adapters.py`, `test_standard_pose_backend.py`, `test_posture_science.py`,
    `test_feature_toggles.py`, `test_debug_ui.py`, `test_vision_replay.py`, and `test_startup_guards.py`.
  - The new runtime regression proves 208 px remains `GOOD`; the projected-lean regression proceeds from
    `ADJUSTING` to `WATCH`; long synthetic shoulder-only drift never reaches WATCH/BAD or accumulates exposure; and
    strong numerator-supported posture change still reaches BAD.
  - `ruff check .`, targeted `py_compile`, and `git diff --check`: passed. `git diff --check` emitted only expected
    LF-to-CRLF conversion warnings. `test_startup_guards.py` emitted the existing Qt font-directory warning and exited
    with code 0.
- Artifacts and privacy: no package, release, camera frame, recording, model, runtime, generated asset, or plan file is
  included. Existing unrelated tracked and untracked files remain outside the delivery set.
- Gaps: no live seated-person camera session, cross-device threshold study, packaged EXE rebuild/self-test, or release
  operation was performed. Remote CI and PR mergeability are checked after push and reported separately.
- Conclusion: the deterministic decision-priority defect is fixed without guessing new sensitivity constants. The
  source change is ready for audit commit, push, and remote CI verification; the reported physical scenario remains a
  manual live-camera confirmation gate.

## 2026-08-15 - Production mode onboarding and console mode wheel

- Source: user request and `docs/plans/EchoPosture_production_mode_onboarding_plan.md`; add the 2.0 production EXE
  startup mode flow and a compact cyclic selector in the central console.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`; starting HEAD `2463387`.
- Backup: `_backups/EchoPosture-source-backup-20260815-production-mode-onboarding/` contains
  `source-head-2463387.zip` and `BACKUP_MANIFEST.txt`. The backup covers the committed source tree before this change
  and intentionally excludes unrelated untracked workspace files.
- Scope and user-visible behavior:
  - `onboarding_toast.py`, `mode_select_card.py`, and `mode_themes.py` implement the fixed-geometry two-stage startup
    toast, internally clipped growth, staggered cards, honest availability reasons, 15-second default selection,
    persisted-mode notice, and real-stage loading/fallback/terminal-failure states without `QGraphicsEffect`.
  - `tray_app.py`, `standard_pose_backend.py`, and `vision_modes.py` connect the selected mode to the production
    `VisionWorker`, keep the face-enhanced wrapper for every supported backend, initialize heavy work off the GUI
    thread, expose real import/model/camera progress, and visibly fall back to Compatibility when Standard fails.
    If Compatibility also fails, the toast now reports terminal startup failure instead of claiming a working fallback.
  - `user_settings.py` atomically persists only `version`, `vision_mode`, and `ask_on_startup` under LocalAppData.
    Frames, face crops, templates, embeddings, measurements, and identity state are not accepted or stored.
  - `mode_wheel_selector.py` and `posture_console.py` add the cyclic lower-edge wheel. Its circular body continues
    below the viewport while all three themed choices remain visible on the upper arc; navigation may pass an
    unavailable mode but only requests an available one. The complete status readout moves above the wheel.
  - `i18n.py` contains matching Chinese and English startup, selector, loading, failure, and settings strings.
  - `test_production_mode_onboarding.py` covers lightweight availability probes, privacy-minimal settings, theme
    boundaries, fixed toast geometry, loading/failure states, cyclic wheel behavior, and full console layout at
    1366x768- and 1920x1080-equivalent window sizes.
- Risk and safeguards:
  - Camera/model startup runs in a daemon initialization thread with generation and stopping guards; stale workers
    are stopped before they can become active. Identity preparation remains asynchronous and is attached to whichever
    worker is current when its signal arrives.
  - Mode changes reset target state and require calibration before normal monitoring resumes. Standard mode never
    downloads a model implicitly, and Professional Beta remains unavailable because no production backend exists.
  - `ui/index.html`, runtime, models, packages, backups, user-authored plans/prototypes, screenshots, and unrelated
    untracked files are outside the intended delivery set.
- Verification from `C:\Users\aaabb\Documents\ICC`:
  - `runtime\python311\python.exe -m py_compile i18n.py onboarding_toast.py posture_console.py
    standard_pose_backend.py tray_app.py vision_modes.py mode_select_card.py mode_themes.py mode_wheel_selector.py
    user_settings.py test_production_mode_onboarding.py`: passed.
  - `ruff check` over the same changed source and test files: passed (`All checks passed!`).
  - With `QT_QPA_FONTDIR=C:\Windows\Fonts`,
    `runtime\python311\python.exe test_production_mode_onboarding.py`: passed. The offscreen Qt plugin emitted only
    its expected unsupported raise/opacity/size-hint warnings.
  - `test_startup_guards.py`, `test_standard_pose_backend.py`, `test_tray_flyout.py`, `test_vision_worker.py`, and
    `test_feature_toggles.py`: passed. `git diff --check`: passed with only LF-to-CRLF notices.
  - Playwright MCP was verified as the configured Microsoft Edge extension session (`Edg/151.0.0.0`) and exercised
    `http://127.0.0.1:8765/ui/onboarding_modes.html` at 1366x768 through boot, mode reveal, unavailable Professional
    hover, Compatibility selection, Standard loading, and handoff. Three temporary 1366x768 screenshots were
    captured and reviewed, then removed with the task-owned localhost server. The three console errors were one
    missing prototype favicon and two extension-injected resource restrictions; no page-script exception was observed.
  - Font-valid offscreen Qt screenshots were manually reviewed at
    `.codex/visual-checks/production-mode-onboarding-fonts/`: onboarding boot/modes/loading and console 1366x768 /
    1920x1080. Text fits, all three wheel items are visible, and the wheel, readout, and side controls do not overlap.
- Artifacts: no package, release, runtime, model, screenshot, recording, plan, HTML prototype, or backup is included.
- Gaps: no live camera session, actual Standard cold model load/warmup, identity-process race under forced shutdown,
  packaged EXE rebuild/self-test, keyboard-only desktop trial, multi-monitor placement trial, or real-user motion study
  was performed. The exact animation timings and mode-theme recognizability remain manual product validation gates.
- Conclusion: deterministic source, UI, and regression evidence is ready for a reviewed commit. Hardware, packaged
  EXE, and remote CI evidence remain explicitly unclaimed.

## 2026-08-17 - GA-2.0.0 semi-portable release asset

- Source: user request to publish a GA-2.0.0 semi-portable distribution that includes everything required to run
  except the separately downloaded model weights.
- Git: commit `pending`, branch `main`, release tag `ga-2.0.0`; package build commit
  `957f42ace82856d2c686da4d271c9443cad29aaf` (packaging/version-label corrections on top of tagged source
  `371fb71b2bc20834608f1edd59d1de4fd88b3126`).
- Backup: `_backups/EchoPosture-source-backup-20260817-semi-portable-release/source-head-957f42a.zip`, with
  `BACKUP_MANIFEST.txt`, was created before the release-document changes. It is local-only and not staged.
- Scope: prepare `EchoPosture-GA-2.0.0-portable-win-x64.zip` for publication under the existing `ga-2.0.0` release without replacing
  `EchoPosture-GA-2.0.0-source.zip`. The semi-portable asset includes the embedded CPython 3.11 runtime, three
  executables, application modules, notices, and the four `tools/fetch_pose_models/` scripts. It excludes
  downloadable Ultralytics YOLO pose weights (`*.pt`) and CVLFace P5 identity weights (`*.safetensors`); MediaPipe's
  dependency-owned `.tflite` runtime resources remain included so Compatibility mode can run immediately.
- Verification:
  - `EchoPostureSelfTest.exe` from the staged package: stages 1 (GPU blur host), 2 (offscreen Debug UI), and 3
    (one-frame vision) exited `0`. Stage 4 opened the tray/runtime chain but exited `1` because the live camera sample
    lacked `trunk_lean_deg`; it reported `startup_calibrated=False` and `baseline=False`. This is recorded as a
    hardware/calibration gap, not a pass.
  - The staged runtime reported `Python 3.11.9` and contained PyQt5, OpenCV, MediaPipe, Ultralytics,
    `torch-2.13.0+cu130`, and `torchvision-0.28.0+cu130`.
  - File inventory found zero `*.pt`, `*.safetensors`, or `*.onnx` files. The only model-format files were 15
    MediaPipe `.tflite` resources in its installed dependency runtime; release and package wording was corrected to
    distinguish these Compatibility-mode resources from excluded, user-downloadable weights.
  - The ZIP documentation entries were rebuilt and checked to contain exactly one copy each at the intended package
    paths; no accidental `dist\\...` ZIP entries remain.
- Artifact: `dist/EchoPosture-GA-2.0.0-portable-win-x64.zip`, 2,313,314,546 bytes, SHA-256
  `353a7880a07ec7885e1f1fe0d902e75f8c67a67754129586ea827c5579c262c1`.
- Gaps: a complete tray self-test requires a live camera scene exposing the torso sufficiently for calibration; that
  condition was not present in this run. On 2026-08-17 GitHub rejected the upload with `HTTP 422: size must be less
  than 2147483648`; the 2,313,314,546-byte archive exceeds that limit by 165,830,898 bytes. No release asset or
  GitHub digest was written. A split-asset or smaller-runtime distribution decision is required before publication.
- Conclusion: the archive structure and runtime dependencies are locally ready, but remote publication is blocked by
  GitHub's single-asset size limit and the recorded hardware-dependent calibration gap.
