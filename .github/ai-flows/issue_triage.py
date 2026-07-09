# -*- coding: utf-8 -*-
"""AI issue triage flow."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import urllib.error
import urllib.request
from typing import Any

from common_ai_client import AIClientAccessBlockedError, AIClientError, chat_completion_raw
from github_ops import env_flag, load_prompt, write_step_summary
from json_guard import guard_result, safe_fallback


AI_ISSUE_TRIGGER = "@ai-issue"
AUTO_LABELS = {"needs-info", "question", "docs"}
SUGGESTED_LABELS = {
    "bug",
    "feature",
    "question",
    "docs",
    "needs-info",
    "android",
    "duplicate-candidate",
    "related-issue",
    "priority-high",
}
RECENT_COMMENT_LIMIT = 20
MAX_BODY_CHARS = 20000
MAX_COMMENT_CHARS = 60000


class FlowError(RuntimeError):
    pass


def read_json_file(path: str | None) -> dict[str, Any]:
    if not path:
        path = os.environ.get("GITHUB_EVENT_PATH")
    if not path:
        return {}
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def repository() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise FlowError("GITHUB_REPOSITORY is required.")
    return repo


def github_token() -> str:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise FlowError("GITHUB_TOKEN is required.")
    return token


def github_api_url(path: str) -> str:
    api_base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{api_base}/{path.lstrip('/')}"


def github_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        github_api_url(path),
        data=body,
        headers={
            "Authorization": f"Bearer {github_token()}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise FlowError(f"GitHub API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise FlowError(f"GitHub API request failed: {exc}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def github_paginated(path: str, *, per_page: int = 100, limit: int = 100) -> list[Any]:
    items: list[Any] = []
    page = 1
    while len(items) < limit:
        separator = "&" if "?" in path else "?"
        data = github_request("GET", f"{path}{separator}per_page={per_page}&page={page}")
        if not isinstance(data, list) or not data:
            break
        items.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return items[:limit]


def event_context(event_name: str, event: dict[str, Any]) -> dict[str, Any] | None:
    issue = event.get("issue")
    if not isinstance(issue, dict) or issue.get("pull_request"):
        return None

    if event_name == "issues":
        return {
            "trigger": "issues",
            "issue_number": int(issue["number"]),
            "user_question": "",
        }

    if event_name == "issue_comment":
        comment = event.get("comment")
        if not isinstance(comment, dict):
            return None
        body = str(comment.get("body") or "")
        if AI_ISSUE_TRIGGER.lower() not in body.lower():
            return None
        return {
            "trigger": "issue_comment",
            "issue_number": int(issue["number"]),
            "user_question": body,
            "comment_author": (comment.get("user") or {}).get("login"),
        }

    return None


def trim(value: str | None, max_chars: int) -> str:
    text = str(value or "")
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 80] + "\n\n[Content truncated by ai-issue-triage]"


def recent_issue_comments(repo: str, issue_number: int) -> list[dict[str, Any]]:
    comments = github_paginated(
        f"repos/{repo}/issues/{issue_number}/comments",
        per_page=100,
        limit=RECENT_COMMENT_LIMIT,
    )
    normalized = []
    for comment in comments[-RECENT_COMMENT_LIMIT:]:
        if not isinstance(comment, dict):
            continue
        normalized.append(
            {
                "user": (comment.get("user") or {}).get("login"),
                "body": trim(str(comment.get("body") or ""), 4000),
                "created_at": comment.get("created_at"),
            }
        )
    return normalized


def build_messages(
    *,
    prompt: str,
    repo: str,
    event_name: str,
    issue: dict[str, Any],
    context: dict[str, Any],
    comments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    payload = {
        "repository": repo,
        "event_name": event_name,
        "trigger": context["trigger"],
        "issue": {
            "number": issue.get("number"),
            "title": issue.get("title"),
            "body": trim(issue.get("body"), MAX_BODY_CHARS),
            "author": (issue.get("user") or {}).get("login"),
            "state": issue.get("state"),
            "labels": [
                label.get("name")
                for label in issue.get("labels", [])
                if isinstance(label, dict) and label.get("name")
            ],
        },
        "user_question": context.get("user_question", ""),
        "recent_comments": comments,
        "allowed_suggested_labels": sorted(SUGGESTED_LABELS),
        "auto_label_allowlist": sorted(AUTO_LABELS),
    }
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def ai_triage(messages: list[dict[str, str]]) -> dict[str, Any]:
    try:
        raw = chat_completion_raw(messages)
    except AIClientAccessBlockedError as exc:
        return {
            "decision": {"action": "ignore", "confidence": 0, "risk": "medium"},
            "classification": {"type": "unknown", "priority": "medium", "labels": []},
            "analysis": {
                "summary": "",
                "possible_modules": [],
                "missing_information": [],
                "maintainer_suggestions": [],
            },
            "effects": {
                "labels": ["ai-client-access-blocked"],
                "notify_team": False,
            },
            "human_message": f"AI provider access was blocked and no safe backup reply is available: {exc}",
        }
    except AIClientError as exc:
        fallback = safe_fallback()
        fallback["classification"] = {"type": "unknown", "priority": "medium", "labels": []}
        fallback["effects"]["labels"] = ["ai-client-error"]
        fallback["human_message"] = f"AI client failed safely: {exc}"
        return fallback
    result = guard_result(raw)
    if result.get("decision", {}).get("action") not in {"comment", "ignore"}:
        result["decision"]["action"] = "comment"
    return result


def selected_auto_labels(result: dict[str, Any]) -> list[str]:
    labels: set[str] = set()
    classification = result.get("classification", {})
    effects = result.get("effects", {})

    for value in classification.get("labels", []):
        if value in AUTO_LABELS:
            labels.add(value)
    for value in effects.get("labels", []):
        if value in AUTO_LABELS:
            labels.add(value)

    issue_type = classification.get("type")
    if issue_type in AUTO_LABELS:
        labels.add(issue_type)

    return sorted(labels)


def bullet_list(items: list[Any], *, limit: int = 8) -> str:
    lines: list[str] = []
    for item in items[:limit]:
        text = item.get("message") if isinstance(item, dict) else str(item)
        text = str(text or "").strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def format_comment(result: dict[str, Any], auto_labels: list[str]) -> str:
    decision = result.get("decision", {})
    classification = result.get("classification", {})
    analysis = result.get("analysis", {})
    message = str(result.get("human_message") or "").strip() or "AI issue triage completed."

    parts = [
        "<!-- ai-issue-triage -->",
        "## AI Issue Triage",
        "",
        f"- action: `{decision.get('action', 'comment')}`",
        f"- risk: `{decision.get('risk', 'medium')}`",
        f"- confidence: `{decision.get('confidence', 0)}`",
        f"- type: `{classification.get('type', 'unknown')}`",
        f"- priority: `{classification.get('priority', 'medium')}`",
    ]
    if auto_labels:
        parts.append(f"- auto labels: `{', '.join(auto_labels)}`")
    parts.extend(["", message])

    summary = str(analysis.get("summary") or "").strip()
    if summary:
        parts.extend(["", "### Summary", summary])

    for title, key in (
        ("Possible modules", "possible_modules"),
        ("Missing information", "missing_information"),
        ("Maintainer suggestions", "maintainer_suggestions"),
    ):
        items = analysis.get(key)
        if isinstance(items, list) and items:
            parts.extend(["", f"### {title}", bullet_list(items)])

    body = "\n".join(parts).strip()
    if len(body) > MAX_COMMENT_CHARS:
        body = body[: MAX_COMMENT_CHARS - 200] + "\n\n[Comment truncated by ai-issue-triage]"
    return body


def add_labels(repo: str, issue_number: int, labels: list[str], *, dry_run: bool) -> None:
    if not labels:
        return
    if dry_run:
        print(json.dumps({"dry_run": True, "labels": labels}, ensure_ascii=False, indent=2))
        return
    github_request("POST", f"repos/{repo}/issues/{issue_number}/labels", payload={"labels": labels})


def create_issue_comment(repo: str, issue_number: int, body: str, *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"dry_run": True, "comment": body}, ensure_ascii=False, indent=2))
        return
    github_request("POST", f"repos/{repo}/issues/{issue_number}/comments", payload={"body": body})


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI issue triage flow")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to GitHub.")
    parser.add_argument("--event-path", help="Path to a GitHub event JSON payload.")
    parser.add_argument("--event-name", help="Override GITHUB_EVENT_NAME for local tests.")
    parser.add_argument("--mock-ai-output", help="Use a local AI JSON output file instead of calling AI.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=False)
    event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    event = read_json_file(args.event_path)
    context = event_context(event_name, event)
    if not context:
        print("ai-issue-triage: event is not applicable.")
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY", "local/repo") if dry_run else repository()
    issue = event["issue"]
    issue_number = int(context["issue_number"])
    comments = [] if dry_run else recent_issue_comments(repo, issue_number)
    prompt = load_prompt("issue_triage.md")
    messages = build_messages(
        prompt=prompt,
        repo=repo,
        event_name=event_name,
        issue=issue,
        context=context,
        comments=comments,
    )

    if args.mock_ai_output:
        result = guard_result(pathlib.Path(args.mock_ai_output).read_text(encoding="utf-8-sig"))
    else:
        result = ai_triage(messages)

    auto_labels = selected_auto_labels(result)
    comment_body = format_comment(result, auto_labels)
    labels = result.get("effects", {}).get("labels", [])
    suppress_comment = isinstance(labels, list) and "ai-client-access-blocked" in labels
    force_reply = context["trigger"] == "issue_comment"

    add_labels(repo, issue_number, auto_labels, dry_run=dry_run)
    if not suppress_comment and (result.get("decision", {}).get("action") != "ignore" or force_reply):
        create_issue_comment(repo, issue_number, comment_body, dry_run=dry_run)

    write_step_summary("issue_triage", result, dry_run)
    print(
        json.dumps(
            {
                "issue_number": issue_number,
                "auto_labels": auto_labels,
                "decision": result.get("decision"),
                "classification": result.get("classification"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
