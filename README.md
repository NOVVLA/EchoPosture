# EchoPosture

> **许可证：GNU AGPLv3（`AGPL-3.0-only`）。** 项目已接受该严格许可证及其相应源码义务；第三方模型权重和训练数据仍需独立审计。完整决策见 [ADR-0003](docs/decisions/ADR-0003-agpl-license-acceptance.md)。

当前标准模式是 [Debug UI 多人姿态原型](docs/STANDARD_MODE.md)：使用本地 YOLO26n-pose 权重输出每个人的人体框和 COCO 17 点骨架，并与兼容模式共用本地人脸增强、目标管理和 CVLFace 身份复核链路；正式托盘/EXE 仍固定使用兼容模式，标准后端及其可选依赖尚未进入 GA 发行包。

EchoPosture is a Windows desktop posture-change and static-exposure reminder. It uses a webcam with MediaPipe/OpenCV-based numeric posture signals, runs quietly from the system tray, performs personal two-anchor calibration, and can apply gradual screen dimming or blur after sustained static exposure.

It is intended as an ergonomics aid, not a medical diagnostic tool.

## Download

GA-2.0.0 publishes a source-only package and a **semi-portable graphical installer** under the same release.
EchoPosture program files and runtime content are downloaded only from the project's official GitHub Release.
The installer's **model weight download source** choice applies only to the separately licensed YOLO pose weights;
it never changes the program download source. The original 2,313,314,546-byte package is split into three official
Release assets because GitHub does not accept a single asset over 2 GiB.
**Neither channel bundles downloadable YOLO pose or CVLFace P5 identity weights** — the semi-portable package does
include MediaPipe's redistributable assets required by Compatibility mode. See
[ADR-0004](docs/decisions/ADR-0004-ga-2-0-source-only-distribution.md) and
[ADR-0005](docs/decisions/ADR-0005-ga-2-0-portable-standard-professional.md) and
[ADR-0006](docs/decisions/ADR-0006-ga-2-0-semi-portable-installer.md) for why.

| | Source-only | Semi-portable |
| --- | --- | --- |
| Asset | [EchoPosture-GA-2.0.0-source.zip](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-source.zip) | [Graphical setup](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-setup.exe) + [part 001](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.001) + [part 002](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.002) + [part 003](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-win-x64.zip.003) |
| SHA256 | `64f5b75fa42a5ef253a84ad5ade0a4c39765e5fc0820708371ecf6fdf48b9c94` | Setup `fc5de97df3fbd31c337fb6775947c21968beba7be3ad553b9a23a6292940975e`; parts and manifest are recorded in [SHA256SUMS](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-SHA256SUMS.txt) |
| Contains | Project source, `docs/`, `NOTICE`, `THIRD_PARTY_NOTICES.md`, `GA_BUILD.txt`, `README_GA.md`, `tools/fetch_pose_models/` | All of the above, plus the embedded Python 3.11 runtime and the built `EchoPosture.exe` / `EchoPostureSelfTest.exe` / `BlurOverlayHost.exe` |
| Requires | Python 3.11 + `pip install -r requirements.txt` | Run the visible installer; no administrator rights or system Python required |
| Downloadable pose/identity weights | Not included | Not included |

Both packages require running one of the four scripts in `tools/fetch_pose_models/` before Standard
or Professional Beta mode will work; Compatibility mode needs no download either way. The installer keeps its
window visible through download, verification, extraction, and script output, and remains open after success or
failure until the user closes it. Mirrors are third-party proxies and every fetched file is checked against the
official SHA-256. The installer's complete public manifest is
[here](https://github.com/NOVVLA/EchoPosture/releases/download/ga-2.0.0/EchoPosture-GA-2.0.0-semi-portable-manifest.json).

## Run

1. Install Python 3.11 and the packages in `requirements.txt` (`python -m pip install -r requirements.txt`).
2. Download and extract the release ZIP (or clone the repository at the tagged commit).
3. Compatibility mode needs no extra download and works immediately.
4. For Standard mode or Professional Beta mode, first fetch the Ultralytics YOLO26 pose weights by
   running one of the four scripts in `tools\fetch_pose_models\` (official source or mirror, English
   or Chinese interface — pick whichever fits your network and language; all four verify the same
   pinned SHA-256):

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\tools\fetch_pose_models\fetch_pose_models.ps1
   ```

5. Run `python tray_app.py` from the package root.
6. Allow camera access if Windows asks.
7. Hold the comfortable upright posture you want to use for the entire 5-second prompt. When the countdown closes and the tray says you may relax, relax naturally; EchoPosture then waits about one second and measures that relaxed posture in the background for about five seconds. Keep only one person in frame and remain naturally relaxed until calibration completes.

Both calibrated postures and the interval between them form your personal normal posture range. After calibration,
EchoPosture briefly rechecks that the target-locked measurements reproduce this range; static exposure stays paused
during that check. The anchors may be similar or identical; users do not need to exaggerate the relaxed posture.
Only sustained movement beyond either side of the range, the measured repeatability band, and a small explicit natural-movement deadband can accumulate exposure. The deadband is a product interaction margin, not a medical threshold.

See `README_GA.md` inside the release package for the full bilingual overview, including third-party
license notices and how to obtain the complete corresponding source under AGPLv3.

## Tray Controls

- Right-click the tray icon to open the menu.
- `立即重新校准` starts the same full two-anchor flow: a visible 5-second preferred stage, a short transition, and a background relaxed stage announced by a tray message.
- `立即测试最深效果` previews the strongest visual intervention.
- `停止` clears the visual overlay, releases the camera, and exits the app.
- Double-click the tray icon to open the console window.

The console shows an eye icon (overall monitoring state) and seven feature switches arranged along a spine motif, plus a side panel with dimming level, blur level, maximum dimming control, blur-strength control, and a one-click max-effect test.

The seven feature switches:

- `启动校准` (CALIBRATION) — trigger a new two-anchor calibration.
- `个人姿态偏离` (PRECISION) — toggle the within-person posture-change model; when off, EchoPosture falls back to legacy threshold checks.
- `72FPS 采集` (PERFORMANCE) — toggle capture between 72 FPS and a lower power-saving rate.
- `压暗干预` (DIMMING) — toggle the screen-dimming part of visual intervention.
- `GPU 模糊` (BLUR) — toggle the screen-blur part of visual intervention.
- `离开/多人检测` (PRESENCE) — toggle detection of the user stepping away or a second person entering frame.
- `换人保护` (IDENTITY) — toggle the check that flags when the person in frame no longer matches the calibrated profile.

All toggles except calibration default to on and can be switched independently while monitoring is active.

## Internationalization (i18n)

EchoPosture supports runtime language switching between Chinese and English, with a third "follow system" mode.

### Default behavior

- On startup, the app detects the system locale via the Windows API (`GetUserDefaultLocaleName`) and POSIX environment variables (`LANG`, `LC_ALL`, `LC_MESSAGES`, `LANGUAGE`).
- Simplified Chinese (`zh-CN`, `zh-TW`, ...) maps to `zh`. English (`en-US`, `en-GB`, ...) maps to `en`. Anything else falls back to `zh` (the project's primary language).
- The choice is session-level only. No registry entries, config files, or persistent state are written.

### Three-state language toggle

The tray flyout's language button cycles through three states:

1. `跟随系统 · 中文` / `Auto · Chinese` — follow the detected system language
2. `语言：中文` / `Language: Chinese` — explicitly Simplified Chinese
3. `Language: English` / `Language: English` — explicitly English

The button label always renders in the currently effective language and reflects the selected mode (manual `zh` / `en` vs `auto`).

### Coverage

All user-facing text is localized across five UI modules:

- `tray_flyout.py` — tray flyout (caption, state, buttons, tooltips)
- `onboarding_toast.py` — onboarding toast popup
- `tray_app.py` — startup calibration dialog, status panel, tray messages, warning dialogs
- `posture_console.py` — debug console (vertebra feature names, tooltips, status lines)
- `debug_ui.py` — visual debug UI (status codes, reason codes, labels, buttons, dialogs)

The visual Debug UI exposes both calibration modes: its primary action runs
the full production-equivalent two-anchor profile, while the visually
secondary single-frame action is retained only for labelled legacy comparison.

### Non-invasive design

- Only text is changed. No icons, layout, or animation is touched.
- Listener pattern (`add_listener` / `remove_listener`): any module can subscribe to language change events and refresh its text in place.
- Rendered text (e.g. `QPainter.drawText` on cached pixmaps) is refreshed by invalidating the cache (`self._card = None`) so the next `paintEvent` redraws with the new language.
- The language button uses `lang_button_text()` to dynamically produce the correct label based on the current mode (`auto` / `zh` / `en`) and the effective language.

## Self Test

Run `EchoPostureSelfTest.exe` from the release package when startup or camera behavior is unclear. It checks the packaged runtime, debug UI, camera/vision path, tray monitor path, and GPU blur helper. A successful self-test is a camera and runtime-chain result; its legacy single-frame baseline is not a successful scientific calibration.

Use the self test first if:

- the camera cannot be opened;
- the tray icon does not appear;
- the console window does not open;
- screen dimming or blur does not behave as expected;
- the app fails under a path that contains non-English characters.

Emergency clear for the native blur host:

- `Ctrl+Alt+Shift+E`

## What It Does

EchoPosture monitors within-person posture changes and static exposure from the webcam:

- face presence and approximate face distance;
- shoulder position and asymmetry;
- torso direction from shoulder and hip landmarks;
- user-away, multi-user, and profile-mismatch states;
- current personal posture deviation, current measurement confidence, and equivalent high-deviation exposure seconds.

The posture model groups face/torso/ear-to-shoulder evidence as forward change and shoulder/trunk evidence as lateral change, using only the strongest evidence in each group. Each runtime feature is admitted only when its own required landmarks are usable, so low-confidence hips cannot drive torso scoring through an otherwise high shoulder-quality frame. Raw shoulder width and estimated distance remain environment prompts and do not directly increase posture deviation. Uniform whole-person scale changes remain measurable through normalized features, so moving closer to or farther from the camera does not force the user back to the calibration distance. Low-quality, ambiguous, turned-head, or camera-reference observations pause intervention without claiming that the person is unrecognized.

Visual intervention is intentionally delayed. Small single-feature changes remain normal variation; a newly corroborated excursion is shown as posture adjustment and must persist for about `2` seconds before it can enter WATCH. Equivalent exposure begins only at the alert-level `0.70` threshold after that confirmation, so reaching, shifting in the chair, and WATCH-only noise cannot preload a future alert. Product policy requires at least `12` equivalent high-deviation seconds, then adds `3` seconds of intervention confirmation. Severe exposure uses deviation `0.85` and `30` equivalent seconds. Recovery decays exposure instead of clearing it instantly, and completed intervention episodes have a `60`-second cooldown. These are adjustable interaction parameters, not medical limits or physiological doses.

A pronounced pelvis-relative trunk lean is accepted as lateral posture evidence even when the shoulders remain nearly parallel, because real side-reclining does not always create shoulder asymmetry. A bounded static-hold add-on begins only after a corroborated deviation passes the two-second adjustment confirmation and remains present for about one minute. It ramps slowly, caps at `0.12`, resets on movement, recovery, low quality, or observation gaps, and cannot create a reminder from an otherwise normal posture by itself.

When intervention starts, EchoPosture does not change system brightness. It uses a full-screen, topmost, click-through overlay and gradually applies dimming and blur. The native GPU blur host is preferred; if desktop capture is unavailable, the app falls back to Windows compositor blur behavior.

## Privacy

The current app is a local Windows desktop prototype. It uses the camera for posture analysis and does not require an account or cloud service to run the released package. Production monitoring does not continuously save feedback, frames, face crops, video, identity templates, or vectors. The explicit reliability command may save a numeric JSON report only when the user supplies `--output`.

## Limitations

- EchoPosture is not a medical device and does not diagnose spinal, vision, or ergonomic conditions.
- It reports personal posture change and static exposure; it does not measure clinical CVA, Cobb angle, or an absolute neck/spine angle.
- Real-camera repeatability, SEM/MDC across devices, external validity, and user comfort outcomes require separate evidence and are not established by the included logic tests.
- Lighting, camera position, occlusion, chair position, and monitor layout can affect detection quality.
- Windows camera permissions and desktop-capture restrictions can affect startup, self-test, or GPU blur behavior.
- Long-running real desktop behavior should still be validated by the user on their own machine.

## Source Repository

The repository contains source code, build scripts, and process documentation. It does not contain generated release folders, embedded runtimes, logs, backups, or `.exe` artifacts.

Useful developer entry points:

- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, test selection, and pull request expectations.
- [docs/README.md](docs/README.md): architecture, release, and troubleshooting documentation index.
- [AGENTS.md（Repository Guidelines，仓库贡献者指南）](AGENTS.md): contributor workflow and development conventions.
- [上传必读(英文版).md（Remote Upload Rules，远端上传规则）](<上传必读(英文版).md>): pre-upload filtering and review requirements.
- [README_EXE.md（Executable Launcher Guide，EXE 启动器说明）](README_EXE.md): launcher and packaged EXE behavior.
- [run_debug_ui.cmd](run_debug_ui.cmd): debug UI entry.
- [run_vision_test.cmd](run_vision_test.cmd): vision test entry.
- [run_overlay_test.cmd](run_overlay_test.cmd): overlay test entry.
- [build_launcher.cmd](build_launcher.cmd): builds the Windows launcher package.
- [ROE.md（Rules of Engagement，项目协作与操作规则）](ROE.md): repository editing, branching, release, and rollback rules.
- [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md): development-log and release-evidence rules.
- [DEVELOPMENT_LOG.md（Development Log，开发日志）](DEVELOPMENT_LOG.md): tracked development and release audit trail.

The offline UI prototype in [ui/index.html](ui/index.html) is a frozen visual reference. Do not change it for general app behavior unless the UI reference itself is the intended target.
