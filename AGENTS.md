# Repository Guidelines

## Project Structure & Module Organization

EchoPosture is a Windows desktop posture-monitoring application. Core Python modules live at the repository root: `tray_app.py` coordinates the application, `vision_test.py` contains posture analysis, `vision_worker.py` owns capture-thread logic, and `tray_flyout.py` implements tray controls. Browser-based interfaces are in `ui/`; launcher and native overlay sources are in `launcher/` and `native/`. Root-level `test_*.py` files are logic tests. Treat `runtime/`, `dist/`, `logs/`, `_backups/`, generated `.exe` files, and `无关文件/` as generated or non-product material unless a task explicitly targets them.

## Build, Test, and Development Commands

- `pip install -r requirements.txt -r requirements-dev.txt` installs Python and lint dependencies for Python 3.11.
- `ruff check .` runs the configured static checks (120-character line limit).
- `python -m py_compile tray_app.py vision_test.py vision_worker.py tray_flyout.py` performs a quick syntax check.
- `python test_startup_guards.py`, `python test_tray_flyout.py`, and `python test_vision_worker.py` run the CI logic suite. Run other `test_*.py` scripts when their area changes.
- `.\run_debug_ui.cmd`, `.\run_vision_test.cmd`, and `.\run_overlay_test.cmd` launch local diagnostic tools using the bundled runtime when available.
- `.\build_launcher.cmd` rebuilds the C# launcher, self-test executable, and C++ blur host.

## Coding Style & Naming Conventions

Use four-space indentation and Python 3.11 syntax. Follow existing conventions: `snake_case` for functions, variables, and modules; `PascalCase` for classes; and `UPPER_SNAKE_CASE` for constants. Add type hints to public or cross-module interfaces. Keep UI text in the existing localization flow (`i18n.py`) rather than duplicating literals. Ruff configuration is authoritative; avoid unrelated formatting churn.

## Testing Guidelines

Tests are executable assertion-based scripts rather than pytest suites. Name new files `test_<area>.py` and test functions `test_<behavior>()`. Keep logic tests deterministic and hardware-independent by using fakes, as in `test_vision_worker.py`. Camera, overlay, and packaged self-tests are supplemental; document any hardware-dependent checks that were skipped.

## Commit & Pull Request Guidelines

Recent history favors concise imperative subjects and Conventional Commit prefixes such as `fix:` and `feat(scope):`; release commits use direct titles such as `Prepare GA-1.2.1 release`. Avoid vague messages like `update` or `changes`. Before committing, follow `ROE.md` (Rules of Engagement，项目协作与操作规则), `PROCESS_AUDIT.md` (Process Audit Rules，过程审计规则), and `上传必读(英文版).md` (Remote Upload Rules，远端上传规则): verify the intended branch, record required evidence in `DEVELOPMENT_LOG.md` (Development Log，开发日志), and keep generated artifacts out of Git. Pull requests should describe user-visible impact, list verification commands, link relevant issues, and include screenshots for `ui/` or tray changes. Ensure the GitHub quality gate and Windows build pass.
