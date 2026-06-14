# Intervention Layer Control Impact Branch

This branch is an investigation and documentation branch for the EchoPosture
visual intervention layer. It is not a ready-to-merge fix branch.

## Branch Purpose

The original issue was observed during active blur intervention:

- The Windows taskbar, quick-launch area, widgets area, and system tray became
  practically unusable while blur was active.
- The EchoPosture tray icon could receive a click, and the taskbar appeared to
  come to the foreground, but the expected tray UI or taskbar interaction did
  not reliably open.
- This created an emergency-exit problem because the tray is the normal place
  to stop the app after intervention starts.

The branch was kept to record what was tried and why those changes should not be
treated as a successful fix.

## Runtime Paths Involved

The production-style tray runtime is:

- `launcher/EchoPostureLauncher.cs`
- `tray_app.py`
- `gpu_blur_overlay.py`
- `native/BlurOverlayHost.cpp`
- `debug_ui.py` for the PyQt fallback overlay class used by the controller

The normal packaged launcher also prepares an ASCII run-root bridge under
LocalAppData. Directly running the temporary worktree with the embedded Python
from the Chinese workspace path can make MediaPipe resource lookup fail. For
manual tests in this investigation, an ASCII test directory was used:

- `%LOCALAPPDATA%\EchoPostureHotfix\blur-taskbar-test`

## Experiments Tried

Three code experiments were committed on this branch and then reverted.

1. Limit overlay coverage to the Windows work area.

   The native GPU overlay and the PyQt fallback overlay were changed to use the
   monitor work area instead of the full desktop rectangle. The goal was to keep
   the taskbar area outside the intervention window. In the user's real desktop
   setup, this did not restore taskbar or tray interaction.

2. Add a fixed bottom safe band.

   A conservative bottom band was excluded from the overlay, independent of what
   Windows reported as the work area. This also did not solve the observed
   taskbar/tray interaction problem.

3. Add an input escape band and change overlay show behavior.

   The overlay was changed to hide when the pointer entered the bottom screen
   band. The code also attempted to disable overlay input and render before
   showing the native overlay. This still did not solve the taskbar/tray
   interaction problem and introduced or preserved a visible white flash when
   intervention started.

Because the experiments failed in real use, they were reverted by commit
`1c0bee8` (`Revert blur overlay experiments`). After that revert, the overlay
source files in this branch matched `main` again:

- `debug_ui.py`
- `gpu_blur_overlay.py`
- `native/BlurOverlayHost.cpp`

## Current Decision

Do not continue trying to fix the taskbar interaction on this branch by changing
overlay geometry or click-through flags. The observed behavior suggests that
Windows may be receiving the click but not completing the taskbar/tray action
while the intervention window or compositor blur path is active.

For now, this branch should be treated as a record of the failure mode and the
discarded approaches.

## Known User Impact

If the taskbar/tray interaction issue still exists in `main`, a user may have no
normal tray-based way to stop EchoPosture once blur intervention is active.

Any future fix should prioritize a separate emergency control path that does not
depend on opening the Windows tray while blur is active. Possible directions:

- A global hotkey handled by the Python tray process as well as the native blur
  host.
- A small always-on-top emergency stop affordance owned by EchoPosture.
- A timed intervention auto-clear policy after a maximum continuous blur period.
- A watchdog shortcut or command-line stop endpoint.

## White Flash Note

The white flash was not present in the main workspace behavior according to the
user's comparison. The experimental overlay changes made on this branch were
therefore reverted rather than refined. If a white flash is observed again after
this branch is reset to main overlay behavior, compare launch method and run-root
behavior before changing overlay rendering again.

## Verification Recorded During Investigation

The following checks were run during the branch work:

- `BlurOverlayHost.exe --self-test` passed after each native rebuild.
- Python syntax checks passed for `debug_ui.py`, `gpu_blur_overlay.py`, and
  `tray_app.py`.
- Manual user testing showed that the taskbar/tray interaction was still not
  fixed by the attempted overlay geometry and input changes.

These checks do not prove a usable fix. They only prove that the experimental
builds were structurally runnable.

