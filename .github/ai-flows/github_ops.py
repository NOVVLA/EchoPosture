# -*- coding: utf-8 -*-
"""Shared GitHub Actions helpers for AI maintainer flow skeletons."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any

from common_ai_client import AIClientError, chat_completion_raw
from json_guard import guard_result


FLOW_DIR = pathlib.Path(__file__).resolve().parent
PROMPT_DIR = FLOW_DIR / "prompts"


def env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_event_payload() -> dict[str, Any]:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        return {}

    path = pathlib.Path(event_path)
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_prompt(prompt_name: str) -> str:
    path = PROMPT_DIR / prompt_name
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return "Return only a JSON object. TODO: flow prompt is not implemented."


def placeholder_ai_output(flow_name: str) -> str:
    return json.dumps(
        {
            "decision": {
                "action": "ignore",
                "confidence": 1,
                "risk": "low",
            },
            "effects": {
                "close_pr": False,
                "request_changes": False,
                "rename_branch": False,
                "notify_team": False,
                "labels": ["ai-maintainer-framework"],
            },
            "human_message": (
                f"{flow_name} framework is installed. Business logic is not implemented yet."
            ),
        }
    )


def emit_result(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=False, indent=2))


def write_step_summary(flow_name: str, result: dict[str, Any], dry_run: bool) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    decision = result.get("decision", {})
    message = result.get("human_message", "")
    lines = [
        f"## {flow_name}",
        "",
        f"- dry_run: `{str(dry_run).lower()}`",
        f"- action: `{decision.get('action', 'unknown')}`",
        f"- confidence: `{decision.get('confidence', 0)}`",
        "",
        message,
        "",
    ]
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def github_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    if dry_run:
        return {"dry_run": True, "method": method, "path": path, "payload": payload}

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"skipped": True, "reason": "GITHUB_TOKEN is not configured."}

    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(
        f"{api_base}/{path.lstrip('/')}",
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {"error": f"GitHub API HTTP {exc.code}", "detail": detail}
    except urllib.error.URLError as exc:
        return {"error": "GitHub API request failed", "detail": str(exc)}

    if not body:
        return {}
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return {"raw": body}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def run_framework_flow(flow_name: str, prompt_name: str, argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{flow_name} AI maintainer framework")
    parser.add_argument("--dry-run", action="store_true", help="Do not perform write actions.")
    parser.add_argument(
        "--call-ai",
        action="store_true",
        help="Exercise the common AI client. Disabled in workflow skeletons by default.",
    )
    args = parser.parse_args(argv)

    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=True)
    event_payload = load_event_payload()
    prompt = load_prompt(prompt_name)

    if args.call_ai:
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "flow": flow_name,
                        "event_name": os.environ.get("GITHUB_EVENT_NAME", "manual"),
                        "event_keys": sorted(event_payload.keys()),
                        "business_logic_status": "not_implemented",
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            raw_output = chat_completion_raw(messages)
        except AIClientError as exc:
            raw_output = json.dumps(
                {
                    "decision": {
                        "action": "comment",
                        "confidence": 0,
                        "risk": "medium",
                    },
                    "effects": {
                        "close_pr": False,
                        "request_changes": False,
                        "rename_branch": False,
                        "notify_team": False,
                        "labels": ["ai-client-error"],
                    },
                    "human_message": f"AI client failed safely: {exc}",
                }
            )
    else:
        raw_output = placeholder_ai_output(flow_name)

    result = guard_result(raw_output)
    emit_result(result)
    write_step_summary(flow_name, result, dry_run)
    return 0
