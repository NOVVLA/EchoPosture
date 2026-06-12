# Development Log

本日志从 Git 历史和当前仓库文件还原，作为后续过程审计的起点。2026-06-09 以前的条目不是完整实时开发记录；它们只记录 Git 能证明的事实和已经识别出的证据缺口。后续提交必须按 [PROCESS_AUDIT.md](PROCESS_AUDIT.md) 补充验证、风险和产物证据。

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
- Scope: added [PROCESS_AUDIT.md](PROCESS_AUDIT.md), added this [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md), and linked both from [README.md](README.md) and [ROE.md](ROE.md).
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
  - Result: passed; repository reported `visibility=PRIVATE` and `isPrivate=true`.
  - Command: `gh release create team-alpha-20260609-154821 dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64.zip --repo NOVVLA/ICC --target db37ea6a88a7958de54f67f3d06c269c6acb6d23 --title "EchoPosture TEAM_ALPHA 20260609-154821" --prerelease`
  - Result: passed; release URL `https://github.com/NOVVLA/ICC/releases/tag/team-alpha-20260609-154821`.
  - Command: `gh release view team-alpha-20260609-154821 --repo NOVVLA/ICC --json tagName,name,isPrerelease,url,targetCommitish,createdAt,publishedAt,assets`
  - Result: passed; tag `team-alpha-20260609-154821`, target commit `db37ea6a88a7958de54f67f3d06c269c6acb6d23`, `isPrerelease=true`, asset state `uploaded`, size `305875036`, digest `sha256:7a0018e09a0c5a7a4f3b0ce350a27cb43c94cd01b0c19f42da2078c46f891fd3`.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: passed after release; repository still reported `visibility=PRIVATE` and `isPrivate=true`.
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
- Conclusion: these commits improve process rules but need this log and [PROCESS_AUDIT.md](PROCESS_AUDIT.md) to make future records auditable.

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
