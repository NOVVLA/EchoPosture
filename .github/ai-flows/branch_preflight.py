# -*- coding: utf-8 -*-
"""Read-only AI branch preflight for EchoPosture changes."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
from typing import Any

from common_ai_client import AIClientAccessBlockedError, AIClientError, chat_completion_raw
from github_ops import emit_result, env_flag, load_prompt, write_step_summary
from json_guard import guard_result, safe_fallback


FLOW_DIR = pathlib.Path(__file__).resolve().parent
REPOSITORY_ROOT = FLOW_DIR.parent.parent
MAX_CHANGED_FILES = 250
MAX_COMMIT_SUBJECTS = 30
MAX_POLICY_CHARS = 16000
GENERATED_PREFIXES = ("runtime/", "dist/", "logs/", "_backups/", ".downloads/", ".uv-cache/")
AUDIT_PATHS = (
    "launcher/",
    "native/",
    "tray_app.py",
    "vision_test.py",
    "posture_console.py",
    "ui/index.html",
    "docs/release.md",
    "changelog.md",
)
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".jks", ".keystore")


class FlowError(RuntimeError):
    """Raised when the requested Git baseline cannot be inspected."""


def read_json_file(path: str) -> dict[str, Any]:
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        raise FlowError(f"Could not read mock context: {path}") from None
    if not isinstance(data, dict):
        raise FlowError("Mock context must be a JSON object.")
    return data


def run_git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise FlowError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def trim(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - 80] + "\n\n[Context truncated by ai-branch-preflight]"


def normalized_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./").lower()


def classify_changed_files(paths: list[str]) -> dict[str, list[str]]:
    generated: list[str] = []
    frozen: list[str] = []
    audit: list[str] = []
    sensitive: list[str] = []
    for path in paths:
        normalized = normalized_path(path)
        if normalized.startswith(GENERATED_PREFIXES):
            generated.append(path)
        if normalized == "ui/index.html":
            frozen.append(path)
        if normalized.startswith(AUDIT_PATHS):
            audit.append(path)
        if normalized.endswith(SENSITIVE_SUFFIXES) or any(
            token in normalized for token in ("credential", "secret", "token", "apikey")
        ):
            sensitive.append(path)
    return {
        "generated_or_local_only": generated,
        "frozen_reference": frozen,
        "audit_sensitive": audit,
        "potentially_sensitive": sensitive,
    }


def parse_name_status(value: str) -> list[str]:
    paths: list[str] = []
    for line in value.splitlines():
        columns = line.split("\t")
        if len(columns) >= 2:
            paths.append(columns[-1])
    return paths[:MAX_CHANGED_FILES]


def parse_commit_subjects(value: str) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for record in value.split("\x1e"):
        record = record.strip()
        if not record or "\x1f" not in record:
            continue
        sha, subject = record.split("\x1f", 1)
        commits.append({"sha": sha, "subject": subject})
    return commits[:MAX_COMMIT_SUBJECTS]


def read_policy_excerpt() -> str:
    sections: list[str] = []
    for name in ("ROE.md", "PROCESS_AUDIT.md", "AGENTS.md"):
        path = REPOSITORY_ROOT / name
        try:
            sections.append(f"## {name}\n{path.read_text(encoding='utf-8')}")
        except OSError:
            sections.append(f"## {name}\n[File unavailable]")
    return trim("\n\n".join(sections), MAX_POLICY_CHARS)


def resolve_base_ref(base_ref: str) -> str:
    candidates = (f"origin/{base_ref}", base_ref)
    for candidate in candidates:
        try:
            return run_git("rev-parse", "--verify", candidate)
        except FlowError:
            continue
    raise FlowError(f"Base ref was not found: {base_ref}")


def collect_context(base_ref: str, target_ref: str) -> dict[str, Any]:
    base_sha = resolve_base_ref(base_ref)
    target_sha = run_git("rev-parse", "--verify", target_ref)
    range_expression = f"{base_sha}...{target_sha}"
    changed_files = parse_name_status(run_git("diff", "--name-status", range_expression))
    commits = parse_commit_subjects(
        run_git(
            "log",
            "--format=%H%x1f%s%x1e",
            f"{base_sha}..{target_sha}",
            f"-n{MAX_COMMIT_SUBJECTS}",
        )
    )
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY", "local/repo"),
        "base_ref": base_ref,
        "base_sha": base_sha,
        "target_ref": target_ref,
        "target_sha": target_sha,
        "changed_files": changed_files,
        "commit_subjects": commits,
        "working_tree_status": run_git("status", "--short"),
        "policy_flags": classify_changed_files(changed_files),
        "policy_excerpt": read_policy_excerpt(),
    }


def build_messages(prompt: str, context: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "flow": "branch_preflight",
        "mode": "read_only_advisory",
        "hard_limits": {
            "github_writes": False,
            "merge_or_release_authority": False,
            "changed_files_truncated": len(context.get("changed_files", [])) >= MAX_CHANGED_FILES,
        },
        "context": context,
    }
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def read_only_result(raw: str | dict[str, Any]) -> dict[str, Any]:
    result = guard_result(raw)
    result["decision"]["action"] = "ignore" if result["decision"]["action"] == "ignore" else "comment"
    result["effects"].update(
        {
            "close_pr": False,
            "request_changes": False,
            "rename_branch": False,
            "notify_team": False,
            "labels": [],
        }
    )
    return result


def ai_preflight(messages: list[dict[str, str]]) -> dict[str, Any]:
    try:
        return read_only_result(chat_completion_raw(messages))
    except AIClientAccessBlockedError as exc:
        fallback = safe_fallback()
        fallback["human_message"] = f"AI provider access was blocked: {exc}"
        return read_only_result(fallback)
    except AIClientError as exc:
        fallback = safe_fallback()
        fallback["human_message"] = f"AI client failed safely: {exc}"
        return read_only_result(fallback)


def append_context_summary(context: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    flags = context.get("policy_flags", {})
    lines = [
        "### Preflight context",
        "",
        f"- base: {context.get('base_ref', 'unknown')}",
        f"- target: {context.get('target_ref', 'unknown')}",
        f"- changed files: {len(context.get('changed_files', []))}",
        f"- generated or local-only paths: {len(flags.get('generated_or_local_only', []))}",
        f"- frozen reference paths: {len(flags.get('frozen_reference', []))}",
        f"- audit-sensitive paths: {len(flags.get('audit_sensitive', []))}",
        f"- potentially sensitive paths: {len(flags.get('potentially_sensitive', []))}",
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI branch preflight")
    parser.add_argument("--base-ref", default="main", help="Trusted comparison branch.")
    parser.add_argument("--target-ref", default="HEAD", help="Ref to inspect.")
    parser.add_argument("--dry-run", action="store_true", help="Record read-only execution.")
    parser.add_argument("--mock-context-file", help="Use a JSON context instead of Git.")
    parser.add_argument("--mock-ai-output", help="Use a local AI JSON output instead of calling AI.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=True)
    context = read_json_file(args.mock_context_file) if args.mock_context_file else collect_context(
        args.base_ref, args.target_ref
    )
    prompt = load_prompt("branch_preflight.md")
    if args.mock_ai_output:
        result = read_only_result(pathlib.Path(args.mock_ai_output).read_text(encoding="utf-8-sig"))
    else:
        result = ai_preflight(build_messages(prompt, context))

    emit_result({"context": context, "result": result})
    write_step_summary("ai-branch-preflight", result, dry_run)
    append_context_summary(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
