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
- Right-clicking the icon opens a menu with `立即重新校准`, `立即测试最深效果`, and `停止`.
- `停止` clears the visual overlay, releases the camera, and exits the program.
- Double-clicking the tray icon opens a small status panel showing the current posture state, dimming level, blur level, max-dim slider, blur-strength slider, and a one-click max-effect test button.

Diagnostic entry:

- `EchoPostureSelfTest.exe`

Build command:

- `build_launcher.cmd`
- `build_blur_overlay_host.cmd` builds only the GPU blur helper.

The EXE is a lightweight native launcher. It does not bundle the full Python runtime into a single binary. Instead, it launches the embedded runtime in `runtime/python311`, sets the required environment variables, and creates an ASCII path bridge at `%LOCALAPPDATA%\EchoPostureDev\current` before starting the app.

This keeps the DEV package as a one-folder portable app while avoiding `.cmd` as the user-facing entry point.

The main UI starts with high precision mode and high performance mode enabled. Visual intervention requires a repeatedly confirmed `BAD` or `CRITICAL` decision, risk score `>= 45`, sustained risk for at least `12` seconds, and an extra `3` seconds of continuous confirmation. It then applies a gradual click-through visual overlay without changing system brightness.

The production tray runtime now tries to launch `BlurOverlayHost.exe`, a native D3D11/DXGI helper that captures each monitor with Desktop Duplication, renders a GPU blur, and excludes its own overlay windows from capture with `WDA_EXCLUDEFROMCAPTURE`. If desktop capture is denied or unavailable, the host keeps `gpu` mode by switching to a native Windows compositor blur fallback. If the native host cannot start at all, the app falls back to the PyQt overlay, which also enables compositor blur instead of dim-only behavior.

Emergency clear for the native host:

- `Ctrl+Alt+Shift+E`

Use `EchoPosture.exe --disable-gpu-blur` to skip the native host and use the PyQt compositor-blur fallback.

Use `EchoPosture.exe --debug-ui` to open the older visual debug window.

The offline UI prototype is included at `ui/index.html`. It is a frozen visual reference file for the OCULI / VERTEBRA HTML sample; do not change that file for general fixes or enhancements unless the UI reference itself is explicitly requested. It is non-invasive and does not connect to the camera, tray runtime, or overlay system.
