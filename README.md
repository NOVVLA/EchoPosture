# EchoPosture

EchoPosture is a Windows desktop posture-monitoring prototype. It uses a webcam with MediaPipe/OpenCV-based posture signals, runs quietly from the system tray, performs startup calibration, and applies gradual screen dimming or blur when posture risk remains high.

It is intended as an ergonomics aid, not a medical diagnostic tool.

## Download

Use the latest GitHub release instead of cloning the source repository if you only want to run the app:

- Release: [EchoPosture GA-1.0.0](https://github.com/NOVVLA/EchoPosture/releases/tag/ga-1.0.0)
- Download: [EchoPosture-GA-1.0.0-win-x64.zip](https://github.com/NOVVLA/EchoPosture/releases/download/ga-1.0.0/EchoPosture-GA-1.0.0-win-x64.zip)
- SHA256: `345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`

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
- Double-click the tray icon to open the status panel.

The status panel shows the current posture state, dimming level, blur level, maximum dimming control, blur-strength control, and a one-click max-effect test.

## Self Test

Run `EchoPostureSelfTest.exe` from the release package when startup or camera behavior is unclear. It checks the packaged runtime, debug UI, vision path, tray monitor path, and GPU blur helper.

Use the self test first if:

- the camera cannot be opened;
- the tray icon does not appear;
- the status panel does not open;
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
