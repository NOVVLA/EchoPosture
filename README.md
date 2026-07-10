# EchoPosture

EchoPosture is a Windows desktop posture-monitoring prototype. It uses a webcam with MediaPipe/OpenCV-based posture signals, runs quietly from the system tray, performs startup calibration, and applies gradual screen dimming or blur when posture risk remains high.

It is intended as an ergonomics aid, not a medical diagnostic tool.

## Download

Use the latest GitHub release instead of cloning the source repository if you only want to run the app:

- Release: [EchoPosture GA-1.2.0 - Maintainer Intelligence](https://github.com/NOVVLA/EchoPosture/releases/tag/ga-1.2.0)
- Download: [EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64.zip](https://github.com/NOVVLA/EchoPosture/releases/download/ga-1.2.0/EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64.zip)
- SHA256: `c4421f9ed760a680f21cc958fa1df84dacfba4f0d52f55fbaf0515bd5c5c5553`

The release package is a portable folder for Windows x64. It includes the embedded Python runtime and required Python dependencies. The source repository does not include `runtime/`, `dist/`, or built `.exe` files.

## Run

1. Download the release ZIP.
2. Extract it to a simple local folder, for example `C:\EchoPosture`.
3. Open the extracted folder.
4. Double-click `EchoPosture.exe`.
5. Allow camera access if Windows asks.
6. When the 5-second startup prompt appears, sit upright in a comfortable posture and stay still until calibration finishes.

After calibration, EchoPosture continues running from the Windows notification area.

Windows SmartScreen may warn about unsigned builds. Only run the package if it came from the release link above and the SHA256 matches.

## Tray Controls

- Right-click the tray icon to open the menu.
- `立即重新校准` starts a new posture baseline calibration.
- `立即测试最深效果` previews the strongest visual intervention.
- `停止` clears the visual overlay, releases the camera, and exits the app.
- Double-click the tray icon to open the console window.

The console shows an eye icon (overall monitoring state) and seven feature switches arranged along a spine motif, plus a side panel with dimming level, blur level, maximum dimming control, blur-strength control, and a one-click max-effect test.

The seven feature switches:

- `启动校准` (CALIBRATION) — trigger a new baseline calibration.
- `高精度评分` (PRECISION) — toggle the full risk-scoring model; when off, EchoPosture falls back to simple threshold checks.
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

### Non-invasive design

- Only text is changed. No icons, layout, or animation is touched.
- Listener pattern (`add_listener` / `remove_listener`): any module can subscribe to language change events and refresh its text in place.
- Rendered text (e.g. `QPainter.drawText` on cached pixmaps) is refreshed by invalidating the cache (`self._card = None`) so the next `paintEvent` redraws with the new language.
- The language button uses `lang_button_text()` to dynamically produce the correct label based on the current mode (`auto` / `zh` / `en`) and the effective language.

## Self Test

Run `EchoPostureSelfTest.exe` from the release package when startup or camera behavior is unclear. It checks the packaged runtime, debug UI, vision path, tray monitor path, and GPU blur helper.

Use the self test first if:

- the camera cannot be opened;
- the tray icon does not appear;
- the console window does not open;
- screen dimming or blur does not behave as expected;
- the app fails under a path that contains non-English characters.

Emergency clear for the native blur host:

- `Ctrl+Alt+Shift+E`

## What It Does

EchoPosture monitors posture signals from the webcam:

- face presence and approximate face distance;
- shoulder position and asymmetry;
- torso direction from shoulder and hip landmarks;
- user-away, multi-user, and profile-mismatch states;
- sustained `BAD` or `CRITICAL` posture risk.

Face-distance/shoulder scoring, user-away/multi-user detection, and profile-mismatch detection can each be turned off independently from the console window; all default to on.

Visual intervention is intentionally delayed. It requires a confirmed `BAD` or `CRITICAL` state, risk score `>= 45`, sustained risk for at least `12` seconds, and an extra `3` seconds of continuous confirmation.

When intervention starts, EchoPosture does not change system brightness. It uses a full-screen, topmost, click-through overlay and gradually applies dimming and blur. The native GPU blur host is preferred; if desktop capture is unavailable, the app falls back to Windows compositor blur behavior.

## Privacy

The current app is a local Windows desktop prototype. It uses the camera for posture analysis and does not require an account or cloud service to run the released package.

## Limitations

- EchoPosture is not a medical device and does not diagnose spinal, vision, or ergonomic conditions.
- A single webcam cannot precisely measure real neck or spine angles.
- Lighting, camera position, occlusion, chair position, and monitor layout can affect detection quality.
- Windows camera permissions and desktop-capture restrictions can affect startup, self-test, or GPU blur behavior.
- Long-running real desktop behavior should still be validated by the user on their own machine.

## Source Repository

The repository contains source code, build scripts, and process documentation. It does not contain generated release folders, embedded runtimes, logs, backups, or `.exe` artifacts.

Useful developer entry points:

- [README_EXE.md](README_EXE.md): launcher and packaged EXE behavior.
- [run_debug_ui.cmd](run_debug_ui.cmd): debug UI entry.
- [run_vision_test.cmd](run_vision_test.cmd): vision test entry.
- [run_overlay_test.cmd](run_overlay_test.cmd): overlay test entry.
- [build_launcher.cmd](build_launcher.cmd): builds the Windows launcher package.
- [ROE.md](ROE.md): repository editing, branching, release, and rollback rules.
- [PROCESS_AUDIT.md](PROCESS_AUDIT.md): development-log and release-evidence rules.
- [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md): tracked development and release audit trail.

The offline UI prototype in [ui/index.html](ui/index.html) is a frozen visual reference. Do not change it for general app behavior unless the UI reference itself is the intended target.
