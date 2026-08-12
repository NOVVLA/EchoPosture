# EchoPosture Troubleshooting

Start with the packaged self-test when the application does not start or camera, tray, console, dimming, or blur behavior
is unclear:

```text
EchoPostureSelfTest.exe
```

It writes `logs\self-test-latest.txt` beside the extracted application. The report identifies the package root, actual
run root, time, output, and exit code for four stages: native overlay host, debug UI, vision, and tray startup. Keep the
original report private until it has been checked for personal paths or other sensitive data.

## Fast Triage

| Symptom | First checks | Next action |
| --- | --- | --- |
| Application does not start | Extract the whole ZIP; confirm `runtime\python311\python.exe` and `tray_app.py` exist | Run the self-test and inspect its startup error |
| Camera cannot open | Windows camera privacy settings; camera in use by another app; physical shutter | Close competing apps, grant desktop-app camera access, retry |
| Camera opens but self-test reports dark or unusable frames | Lens cover, lighting, virtual camera, wrong device | Improve front lighting or select another camera index in source diagnostics |
| Startup calibration fails | Face, shoulders, ears and upper torso visible; one person; stable preferred/relaxed stages | Reposition camera, improve lighting, remain still for both stages, retry calibration |
| Tray icon is missing | Notification-area overflow; process exited; startup warning behind another window | Expand hidden tray icons, then run the self-test |
| Console does not open | App finished onboarding and calibration; tray icon is active | Double-click the tray icon; review any tray warning |
| Dimming works but blur does not | Native-host stage and `mode`/reason in diagnostics | Allow compositor fallback or use `--disable-gpu-blur` to isolate the host |
| Overlay remains visible | Tray Stop command; emergency hotkey | Press `Ctrl+Alt+Shift+E`, then terminate stale EchoPosture processes if necessary |
| Works from one path but not another | `Run root` in the self-test log; LocalAppData write access | Extract to `C:\EchoPosture` and retry |
| SmartScreen warns | Release URL and ZIP SHA256 | Run only an official asset whose digest matches the public README/release |

## Reading the Self-Test

Expected stages:

```text
[1/4] GPU blur overlay host self-test
[2/4] Debug UI offscreen self-test
[3/4] Vision one-frame self-test
[4/4] Tray monitor self-test
```

For a complete pass, all four stages exit `0`; the tray stage reports that the camera and runtime chain started. The
self-test's legacy one-frame baseline is not evidence that the production two-anchor scientific calibration passed.
Interpret failures by stage:

- Stage 1 only: native overlay or desktop-capture problem. Monitoring may still run through the PyQt compositor
  fallback, but native blur is not verified.
- Stage 2 only: PyQt platform plugin, display, or packaged module problem.
- Stage 3 only: camera, OpenCV, MediaPipe resource, or one-frame landmark path problem.
- Stage 4 only: camera sampling or startup runtime problem. Production calibration can still fail later if either the
  visible 5-second preferred stage or the background relaxed stage has fewer than five quality-gated samples.
- Several missing-file failures: incomplete extraction or an incorrectly assembled package.

An environment-sensitive failure is still a failed check. Record the exact stage and observation instead of reporting
the whole self-test as passed.

## Startup and Embedded Runtime

The executable is a launcher, not a self-contained single binary. These must stay together:

```text
EchoPosture.exe
EchoPostureSelfTest.exe
BlurOverlayHost.exe
tray_app.py and supporting Python modules
runtime\python311\python.exe and its packaged dependencies
```

If the launcher reports a missing runtime or script:

1. Delete the incomplete extracted folder, not the original ZIP.
2. Verify the ZIP SHA256 against the GitHub release.
3. Extract the entire archive with Windows Explorer or another trusted ZIP tool.
4. Run the self-test before the main application.

Do not copy only `EchoPosture.exe` to the desktop.

## Non-ASCII Paths and the Run Root

The GA-1.2.1 launcher first creates a junction at `%LOCALAPPDATA%\EchoPostureGA121\current`. If junction creation fails,
it mirrors the package to `%LOCALAPPDATA%\EchoPostureGA121\current-copy`; if that also fails, it runs from the package
directory.

Check the `Run root:` line in `logs\self-test-latest.txt`:

- an `EchoPostureGA121` LocalAppData path shows that the compatibility layer worked;
- the original package path shows that both compatibility attempts were unavailable;
- a package path containing non-ASCII characters can expose MediaPipe resource-loading problems in restrictive
  environments.

For diagnosis, extract the release to `C:\EchoPosture`, confirm that `%LOCALAPPDATA%` is writable for the current user,
and rerun the self-test. Do not manually create a junction unless you understand and verify both its source and target.

## Camera Permission or Camera Busy

When the camera cannot be opened:

1. Open Windows Settings and allow camera access for the device and desktop apps.
2. Close Teams, Zoom, browser camera tabs, OBS, Camera, and other applications that may hold the camera.
3. Check a physical privacy shutter, hardware key, or vendor privacy utility.
4. Test the camera in the Windows Camera app, close that app, then retry EchoPosture.
5. Restart EchoPosture after changing permission settings.

Source-tree diagnostics accept a camera index:

```powershell
.\run_vision_test.cmd --camera 1 --max-samples 10
.\run_debug_ui.cmd --camera 1
```

The packaged launcher also forwards `--camera`, for example `EchoPosture.exe --camera 1`, but normal users should try
the default camera first.

## Dark Frames and Calibration Failure

Camera-open success does not prove that usable landmarks are available. EchoPosture's production path needs complete,
single-person, quality-gated samples in both calibration stages; it does not silently promote one frame to a baseline.

- Face the camera with even front lighting; avoid a bright window behind you.
- Keep the face, both shoulders, and upper torso in frame.
- Remove lens covers and verify that the preview is not black.
- Keep one person in frame. Hold the preferred posture throughout the visible 5-second countdown; relax only after the
  prompt, then remain reasonably still during the background relaxed measurement until completion.
- A moving target, low visibility, turned head, temporary target uncertainty, or missing keypoint skips that frame but
  preserves earlier valid samples. Multiple people or an ambiguous target reset the current anchor because identity
  contamination cannot be averaged away.
- Hip visibility gates only hip-dependent torso features. Clear shoulders and face measurements can still contribute
  to calibration when the hips are less visible.
- Recalibrate after moving the camera, chair, or monitor. A detected camera drift pauses exposure and reports that
  recalibration is required.
- Remain naturally relaxed until the relaxed measurement completes. The app then briefly validates that the
  target-locked measurements still fall in the two-anchor personal normal range. This validation reports `UNKNOWN`
  and pauses exposure; staying in the relaxed calibration ending pose must not create a static-exposure episode.

A successful debug preview with a failed tray calibration usually means one of the two stages did not contain enough
quality-gated samples, not that the tray icon itself is broken. The debug panel's one-frame button is an explicit legacy
path and must not be used as proof of scientific calibration.

## Numeric Reliability Report

To collect repeatability evidence deliberately, run the command from the repository root:

```text
runtime\python311\python.exe tools\collect_posture_reliability.py --frames 200 --output report.json
```

The command prompts for two equal numeric sampling blocks with a short transition between them; this validation tool
is separate from the production UI timing path. The report contains only numeric feature statistics, anchor separation
versus MDC, hardware/resolution/backend/model metadata, sample counts, and an explicit unverified-items list. Without
`--output`, the JSON is printed and no report is written. This command does not establish clinical validity or
cross-device reliability by itself.

## Tray and Console

EchoPosture stays running in the Windows notification area after calibration. Windows may place its icon in the hidden
overflow area.

- Right-click opens the tray flyout.
- Double-click opens or hides the console.
- The flyout monitoring switch pauses or resumes capture after startup is complete.
- Recalibration and monitoring changes are intentionally rejected while onboarding or startup calibration is active.
- Stop clears visual intervention, releases the camera, closes helper UI, hides the tray icon, and exits.

If a flyout or console error occurs, monitoring is designed to continue and a tray warning should appear. Capture the
exact warning text and the action that triggered it.

## Blur, Dimming, and Desktop Capture

The preferred path is `gpu_blur_overlay.py` controlling `BlurOverlayHost.exe`. The controller falls back when the host
is missing, exits, fails its pipe, or does not report healthy status. Desktop-capture restrictions can also cause the
native host to use a different mode.

Isolation steps:

1. Run `EchoPostureSelfTest.exe` and inspect stage 1.
2. From a source or package console, run `BlurOverlayHost.exe --self-test`.
3. Launch `EchoPosture.exe --disable-gpu-blur` to force the PyQt compositor-overlay path.
4. Use the tray max-effect preview to test the configured overlay for eight seconds.

`--disable-gpu-blur` is a diagnostic switch, not proof that the native host is fixed. If the fallback works and the
native path fails, attach the stage-1 output and Windows/display configuration to the issue.

## Emergency Overlay Clear

Try these in order:

1. Open the tray flyout and choose Stop.
2. Press `Ctrl+Alt+Shift+E` to clear the native host.
3. If the UI is unavailable, open Task Manager and end remaining `EchoPosture`, `BlurOverlayHost`, or package
   `pythonw.exe` processes after confirming they belong to this application.
4. Record what remained running and whether input was still click-through.

Do not reboot first unless the screen is unusable; process state and self-test output are valuable evidence.

## Source-Tree Diagnostics

Use these only from a trusted source checkout with its local embedded runtime or a prepared Python 3.11 environment:

```powershell
.\run_debug_ui.cmd
.\run_vision_test.cmd
.\run_overlay_test.cmd
.\BlurOverlayHost.exe --self-test
```

`run_debug_ui.cmd` opens the live P3/P4 target-tracking panel. Use
`.\run_debug_ui.cmd --camera 1` when the default camera index is wrong. Keep
one clear person in view during calibration. The panel should first show
`ACQUIRING`; after calibration it should show `TARGET_LOCKED`, a numeric locked
track, and `People present = 1`. `MULTI_PRESENT`, `TARGET_OCCLUDED`,
`TARGET_REACQUIRING`, `IDENTITY_UNCERTAIN`, or `TARGET_AMBIGUOUS` are safety
states, not posture scores; read the adjacent state reason before treating the
posture result as valid.

To prove the panel wiring without a camera or desktop display, run:

```powershell
runtime\python311\python.exe test_debug_ui.py
```

This uses a fixed frame and a real target manager/analyzer, then asserts the
`ACQUIRING` -> `TARGET_LOCKED` transition, track `1`, and person count `1`.
It does not prove camera permissions, MediaPipe landmark quality, or packaged
Windows behavior; those still require the live CMD or the packaged self-test.

`run_overlay_test.cmd` repeatedly fades a simple click-through dimming overlay and is separate from the production
native blur host. Stop it with `Ctrl+C` in its terminal.

For logic-only regressions that do not require a camera:

```powershell
python test_startup_guards.py
python test_tray_flyout.py
python test_vision_worker.py
python test_feature_toggles.py
```

## Reporting a Useful Issue

Include:

- EchoPosture release version or commit SHA;
- Windows version, display count/scaling, and camera model when relevant;
- exact entry point and arguments;
- self-test stage, exit code, and the smallest relevant output excerpt;
- whether the extracted path contains non-ASCII characters;
- whether the LocalAppData bridge or `current-copy` was used;
- expected behavior, actual behavior, and recovery steps attempted;
- whether Stop and `Ctrl+Alt+Shift+E` cleared the overlay.

Remove camera images, usernames, absolute personal paths, tokens, and unrelated diagnostic data. Report suspected
security vulnerabilities privately according to the [Security Policy](../SECURITY.md), not in a public issue.
