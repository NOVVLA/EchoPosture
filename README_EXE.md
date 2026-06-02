# EchoPosture EXE launcher

The project now includes a Windows executable launcher.

Primary entry:

- `EchoPosture.exe`

Default behavior:

- Launches the tray monitor.
- Shows a polished 5-second startup prompt asking the user to sit upright in a comfortable posture.
- Collects camera samples during the countdown.
- Uses the averaged startup samples as the baseline for the rest of the run.
- Shows a small EchoPosture icon in the Windows notification area.
- Right-clicking the icon opens a menu with `停止`.
- `停止` clears the visual overlay, releases the camera, and exits the program.
- Double-clicking the tray icon opens a small status panel showing only the current posture state, dimming level, and blur level.

Diagnostic entry:

- `EchoPostureSelfTest.exe`

Build command:

- `build_launcher.cmd`
- `build_blur_overlay_host.cmd` builds only the GPU blur helper.

The EXE is a lightweight native launcher. It does not bundle the full Python runtime into a single binary. Instead, it launches the embedded runtime in `runtime/python311`, sets the required environment variables, and creates an ASCII path bridge at `%LOCALAPPDATA%\EchoPostureDev\current` before starting the app.

This keeps the DEV package as a one-folder portable app while avoiding `.cmd` as the user-facing entry point.

The main UI starts with high precision mode and high performance mode enabled. Visual intervention requires a repeatedly confirmed `BAD` or `CRITICAL` decision, risk score `>= 45`, sustained risk for at least `12` seconds, and an extra `3` seconds of continuous confirmation. It then applies a gradual click-through visual overlay without changing system brightness.

The production tray runtime now tries to launch `BlurOverlayHost.exe`, a native D3D11/DXGI helper that captures each monitor with Desktop Duplication, renders a GPU blur, and excludes its own overlay windows from capture with `WDA_EXCLUDEFROMCAPTURE`. If the host cannot start, cannot capture the desktop, or detects unsafe capture behavior, the app automatically falls back to the previous PyQt dim-only overlay and the tray status panel reports blur as `0%`.

Emergency clear for the native host:

- `Ctrl+Alt+Shift+E`

Use `EchoPosture.exe --disable-gpu-blur` to force the dim-only fallback.

Use `EchoPosture.exe --debug-ui` to open the older visual debug window.
