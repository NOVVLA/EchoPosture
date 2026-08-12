# DEVELOPMENT_LOG（Development Log，开发日志）

## 2026-07-25 - Strengthen PR Review Escalation Guidance Without Weakening Close Gates

- Source: user request to make the PR reviewer more willing to identify present, easily minimized defects and to
  investigate allowed close conditions assertively, while preserving every existing close gate.
- Git: implementation delivered as remote commit `783f771e8f6ebd39dfaf84aea85f5bbffe325937`
  (`feat(review): strengthen PR escalation guidance`), branch `main`, pushed to `origin/main`.
- Scope: updated the PR review prompt to reject "easy to fix" as a reason to ignore a proven problem, require explicit
  findings for evidence-backed defects, and direct the model to test every close gate when it considers closure. Added
  a pure-logic regression test and included it in the remote quality gate.
- Risk: prompt guidance may produce more review findings and more primary close candidates. It does not expand the five
  hard close-rule categories, lower the primary `0.95` confidence threshold, bypass the independent reviewer, or
  permit merging.
- Verification:
  - Command: `runtime\python311\python.exe test_ai_pr_review_guards.py`.
  - Result: passed. Verifies that second-review disagreement, insufficient primary confidence, and missing hard-rule
    evidence all prevent closure.
  - Command: existing AI maintainer, startup, tray flyout, and vision worker logic tests; plus Python compilation and
    `git diff --check`.
  - Result: passed.
  - Command: remote quality-gate run `30155762398` and CodeQL run `30155762406`.
  - Result: passed. Quality gate completed Ruff, Python compilation, the complete logic suite including the new PR
    review guard test, and Windows build; CodeQL completed native build and analysis.
- Gaps: none for the prompt and guard implementation.
- Conclusion: implemented and validated. The model is more assertive about raising defects, but ordinary defects remain
  request-changes cases and automated closure still requires all existing independent gates.

## 2026-07-25 - Replace AI Release Notes Draft with Strict Post-Publication Audit

- Source: user request to audit every formally published GitHub Release, strictly identify missing release information,
  and create a follow-up Issue when the published information needs completion.
- Git: implementation commits `ff5a3b7317709e5989757660f1525c372d718f78`
  (`feat(workflows): audit published releases`) and `625978df0750a852a6eb85bba60da122808d789c`
  (`fix(workflows): enforce strict release findings`), branch `main`, pushed to `origin/main`.
- Scope: replaced `ai-release-notes` with `ai-release-audit`. It runs on `release.published` and supports a manual tag
  re-audit. The flow runs trusted default-branch code, reads only bounded Release metadata, applies deterministic
  naming/body/asset/digest checks, and accepts only allowlisted AI finding categories with evidence and confidence at
  least `0.70`.
- Risk: this flow can create one public Issue for a published Release. It has only `contents: read` and `issues: write`;
  it cannot edit or withdraw a Release, change tags or assets, alter repository files, merge, or change settings. Open
  audit Issues are deduplicated by a stable tag marker.
- Verification:
  - Command: `runtime\python311\python.exe test_ai_maintainer_manual_flows.py`.
  - Result: passed. Covers clean-release no-op, missing required information planning exactly one Issue, and rejection of
    AI finding categories outside the allowlist.
  - Command: `runtime\python311\python.exe test_startup_guards.py`, `test_tray_flyout.py`, and
    `test_vision_worker.py`.
  - Result: passed; existing logic suites remained green.
  - Command: `runtime\python311\python.exe -m py_compile .github\ai-flows\branch_preflight.py`
    `.github\ai-flows\release_audit.py test_ai_maintainer_manual_flows.py`, and `git diff --check`.
  - Result: passed.
  - Command: local Ruff check.
  - Result: skipped; Ruff is not installed in the local runtime. The updated remote quality gate installs
    `requirements-dev.txt` and is the clean-environment authority.
  - Command: remote quality-gate runs `30152308106` and `30152392639`, plus CodeQL runs `30152308116` and
    `30152392641`.
  - Result: all passed. Each quality gate completed Ruff, Python compilation, the logic suite, and the Windows build;
    each CodeQL run completed native build and analysis.
  - Command: manual dry-run `ai-release-audit` run `30152400507` against published `ga-1.2.1`.
  - Result: passed. The model identified four allowlisted, evidenced follow-ups and produced
    `outcome=issue_planned`; `dry_run=true` prevented creation of the proposed Issue.
- Gaps: none for the implemented trigger and dry-run path. The next real `release.published` event will create its
  deduplicated Issue when the deterministic or strict allowlisted finding gate is met.
- Conclusion: implemented, pushed, and exercised against the configured provider. The workflow can only create a
  follow-up Issue; it cannot edit or withdraw a Release or otherwise modify release assets, tags, or repository files.

## 2026-07-25 - Implement Read-Only AI Branch Preflight and Release Notes Drafts

- Source: user request to complete the two lowest-risk AI maintainer workflow frameworks and push them to the canonical remote.
- Git: implementation commit `260e49757b0a6e4469d87ffac3a9665c62c92509`
  (`feat(workflows): implement AI branch and release drafts`), branch `main`, pushed to `origin/main`.
- Scope: replaced the placeholder implementations for ai-branch-preflight and ai-release-notes with flow-specific
  context collection, OpenAI-compatible JSON analysis, guarded read-only results, structured Actions summaries, workflow
  inputs, prompts, and deterministic mock tests. Updated the quality gate to lint, compile, and run those tests.
- Risk: the workflows receive repository metadata and configured AI service Secrets at runtime. They must remain
  read-only: no comments, labels, reviews, merges, tags, releases, asset uploads, repository-file edits, or audit-log
  edits are permitted by either flow.
- Verification:
  - Command: runtime/python311/python.exe test_ai_maintainer_manual_flows.py
  - Result: passed; mock branch and release executions produced step summaries and cleared every requested write effect.
  - Command: runtime/python311/python.exe test_startup_guards.py, test_tray_flyout.py, and test_vision_worker.py
  - Result: passed; existing logic suite remained green in the project runtime.
  - Command: runtime/python311/python.exe -m py_compile on both new flow modules and the new test
  - Result: passed.
  - Command: local branch and release context collection against main..HEAD and ga-1.2.1..HEAD
  - Result: passed; branch comparison returned the expected empty baseline and release collection returned 16 commits.
  - Command: git diff --check and changed-file line-length scan
  - Result: passed.
  - Command: Ruff local check
  - Result: skipped; neither system Python nor runtime/python311 has the Ruff module. The updated remote quality gate installs
    requirements-dev.txt and will provide the authoritative clean-environment Ruff result.
  - Command: remote quality gate run `30149698916` and CodeQL run `30149698902` on the implementation commit
    `260e497`.
  - Result: passed. `python-quality` installed the development requirements, ran Ruff, compiled the Python sources, and
    passed the logic tests; `windows-build` passed; CodeQL `analyze` passed after building the launcher and native host.
  - Command: manual remote `ai-branch-preflight` run `30149717871` with `base_ref=main`, `target_ref=HEAD`, and
    `dry_run=true`.
  - Result: passed. The configured model returned structured JSON with `action=ignore`, confidence `0.90`, and correctly
    reported that both refs resolve to the same commit; no repository write was attempted.
  - Command: manual remote `ai-release-notes` run `30149718787` with `from_ref=ga-1.2.1`, `to_ref=HEAD`,
    `version=0.0.0-validation`, `channel=GA`, and `dry_run=true`.
  - Result: passed. The configured model returned a human-review draft, flagged the validation version as a placeholder,
    and explicitly reported that no tag, release, asset, checksum, or repository file was created or modified.
- Gaps: none for this L1 read-only implementation. The two remaining framework-only flows still require their own
  context collection and separately reviewed action policies before they can be implemented.
- Conclusion: implemented, pushed, and exercised against the configured provider. Both flows remain read-only regardless
  of requested model output and are advisory only; they are not merge gates.

## 2026-07-18 - Add Maintainer Architecture, Release, Troubleshooting, and Contribution Guides

- Source: user request to complete the first-round documentation set and verify that each document is operationally useful.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: added `CONTRIBUTING.md` and `docs/README.md`, `docs/ARCHITECTURE.md`, `docs/RELEASE.md`, and
  `docs/TROUBLESHOOTING.md`; linked the new documentation index and contribution guide from the public README.
- Risk: documentation-only change. Incorrect architecture, package, or diagnostic claims could misdirect contributors
  or release maintainers, so critical assertions were checked against source, CI, the GA-1.2.1 package, and the live
  GitHub release.
- Verification:
  - Command: local Markdown link resolver over `CONTRIBUTING.md`, `README.md`, and `docs/*.md`.
  - Result: passed; 32 local links resolved to existing files.
  - Command: source assertion check against `launcher/EchoPostureLauncher.cs`, `tray_app.py`, `vision_worker.py`,
    `gpu_blur_overlay.py`, `native/BlurOverlayHost.cpp`, and `build_launcher.cmd`.
  - Result: passed; all 28 checked launcher, timing, intervention, IPC, hotkey, and build assertions matched source.
  - Command: compare the documented release allowlist with `dist/EchoPosture-GA-1.2.1-win-x64`.
  - Result: passed; all 17 required top-level entries were present, there were no extra entries, and no forbidden
    top-level repository, audit, backup, or log directories were present.
  - Command: `Get-FileHash -Algorithm SHA256 dist\EchoPosture-GA-1.2.1-win-x64.zip` and live
    `gh release view ga-1.2.1` metadata comparison.
  - Result: passed; local ZIP and uploaded asset both reported
    `7d8f6142eb760ad456155f327b7c4550ee222a85bb24a3a6964318ca5267b618`; live asset name, uploaded state,
    release/tag, draft/prerelease state, and target commit also matched the guide's current baseline.
  - Command: stale version and personal workspace path scan over the new documentation.
  - Result: passed; no GA-1.0.0, `EchoPostureGA100`, or personal absolute workspace path was present.
  - Command: `git diff --check`.
  - Result: passed, exit 0.
- Gaps: no application runtime, camera, overlay, or package build test was run because executable behavior did not
  change. Markdown rendering was checked structurally rather than through a browser preview.
- Conclusion: ready to commit and push; the first-round documentation set has navigable entry points, source-grounded
  architecture, an auditable release checklist, symptom-driven diagnostics, and a contributor workflow tied to CI.

## 2026-07-17 - Align Maintainer Documentation with GA-1.2.1

- Source: user request to correct stale GA-1.0.0 references and unify the current version information.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: updated `README_EXE.md` and the local-only `README.local.md` to identify GA-1.2.1, its `EchoPostureGA121` ASCII bridge, and the `EchoPosture-GA-1.2.1-win-x64` package directory.
- Risk: documentation-only change; no launcher, runtime, package, or release artifact was modified.
- Verification:
  - Command: `rg -n "GA-1.0.0|EchoPostureGA100" README.md README.local.md README_EXE.md`
  - Result: passed; no stale GA-1.0.0 or `EchoPostureGA100` references remain in the current README files.
  - Command: compare the documented bridge and package directory with `launcher/EchoPostureLauncher.cs` and local `dist` contents.
  - Result: passed; the launcher uses `EchoPostureGA121`, and `dist/EchoPosture-GA-1.2.1-win-x64` exists.
  - Command: `git diff --check`
  - Result: passed, exit 0.
- Gaps: no runtime test was run because the change only corrects documentation version labels.
- Conclusion: ready to commit and push; current README version information is aligned with GA-1.2.1.

## 2026-07-16 - Clarify AI Workflow Names and Repository Document Labels

- Source: user request to make the AI issue-triage and PR-review workflow entries easier to discover and to clarify repository document names for maintainers.
- Git: commit `pending`, branch `main`, target `origin/main`.
- Scope: changed only the display names of `ai-issue-triage` and `ai-pr-review` (including their jobs) to show their respective `@ai-issue` and `@ai-review` comment entry points. Added bilingual filename labels and links in `CHANGELOG.md`, `README_EXE.md`, `DEVELOPMENT_LOG.md`, `PROCESS_AUDIT.md`, and `ROE.md`.
- Risk: GitHub Actions checks will display longer Unicode names. Workflow triggers, permissions, job steps, conditions, and implementation code are unchanged.
- Verification:
  - Command: `git diff --check`
  - Result: passed, exit 0.
  - Command: `git diff --word-diff=porcelain -- .github/workflows/ai-issue-triage.yml .github/workflows/ai-pr-review.yml`
  - Result: passed; review confirmed that only the two workflow and job `name` scalar values changed in each file.
- Gaps: no remote Actions run has executed for this display-name-only change. The local environment lacks both PowerShell `ConvertFrom-Yaml` and Python `PyYAML`, so a local YAML parser was unavailable.
- Conclusion: ready to commit and push to `main`; no runtime or workflow-logic behavior changed.

## 2026-07-11 - Keep Open Python Dependency Ranges Stable

- Source: user request after review of Dependabot PRs #16 and #17, which only raised open `>=` lower bounds despite CI already resolving the newer releases.
- Git: commit `pending`, branch `chore/dependabot-open-range-policy`, target `origin/main`.
- Scope: set the root `pip` Dependabot entry to `versioning-strategy: increase-if-necessary`. Existing compatible open requirements, such as `opencv-python>=4.8.0` and `PyQt5>=5.15.9`, will no longer be mechanically raised for routine version updates.
- Risk: Dependabot will not create a version-update PR when the current open requirement already permits the available version. A maintainer must deliberately change a minimum version when dropping older-runtime compatibility is intended. Security updates remain enabled separately through GitHub Dependabot alerts and security updates.
- Verification:
  - Source: GitHub Dependabot options reference confirms that `pip` supports `versioning-strategy`; its `increase-if-necessary` example preserves an already-compatible requirement for a minor update.
  - Command: `git diff --check`
  - Result: passed, exit 0.
- Gaps: GitHub validates the Dependabot configuration after the PR is opened; no local Dependabot runner is configured.
- Conclusion: pending review and GitHub configuration validation.

## 2026-07-10 - GA-1.2.0 Maintainer Intelligence Package and Release

- Source: user request to package the current remote `main` as GA-1.2.0 and publish a new downloadable GitHub Release with an OpenAI-style feature name.
- Git: release source commit `4b102be87b99a44b903cb140cf8190e156d0c322`, branch `main`, tag `ga-1.2.0`.
- Scope: changed launcher release labeling to GA-1.2.0, moved the ASCII bridge to `%LOCALAPPDATA%\EchoPostureGA120`, rebuilt all Windows executables, assembled a minimal current-main portable runtime, removed local logs/internal work files, and named the release `EchoPosture GA-1.2.0 - Maintainer Intelligence`.
- Verification:
  - `runtime\python311\python.exe -m py_compile ...`: passed.
  - `runtime\python311\python.exe test_vision_worker.py`: passed; output ended with `ALL TESTS PASSED`.
  - `runtime\python311\python.exe test_feature_toggles.py`: passed; output ended with `ALL TESTS PASSED`.
  - `.\build_launcher.cmd`: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - First package self-test: environment-only calibration failure because no usable face/shoulder sample was captured; GPU, UI, and vision stages exited 0.
  - Second package self-test: passed; run root `%LOCALAPPDATA%\EchoPostureGA120\current`, all four stages exited 0, `startup_calibrated=True`, and `baseline=True`.
  - Sanitized package verification: GPU host, Debug UI, and Vision stages exited 0; the tray stage could not capture a face/shoulder calibration sample in two attempts, matching the known environment-sensitive calibration condition rather than a missing-file failure.
  - ZIP structure audit: required EXEs, embedded Python, runtime modules, `LICENSE`, and GA build metadata were present; forbidden entries count was 0.
  - Sensitive-content audit: no local user paths, API keys, token-like values, logs, internal process documents, build scripts, test files, or repository metadata were present outside the embedded third-party runtime.
- Artifacts:
  - Package: `dist\EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64`
  - ZIP: `dist\EchoPosture-GA-1.2.0-Maintainer-Intelligence-win-x64.zip`
  - ZIP size: `301525653` bytes
  - SHA256: `AE0A615B45CFC57829C00523F40DDE05BD245011877CEE8C1C5EDF14E5798EC7`
- Release focus: current desktop mainline, bilingual UI, runtime console controls, AI Maintainer PR/Issue automation, and Claude-route backup failover.
- Remaining gap: long-running camera/overlay behavior and everyday tray interaction still require normal user-side desktop use beyond the packaged self-test.

本日志从 Git 历史和当前仓库文件还原，作为后续过程审计的起点。2026-06-09 以前的条目不是完整实时开发记录；它们只记录 Git 能证明的事实和已经识别出的证据缺口。后续提交必须按 [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md) 补充验证、风险和产物证据。

## 2026-07-07 - Wire Console Feature Toggles to Analyzer Flags

- Source: user request to push the local feature-toggle changes and merge them to the remote main branch.
- Git: commit `pending`, branch `codex/console-feature-toggles`, target `origin/main`.
- Scope:
  - `vision_test.py` `HighPrecisionPostureAnalyzer`: added default-on runtime flags for precision scoring, presence checks, and identity checks.
  - `posture_console.py`: changed the PRECISION, PRESENCE, and IDENTITY vertebrae from disabled placeholders to real toggles wired to the analyzer flags.
  - `test_feature_toggles.py`: added headless checks for defaults, off/on behavior, presence suppression, identity suppression, and basic-mode fallback scoring.
  - `README.md`: documented the console window and the seven tray-console feature controls.
- Risk: turning precision off uses the older threshold-based scoring path with a fixed BAD risk score for intervention compatibility; turning presence off allows multi-face frames to continue through normal scoring; the toggle values are runtime-only and reset to default-on after restart.
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile posture_console.py vision_test.py test_feature_toggles.py`
  - Result: passed, exit 0.
  - Command: `runtime\python311\python.exe test_feature_toggles.py`
  - Result: passed, output ended with `ALL TESTS PASSED`, exit 0.
- Gaps: no live click-through test of the console vertebrae was run on the desktop UI in this pass.
- Conclusion: ready to finish cherry-pick, verify, and push to `main`.

## 2026-06-16 - Public README Rewrite

- Source: user request to keep the local maintainer README for internal use while replacing the remote-facing README with a guide public users can follow.
- Git: commit `d9a4e3917a3d49470b3d8ab86a37a3aeb390fa5c`, branch `main`, tag `none`.
- Scope: rewrote [README.md](README.md) as a public GitHub landing page; removed local machine paths, local `dist/` and `runtime/` assumptions, and debug-first instructions; added release download, SHA256, first-run steps, tray controls, self-test guidance, source/developer entry points, and current limitations. Preserved the prior local README as untracked `README.local.md`.
- Risk:
  - Public users must be directed to the GitHub release ZIP rather than source-tree-only or local-package paths.
  - The root README is the GitHub landing page and must not require knowledge of this local workspace.
  - The local maintainer README must remain untracked so it is not uploaded as public guidance.
- Verification:
  - Command: `gh release view ga-1.0.0 --repo NOVVLA/EchoPosture --json tagName,name,isPrerelease,isDraft,url,targetCommitish,assets`
  - Result: passed; release `EchoPosture GA-1.0.0` is not draft or prerelease, asset `EchoPosture-GA-1.0.0-win-x64.zip` exists with digest `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`.
  - Command: `gh repo view NOVVLA/EchoPosture --json nameWithOwner,url,visibility,isPrivate,defaultBranchRef`
  - Result: passed; repository is `NOVVLA/EchoPosture`, `visibility=PUBLIC`, `isPrivate=false`, default branch `main`.
  - Command: `git fetch origin main`
  - Result: failed because Git HTTPS could not connect to `github.com:443`; GitHub API checks remained available.
- Artifacts: public README update for `https://github.com/NOVVLA/EchoPosture`.
- Gaps: remote update may need the GitHub API path if ordinary Git push remains unavailable in this environment.
- Conclusion: ready to publish after diff review.

## 2026-06-15 - Repository Rename and Public Visibility

- Source: user request to stop using `ICC` as the remote repository name, use the Markdown project name, and keep the repository public.
- Git: commit `50443e71808f11057caadaddeef731006b6be974`, branch `main`, tag `none`.
- Scope: renamed the GitHub repository from `NOVVLA/ICC` to `NOVVLA/EchoPosture`; updated local `origin` to `https://github.com/NOVVLA/EchoPosture.git`; updated process rules so the canonical repository and visibility checks match the public `EchoPosture` repository.
- Risk:
  - Release, push, and audit commands must use the renamed repository.
  - Old `NOVVLA/ICC` links remain as historical release evidence only and must not be treated as the current canonical repository.
  - Documentation that still says the repository should be private would conflict with the current public release posture.
- Verification:
  - Command: `gh repo view NOVVLA/ICC --json name,nameWithOwner,url,isPrivate,visibility,defaultBranchRef`
  - Result: passed before rename; repository reported `nameWithOwner=NOVVLA/ICC`, `visibility=PUBLIC`, and `isPrivate=false`.
  - Command: `gh repo view NOVVLA/EchoPosture --json nameWithOwner,url,visibility,isPrivate`
  - Result: failed before rename because `NOVVLA/EchoPosture` did not yet exist.
  - Command: `gh repo rename -R NOVVLA/ICC EchoPosture --yes`
  - Result: passed.
  - Command: `gh repo view NOVVLA/EchoPosture --json name,nameWithOwner,url,isPrivate,visibility,defaultBranchRef`
  - Result: passed after rename; repository reported `nameWithOwner=NOVVLA/EchoPosture`, `url=https://github.com/NOVVLA/EchoPosture`, `visibility=PUBLIC`, `isPrivate=false`, and default branch `main`.
  - Command: `git remote set-url origin https://github.com/NOVVLA/EchoPosture.git`
  - Result: passed.
  - Command: `git remote -v`
  - Result: passed; fetch and push now point to `https://github.com/NOVVLA/EchoPosture.git`.
- Artifacts: GitHub repository URL `https://github.com/NOVVLA/EchoPosture`.
- Gaps: historical release URLs that were created under `NOVVLA/ICC` are retained as old evidence; GitHub should redirect them, but new commands and rules must use `NOVVLA/EchoPosture`.
- Conclusion: repository name now matches the Markdown project name `EchoPosture`, and the target repository visibility is public.

## 2026-06-13 - GA-1.0.0 Package and Release

- Source: user request to use the latest `main`, set the version to `GA-1.0.0`, build a release package, push to remote, and create a GitHub release.
- Git: release source commit `197fbb092a7b7fbd61626c5c5df709aed01d103c`, branch `main`, tag `ga-1.0.0`; post-release audit commit `pending`.
- Scope: changed package/release labeling to `GA-1.0.0`; changed launcher ASCII bridge from `%LOCALAPPDATA%\EchoPostureTeamAlpha` to `%LOCALAPPDATA%\EchoPostureGA100`; changed self-test title to `EchoPosture GA-1.0.0 self-test`; updated release docs and audit rules; built and packaged a portable Windows x64 folder.
- Risk:
  - Launcher bridge path affects MediaPipe resource loading when the package is under the current Chinese workspace path.
  - Release package must not reuse the old TEAM_ALPHA package, path, bridge label, or release tag.
  - Package verification needs LocalAppData write access; sandboxed execution cannot create the ASCII bridge.
- Verification:
  - Command: `git fetch origin`
  - Result: passed; local `main` matched `origin/main` before release work.
  - Command: `runtime\python311\python.exe -m py_compile tray_app.py vision_worker.py gpu_blur_overlay.py onboarding_toast.py tray_flyout.py posture_console.py debug_ui.py vision_test.py`
  - Result: passed (exit 0).
  - Command: `.\build_launcher.cmd`
  - Result: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - Command: `dist\EchoPosture-GA-1.0.0-win-x64\EchoPostureSelfTest.exe`
  - Result: failed under sandbox because `%LOCALAPPDATA%\EchoPostureGA100` could not be created; MediaPipe then ran from the Chinese path and missed bundled resources.
  - Command: `dist\EchoPosture-GA-1.0.0-win-x64\EchoPostureSelfTest.exe` with approved unsandboxed execution.
  - Result: passed; report showed run root `C:\Users\aaabb\AppData\Local\EchoPostureGA100\current`, GPU host exit code 0, Debug UI exit code 0, Vision exit code 0, Tray monitor exit code 0.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: passed; repository reported `visibility=PUBLIC` and `isPrivate=false`.
  - Command: `gh release create ga-1.0.0 dist\EchoPosture-GA-1.0.0-win-x64.zip --repo NOVVLA/ICC --target 197fbb092a7b7fbd61626c5c5df709aed01d103c --title "EchoPosture GA-1.0.0"`
  - Result: passed; release URL `https://github.com/NOVVLA/ICC/releases/tag/ga-1.0.0`.
  - Command: `gh release view ga-1.0.0 --repo NOVVLA/ICC --json tagName,name,isPrerelease,isDraft,url,targetCommitish,createdAt,publishedAt,assets`
  - Result: passed; tag `ga-1.0.0`, target commit `197fbb092a7b7fbd61626c5c5df709aed01d103c`, `isDraft=false`, `isPrerelease=false`, asset state `uploaded`, size `305721523`, digest `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`.
  - Command: `git ls-remote --tags origin ga-1.0.0`
  - Result: passed; remote tag exists at `639d1dde2f18faf98b8b000ec406941af791ccef`.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: passed after release; repository still reported `visibility=PUBLIC` and `isPrivate=false`.
- Artifacts:
  - Package: `dist\EchoPosture-GA-1.0.0-win-x64`
  - Zip: `dist\EchoPosture-GA-1.0.0-win-x64.zip`
  - Zip size: `305721523` bytes
  - SHA256: `345B9F9E06CA058AF77197EE741B9C87E60D59FCE27B7357728F9C8576CFF5F4`
  - Release URL: `https://github.com/NOVVLA/ICC/releases/tag/ga-1.0.0`
  - GitHub asset digest: `sha256:345b9f9e06ca058af77197ee741b9c87e60d59fce27b7357728f9c8576cff5f4`
- Gaps: GUI animation smoothness, tray flyout interaction, and long-running camera/overlay behavior still require user-side real desktop validation beyond self-test.
- Conclusion: GA-1.0.0 package was released and post-release checks passed.

## 2026-06-09 - Audit Baseline

- Source: maintenance audit request.
- Git: `6ba14c73bce0a7bca2e11eafe4ac229a79a54d44`, branch `main`.
- Scope: no code change in this baseline; reviewed Git history, tag, ignored directories, docs, logs, backups and package presence.
- Evidence from Git:
  - Current tracked files are source and docs only; `logs/`, `dist/`, `runtime/`, `_backups/` are ignored.
  - Only tag is `dev-20260607-144042`, pointing to `7fa5b6970d20409a310c1837f2abd0c0fa202be2`.
  - Later working-tree review showed separate TEAM_ALPHA-related edits in existing files; this baseline does not validate those edits unless a later log entry explicitly records their verification.
- Gaps:
  - Existing logs do not prove current DEV package verification.
  - Release/package hash and GitHub release回查结果 are not recorded in tracked docs.
  - Early backup `EchoPosture-source-backup-20260530-194638` lacks `BACKUP_MANIFEST.txt`.
- Conclusion: Git can reconstruct the change sequence, but future process credibility requires tracked development logs.

## 2026-06-09 - Process Audit Documentation

- Source: user request to make future development logs credible and readable from Git.
- Git: commit `pending`, branch `main`.
- Scope: added [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md), added this [DEVELOPMENT_LOG.md（Development Log，开发日志）](DEVELOPMENT_LOG.md), and linked both from [README.md](README.md) and [ROE.md（Rules of Engagement，项目协作与操作规则）](ROE.md).
- Risk:
  - Documentation rules now affect future commit and release workflow.
  - Existing working-tree changes in `CHANGELOG.md`, `README_EXE.md`, `launcher/EchoPostureLauncher.cs`, and TEAM_ALPHA edits in existing docs were present during this documentation pass and are not validated by this entry unless separately logged.
- Verification:
  - Command: `git log --reverse --date=iso --pretty=format:'%h %H %ad %an %s'`
  - Result: passed; used to reconstruct historical commit sequence.
  - Command: `git status --short`
  - Result: passed; used to identify current tracked and untracked changes.
  - Command: `git diff -- README.md ROE.md PROCESS_AUDIT.md DEVELOPMENT_LOG.md`
  - Result: passed for tracked README/ROE diff; new untracked audit files were reviewed by direct content inspection.
- Artifacts: no release artifact.
- Gaps: no runtime or UI verification was needed because this entry only changes process documentation.
- Conclusion: ready for review; commit SHA should be filled after commit.

## 2026-06-09 - TEAM_ALPHA Package and Release

- Source: user request to package the current project and create a GitHub release using TEAM_ALPHA labels instead of DEV labels.
- Git: release source commit `db37ea6a88a7958de54f67f3d06c269c6acb6d23`, branch `main`, tag `team-alpha-20260609-154821`; post-release audit commit `pending`.
- Scope: changed package/release naming rules and docs from `DEV` / `dev-...` to `TEAM_ALPHA` / `team-alpha-...`; changed launcher ASCII bridge from `%LOCALAPPDATA%\EchoPostureDev` to `%LOCALAPPDATA%\EchoPostureTeamAlpha`; changed self-test title to `EchoPosture TEAM_ALPHA self-test`; built and packaged a portable Windows x64 folder.
- Risk:
  - Launcher bridge path affects MediaPipe resource loading when the package is under the current Chinese workspace path.
  - Release package must not use the old DEV package or release tag.
  - Package verification needs LocalAppData write access; sandboxed execution cannot create the ASCII bridge.
- Verification:
  - Command: `.\build_launcher.cmd`
  - Result: passed; rebuilt `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`.
  - Command: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64\EchoPostureSelfTest.exe`
  - Result: failed under sandbox because `%LOCALAPPDATA%\EchoPostureTeamAlpha` could not be created; MediaPipe then ran from the Chinese path and missed bundled resources.
  - Command: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64\EchoPostureSelfTest.exe` with approved unsandboxed execution.
  - Result: passed; report showed run root `C:\Users\aaabb\AppData\Local\EchoPostureTeamAlpha\current`, GPU host exit code 0, Debug UI exit code 0, Vision exit code 0, Tray monitor exit code 0.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: historical pre-public-state check; superseded by the 2026-06-15 public visibility record above.
  - Command: `gh release create team-alpha-20260609-154821 dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64.zip --repo NOVVLA/ICC --target db37ea6a88a7958de54f67f3d06c269c6acb6d23 --title "EchoPosture TEAM_ALPHA 20260609-154821" --prerelease`
  - Result: passed; release URL `https://github.com/NOVVLA/ICC/releases/tag/team-alpha-20260609-154821`.
  - Command: `gh release view team-alpha-20260609-154821 --repo NOVVLA/ICC --json tagName,name,isPrerelease,url,targetCommitish,createdAt,publishedAt,assets`
  - Result: passed; tag `team-alpha-20260609-154821`, target commit `db37ea6a88a7958de54f67f3d06c269c6acb6d23`, `isPrerelease=true`, asset state `uploaded`, size `305875036`, digest `sha256:7a0018e09a0c5a7a4f3b0ce350a27cb43c94cd01b0c19f42da2078c46f891fd3`.
  - Command: `gh repo view NOVVLA/ICC --json nameWithOwner,visibility,isPrivate,url`
  - Result: historical pre-public-state check; superseded by the 2026-06-15 public visibility record above.
  - Command: `git ls-remote --tags origin team-alpha-20260609-154821`
  - Result: failed; network connection timed out after 300 seconds.
  - Command: `git fetch origin tag team-alpha-20260609-154821`
  - Result: passed; fetched the new tag into the local repository.
- Artifacts:
  - Package: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64`
  - Zip: `dist\EchoPosture-TEAM_ALPHA-20260609-154821-win-x64.zip`
  - Zip size: `305875036` bytes
  - SHA256: `7A0018E09A0C5A7A4F3B0CE350A27CB43C94CD01B0C19F42DA2078C46F891FD3`
  - Release URL: `https://github.com/NOVVLA/ICC/releases/tag/team-alpha-20260609-154821`
  - GitHub asset digest: `sha256:7a0018e09a0c5a7a4f3b0ce350a27cb43c94cd01b0c19f42da2078c46f891fd3`
- Gaps: the first `git ls-remote` tag check timed out, but `gh release view` and `git fetch origin tag team-alpha-20260609-154821` confirmed the release tag.
- Conclusion: TEAM_ALPHA package was released and post-release checks passed.

## 2026-05-30 - Initial EchoPosture MVP

- Source: reconstructed from Git.
- Git: `1c4a619a58b2da9701e6aaea7038cf43f2eaeb02`.
- Scope: added the initial README, debug UI, overlay test, vision test, requirements and run scripts.
- Files: `.gitignore`, `README.md`, `debug_ui.py`, `overlay_test.py`, `requirements.txt`, `run_debug_ui.cmd`, `run_overlay_test.cmd`, `run_vision_test.cmd`, `vision_test.py`.
- Git evidence: 9 files changed, 1180 insertions.
- Missing audit content:
  - No recorded user requirement, acceptance criteria or design rationale.
  - No tracked verification command output.
  - No dependency snapshot beyond `requirements.txt`.
  - No known camera/MediaPipe/overlay environment notes.
- Conclusion: source introduction is clear; runtime verification is not auditable from Git alone.

## 2026-06-02 - Tray Runtime, Launcher and GPU Overlay

- Source: reconstructed from Git.
- Git: `692f339e43eeaf5199685787962772ffa97dfdbf`.
- Scope: introduced production-style tray runtime, EXE launcher docs and sources, GPU blur controller, native D3D11/DXGI host, build scripts and expanded high-precision posture analysis.
- Files: `.gitignore`, `CHANGELOG.md`, `README.md`, `README_EXE.md`, `build_blur_overlay_host.cmd`, `build_launcher.cmd`, `debug_ui.py`, `gpu_blur_overlay.py`, `launcher/EchoPostureLauncher.cs`, `native/BlurOverlayHost.cpp`, `tray_app.py`, `vision_test.py`.
- Git evidence: 12 files changed, 3840 insertions, 74 deletions.
- Missing audit content:
  - No split log for tray, launcher, GPU host, posture scoring and docs.
  - No tracked build output for `EchoPosture.exe`, `EchoPostureSelfTest.exe` or `BlurOverlayHost.exe`.
  - No tracked self-test summary proving camera, UI, vision and tray checks passed.
  - No risk record for overlay cleanup, camera release, DXGI failure, compositor fallback or UI blocking.
- Conclusion: implementation scope is well evidenced by Git; verification and risk closure are not.

## 2026-06-07 - DEV UI Prototype and Blur Fallback Controls

- Source: reconstructed from Git.
- Git: `7fa5b6970d20409a310c1837f2abd0c0fa202be2`.
- Tag: `dev-20260607-144042`.
- Scope: added frozen offline UI reference, expanded blur fallback behavior and controls, updated DEV package metadata and docs.
- Files: `CHANGELOG.md`, `README.md`, `README_EXE.md`, `build_blur_overlay_host.cmd`, `debug_ui.py`, `gpu_blur_overlay.py`, `launcher/EchoPostureLauncher.cs`, `native/BlurOverlayHost.cpp`, `tray_app.py`, `ui/index.html`, `vision_test.py`.
- Git evidence: 11 files changed, 1585 insertions, 49 deletions.
- Local artifact evidence: `dist/EchoPosture-DEV-20260607-144042-win-x64` exists and includes `DEV_BUILD.txt`.
- Missing audit content:
  - No tracked SHA256 for the DEV package or key EXE files.
  - No tracked build transcript or release回查结果.
  - Package `logs` directory has no current self-test output.
  - UI prototype has no tracked screenshot or visual comparison note.
  - Existing tag proves source point, not package integrity.
- Conclusion: source tag and package directory exist; package verification remains underdocumented.

## 2026-06-07 - Restore Frozen UI Reference

- Source: reconstructed from Git.
- Git: `9ce2a99c0e85dde7222b4594551d2b483c923569`.
- Scope: restored `ui/index.html` as a frozen visual reference and updated docs.
- Files: `CHANGELOG.md`, `README.md`, `README_EXE.md`, `ui/index.html`.
- Git evidence: 4 files changed, 9 insertions, 30 deletions.
- Missing audit content:
  - No record explaining what was changed before restore and why restore was required.
  - No visual before/after evidence.
  - No explicit frozen-file exception note tied to the commit.
- Conclusion: restore action is visible in Git; rationale and validation need future documentation discipline.

## 2026-06-07 - Project Editing Rules

- Source: reconstructed from Git.
- Git: `94ca210e149a01dd59dc2c3a53e5e9f1d221cf47`.
- Scope: added `ROE.md` and linked project rules from README.
- Files: `README.md`, `ROE.md`.
- Git evidence: 2 files changed, 73 insertions.
- Missing audit content:
  - Rule effective date is visible, but prior commits were not created under these rules.
  - No explicit migration note for older process gaps until this development log.
- Conclusion: rules became tracked here; earlier history remains partially reconstructed.

## 2026-06-08 - OCULI/VERTEBRA Console Integration

- Source: reconstructed from Git.
- Git: `9c448b77ffdfdc4df2ab9c107b580af341e962ef`.
- Scope: added `posture_console.py`, connected console to tray double-click and added supporting vision/tray changes.
- Files: `posture_console.py`, `tray_app.py`, `vision_test.py`.
- Git evidence: 3 files changed, 965 insertions, 9 deletions.
- Missing audit content:
  - No UI screenshot or viewport verification.
  - No manual interaction checklist for tray double-click, console open/close, state readout or failure behavior.
  - No performance note for the new console path.
- Conclusion: integration is clear in Git; UI behavior needs tracked verification.

## 2026-06-08 - Console Polish

- Source: reconstructed from Git.
- Git: `edc61914396e9be97b144c020f7a73d954be3f66`.
- Scope: polished console performance, labeled switches and fused frameless UI.
- Files: `posture_console.py`.
- Git evidence: 1 file changed, 335 insertions, 107 deletions.
- Missing audit content:
  - No visual regression note.
  - No performance measurement or interaction checklist.
  - No accessibility or scaling note.
- Conclusion: code change is localized; user-facing verification is missing.

## 2026-06-09 - Process Rule Tightening

- Source: reconstructed from Git.
- Git:
  - `ff4e1cb0dc40698f73afc5e72335e4dd288db95b` - document merge branch policy.
  - `437e0aaee0ed1d3eef9a2d91f8d1a684191390da` - document canonical repository remote.
  - `6ba14c73bce0a7bca2e11eafe4ac229a79a54d44` - tighten commit push requirement.
- Scope: clarified branch, remote and commit/push rules in `ROE.md`.
- Missing audit content:
  - Rules were updated, but no separate process audit file existed before this change.
  - No release verification template existed before this change.
- Conclusion: these commits improve process rules but need this log and [PROCESS_AUDIT.md（Process Audit Rules，过程审计规则）](PROCESS_AUDIT.md) to make future records auditable.

## 2026-06-09 - Tray Icon Logo Asset

- Source: reconstructed from Git.
- Git: `a4a8eb8e2f0e311143abf5141c56782f929b296f`.
- Scope: added `logo.png` and updated tray icon usage.
- Files: `logo.png`, `tray_app.py`.
- Git evidence: 2 files changed, 6 insertions.
- Missing audit content:
  - No image provenance note.
  - No tray icon visual check in notification area.
  - No fallback behavior note if the asset cannot load.
- Conclusion: change is small and visible; asset provenance and UI verification should be tracked going forward.

## 2026-06-13 - Onboarding Toast, Tray Flyout, Decorative Eye, Console Geometry

- Source: user request（统一 UI 至 ui/onboarding.html 演示：开场弹窗开关、托盘浮窗替代右键菜单、眼睛改纯装饰、控制台黄金分割居中+入场动画）。
- Git: commit `pending`, branch `main`.
- Scope:
  - 新增 `ui/onboarding.html`（开场流程演示参考，用户提供）。
  - 新增 `onboarding_toast.py`：右下角开场弹窗 + 苹果式眼睛滑条开关（单条时间轴驱动；玻璃卡片+logo 衬底预渲染为 pixmap；入场/谢幕只动 windowOpacity/位置）。共享 `render_glass_card()`；`EyeSlideSwitch` 支持 one_shot 与双向两种模式。
  - 新增 `tray_flyout.py`：托盘右键玻璃浮窗（监测开关 + 重新校准/最深效果/红色退出按钮 + 左上齿轮开控制台），Qt.Popup 点外自动收起。
  - `tray_app.py`：启动流程改为 开场弹窗→校准倒计时；移除 QMenu 托盘菜单，右键→浮窗；新增 open_console()；stop() 收口弹窗/浮窗。另含此前在途的高 DPI 属性改动（AA_EnableHighDpiScaling/AA_UseHighDpiPixmaps）。
  - `posture_console.py`：眼睛改纯装饰（常闭、点击穿透、删除 set_open/clicked），监测启停职责移交托盘浮窗；新增眼下 ECHOPOSTURE 字样；窗口尺寸=可用高度×0.618（保持 880:600）自动居中；每次显示播放 420ms 淡入+上浮入场动画；另含此前在途的 UI_SCALE=1.17 缩放改动。
- Risk: 启动流程新增用户确认环节（不拨开关则不进入校准）；托盘右键不再有原生菜单（退出入口移至浮窗红色按钮）；README 中"托盘菜单"描述已过时（待后续文档更新）；UI_SCALE/高 DPI 在途改动与本任务同提交（用户已确认提交当前文件状态）。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile onboarding_toast.py tray_flyout.py tray_app.py posture_console.py`
  - Result: passed (exit 0)。
  - Command: 静态接线断言脚本（导入四模块；断言 EyeSlideSwitch one_shot/set_on/toggled、TrayFlyout 按钮与 popup_bottom_right、EyeItem 无 clicked/set_open、tray_app 无 QMenu()/QAction(/setContextMenu、Context→flyout 接线）
  - Result: passed（临时脚本已按 ROE 清理，不入库）。
- Gaps: 本机 shell 环境 Qt GUI 层无法初始化（QGuiApplication 构造挂起，QCoreApplication 正常），开场弹窗动画、浮窗交互、控制台入场动画均未实机目检，待用户验证；README 托盘菜单章节未更新。
- Artifacts: 备份 `_backups/pre-vision-worker-20260613-000411/`（含 BACKUP_MANIFEST.txt，HEAD ef3ebc1）。
- Conclusion: local only; 待用户实机验证 UI 行为。

## 2026-06-13 - Move Vision Pipeline Off the GUI Thread

- Source: user request（UI 明显卡顿）。根因：TrayMonitor 以 72Hz QTimer 在 GUI 主线程同步执行 摄像头读帧 + MediaPipe FaceMesh/Pose 推理 + 评分（单次 50-150ms >> 14ms 周期），事件循环饱和导致全部动画掉帧；重新校准同步连采 18 帧另卡死主线程约 3 秒。
- Git: commit `pending`, branch `main`.
- Scope:
  - 新增 `vision_worker.py`：VisionWorker daemon 线程持有 VisionEngine+analyzer（构造/调用/close 全在工作线程），最新值信箱 + 一次性错误/校准回执；`average_calibration_sample`/`sample_is_usable` 从 tray_app 迁出为纯函数。
  - `tray_app.py`：监测主循环改为 10Hz 轻量 `_tick`（只取信箱、驱动 overlay、消费回执，<1ms/帧）；启动校准与 recalibrate_now 全部后台化（采样/平均/定基线在工作线程，结果回执后按原分支提示与恢复）；`--self-test` 保留完全同步本地路径不经 worker；`stop()` 收口 `worker.stop(join_timeout=2)`；`_EngineProxy` 保持 `monitor.engine.set/get_capture_fps` 接口，posture_console 零改动。TrayMonitor 公开接口无变化。
- Risk: 校准状态机（startup/recal × 成功/失败/进行中暂停退出）是最大回归面；worker join 超时（驱动卡死）时摄像头灯可能延迟熄灭；校准提示从同步变为约 1-3 秒后回执。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile vision_worker.py tray_app.py posture_console.py gpu_blur_overlay.py onboarding_toast.py tray_flyout.py`
  - Result: passed (exit 0)。
  - Command: `runtime\python311\python.exe test_vision_worker.py`（FakeEngine + 真 analyzer 逻辑层测试：线程归属、信箱覆盖、校准平均与旧语义一致、失败回执、错误一次性传播、出错自暂停、start 失败同步抛出、fps 往返、stop join、close 在工作线程）
  - Result: passed，输出 `ALL TESTS PASSED`，exit 0。测试入库为 `test_vision_worker.py`。
  - Command: tray_app/gpu_blur_overlay/posture_console 接线静态断言（无 calibration_timer、tick=100ms、worker.stop、self-test 同步路径、公开接口齐全）
  - Result: passed（临时脚本已清理）。
- Gaps: 本机无法初始化 Qt GUI 层，未实机验证：动画流畅度（核心验收）、启动校准/重校准 toast、摄像头拔出错误路径、退出后摄像头灯熄灭、`--self-test` 实跑。待用户按清单验证。
- Artifacts: 回退点 commit 861ad1a + `_backups/pre-vision-worker-20260613-000411/`。
- Conclusion: local only; 待用户实机验证。

## 2026-06-13 - Console Hide Hibernation and Overlay IPC Dedup

- Source: 同上卡顿任务的次要优化项。
- Git: commit `pending`, branch `main`.
- Scope:
  - `posture_console.py`：hideEvent 停 250ms refresh_timer 并停所有椎骨呼吸辉光动画（控制台"关闭"按钮实为 hide，此前隐藏后仍持续重绘）；showEvent 恢复。
  - `gpu_blur_overlay.py`：set_target/set_config IPC 去重（仅状态/配置变化时写管道）；gpu_ready 恢复时强制重发；force_clear/boost 同步缓存。
- Risk: 去重缓存与宿主实际状态不一致会导致命令漏发——已在 gpu 恢复、clear、boost 路径强制重置缓存。
- Verification: 同上一条目的 py_compile 与接线断言（hideEvent/_last_sent_target/_config_dirty 存在）；GPU 宿主实际行为待用户实机验证（压暗/模糊触发与解除、最深效果测试）。
- Conclusion: local only; 待用户实机验证。

## 2026-06-13 - Restyle Startup Calibration Dialog to Glass-Card Language

- Source: user request（把校准提示框统一成与开场弹窗/托盘浮窗一致的风格：logo 半透明打底、无边框、布局好看、配色合理）。
- Git: commit `99d8146`, branch `main`.
- Scope:
  - `tray_app.py` `StartupCalibrationDialog`：由浅色（`#f7f9fc`）带 1px 边框、居中的 `QDialog`，改造为同族视觉语言——`FramelessWindowHint` + `WA_TranslucentBackground` 无边框透明窗；复用 `onboarding_toast.render_glass_card()`（深色玻璃渐变 + 右侧 logo 蓝图衬底向左渐隐 + 1px 高光描边）；三段静态文字（小标题 `ECHOPOSTURE · 启动校准` / 主标题 `请坐直，保持舒适姿态` / 两行说明）沿用 toast 做法一次性画进缓存 pixmap，银白/银灰分级、左对齐垂直居中。
  - 新增 `_CountdownRing` 自绘控件替代旧的大号数字：淡白底环 + 银白→品牌红渐变进度弧（12 点顺时针递减）+ 居中数字，作为右侧焦点，与左侧文字构成左文右环布局；动态部分作为子控件自绘，文字进卡片（与 toast 开关/文字分工一致）。
  - `showEvent` 入场 240ms `windowOpacity` 0→1 淡入；`_center_on_screen` 主屏居中。
  - 对外接口不变：`StartupCalibrationDialog(seconds)` → `step()` → `_refresh()` 全保留，`_countdown_step`/`finalize_calibration` 驱动逻辑零改动。导入相应补充（QEasingCurve/QPointF/QPropertyAnimation/QRectF、QBrush/QLinearGradient/QPen、render_glass_card/_font/SILVER_*/RED_SOFT）。
- Risk: 无边框窗失去原生标题栏/关闭按钮（弹窗本就倒计时结束自动关闭，无影响）；窗口标志由 `Qt.Dialog|Customize|Title|StayOnTop` 改为 `Qt.Dialog|Frameless|StayOnTop`；视觉为纯样式改动，不触碰校准状态机。
- Verification:
  - Command: `runtime\python311\python.exe -m py_compile tray_app.py`
  - Result: passed (exit 0)。
  - Command: 离屏冒烟（QT_QPA_PLATFORM=offscreen 构造对话框 + repaint + 连续 step()）
  - Result: passed；圆环定位 (422,60)、尺寸 580×248，倒计时 5→4→3→2→1→0 且归零时 `step()` 返回 True、`_CountdownRing` 数值随之更新；玻璃卡/ logo 衬底/圆环弧等矢量部分渲染正常（临时预览脚本已清理，不入库）。
- Gaps: 本机 offscreen 沙箱 Qt 字体子系统不可用（`QFontDatabase().families()` 直接令进程崩溃），所有 `drawText` 静默不出字，故无法在本环境截出带文字成品图——左侧三段文字与圆环内数字的实际排版需用户在真机/真实显示下目检。
- Conclusion: local only; 矢量布局与倒计时行为已验证，文字渲染待用户实机目检。

## 2026-07-11 - Security Policy and Dependency Update Automation

- Source: user request to add the highest-priority repository health and security files.
- Git: commit `pending`, branch `docs/security-maintenance`, tag `none`.
- Scope:
  - Added `SECURITY.md` with supported-version boundaries, a private reporting route, response targets, coordinated
    disclosure guidance, dependency triage expectations, privacy precautions, and safe-harbor language.
  - Added `.github/dependabot.yml` for weekly root-level `pip` and GitHub Actions version checks with bounded open pull
    request counts.
  - Enabled and verified repository settings for Dependabot alerts, Dependabot security updates, and private
    vulnerability reporting as part of the same maintenance task.
- Risk:
  - The response targets create ongoing maintainer expectations and must be revisited if maintainer capacity changes.
  - Dependabot pull requests can expose compatibility regressions in MediaPipe, OpenCV, PyQt, packaging, launcher, or
    native build paths; automated updates still require normal review and verification.
  - The existing HTTP Python package index configuration remains outside this file-addition task and is a follow-up
    supply-chain risk.
- Verification:
  - Command: `git diff --check`.
  - Result: passed (exit 0); no whitespace errors.
  - Command: line-length review for `SECURITY.md` and `.github/dependabot.yml`.
  - Result: passed; no line exceeded 120 characters.
  - Command: manual schema review against GitHub's official Dependabot options reference.
  - Result: passed; configuration uses version 2 with required ecosystem, directory, and schedule fields for root-level
    `pip` and `github-actions` manifests.
  - Command: local YAML parser checks through Python PyYAML and Ruby YAML.
  - Result: skipped; neither PyYAML nor Ruby is installed in the available environment. The configuration remains
    subject to GitHub's server-side processing after merge.
  - Command: GitHub REST API enablement and status checks for vulnerability alerts, automated security fixes, and
    private vulnerability reporting.
  - Result: passed; enablement calls returned HTTP 204, private vulnerability reporting returned `enabled: true`, and
    automated security fixes returned `enabled: true` with `paused: false`.
- Artifacts: documentation and repository configuration only; no release or binary artifacts.
- Gaps: Dependabot's first scheduled job and generated pull request cannot be verified before the configuration reaches
  the default branch.
- Conclusion: file-level validation passed; ready for remote pull-request verification.

## 2026-08-09 - Phase 1 Calibration Safety and Multi-user Debounce

- Source: user request to implement the first priority from `docs/plans/EchoPosture_vision_identity_upgrade_plan.md`.
- Git: implementation commit `329c537`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - `vision_test.py`: require a single person, both face and pose observations, and complete core posture metrics before automatic calibration; debounce multi-user state for 0.3 seconds.
  - `vision_worker.py`: reuse the shared calibration predicate, filter averaged samples, and reset the calibration window when a second person appears.
  - `test_feature_toggles.py`, `test_vision_worker.py`: add deterministic coverage for incomplete/multi-person calibration samples, calibration-window reset, and multi-user debounce.
  - Plan reference: `docs/plans/EchoPosture_vision_identity_upgrade_plan.md` was already present at the canonical path in the PR base (`origin/main`, commit `3691e8d`); no plan-file move is included in this PR.
- Risk: stricter calibration may reject short-lived partial camera observations and require the user to remain visible with complete face and pose metrics; multi-user status now waits 0.3 seconds before suppression.
- Verification:
  - Command: `runtime\\python311\\python.exe -m py_compile vision_test.py vision_worker.py test_feature_toggles.py test_vision_worker.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed, exit 0.
  - Command: `runtime\\python311\\python.exe test_feature_toggles.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; `ALL TESTS PASSED`, exit 0.
  - Command: `runtime\\python311\\python.exe test_vision_worker.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; `ALL TESTS PASSED`, exit 0.
  - Command: `runtime\\python311\\python.exe test_startup_guards.py` with `PYTHONDONTWRITEBYTECODE=1`.
  - Result: passed; 8 tests, exit 0.
  - Command: `git diff --check`.
  - Result: passed; only the repository's existing LF/CRLF conversion warnings were reported.
- Gaps: Ruff was not run because the `ruff` command is unavailable in the current environment; no real-camera or packaged Windows self-test was run; the PR and remote merge were not yet completed at log-entry creation time.
- Artifacts: no release or binary artifacts.
- Conclusion: local implementation validated for logic tests; ready for PR review after commit and push.

## 2026-08-09 - PR22 AI Review Follow-up

- Source: GitHub Actions AI review comment `5231950418` on PR #22.
- Git: implementation commit `30906d6`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - Clear the multi-user debounce anchor when presence checking is disabled, preventing stale timestamps from bypassing the confirmation window after re-enabling the feature.
  - Derive averaged observation flags from eligible samples instead of force-stamping them.
  - Use `calibration_sample_is_complete` as the single canonical calibration predicate across `vision_test.py`, `vision_worker.py`, and `tray_app.py`.
  - Add regression coverage for an ineligible fallback and the presence-toggle debounce path.
  - Surface missing calibration conditions when no complete sample is available, so calibration failure is diagnosable from the tray message.
- Risk: the same-frame completeness invariant remains intentionally conservative; real-camera co-occurrence of face and pose metrics is still unverified and must be checked before merge.
- Verification:
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed, 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed, `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe -m py_compile tray_app.py vision_test.py vision_worker.py test_feature_toggles.py test_vision_worker.py`: passed.
- Gaps: Ruff remains unavailable in the environment; no real-camera or packaged Windows self-test was run.
- Artifacts: no release or binary artifacts.
- Conclusion: AI review findings addressed where confirmed; PR requires CI rerun and real-camera review of the conservative calibration condition.

## 2026-08-10 - Vision Plan Priority Handoff Register

- Source: user request to record the remaining 2.0 implementation priorities for handoff and later audit.
- Git: implementation commit `98bc4ba`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope: added an execution register to `docs/plans/EchoPosture_vision_identity_upgrade_plan.md` covering P1 review gates and the ordered P2-P8 work, with task IDs, dependencies, status definitions, and completion evidence.
- Current state: P1 remains in review in PR #22; P2 is the next executable priority after P1 approval and evidence completion. No P2-P8 implementation has started.
- Verification: `git diff --check` passed; no source or runtime behavior changed.
- Gaps: the register intentionally preserves the known real-camera, packaged self-test, licensing, and release-validation gates.

## 2026-08-10 - Phase 2 Evidence Assets and Architecture Decision

- Source: user instruction to begin P2 after the P1 implementation work.
- Git: local branch `codex/pr2-phase1-calibration-safety`; PR #22 was checked through the GitHub API and remains open and unmerged (`merged: false`, `state: open`).
- Scope:
  - Added `docs/decisions/ADR-0001-vision-modes-and-fallback.md` to freeze the three mode responsibilities, fallback order, safety semantics, and evidence gates.
  - Added `docs/vision-evidence/README.md`, empty `recording_manifest.csv`, and empty `deletion_log.csv` with consent, retention, deletion, and no-media-in-Git rules.
  - Added `docs/vision-evidence/metrics-baseline.md` with timing boundaries, P50/P95 metrics, scenario matrix, and initial performance gates.
  - Added `docs/vision-evidence/license-audit.md` with source-linked, field-separated audits for Ultralytics YOLO26 candidates, CVLFace AdaFace ViT, AdaFace IR101, and CAFace.
  - Linked the new evidence documents from `docs/README.md` and marked P2 `IN_PROGRESS` in the plan register.
- Verification:
  - Playwright extension session opened the official Ultralytics license page, CVLFace model/repository, AdaFace repository, and CAFace repository; observed source text and repository license metadata.
  - GitHub API returned repository license metadata: Ultralytics `AGPL-3.0`; CVLFace, AdaFace, and CAFace `MIT`.
  - No candidate weights were downloaded; exact weight license, revision, SHA-256, and training-data redistribution terms remain explicitly unverified.
- Gaps: no consented recordings or benchmark values exist yet; P1 remote merge, real-camera evidence, and packaged self-test remain open. P2 does not authorize model integration or P3-P8 implementation.
- Conclusion: P2 evidence framework and architecture decision are in progress; release-facing license approval is blocked until exact artifacts and data terms are audited.

## 2026-08-10 - Phase 3/4 Unified Backend and Target State Machine

- Source: user instruction to implement P3 and P4 together after the P2 evidence documents.
- Git: local branch `codex/pr2-phase1-calibration-safety`; no commit or remote push was requested in this turn.
- Scope:
  - Added `vision_backend.py` with `PersonObservation`, `Keypoint`, `VisionCapabilities`, `VisionBackend`, and `CompatibilityBackend`.
  - Added `vision_tracking.py` with deterministic bounding-box/velocity association, track lifecycle, calibration target lock, occlusion, away, reacquisition, identity-uncertain, multi-present, and target-ambiguous states.
  - Wired `TrayMonitor` and `VisionWorker` through the compatibility backend and target manager while preserving the existing synchronous packaged self-test path.
  - Extended immutable samples/snapshots with target state and track metadata; `MULTI_PRESENT` continues posture scoring when the target observation remains separate, while ambiguous face/body association is safety-suppressed.
  - Added target-specific `PostureFeatures` extraction so the analyzer consumes the locked target observation instead of an arbitrary frame-level sample from a multi-person backend.
  - Added localized labels for new target states and `test_vision_tracking.py` covering backend conversion, crossing, multi-person continuation, occlusion/reacquisition, no silent promotion, ambiguity, analyzer gating, and worker integration.
  - Added `vision_replay.py`, `test_vision_replay.py`, and the metrics-only `benchmark-synthetic-p3-p4.jsonl` replay matrix covering multi-person entry/exit, target departure/return, crossing, and away transitions.
  - Updated `docs/ARCHITECTURE.md` and the vision plan checklist/status for EP-VISION-010/011 and EP-TRACK-001 through EP-TRACK-005.
- Verification:
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py`: passed.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py`: passed.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all P3/P4 deterministic tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed.
  - `git diff --check`: passed; only the repository's existing LF/CRLF conversion warnings were reported.
- Gaps: no real-camera run, consented recording replay, packaged Windows self-test, or multi-person pose backend was executed in this environment. Compatibility mode intentionally emits `TARGET_AMBIGUOUS` when its single pose cannot be paired with one of multiple faces; full `MULTI_PRESENT` continuation requires a backend that emits separate person observations.
- Conclusion: P3/P4 implementation and deterministic integration are complete locally; hardware/replay/package evidence remains required before changing their priority status to release-complete.

## 2026-08-10 - Phase 3/4 Completion Audit Hardening

- Scope:
  - Added `PostureFeatures` and `PostureFeatureExtractor`; the worker now scores the locked target's observation, not a frame-level bystander sample.
  - Limited ambiguous-face suppression to ambiguous target association; a clear target remains scoreable while an ambiguous bystander is tracked separately.
  - Added one-second multi-person exit stabilization, timestamp-scaled velocity prediction, non-target pruning coverage, numeric timestamp support, and presence/identity toggle coverage.
  - Added the metrics-only JSONL replay CLI and synthetic 18-frame matrix; no camera frames or identity data are stored.
- Verification:
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 expected state frames.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; target-specific scoring, ambiguous bystander, exit stabilization, numeric timestamp, and all prior P3/P4 cases.
  - Ruff and startup guard checks passed after the hardening changes.
- Remaining external evidence is unchanged: real camera, consented recording replay, and packaged Windows self-test are not run in this environment.

## 2026-08-10 - P4 Cross-frame Association Hardening

- Source: deterministic regression exposed a silent target swap when two people crossed and the backend supplied no stable detection IDs.
- Scope:
  - `vision_tracking.py`: replaced observation-order greedy association with global one-to-one frame matching; motion prediction now carries more weight than stale-frame IoU, exact detection IDs remain authoritative, and near-tied geometry enters `TARGET_AMBIGUOUS`.
  - `test_vision_tracking.py`: added regression coverage for the no-ID crossing case and a symmetric geometry tie that must not silently switch the locked target.
- Verification:
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all tracking, worker integration, target-specific scoring, crossing, occlusion, and ambiguity tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 18 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed; `ALL TESTS PASSED`.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_replay.py vision_replay.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_replay.py vision_replay.py`: passed.
  - `git diff --check`: passed; only existing LF/CRLF conversion warnings were reported.
- Gaps: P2 evidence assets still have no consented recordings, measured camera baselines, or exact candidate-weight license/SHA-256 audit; real-camera, packaged self-test, and remote P1 merge remain unverified. P3/P4 therefore remain `IN_PROGRESS` in the plan register.
- Conclusion: deterministic association safety is hardened locally; this does not close the external P2/P4 evidence gates.

## 2026-08-10 - P3/P4 Local Implementation Completion Audit

- Source: user instruction to proceed with P3 and P4 together after the P2 architecture/evidence work.
- Scope:
  - P3: completed the model-independent observation/capability contract, compatibility MediaPipe adapter, target-specific posture feature extraction, and Worker integration while preserving the legacy sample path.
  - P4: completed target lock, global one-to-one association, velocity prediction, track lifecycle, multi-person continuation, occlusion/away/reacquisition states, face-body ambiguity handling, and no-silent-promotion safeguards.
  - Hardened compatibility association so a missing face anchor is ambiguous, and hardened calibration completeness so normalized target samples still reject `person_count != 1`, `MULTI_PRESENT`, and `TARGET_AMBIGUOUS` frames.
  - Extended `benchmark-synthetic-p3-p4.jsonl` to 24 metrics-only frames covering stable-ID crossing, no-ID crossing, geometry ties, multi-person entry/exit, target departure/return, and away transitions.
- Verification:
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; all P3/P4 state, association, target-specific scoring, and Worker integration tests.
  - `runtime\\python311\\python.exe vision_replay.py docs\\vision-evidence\\benchmark-synthetic-p3-p4.jsonl`: passed; 24 frames.
  - `runtime\\python311\\python.exe test_vision_replay.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_feature_toggles.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`, including target-manager presence calibration reset.
  - `runtime\\python311\\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\\python311\\python.exe test_tray_flyout.py`: passed; `ALL TESTS PASSED`.
  - `ruff check vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_worker.py test_vision_replay.py vision_replay.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile vision_backend.py vision_tracking.py vision_test.py vision_worker.py tray_app.py debug_ui.py i18n.py test_vision_tracking.py test_vision_worker.py test_vision_replay.py vision_replay.py`: passed.
  - `git diff --check`: passed; only existing LF/CRLF conversion warnings were reported.
- Remaining gates: real camera and consented recording replay, packaged Windows self-test, P1 remote merge, measured P2 baselines, and exact candidate-weight/data-license evidence remain unverified. The plan register therefore keeps P2/P3/P4 at `IN_PROGRESS` rather than release-complete.
- Conclusion: P3/P4 implementation and deterministic evidence are complete locally; external validation is still required before release sign-off.

## 2026-08-10 - Debug UI Target Panel Verification

- Source: user request to make the existing CMD test panel show the latest P2/P3/P4 changes in a directly verifiable page.
- Scope:
  - `debug_ui.py`: added an injectable backend factory for deterministic panel tests; the production path remains `CompatibilityBackend + TargetManager`.
  - `test_debug_ui.py`: added an offscreen, camera-free test using a fixed frame plus the real target manager and posture analyzer. It verifies `ACQUIRING`, calibration, `TARGET_LOCKED`, track `1`, and people count `1`.
  - `run_debug_ui.cmd`: keeps `--target-panel` enabled and forwards caller arguments such as `--camera 1`.
  - `docs/README.md` and `docs/TROUBLESHOOTING.md`: documented live-panel and camera-free verification commands, expected states, and evidence limits.
- Verification:
  - `runtime\python311\python.exe -m py_compile debug_ui.py vision_backend.py test_debug_ui.py`: passed.
  - `ruff check debug_ui.py vision_backend.py i18n.py test_debug_ui.py`: passed.
  - `runtime\python311\python.exe test_debug_ui.py`: passed; `ACQUIRING` -> `TARGET_LOCKED`, track `1`, people `1`.
  - `runtime\python311\python.exe test_vision_tracking.py`: passed; all tests.
  - `runtime\python311\python.exe test_vision_worker.py`: passed; all tests.
  - `runtime\python311\python.exe test_startup_guards.py`: passed; 8 tests.
  - `runtime\python311\python.exe vision_replay.py docs\vision-evidence\benchmark-synthetic-p3-p4.jsonl`: passed; 24 frames.
- Evidence limits: this validates panel wiring and state presentation without hardware. Real camera landmark quality, display behavior, and packaged self-test still need user-side execution.

## 2026-08-10 - P5 Model-independent identity verifier foundation

- Scope:
  - Added `identity_verifier.py` with the `IdentityVerifier` contract, three-state results (`IDENTITY_CONFIRMED`, `IDENTITY_UNCERTAIN`, `IDENTITY_MISMATCH`), quality scoring, normalized landmark alignment, configurable 8-20 frame aggregation, and debounced decisions.
  - Added asynchronous submit/request APIs with reacquisition and heartbeat trigger gates.
  - Kept raw frames, face crops, and temporary bystander vectors outside the data model; `clear_template()` and `close()` release the in-memory template, score window, and trigger state.
  - Added `test_identity_verifier.py` covering quality rejection, enrollment, aggregation, mismatch safety, async trigger throttling, and cleanup.
- Verification:
  - `runtime\\python311\\python.exe test_identity_verifier.py`: passed; `ALL TESTS PASSED`.
  - `ruff check identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_vision_worker.py`: passed; `ALL TESTS PASSED`.
  - `runtime\\python311\\python.exe test_vision_tracking.py`: passed; `ALL TESTS PASSED`.
- Remaining gates:
  - CVLFace AdaFace ViT-Base KP-RPE and AdaFace IR101 adapters are not integrated because exact weights, SHA-256, training-data terms, and distribution permissions remain blocked in `docs/vision-evidence/license-audit.md`.
  - No real-camera, consented-recording, false-accept/false-reject, or packaged privacy audit has been run.
- Conclusion: P5 model-independent foundation is implemented locally; P5 is not release-complete.

## 2026-08-10 - P5 pinned CVLFace adapters and offline cache preparation

- Scope:
  - Added `identity_model_adapters.py` with pinned CVLFace specs for ViT-Base KP-RPE/WebFace4M revision `6530d73fb0af4d1d8287f31d559780c648ebd22a` and IR101/WebFace4M revision `f2b38d9e24bfe301490d8dd081d8924b102333dd`.
  - Added `requirements-p5-models.txt` as a separate optional environment definition (`torch`, `torchvision`, `transformers`, `huggingface-hub`, `safetensors`, `Pillow`); the desktop runtime was not modified.
  - Added `tools/download_p5_models.ps1`, which downloads only the pinned files and writes a SHA-256 manifest outside Git.
- Official sources checked:
  - CVLFace model card quick start: `https://huggingface.co/minchul/cvlface_adaface_vit_base_kprpe_webface4m`.
  - CVLFace model download guidance: `https://github.com/mk-minchul/CVLface/blob/main/README_MODELS.md`.
- Verification:
  - `ruff check identity_model_adapters.py test_identity_model_adapters.py identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile identity_model_adapters.py test_identity_model_adapters.py identity_verifier.py test_identity_verifier.py vision_backend.py vision_worker.py`: passed.
  - `runtime\\python311\\python.exe test_identity_model_adapters.py`: passed; `ALL TESTS PASSED`.
  - Identity, Worker, and target-tracking tests all passed.
- Download status:
  - PowerShell direct download failed with `无法连接到远程服务器`.
  - Edge downloaded ViT `model.safetensors` (460344344 bytes, SHA-256 `3c6d37ea874c2f38ffc9a7f0e9247efc994c3fb5c12d044759ac294e19d127f7`) and IR101 `model.safetensors` (260980552 bytes, SHA-256 `21adb6220e8799a0e658f16946df9649c7269f432fe9810a7b9c4ad1241080a8`) into `D:\\Download\\EchoPosture-P5\\models`.
  - Edge downloaded ViT `pretrained_model/model.pt` (460381841 bytes, SHA-256 `b8d5adde0a00f6482b5e866b6e37eeaa947302a40d9af31c211af72f34d38afb`) and IR101 `pretrained_model/model.pt` (261111273 bytes, SHA-256 `7a3341c3afc507fd6f50345638d2f3ef2f0e931d5b4f5aba60e15709853fcf5e`).
  - Official CVLFace custom code, config, wrapper, and model YAML files were hydrated from the GitHub repository into both caches; `missing_model_files()` now returns empty tuples for both specs.
- Conclusion: both pinned model caches are locally complete for the adapter's core file gate; Torch/Transformers installation and actual model inference remain unverified, and no weight is licensed for distribution.

## 2026-08-10 - P5 isolated model environment

- Created `D:\\Download\\EchoPosture-P5\\venv` with `uv` and Python 3.11.9.
- Installed the optional model stack from `requirements-p5-models.txt`: Torch 2.1.2, torchvision 0.16.2, Transformers 4.33.0, huggingface-hub, safetensors, Pillow, OmegaConf, PyYAML, and their dependencies.
- The first local ViT load reached Transformers custom-code loading and exposed two issues: NumPy 2.x is incompatible with the Torch 2.1.2 wheel, and the local model directory must be temporarily added to `sys.path`. The adapter now handles the latter and the requirements pin `numpy<2` for the former.
- The follow-up NumPy install and smoke command were blocked by the execution approval service overload; no successful model inference result is claimed.
- `tools\\hydrate_p5_model_code.ps1` now pins CVLFace GitHub commit `308142aa50adf2e187711354f7524635d3414f1e`; rerunning that pinned refresh was also blocked by the same transient approval-service overload.
- Final `ruff check identity_model_adapters.py test_identity_model_adapters.py` and `git diff --check`: passed (only existing LF/CRLF conversion warnings remain).

## 2026-08-10 - P5 repository-bundled weights and startup wiring

- Copied the complete pinned ViT-KP-RPE and IR101 CVLFace model directories,
  including custom model code and configuration, into `models/p5/`.
- Added `.gitattributes` rules so `.safetensors` and `.pt` files use Git LFS.
- Changed `identity_model_adapters.default_model_root()` to prefer the
  repository-bundled `models/p5/` path; the D-drive cache remains a fallback.
- Updated `TrayMonitor` to load the bundled ViT adapter during normal startup,
  create an `IdentityVerifier`, inject it into `VisionWorker`, and release both
  verifier and model on shutdown. Missing dependencies or a damaged cache
  disable only the identity gate and leave posture monitoring running.
- No-camera inference smoke test and license/distribution approval remain open.
- The smoke test reached the bundled CVLFace custom code and exposed a missing
  `timm` dependency; `requirements-p5-models.txt` now pins `timm==0.9.12`, but
  installation timed out before a second load attempt.

## 2026-08-11 - Posture science core refactor v1

- Source: user-approved posture science refactor plan; implementation of the accepted ADR-0002 decision.
- Git: commit `pending`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope: added `posture_science.py` and metrics-only `tools/collect_posture_reliability.py`; extended
  `VisionSample`, `PostureFeatures`, `Keypoint`, target motion/activity output, and `PostureDecision`; switched the
  production tray analyzer and both startup/manual recalibration flows to a two-anchor profile; the original timing
  interpretation was later corrected in the 2026-08-12 entry below; retained `set_baseline_from_sample()` only for
  explicit legacy debug/self-test; updated tray intervention,
  i18n, debug metrics, README/docs, ADR-0002, replay, and focused tests.
- Product policy: watch enter/exit `0.50/0.40`, alert enter/exit `0.70/0.55`, severe deviation `0.85`, equivalent
  exposure `12s/30s`, confirmation `3s`, cooldown `60s`. These values are interaction policy parameters, not medical
  or physiological standards.
- Data boundary: runtime monitoring does not save frames, video, face crops, identity templates, or vectors. The
  reliability command writes a numeric JSON report only when `--output` is explicitly supplied.
- Recovery: created `_backups/posture-science-v1-preedit-20260811-170304/` before edits; the worktree already contained
  unrelated identity/model and documentation changes, which were preserved.
- Verification passed:
  - `runtime\\python311\\python.exe -m py_compile posture_science.py vision_test.py vision_backend.py vision_tracking.py vision_worker.py tray_app.py debug_ui.py i18n.py`
  - `runtime\\python311\\python.exe test_posture_science.py`
  - `runtime\\python311\\python.exe test_feature_toggles.py`
  - `runtime\\python311\\python.exe test_vision_worker.py`
  - `runtime\\python311\\python.exe test_vision_tracking.py`
  - `runtime\\python311\\python.exe test_vision_replay.py`
  - `runtime\\python311\\python.exe test_startup_guards.py`
  - `runtime\\python311\\python.exe test_debug_ui.py` (offscreen; Qt emitted existing missing-font-directory warnings)
  - `runtime\\python311\\python.exe tools\\collect_posture_reliability.py --help`
- Additional verification passed: `ruff check .`; `git diff --check` (only existing LF/CRLF conversion warnings).
- Not run: real camera reliability collection, `--output` report generation, SEM/MDC cross-device repeatability,
  external clinical validity, user comfort feedback, package build, and GUI/manual overlay observation.
- Conclusion: local implementation ready for static verification; real-camera and external-validity evidence remain open.

## 2026-08-12 - Debug UI full two-anchor calibration

- Source: user report that the diagnostic UI exposed only the legacy single-frame calibration after the production
  path had moved to the two-anchor posture model.
- Git: core behavior commit `bac3c33`, UI/docs in this commit, branch
  `codex/pr2-phase1-calibration-safety`, tag `none`.
- Scope:
  - Made the Debug UI primary calibration action run the production-equivalent explicit phase flow: a full visible
    five-second preferred-posture stage, an approximately one-second ignored transition, then a silent approximately
    five-second relaxed-posture stage with at most two seconds of bounded extension.
  - Reused `CalibrationPlan`, `CalibrationAccumulator`, `calibration_rejection_reason()`,
    `calibration_measurement_values()`, and `HighPrecisionPostureAnalyzer.set_calibration_profile()` so stage counts,
    quality gates, MDC feature disabling, and failure semantics match the production decision layer.
  - Added live preferred/relaxed sample counts, rejection details, cancellation, failure, and successful profile
    summary in both Chinese and English.
  - Preserved the legacy single-frame path as a visually secondary, explicitly labelled comparison button. The fast
    packaged `debug_ui.py --self-test` contract still uses that explicit legacy comparison and reports its mode.
  - Extended the offscreen Debug UI test to cover a complete 5+5-sample profile and the separate legacy path.
- Evidence boundary: deterministic UI tests use timestamped numeric samples and do not prove real-camera repeatability
  or cross-device SEM/MDC. Those external evidence gates remain open.

## 2026-08-12 - Correct dual-anchor production timing

- Source: user-reported severe production bug. The initial implementation incorrectly split the existing visible
  five-second countdown into 2 seconds preferred plus 3 seconds relaxed, even though the user had not yet been told to
  relax. This shortened both anchors and caused frequent valid-sample failures.
- Root-cause fix:
  - Kept the visible countdown at five seconds and assigned every sample in it only to the preferred anchor.
  - Added an explicit preferred/transition/relaxed state machine. The countdown closes before the tray says the user
    may relax; transition samples are ignored for about one second and cannot count or reset either anchor.
  - Added a silent approximately five-second relaxed window. If it has fewer than five valid samples at the nominal
    target, collection may extend by at most two seconds before reporting failure.
  - Routed startup calibration, manual recalibration, and the Debug UI primary calibration through the same phase
    semantics. The labelled legacy single-frame Debug UI and self-test paths remain separate.
- Policy boundary: 5-second preferred, about 1-second transition, about 5-second relaxed, and 2-second maximum
  extension are adjustable product interaction timings, not medical or physiological standards.
- Evidence boundary: deterministic tests verify phase ownership, ignored transition samples, bounded extension,
  timeout failure, dialog-before-relax ordering, and legacy separation. Real-camera timing and repeatability remain an
  independent evidence gate.

## 2026-08-12 - Fix calibration quality dropout amplification

- Source: user reported production calibration still failed with both `preferred_samples` and `pose_quality_low` even
  during the full five-second preferred stage.
- Root cause:
  - Every rejected frame cleared all previously accepted samples in the active anchor, so one transient quality or
    motion dropout near the end converted an otherwise valid five-second window into a sample shortage.
  - Aggregate `pose_quality` used the minimum visibility across shoulders and hips. A partly cropped or lower-quality
    hip therefore rejected otherwise reliable face/shoulder evidence, despite hip-dependent features being optional.
  - The calibration layer added an unvalidated `0.65` pose cutoff above the backend's own `0.50` usable-landmark
    threshold, discarding otherwise measurable `0.50-0.64` shoulder observations before SEM/MDC could assess them.
- Fix:
  - Multiple-person and ambiguous-target observations still reset the active anchor because they can contaminate
    identity. Zero-person dropouts, low quality, motion, missing keypoints, and temporary uncertainty now abstain for
    one frame and are counted for audit without erasing accepted samples. Previously, `face_count == 0` was mistakenly
    grouped with multiple-person contamination and could still clear the full preferred window.
  - Aggregate pose quality now represents the required shoulder pair. Landmark-level gates remove hip-dependent torso
    features when hip visibility is low while retaining reliable face/shoulder, shoulder-asymmetry, and ear/shoulder
    evidence.
  - The calibration pose floor now matches the backend's `0.50` usability floor. Feature repeatability statistics and
    MDC, rather than an unsupported stricter whole-frame threshold, decide whether a feature has usable evidence.
- Evidence: deterministic regressions prove that four valid samples survive an intervening low-quality frame and reach
  five on the next valid frame, and that `0.55/0.58` hip visibility does not reject high-confidence shoulder evidence.
- Remaining evidence gate: a real-camera production calibration must still be rerun to confirm the observed hardware
  no longer fails; deterministic tests do not establish the user's live camera result.

## 2026-08-12 - Prevent relaxed-anchor startup exposure and noise amplification

- Source: user observed that the Debug UI did not clearly distinguish the two anchor stages and that monitoring entered
  `WATCH` immediately after calibration even though the ending posture had not changed.
- Deterministic root cause:
  - The calibration necessarily ended at the relaxed anchor, which is defined as deviation `1.0`; monitoring began on
    the next frame, so holding the expected ending posture immediately opened WATCH and accumulated exposure.
  - Runtime scoring used SEM-derived MDC as if it were the complete single-frame noise band. Because SEM shrinks with
    sample count, a marginal anchor span could leave a near-zero denominator and amplify ordinary frame jitter.
- Fix:
  - Added a post-calibration preferred-posture re-entry gate. The relaxed ending posture and all re-entry frames pause
    exposure; monitoring activates only after the preferred range is held for about two stable seconds.
  - Runtime tolerance now uses the larger of MDC and `1.96 ×` within-anchor standard deviation. Anchor features that do
    not clear this single-observation repeatability floor with a minimum signal margin are disabled before group
    scoring.
  - Added a high-contrast Debug UI stage card: green preferred, orange transition, purple silent relaxed, blue re-entry,
    plus distinct active and failed states. The card now sits directly above the camera area at the same width, rather
    than being buried in the metrics panel. The legacy single-frame control remains separately labelled.
- Policy boundary: the `1.96` repeatability multiplier, minimum signal margin, and two-second re-entry stability are
  adjustable product parameters, not medical or physiological standards.
- Evidence:
  - Deterministic regressions cover 60 seconds at the relaxed ending posture with zero exposure, preferred re-entry
    activation, preferred-range runtime jitter, rejection of an all-noise near-identical anchor profile, marginal
    feature disabling, and distinct Debug UI states.
  - A separate long-hold regression activates monitoring after preferred re-entry, then holds the preferred posture for
    five minutes; every decision remains `GOOD`, `posture_deviation` remains `0`, and exposure remains `0`.
  - The offscreen Qt geometry check at a 1020 x 700 Debug UI reports a 678 x 86 stage card above a 678 x 576 camera
    area, with equal widths and no overlap. Offscreen preferred/relaxed screenshots confirmed the green/purple stage
    styling, camera placement, and control hierarchy. Qt emitted its existing bundled-runtime missing-font-directory
    warning and rendered system UI text blank in those screenshots, so they are not treated as Chinese text or font
    fidelity evidence.
- Verification passed from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe -m py_compile posture_science.py vision_test.py vision_worker.py tray_app.py debug_ui.py tools\collect_posture_reliability.py test_posture_science.py test_feature_toggles.py test_vision_worker.py test_vision_tracking.py test_startup_guards.py test_debug_ui.py test_vision_replay.py`
  - `ruff check .`
  - `runtime\python311\python.exe test_posture_science.py`
  - `runtime\python311\python.exe test_feature_toggles.py`
  - `runtime\python311\python.exe test_vision_worker.py`
  - `runtime\python311\python.exe test_vision_tracking.py`
  - `runtime\python311\python.exe test_startup_guards.py`
  - `runtime\python311\python.exe test_debug_ui.py`
  - `runtime\python311\python.exe test_vision_replay.py`
  - `git diff --check`
- Verification note: `runtime\python311\python.exe -m ruff check .` was unavailable because the bundled interpreter
  does not include the `ruff` module; the repository's installed `ruff check .` executable passed instead.
- Backup: before staging, `git stash create` captured all 18 tracked modifications at object
  `388fd230704151915bcc5a057d12a587e5d95859` from source HEAD
  `9ad26519e9ed5d0f049696652d15f0cb3bd71d78`; no untracked local artifacts were included.
- Gaps: a real-camera production calibration must still be rerun under the user's camera, framing, lighting, normal
  movement, and lens-drift conditions. No live-camera pass, successful screenshot-based text/font review, consented
  recording, or external-validity result is claimed.

## 2026-08-12 - Harden runtime posture evidence and debug calibration cues

- Source: continued investigation after the user reported calibration failures and unclear dual-anchor stage changes;
  manual follow-up to the incomplete PR review.
- Git: runtime commit `dcbcf20`, Debug UI commit `eedadfe`, branch
  `codex/pr2-phase1-calibration-safety`, existing PR `#23`, tag `none`.
- Runtime root causes and fixes:
  - Production scoring called unfiltered `measurement_values()`, so a hip pair at confidence `0.20` could still let a
    noisy `torso_shoulder_ratio` drive `WATCH`, `BAD`, and `CRITICAL` while aggregate shoulder quality remained `0.95`.
    Runtime extraction now applies the same feature-local shoulder/hip/ear gates as calibration, and decision
    confidence is computed only from the features that actually reached scoring. Low-quality hip-dependent evidence
    now abstains and cannot accumulate exposure.
  - A normalized anchor span of `0.020` with a `0.015` runtime noise floor left only a `0.005` scoring denominator.
    The product reliability margin now requires anchor separation of at least `2.0` runtime-noise bands; narrower
    features are disabled instead of amplifying frame jitter.
  - `ExposureAccumulator` previously integrated throughout WATCH hysteresis, so deviation `0.60` could preload minutes
    of exposure below the `0.70` alert threshold. Integration now occurs only while alert hysteresis is active; WATCH
    remains an observation state and recovery still decays existing exposure exponentially.
- Debug UI behavior:
  - The full production-equivalent dual-anchor control remains the primary action; the legacy single-frame comparison
    remains secondary and explicitly labelled.
  - The stage area is now a 136px-or-taller full-color card with localized `1/2`, relax, `2/2`, return, active, and retry
    badges plus a stable progress bar. When the preferred five-second stage ends, a high-contrast one-second prompt is
    overlaid in the center of the camera area before silent relaxed sampling starts.
- Verification passed from `C:\Users\aaabb\Documents\ICC驼背项目`:
  - `runtime\python311\python.exe -m py_compile posture_science.py vision_test.py debug_ui.py i18n.py tools\collect_posture_reliability.py test_posture_science.py test_feature_toggles.py test_debug_ui.py test_vision_replay.py`
  - `ruff check .`
  - All tracked root logic scripts: `test_posture_science.py`, `test_feature_toggles.py`, `test_vision_worker.py`,
    `test_vision_tracking.py`, `test_startup_guards.py`, `test_debug_ui.py`, `test_vision_replay.py`,
    `test_tray_flyout.py`, `test_identity_model_adapters.py`, `test_identity_verifier.py`,
    `test_ai_pr_review_guards.py`, and `test_ai_maintainer_manual_flows.py`.
  - `runtime\python311\python.exe tools\collect_posture_reliability.py --help`.
  - `git diff --check` passed with only the repository's existing LF/CRLF conversion warnings.
  - Offscreen Qt validation at `1020 x 700`: stage card `678 x 141`, camera `678 x 521`, centered prompt
    `598 x 150` fully inside the camera area, phase badge `放松`, progress `50`, and nonblank window render.
- Verification note: the bundled Qt runtime continues to report its existing missing-font-directory warning. The
  deterministic tests verify localized strings and geometry, but do not establish packaged font rendering fidelity.
- Backup: `git stash create` captured all tracked changes at object
  `84dac123f71cce8bf3d8eeb6767251af4c65c300`; untracked models, review folders, posters, and local artifacts were not
  included or staged.
- Gaps: real-camera calibration, cross-device SEM/MDC, user-visible packaged UI, consented recording, and external
  validity remain independent evidence gates. No medical or hardware-level validation is claimed.
- Conclusion: runtime false-exposure paths and Debug UI stage visibility are covered by deterministic regression tests;
  ready for delivery to the existing PR branch.

## 2026-08-11 - AI review findings routed into the vision plan

- Source: user request after manual audit of the AI review posted on PR #23.
- Git: plan commit `5e8953626609ed4ea50ec4cfc1fbad2f5cecc0a6`, branch `codex/pr2-phase1-calibration-safety`, tag `none`.
- Facts corrected:
  - PR #23 changes `.gitattributes`, model adapter code, and local download/hydration tooling, but its 42 changed files and remote head tree contain no tracked `models/p5/` weight files.
  - The earlier "repository-bundled weights" entry described a local, untracked worktree copy. It did not establish that weights were committed, uploaded, or distributed through the PR.
  - Exact weight and training-data license approval remains a future integration/release gate; it is not evidence that this PR currently redistributes weights.
- Scope:
  - Added `EP-TRACK-006` to bound global association work and require a safe ambiguity fallback plus adversarial-count latency evidence before a real multi-person backend is connected.
  - Added `EP-ID-008` so disabling identity verification prevents model loading, verifier injection, verification requests, and embedding processing, then clears in-memory state.
  - Linked `EP-UI-002` to the runtime gate and updated the P4/P5 priority register and completion evidence.
- Risk: this change records follow-up work only; the current recursive matcher and identity runtime behavior are not fixed by this documentation commit.
- Verification:
  - `git diff --check`: passed.
  - Targeted `rg` review confirmed `EP-TRACK-006` and `EP-ID-008` appear in their phase lists, priority rows, and handoff status text.
  - GitHub API confirmed PR #23 remote head `bcd4bfb17d39916055439462a89058fd1f725307`; changed files matching `models/p5/*`: `0`; head-tree paths matching `models/p5/*`: `0`.
  - Pushed plan commit `5e8953626609ed4ea50ec4cfc1fbad2f5cecc0a6` to the PR branch; GitHub then reported the same SHA as PR #23 head and still reported `0` changed files matching `models/p5/*`.
  - Posted the corrective `@ai-review` request at `https://github.com/NOVVLA/EchoPosture/pull/23#issuecomment-5255309355`.
  - AI review run `31507828605` completed successfully, but the model output failed JSON parsing and the workflow safely downgraded to a confidence-0 comment at `https://github.com/NOVVLA/EchoPosture/pull/23#issuecomment-5255324440`; it did not issue a substantive corrected review.
- Gaps: implementation, unit tests, real-camera behavior, latency measurements, privacy audit, and license approval remain open under the new and existing plan tasks.
- Conclusion: plan update and corrective comment delivered; the AI route executed safely but did not produce a substantive correction, so the earlier `CHANGES_REQUESTED` review remains for manual handling.

## 2026-08-11 - AI PR Review Timeout Recovery

- Source: repeated GitHub Actions failures in `ai-pr-review` runs #69 and #70; both ended with an uncaught `TimeoutError` after the 60-second client deadline.
- Git: implementation commit `97c34a1`, branch `fix/ai-review-timeout-recovery`, tag `none`.
- Scope:
  - `.github/ai-flows/common_ai_client.py`: classify socket/read timeouts as `AIClientTimeoutError`, keeping them inside the existing safe AI error contract.
  - `.github/ai-flows/pr_review.py`: use a configurable `AI_PR_REVIEW_TIMEOUT_SECONDS` value with a 300-second default for primary and secondary review calls, while tolerating invalid or non-positive configuration.
  - `.github/workflows/ai-pr-review.yml`: expose the timeout override through the repository variable `AI_PR_REVIEW_TIMEOUT_SECONDS`.
  - `.github/workflows/quality-gate.yml`, `test_ai_client_timeout.py`: run lint, compile, and regression checks for the shared client and timeout fallback.
- Risk: a longer request deadline can keep the review job waiting longer, but remains below the workflow's 20-minute job limit and leaves room for a slow non-streaming response such as the observed 73 seconds; timeout failures now produce an auditable safe comment/label instead of crashing the job.
- Verification:
  - `runtime\\python311\\python.exe test_ai_client_timeout.py`: passed on Python 3.11.9; timeout wrapping, the 300-second PR review default, and safe fallback all passed.
  - `runtime\\python311\\python.exe test_ai_pr_review_guards.py`: passed.
  - `runtime\\python311\\python.exe test_ai_maintainer_manual_flows.py`: passed.
  - `runtime\\python311\\python.exe -m py_compile .github/ai-flows/common_ai_client.py .github/ai-flows/pr_review.py test_ai_client_timeout.py`: passed.
  - `ruff check .github/ai-flows/common_ai_client.py .github/ai-flows/pr_review.py test_ai_client_timeout.py`: passed.
  - `git diff --check`: passed; only existing LF-to-CRLF checkout warnings were emitted.
- Gaps: no local provider credentials are available, so a real AI response and post-fix GitHub run require remote verification after publication. `actionlint`, PyYAML, and Ruby YAML were unavailable locally, so workflow YAML parsing is deferred to GitHub Actions.
- Artifacts: no release or binary artifacts.
- Conclusion: local regression validation passed; ready for remote branch CI and pull-request review.
