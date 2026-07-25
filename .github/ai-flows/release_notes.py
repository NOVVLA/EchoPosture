# -*- coding: utf-8 -*-
"""Read-only AI release-notes drafting flow for EchoPosture."""

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
MAX_COMMITS = 120
MAX_CHANGELOG_CHARS = 14000
MAX_RELEASE_GUIDE_CHARS = 16000


class FlowError(RuntimeError):
    """Raised when a release range cannot be collected."""


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


def trim(value: str, limit: int, marker: str) -> str:
    if len(value) <= limit:
        return value
    return value[: limit - len(marker) - 2] + "\n\n" + marker


def parse_commits(value: str) -> list[dict[str, str]]:
    commits: list[dict[str, str]] = []
    for record in value.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        columns = record.split("\x1f")
        if len(columns) != 3:
            continue
        commits.append({"sha": columns[0], "subject": columns[1], "author": columns[2]})
    return commits[:MAX_COMMITS]


def read_file_excerpt(name: str, limit: int) -> str:
    try:
        value = (REPOSITORY_ROOT / name).read_text(encoding="utf-8")
    except OSError:
        return f"[{name} unavailable]"
    return trim(value, limit, f"[{name} truncated by ai-release-notes]")


def collect_context(from_ref: str, to_ref: str, version: str, channel: str) -> dict[str, Any]:
    from_sha = run_git("rev-parse", "--verify", from_ref)
    to_sha = run_git("rev-parse", "--verify", to_ref)
    commit_range = f"{from_sha}..{to_sha}"
    commits = parse_commits(
        run_git(
            "log",
            "--format=%H%x1f%s%x1f%an%x1e",
            commit_range,
            f"-n{MAX_COMMITS}",
        )
    )
    return {
        "repository": os.environ.get("GITHUB_REPOSITORY", "local/repo"),
        "from_ref": from_ref,
        "from_sha": from_sha,
        "to_ref": to_ref,
        "to_sha": to_sha,
        "version": version,
        "channel": channel,
        "commit_count": len(commits),
        "commits": commits,
        "diff_stat": run_git("diff", "--stat", commit_range),
        "changelog_excerpt": read_file_excerpt("CHANGELOG.md", MAX_CHANGELOG_CHARS),
        "release_guide_excerpt": read_file_excerpt("docs/RELEASE.md", MAX_RELEASE_GUIDE_CHARS),
    }


def build_messages(prompt: str, context: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "flow": "release_notes",
        "mode": "read_only_draft",
        "hard_limits": {
            "create_tag": False,
            "create_or_edit_release": False,
            "upload_assets": False,
            "edit_repository_files": False,
            "invent_artifact_hashes_or_validation": False,
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


def ai_release_notes(messages: list[dict[str, str]]) -> dict[str, Any]:
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


def append_release_summary(context: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "### Release draft context",
        "",
        f"- channel: {context.get('channel', 'unknown')}",
        f"- version: {context.get('version', 'unknown')}",
        f"- range: {context.get('from_ref', 'unknown')}..{context.get('to_ref', 'unknown')}",
        f"- commits supplied: {context.get('commit_count', 0)}",
        "- no tag, release, asset, repository file, or audit record was changed",
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI release notes draft")
    parser.add_argument("--from-ref", required=True, help="Inclusive baseline before the release range.")
    parser.add_argument("--to-ref", default="HEAD", help="Release candidate ref.")
    parser.add_argument("--version", required=True, help="Proposed visible version.")
    parser.add_argument("--channel", choices=("GA", "TEAM_ALPHA"), required=True)
    parser.add_argument("--dry-run", action="store_true", help="Record read-only execution.")
    parser.add_argument("--mock-context-file", help="Use a JSON context instead of Git.")
    parser.add_argument("--mock-ai-output", help="Use a local AI JSON output instead of calling AI.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=True)
    context = read_json_file(args.mock_context_file) if args.mock_context_file else collect_context(
        args.from_ref,
        args.to_ref,
        args.version,
        args.channel,
    )
    prompt = load_prompt("release_notes.md")
    if args.mock_ai_output:
        result = read_only_result(pathlib.Path(args.mock_ai_output).read_text(encoding="utf-8-sig"))
    else:
        result = ai_release_notes(build_messages(prompt, context))

    emit_result({"context": context, "result": result})
    write_step_summary("ai-release-notes", result, dry_run)
    append_release_summary(context)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
