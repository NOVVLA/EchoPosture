# EchoPosture Documentation

This directory contains the maintained technical documentation for EchoPosture. The root [README](../README.md)
is the end-user landing page; the documents here are for contributors and maintainers.

## Start Here

- [Architecture](ARCHITECTURE.md): runtime components, process and thread boundaries, state flow, and extension points.
- [Release Guide](RELEASE.md): version preparation, validation, packaging, sanitization, publication, and rollback.
- [Troubleshooting](TROUBLESHOOTING.md): user and maintainer diagnosis for startup, camera, calibration, tray, and overlay failures.
- [Vision plan](plans/EchoPosture_vision_identity_upgrade_plan.md): phased multi-mode vision and identity upgrade plan.
- [Vision ADR](decisions/ADR-0001-vision-modes-and-fallback.md): P2 mode responsibilities, fallback order, and evidence gates.
- [Vision evidence](vision-evidence/README.md): consent-controlled recording metadata, deletion records, metrics, and license audit.
- [Contributing](../CONTRIBUTING.md): development setup, change workflow, test selection, and pull request expectations.

## Debug UI Test Panel

From the source checkout, start the live diagnostic panel with:

```powershell
.\run_debug_ui.cmd --camera 0
```

The CMD always enables the P3/P4 target panel. The right-hand panel shows the
current target state, locked track ID, people present, association score, and
state reason alongside the posture metrics. Click `Calibrate Current Posture`
only when one clear person is visible; a successful calibration changes the
target state from `ACQUIRING` to `TARGET_LOCKED` and records the track ID.

For a camera-free proof of the panel wiring, run:

```powershell
runtime\python311\python.exe test_debug_ui.py
```

For a packaged/offscreen smoke check, use `debug_ui.py --self-test`; this
prints the same target fields (`target_state`, `target_track`,
`target_count`, `target_score`, and `target_reason`). `--no-target-panel` is
available only for legacy single-sample comparison.

## Repository Process Documents

These files remain at the repository root because they govern every change:

- [ROE](../ROE.md): editing, branching, commit, push, release, rollback, and backup rules.
- [Process Audit](../PROCESS_AUDIT.md): required evidence and development-log format.
- [Development Log](../DEVELOPMENT_LOG.md): chronological implementation and release evidence.
- [Remote Upload Rules](<../上传必读(英文版).md>): files that may and may not be uploaded.
- [Security Policy](../SECURITY.md): supported versions and private vulnerability reporting.

When a document disagrees with executable code or a current GitHub release, treat that as documentation drift: verify
the live behavior, fix the document, and record the correction under the repository audit rules.
