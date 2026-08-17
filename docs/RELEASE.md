# EchoPosture Release Guide

This is the maintained procedure for publishing a Windows x64 GA or TEAM_ALPHA build. It complements, and does not
replace, [ROE](../ROE.md), [Process Audit](../PROCESS_AUDIT.md), and the
[Remote Upload Rules](<../上传必读(英文版).md>).

The important distinction is:

- `build_launcher.cmd` builds the three Windows executables in the repository root;
- release packaging is a separate allowlist-based assembly step that adds application modules and the embedded
  Python runtime;
- publishing is complete only after the local ZIP, GitHub asset, tag, release metadata, public README, and audit log
  agree.

## Release Naming

| Channel | Version label | Tag | Package and asset |
| --- | --- | --- | --- |
| GA | `GA-X.Y.Z` | `ga-X.Y.Z` | `EchoPosture-GA-X.Y.Z-win-x64` / `.zip` |
| TEAM_ALPHA | `TEAM_ALPHA-<timestamp>` | `team-alpha-<timestamp>` | `EchoPosture-TEAM_ALPHA-<timestamp>-win-x64` / `.zip` |

Do not use the retired `DEV` naming for new builds. A GA ASCII bridge is version-specific, for example GA-1.2.1 uses
`%LOCALAPPDATA%\EchoPostureGA121`. Choose the next bridge label deliberately and use it consistently in launcher code
and package documentation.

## Required Environment

- Windows x64.
- Git and GitHub CLI authenticated for `NOVVLA/EchoPosture`.
- Python 3.11 dependencies from `requirements.txt` and `requirements-dev.txt` for source validation.
- A complete embedded runtime at `runtime/python311`; this directory is local-only and not in Git.
- Visual Studio C++ Build Tools with the x64 toolchain. `build_blur_overlay_host.cmd` discovers it through `vswhere.exe`.
- .NET Framework C# compiler at the standard 32-bit or 64-bit Framework path.
- Permission to create the versioned bridge under `%LOCALAPPDATA%` for the packaged self-test.
- A reviewed `AGPL-3.0-only` source-delivery plan for the exact release commit, including any network-interaction
  source offer required by section 13.

If any required environment component is missing, stop before tagging or publishing. A successful C# build alone does
not prove that the native host or portable runtime is complete.

## 1. Establish the Release Baseline

Run from the repository root:

```powershell
$Version = "X.Y.Z"                 # Replace before running release commands.
$ReleaseSourceSha = "40-char-sha"  # Set after the versioned source commit is created.
$Tag = "ga-$Version"
$Package = "dist\EchoPosture-GA-$Version-win-x64"
$Zip = "$Package.zip"

git status --short --branch
git remote -v
git fetch origin main
git rev-list --left-right --count origin/main...main
gh repo view NOVVLA/EchoPosture --json nameWithOwner,defaultBranchRef,visibility,isPrivate
```

Confirm all of the following:

- the intended source branch and commit are known;
- tracked changes are understood and release-related;
- `origin` is `https://github.com/NOVVLA/EchoPosture.git`;
- the repository is public and `main` is the default branch;
- the local source is not accidentally behind or diverged from the intended remote baseline.

Do not stage ignored runtimes, packages, logs, backups, screenshots, review directories, or unrelated untracked files.

## 2. Prepare the Versioned Source

Update and review every current-version surface:

1. `launcher/EchoPostureLauncher.cs`
   - version-specific `%LOCALAPPDATA%\EchoPosture...` bridge;
   - self-test title.
2. `CHANGELOG.md`
   - user-visible changes and release-channel change.
3. `README_EXE.md`
   - current package and bridge description when those values change.
4. Package-local `GA_BUILD.txt` and `README_GA.md`
   - created in the staging directory later; never copied from an older release without review.
5. `README.md`
   - release URL, asset URL, and SHA256 are updated only after the final asset and checksum exist.

Search for stale labels before building:

```powershell
rg -n "GA-[0-9]+\.[0-9]+\.[0-9]+|ga-[0-9]+\.[0-9]+\.[0-9]+|EchoPostureGA[0-9]+" `
  README.md README_EXE.md CHANGELOG.md launcher/EchoPostureLauncher.cs
```

Record the preparation and planned verification in `DEVELOPMENT_LOG.md`. Commit and push the versioned source with a
specific subject such as `Prepare GA-X.Y.Z release`. The release tag must target this reviewed source commit.

## 3. Validate Source and Build

Install dependencies when the environment is not already prepared:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the CI-equivalent checks:

```powershell
ruff check debug_ui.py gpu_blur_overlay.py onboarding_toast.py overlay_test.py posture_console.py posture_science.py `
  test_startup_guards.py test_tray_flyout.py test_vision_worker.py tray_app.py tray_flyout.py `
  test_posture_science.py vision_test.py vision_worker.py

python -m py_compile debug_ui.py gpu_blur_overlay.py onboarding_toast.py overlay_test.py posture_console.py posture_science.py `
  test_startup_guards.py test_tray_flyout.py test_vision_worker.py tray_app.py tray_flyout.py `
  test_posture_science.py vision_test.py vision_worker.py

python test_posture_science.py
python test_startup_guards.py
python test_tray_flyout.py
python test_vision_worker.py
python test_feature_toggles.py
```

Then build all Windows executables:

```powershell
.\build_launcher.cmd
```

Expected root outputs are `BlurOverlayHost.exe`, `EchoPosture.exe`, and `EchoPostureSelfTest.exe`. Confirm that the
command exits successfully and that all three files have fresh timestamps. Do not treat old binaries left in the root
as evidence of a successful build.

## 4. Assemble from an Allowlist

Create a new, empty staging directory under `dist`. Never copy the repository wholesale and then try to delete unsafe
content.

### 4a. GA-2.0 source-only channel

GA-2.0 is a **source-only** release. It is not a portable package: it contains no embedded runtime, no built
executables, and no model weights. This is a licensing decision, not a packaging regression — see
[ADR-0004](decisions/ADR-0004-ga-2-0-source-only-distribution.md).

The GA-2.0 allowlist is the tracked source tree plus the model-fetch tooling:

```text
*.py application modules (excluding test_*.py)
tools/fetch_pose_models/
docs/  CHANGELOG.md  CONTRIBUTING.md  SECURITY.md  README.md
LICENSE  NOTICE  THIRD_PARTY_NOTICES.md
GA_BUILD.txt  README_GA.md
logo.png
```

`tools/fetch_pose_models/` holds four scripts: `fetch_pose_models.ps1` and `fetch_pose_models_mirror.ps1` (English, the
canonical release scripts) plus `fetch_pose_models_zh.ps1` and `fetch_pose_models_mirror_zh.ps1` (Chinese
localizations with identical behavior — same catalog, same hashes, same Y/N confirmation, same face-model notice,
translated text only).

`README_GA.md` for this channel must state, in English, near the top and before any install instructions:

- the package contains **no model weights** and is **not a portable package**;
- a portable build is not offered for legal reasons;
- Compatibility mode works without any download;
- Standard mode and Professional Beta mode **require** running one of the scripts in `tools\fetch_pose_models\` first
  (official source or mirror, English or Chinese — all four install the identical, identically verified weights);
- the fetched weights are Ultralytics AGPL-3.0 artifacts governed by their own terms;
- how to obtain the complete corresponding source for that exact build under GNU AGPLv3.

The GA-2.0 package must not contain:

```text
.git/  .github/  .codex/  .agents/  .claude/  logs/  _backups/  dist/  runtime/
review folders  test_*.py  *.obj  *.pdb  *.exe  credentials  API keys
personal screenshots  local absolute paths  internal process documents
models/  any model weight  training data
```

Verify before compressing:

```powershell
Get-ChildItem -Recurse $Package -Include *.pt,*.safetensors,*.onnx,*.tflite | Should -BeNullOrEmpty
```

Any hit is a release blocker.

### 4b. Portable channel — semi-portable, weights excluded (published from GA-2.0.0 onward)

As of [ADR-0005](decisions/ADR-0005-ga-2-0-portable-standard-professional.md), the portable channel is published
alongside the §4a source-only package, under the **same** release tag. It bundles the embedded runtime and built
executables so the user does not need Python or a compiler, but it still contains **no model weights** — the user
still runs one of the four `tools/fetch_pose_models/` scripts after installing it, exactly as with the source-only
package. Compatibility mode needs no download either way.

The portable-channel allowlist is:

```text
BlurOverlayHost.exe
EchoPosture.exe
EchoPostureSelfTest.exe
*.py application modules (excluding test_*.py) — including standard_pose_backend.py
  and professional_pose_backend.py now that ADR-0005 has approved them for this channel
tools/fetch_pose_models/
docs/  NOTICE  THIRD_PARTY_NOTICES.md
logo.png
LICENSE
GA_BUILD.txt
README_GA.md
runtime/
```

`runtime/` must contain the tested embedded CPython 3.11 runtime, PyQt5, OpenCV, MediaPipe, Ultralytics, and — for
Professional Beta — CUDA `torch`/`torchvision`, plus any other transitive modules needed by the application. A system
Python installation must not be required by the finished package.

`GA_BUILD.txt` must identify at least the release label, build date, exact source commit, platform, embedded Python
version, primary and diagnostic entries, and versioned bridge. Per ADR-0005, this exact source commit may be newer
than the commit the release tag targets when the delta is packaging/versioning-label corrections only (e.g. the
launcher bridge label); it must never silently diverge in application behavior from the tagged source. `README_GA.md`
must state how to start the app, run the self-test, find its log, interpret SmartScreen, verify the ZIP checksum, that
no downloadable YOLO/CVLFace weights are bundled and how to fetch the YOLO weights via `tools/fetch_pose_models/`, and how to obtain the complete
corresponding source for that exact build under GNU AGPLv3.

The package must not contain user-downloadable model artifacts:

```text
.git/  .github/  .codex/  .agents/  .claude/  logs/  _backups/  dist/
review folders  build scripts  test_*.py  *.obj  *.pdb  credentials  API keys
personal screenshots  local absolute paths  internal process documents
*.pt  *.safetensors  *.onnx  training data  models/

MediaPipe `.tflite` files under its embedded runtime are allowed when required by Compatibility mode.
```

Third-party notices and files inside the embedded runtime are allowed when required by those dependencies.

The CVLFace P5 identity weights under `models/p5/` are **blocked from every channel**. They are trained on WebFace4M,
whose terms restrict use to academic research and forbid redistribution; the model cards require downstream users to
follow that training-data license. No packaging step, notice file, or source offer cures this. Do not add a fetch
script for them either — this project does not help users obtain weights it cannot itself redistribute.

## 5. Test the Staged Package

Run the diagnostic from inside the new package, outside a restrictive sandbox so the launcher can create its
LocalAppData bridge:

```powershell
& "$Package\EchoPostureSelfTest.exe"
```

Review `$Package\logs\self-test-latest.txt`. It contains four stages:

1. native GPU blur host;
2. offscreen debug UI;
3. one-frame vision path;
4. tray startup calibration and evaluation.

A normal release candidate should have exit code `0` for every stage, `startup_calibrated=True`, and `baseline=True`.
Camera and calibration checks are environment-sensitive, but a failure must be recorded as a failure or explicit gap;
it must not be rewritten as a pass. After reviewing the report, remove the generated package `logs` directory before
creating the public ZIP.

Also perform focused desktop checks when the release changes tray behavior, localization, camera handling, or overlay
behavior. At minimum verify that Stop clears the overlay and exits, and use `Ctrl+Alt+Shift+E` to confirm the native
emergency clear path when the native host changed.

## 6. Audit and Create the ZIP

Before compression, recursively inspect the staging tree and search text-bearing files for local usernames, workspace
paths, secret names, tokens, or old version labels. Confirm the allowlist and forbidden-entry counts in the development
log.

Create the ZIP and hash it:

```powershell
Compress-Archive -LiteralPath $Package -DestinationPath $Zip
Get-FileHash -Algorithm SHA256 -LiteralPath $Zip
```

Open or list the ZIP after creation; do not assume the staging-directory audit proves the archive layout. The archive
must expand to one top-level package folder, not scatter files into the extraction directory.

Record the final file size and SHA256. Use that exact lowercase or uppercase digest consistently in `README.md`, release
notes, and `DEVELOPMENT_LOG.md`.

## 7. Tag and Publish

Create an annotated tag on the reviewed release source commit and push it:

```powershell
git tag -a $Tag $ReleaseSourceSha -m "EchoPosture GA-$Version"
git push origin $Tag
```

Create the GitHub release with the final ZIP. Prefer a reviewed release-notes file so the published body is auditable:

```powershell
$ReleaseNotes = "path\to\reviewed-release-notes.md"
gh release create $Tag $Zip `
  --repo NOVVLA/EchoPosture `
  --verify-tag `
  --title "EchoPosture GA-$Version" `
  --notes-file $ReleaseNotes
```

For TEAM_ALPHA, use the TEAM_ALPHA naming convention and pass `--prerelease`.

## 8. Post-Publication Verification

Query the live release rather than relying on upload output:

```powershell
gh release view $Tag --repo NOVVLA/EchoPosture `
  --json tagName,name,isDraft,isPrerelease,url,targetCommitish,assets,publishedAt
gh repo view NOVVLA/EchoPosture --json visibility,isPrivate,defaultBranchRef
git ls-remote origin "refs/tags/$Tag"
```

Confirm:

- tag name and tag target;
- release title, draft state, and prerelease state;
- exact asset name, uploaded state, byte size, and SHA256 digest;
- local ZIP SHA256 equals the GitHub asset digest;
- repository remains public;
- public README links resolve to this release and asset.

Update `README.md` with the new URLs and digest, complete the release evidence in `DEVELOPMENT_LOG.md`, review the diff,
then commit and push that post-release documentation. This second commit does not change the already tagged source; it
records the immutable artifact that was produced from it.

## Failed Release or Replacement

- Before publication: discard the candidate staging directory, fix the source or packaging process, rebuild, and rerun
  all affected checks. Do not reuse an ambiguous ZIP.
- Wrong or unsafe uploaded asset: remove or replace the asset only with explicit authorization, update release notes,
  recompute and publish the digest, and record the incident. Never silently replace an asset.
- Wrong source after publication: publish a corrected release or follow an explicitly approved rollback plan. Do not
  move an existing public tag to hide the error.
- Source rollback: prefer `git revert` and repeat all package and remote verification required by ROE.

Release completion means the source, package, checksum, tag, GitHub metadata, public README, and audit record all tell
the same verifiable story.
