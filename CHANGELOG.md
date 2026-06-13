# Changelog

## 2026-06-13

### Changed

- Set the release channel and package labeling to `GA-1.0.0`.
- Updated the launcher ASCII bridge path and self-test label for the GA release.

## 2026-06-09

### Changed

- Switched package and GitHub release labeling from `DEV` / `dev-...` to `TEAM_ALPHA` / `team-alpha-...`.
- Updated the launcher bridge path and self-test label to use TEAM_ALPHA naming.

## 2026-06-07

### Added

- Added `ui/index.html` as a non-invasive offline HTML/SVG prototype that replicates the frozen OCULI / VERTEBRA UI sample with an eye master switch, vertebra feature switches, and status readout.
- Added tray controls for immediate recalibration, max visual effect testing, max dimming, and blur strength adjustment.

### Changed

- Updated GPU blur behavior to prefer the native host while falling back to Windows compositor blur when desktop capture is unavailable.
- Updated DEV package metadata and documentation for `EchoPosture-DEV-20260607-144042-win-x64`.

### Fixed

- Added dedicated warnings for camera permission failures, black camera frames, and screen capture limits.
- Documented `ui/index.html` as a frozen visual reference file that should not be changed unless the UI reference itself is explicitly requested.

## 2026-06-02

### Added

- Added `tray_app.py` as the production-style tray runtime with startup calibration, background posture monitoring, a tray status panel, and a stop action that clears overlays and releases the camera.
- Added high-precision posture analysis in `vision_test.py`, including distance estimation, head-turn detection, shoulder width narrowing, shoulder asymmetry, trunk lean, sustained-risk scoring, and presence/profile suppression states.
- Added gradual visual intervention controls that only activate after confirmed `BAD` or `CRITICAL` posture decisions with sustained risk.
- Added `gpu_blur_overlay.py` and `native/BlurOverlayHost.cpp` for optional D3D11/DXGI GPU blur overlay support with Windows compositor blur fallback.
- Added C# launcher sources and build scripts for `EchoPosture.exe`, `EchoPostureSelfTest.exe`, and `BlurOverlayHost.exe`.
- Added `README_EXE.md` with launcher, self-test, GPU blur fallback, and emergency clear notes.

### Changed

- Updated `README.md` to describe the tray-first startup flow, calibration behavior, high-precision scoring, visual intervention thresholds, and current DEV-package limitations.
- Expanded the debug UI with high-precision controls, distance/trunk/risk readouts, updated posture states, and visual overlay behavior.
- Updated MediaPipe face processing to detect multiple faces and collect additional face, shoulder, hip, torso, and head-turn metrics.

### Fixed

- Fixed corrupted Chinese text in the tray startup prompt, status panel, notifications, and EXE documentation.
- Ignored generated binaries, object files, logs, backup folders, and distribution folders so GitHub receives source and documentation instead of local build artifacts.
