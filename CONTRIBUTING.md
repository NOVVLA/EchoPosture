# Contributing to EchoPosture

Thank you for improving EchoPosture. This project combines Python/PyQt, camera and MediaPipe processing, a C# launcher,
and a native Windows overlay host. A small-looking change can cross UI, thread, camera, or release boundaries, so every
contribution should be scoped and verified deliberately.

## Before You Start

Read the documents that match your work:

- [Architecture](docs/ARCHITECTURE.md): component ownership, thread/process boundaries, and invariants.
- [Troubleshooting](docs/TROUBLESHOOTING.md): supported diagnostics and evidence to collect.
- [ROE](ROE.md): maintainer rules for branches, commits, push, rollback, release, and backup.
- [Process Audit](PROCESS_AUDIT.md): when and how to update `DEVELOPMENT_LOG.md`.
- [Remote Upload Rules](<上传必读(英文版).md>): content that must stay local.
- [Security Policy](SECURITY.md): private vulnerability reporting.

`AGENTS.md` contains repository instructions for coding agents. Human contributors should use this guide as the normal
entry point while still respecting the project process documents above.

## Development Environment

The supported development baseline is Windows x64 and Python 3.11.

For Python changes:

```powershell
python -m venv .python\venv
.\.python\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
```

For launcher or native-host changes, also install:

- Visual Studio C++ Build Tools with the x64 C++ toolchain and Windows SDK;
- .NET Framework C# compiler available from its standard Windows Framework directory.

A camera is not required for deterministic logic tests. It is required for camera extraction, calibration, and full
packaged self-test validation. Desktop overlay checks require an interactive Windows session.

The repository does not track `runtime/`, built executables, `dist/`, logs, or backups. Maintainers may have a local
embedded runtime; external contributors can use a Python 3.11 virtual environment for logic checks.

## Choose the Right Change Surface

| Intent | Primary location |
| --- | --- |
| Camera capture or landmark extraction | `vision_test.py` / `VisionEngine` |
| Posture thresholds, scoring, presence, or identity guard | `vision_test.py` analyzers |
| Capture thread, mailbox, calibration commands | `vision_worker.py` |
| Tray lifecycle, startup flow, intervention gate | `tray_app.py` |
| Tray flyout | `tray_flyout.py` |
| Console feature controls | `posture_console.py` / `FEATURE_REGISTRY` |
| User-facing strings or language behavior | `i18n.py` plus consuming widget |
| Python/native overlay coordination | `gpu_blur_overlay.py` |
| D3D11/DXGI native overlay | `native/BlurOverlayHost.cpp` |
| Packaged EXE startup and self-test | `launcher/EchoPostureLauncher.cs` |
| Frozen visual reference | `ui/index.html`, only when explicitly requested |

Do not implement production behavior in `ui/index.html`. It is a frozen visual reference and is disconnected from the
camera, tray runtime, and overlay system.

## Change Workflow

1. Inspect `git status --short --branch` before editing. Preserve unrelated changes and untracked local material.
2. Define one clear behavior or documentation outcome. Avoid drive-by formatting or unrelated refactors.
3. Follow the architecture invariants, especially worker ownership, non-blocking GUI behavior, overlay cleanup, and
   localization.
4. Add or update a deterministic test when behavior can be tested without camera or desktop hardware.
5. Run the smallest focused checks plus the common quality checks below.
6. Update user documentation when behavior, controls, arguments, limitations, or diagnostics change.
7. Update `DEVELOPMENT_LOG.md` when required by `PROCESS_AUDIT.md`; record actual failures and skipped checks.
8. Review `git diff --check`, `git diff`, and the exact staged paths before committing.

Repository maintainers follow the branch and push policy in `ROE.md`. External contributors normally work in a fork or
topic branch and open a pull request against `main`; do not force-push over reviewed history or rewrite public tags.

## Code Style

- Use Python 3.11 syntax and four-space indentation.
- Use `snake_case` for functions, variables, and modules; `PascalCase` for classes; `UPPER_SNAKE_CASE` for constants.
- Add type hints to public or cross-module interfaces.
- Keep lines within 120 characters where practical; Ruff configuration is authoritative.
- Keep user-facing text in `i18n.py` rather than duplicating Chinese or English literals in widgets.
- Avoid broad formatting churn in mixed Chinese/English source files.
- Keep continuous camera and MediaPipe work off the Qt GUI thread.
- Ensure every pause, failure, recalibration, and shutdown path clears visual intervention when appropriate.

## Tests and Checks

### Common static checks

These match the Python files covered by the GitHub quality gate:

```powershell
ruff check debug_ui.py gpu_blur_overlay.py onboarding_toast.py overlay_test.py posture_console.py `
  test_startup_guards.py test_tray_flyout.py test_vision_worker.py tray_app.py tray_flyout.py `
  vision_test.py vision_worker.py

python -m py_compile debug_ui.py gpu_blur_overlay.py onboarding_toast.py overlay_test.py posture_console.py `
  test_startup_guards.py test_tray_flyout.py test_vision_worker.py tray_app.py tray_flyout.py `
  vision_test.py vision_worker.py
```

### Deterministic logic tests

```powershell
python test_startup_guards.py
python test_tray_flyout.py
python test_vision_worker.py
python test_feature_toggles.py
```

The first three run in CI. Run `test_feature_toggles.py` whenever analyzer or console switch behavior changes.

### Windows binary build

```powershell
.\build_launcher.cmd
```

This rebuilds `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`. Generated binaries remain local
and must not be committed.

### Hardware and interactive checks

Use the smallest relevant diagnostic:

```powershell
.\run_vision_test.cmd
.\run_debug_ui.cmd
.\run_overlay_test.cmd
.\BlurOverlayHost.exe --self-test
```

For release-package work, run the staged `EchoPostureSelfTest.exe` and follow the complete
[Release Guide](docs/RELEASE.md). Camera, tray, and overlay checks must state the entry point, action, observation, and
recovery result. “Looks good” is not sufficient evidence.

## Test Selection by Risk

| Change | Required focused checks |
| --- | --- |
| `vision_worker.py` or calibration lifecycle | `test_vision_worker.py`, `test_startup_guards.py` |
| Analyzer or presence/profile logic | `test_feature_toggles.py`, `test_vision_worker.py` |
| Tray flyout or startup controls | `test_tray_flyout.py`, `test_startup_guards.py` |
| Localization | relevant logic test plus manual Chinese, English, and follow-system refresh |
| Python overlay controller | syntax/Ruff, native host self-test, forced fallback, clear-on-stop check |
| Native host | `build_blur_overlay_host.cmd`, native self-test, emergency clear, multi-monitor check when relevant |
| Launcher | `build_launcher.cmd`, staged/package self-test, non-ASCII or ASCII-bridge check when relevant |
| Documentation only | link/path/version checks and `git diff --check`; no runtime test unless the document claims runtime output |

If hardware-dependent verification is unavailable, explain why, identify the unverified behavior, and do not mark it
as passed.

## Pull Request Checklist

A pull request should include:

- a concise description of the user-visible or maintainer-visible outcome;
- the exact baseline and scope of the change;
- risks involving camera access, worker shutdown, UI blocking, overlay cleanup, packaging, or data exposure;
- every verification command actually run and its result;
- skipped checks and remaining risk;
- screenshots for changed tray or console UI;
- linked issues or rationale;
- documentation and development-log updates when required.

Before submission:

```powershell
git status --short
git diff --check
git diff --cached
```

Stage named paths explicitly. Do not use `git add .` or `git add -A` in a workspace that contains local artifacts.

## Files That Must Stay Local

Do not commit or upload:

- `runtime/`, `dist/`, `logs/`, `_backups/`, generated `.exe`, `.obj`, or `.pdb` files;
- `.codex/`, `.agents/`, `.claude/`, review worktrees, temporary screenshots, or editor state;
- `README.local.md` and machine-specific paths or notes;
- camera images, personal data, credentials, tokens, cookies, or private diagnostic output.

An ignored file is not automatically safe to publish. If a normally local file is intentionally required, explain why
and obtain explicit maintainer approval before staging it.

## Security Reports

Do not open a public issue for an unpatched vulnerability. Use
[GitHub private vulnerability reporting](https://github.com/NOVVLA/EchoPosture/security/advisories/new) and follow
`SECURITY.md`.

## Definition of Done

A contribution is ready when the intended behavior is implemented, focused and common checks pass, hardware gaps are
explicit, cleanup and fallback paths are preserved, docs and audit evidence match the implementation, the staged diff
contains only intended files, and the GitHub-required quality and Windows build checks succeed.
