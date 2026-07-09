# -*- coding: utf-8 -*-
"""AI PR review flow.

This flow reviews pull request diffs, comments with JSON-grounded feedback, and
only escalates to request-changes or close actions after local hard gates pass.
It never merges pull requests.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from common_ai_client import AIClientError, chat_completion_raw
from github_ops import env_flag, load_prompt, write_step_summary
from json_guard import guard_result, safe_fallback


MAX_DIFF_CHARS = int(os.environ.get("AI_PR_REVIEW_MAX_DIFF_CHARS", "70000"))
MAX_COMMENT_CHARS = 60000
RECENT_COMMENT_LIMIT = 20
AI_REVIEW_TRIGGER = "@ai-review"
HARD_CLOSE_RULES = {
    "obviously_unrelated_code",
    "malicious_submission",
    "pure_garbage_test_submission",
    "mass_core_code_deletion_without_explanation",
    "large_mixed_unrelated_and_valid_changes",
}


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
    accept: str = "application/vnd.github+json",
) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        github_api_url(path),
        data=body,
        headers={
            "Authorization": f"Bearer {github_token()}",
            "Accept": accept,
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

    if accept.endswith(".diff"):
        return raw
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
        page_path = f"{path}{separator}per_page={per_page}&page={page}"
        data = github_request("GET", page_path)
        if not isinstance(data, list) or not data:
            break
        items.extend(data)
        if len(data) < per_page:
            break
        page += 1
    return items[:limit]


def get_pull_request(repo: str, number: int) -> dict[str, Any]:
    data = github_request("GET", f"repos/{repo}/pulls/{number}")
    if not isinstance(data, dict):
        raise FlowError(f"Pull request #{number} was not returned as an object.")
    return data


def get_pull_diff(repo: str, number: int) -> str:
    diff = github_request(
        "GET",
        f"repos/{repo}/pulls/{number}",
        accept="application/vnd.github.v3.diff",
    )
    if not isinstance(diff, str):
        raise FlowError(f"Pull request #{number} diff was not returned as text.")
    return diff


def trim_text(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False

    marker = "\n\n[... diff truncated by ai-pr-review ...]\n\n"
    side = max((max_chars - len(marker)) // 2, 1000)
    return f"{value[:side]}{marker}{value[-side:]}", True


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
                "body": str(comment.get("body") or "")[:4000],
                "created_at": comment.get("created_at"),
            }
        )
    return normalized


def event_context(event_name: str, event: dict[str, Any], repo: str) -> dict[str, Any] | None:
    if event_name == "pull_request":
        pr = event.get("pull_request")
        if not isinstance(pr, dict):
            return None
        if pr.get("draft"):
            return {
                "skip": True,
                "reason": "Draft pull request; waiting for ready_for_review.",
            }
        return {
            "skip": False,
            "trigger": "pull_request",
            "pull_number": int(pr["number"]),
            "user_question": "",
        }

    if event_name == "issue_comment":
        issue = event.get("issue")
        comment = event.get("comment")
        if not isinstance(issue, dict) or not isinstance(comment, dict):
            return None
        if not issue.get("pull_request"):
            return None

        body = str(comment.get("body") or "")
        if AI_REVIEW_TRIGGER.lower() not in body.lower():
            return None

        return {
            "skip": False,
            "trigger": "issue_comment",
            "pull_number": int(issue["number"]),
            "user_question": body,
            "comment_author": (comment.get("user") or {}).get("login"),
        }

    return None


def build_review_messages(
    *,
    prompt: str,
    repo: str,
    event_name: str,
    pr: dict[str, Any],
    diff: str,
    diff_truncated: bool,
    context: dict[str, Any],
    comments: list[dict[str, Any]],
) -> list[dict[str, str]]:
    payload = {
        "repository": repo,
        "event_name": event_name,
        "trigger": context["trigger"],
        "pull_request": {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "body": pr.get("body"),
            "author": (pr.get("user") or {}).get("login"),
            "base": (pr.get("base") or {}).get("ref"),
            "head": (pr.get("head") or {}).get("ref"),
            "changed_files": pr.get("changed_files"),
            "additions": pr.get("additions"),
            "deletions": pr.get("deletions"),
        },
        "user_question": context.get("user_question", ""),
        "recent_comments": comments,
        "diff_truncated": diff_truncated,
        "diff": diff,
    }
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def ai_review(messages: list[dict[str, str]]) -> dict[str, Any]:
    try:
        raw = chat_completion_raw(messages)
    except AIClientError as exc:
        fallback = safe_fallback()
        fallback["effects"]["labels"] = ["ai-client-error"]
        fallback["human_message"] = f"AI client failed safely: {exc}"
        return fallback
    return guard_result(raw)


def hard_close_rule(result: dict[str, Any]) -> str | None:
    evidence = result.get("analysis", {}).get("evidence", [])
    if not isinstance(evidence, list):
        return None

    for item in evidence:
        if not isinstance(item, dict):
            continue
        rule = item.get("hard_rule")
        if item.get("supports_close") is True and rule in HARD_CLOSE_RULES:
            return str(rule)
    return None


def review_model_allows_close(
    *,
    primary_result: dict[str, Any],
    prompt: str,
    repo: str,
    pr: dict[str, Any],
    diff_excerpt: str,
    hard_rule: str,
) -> bool:
    review_model = os.environ.get("AI_REVIEW_MODEL")
    if not review_model:
        return True

    messages = [
        {
            "role": "system",
            "content": (
                "You are the second reviewer for an automated PR close decision. "
                "Return only JSON: {\"review\":{\"agree_close\":true|false,"
                "\"confidence\":0.0,\"reason\":\"\"}}. Agree only when the "
                "primary JSON, hard rule, and diff evidence clearly support closing."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "repository": repo,
                    "pull_request": {
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "author": (pr.get("user") or {}).get("login"),
                    },
                    "hard_rule": hard_rule,
                    "primary_result": primary_result,
                    "diff_excerpt": diff_excerpt[:20000],
                },
                ensure_ascii=False,
            ),
        },
    ]

    try:
        raw = chat_completion_raw(messages, model=review_model)
        parsed = json.loads(raw)
    except (AIClientError, json.JSONDecodeError, TypeError):
        return False

    review = parsed.get("review") if isinstance(parsed, dict) else None
    if not isinstance(review, dict):
        return False
    try:
        confidence = float(review.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0
    return review.get("agree_close") is True and confidence >= 0.80


def should_request_changes(result: dict[str, Any]) -> bool:
    decision = result.get("decision", {})
    effects = result.get("effects", {})
    return (
        decision.get("action") == "request_changes"
        and effects.get("request_changes") is True
        and float(decision.get("confidence", 0)) >= 0.80
        and decision.get("risk") in {"high", "critical"}
    )


def should_close(
    *,
    result: dict[str, Any],
    hard_rule: str | None,
    review_model_agrees: bool,
) -> bool:
    decision = result.get("decision", {})
    effects = result.get("effects", {})
    return (
        decision.get("action") == "close"
        and effects.get("close_pr") is True
        and float(decision.get("confidence", 0)) >= 0.95
        and decision.get("risk") in {"high", "critical"}
        and hard_rule is not None
        and review_model_agrees
    )


def bullet_list(items: list[Any], *, limit: int = 8) -> str:
    lines: list[str] = []
    for item in items[:limit]:
        if isinstance(item, dict):
            text = item.get("message") or item.get("summary") or json.dumps(item, ensure_ascii=False)
        else:
            text = str(item)
        text = text.strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def format_review_comment(result: dict[str, Any], *, hard_rule: str | None, closed: bool) -> str:
    decision = result.get("decision", {})
    analysis = result.get("analysis", {})
    message = str(result.get("human_message") or "").strip()
    if not message:
        message = "AI review completed."

    parts = [
        "<!-- ai-pr-review -->",
        "## AI PR Review",
        "",
        f"- action: `{decision.get('action', 'comment')}`",
        f"- risk: `{decision.get('risk', 'medium')}`",
        f"- confidence: `{decision.get('confidence', 0)}`",
    ]
    if hard_rule:
        parts.append(f"- close hard rule: `{hard_rule}`")
    if closed:
        parts.append("- PR close gate: `passed`")
    parts.extend(["", message])

    summary = str(analysis.get("summary") or "").strip()
    if summary:
        parts.extend(["", "### Summary", summary])

    for title, key in (
        ("Problems", "problems"),
        ("Evidence", "evidence"),
        ("Recommended fixes", "recommended_fixes"),
    ):
        items = analysis.get(key)
        if isinstance(items, list) and items:
            parts.extend(["", f"### {title}", bullet_list(items)])

    body = "\n".join(parts).strip()
    if len(body) > MAX_COMMENT_CHARS:
        body = body[: MAX_COMMENT_CHARS - 200] + "\n\n[Comment truncated by ai-pr-review]"
    return body


def add_labels(repo: str, issue_number: int, labels: list[str], *, dry_run: bool) -> None:
    labels = [label for label in labels if isinstance(label, str) and label.strip()]
    if not labels:
        return
    if dry_run:
        return
    github_request("POST", f"repos/{repo}/issues/{issue_number}/labels", payload={"labels": labels})


def create_issue_comment(repo: str, issue_number: int, body: str, *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"dry_run": True, "comment": body}, ensure_ascii=False, indent=2))
        return
    github_request("POST", f"repos/{repo}/issues/{issue_number}/comments", payload={"body": body})


def request_changes(repo: str, pull_number: int, body: str, *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"dry_run": True, "request_changes": body}, ensure_ascii=False, indent=2))
        return
    github_request(
        "POST",
        f"repos/{repo}/pulls/{pull_number}/reviews",
        payload={"event": "REQUEST_CHANGES", "body": body},
    )


def close_pull_request(repo: str, pull_number: int, *, dry_run: bool) -> None:
    if dry_run:
        print(json.dumps({"dry_run": True, "close_pr": pull_number}, indent=2))
        return
    github_request("PATCH", f"repos/{repo}/pulls/{pull_number}", payload={"state": "closed"})


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI PR review flow")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to GitHub.")
    parser.add_argument("--event-path", help="Path to a GitHub event JSON payload.")
    parser.add_argument("--event-name", help="Override GITHUB_EVENT_NAME for local tests.")
    parser.add_argument("--mock-diff-file", help="Use a local diff file instead of GitHub API.")
    parser.add_argument("--mock-ai-output", help="Use a local AI JSON output file instead of calling AI.")
    args = parser.parse_args(argv)

    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=False)
    event_name = args.event_name or os.environ.get("GITHUB_EVENT_NAME", "")
    event = read_json_file(args.event_path)
    repo = os.environ.get("GITHUB_REPOSITORY", "local/repo") if dry_run else repository()
    context = event_context(event_name, event, repo)

    if not context:
        print("ai-pr-review: event is not applicable.")
        return 0
    if context.get("skip"):
        print(f"ai-pr-review: {context['reason']}")
        return 0

    pull_number = int(context["pull_number"])
    if dry_run and "pull_request" in event:
        pr = event["pull_request"]
    else:
        pr = get_pull_request(repo, pull_number)

    if args.mock_diff_file:
        raw_diff = pathlib.Path(args.mock_diff_file).read_text(encoding="utf-8")
    elif dry_run:
        raw_diff = "diff --git a/example.py b/example.py\n+print('dry run')\n"
    else:
        raw_diff = get_pull_diff(repo, pull_number)

    diff, diff_truncated = trim_text(raw_diff, MAX_DIFF_CHARS)
    comments = [] if dry_run else recent_issue_comments(repo, pull_number)
    prompt = load_prompt("pr_review.md")
    messages = build_review_messages(
        prompt=prompt,
        repo=repo,
        event_name=event_name,
        pr=pr,
        diff=diff,
        diff_truncated=diff_truncated,
        context=context,
        comments=comments,
    )

    if args.mock_ai_output:
        result = guard_result(pathlib.Path(args.mock_ai_output).read_text(encoding="utf-8-sig"))
    else:
        result = ai_review(messages)

    hard_rule = hard_close_rule(result)
    review_agrees = True
    if result.get("effects", {}).get("close_pr") is True and hard_rule:
        review_agrees = review_model_allows_close(
            primary_result=result,
            prompt=prompt,
            repo=repo,
            pr=pr,
            diff_excerpt=diff,
            hard_rule=hard_rule,
        )

    close_allowed = should_close(
        result=result,
        hard_rule=hard_rule,
        review_model_agrees=review_agrees,
    )
    request_changes_allowed = should_request_changes(result) and not close_allowed
    comment_body = format_review_comment(result, hard_rule=hard_rule, closed=close_allowed)

    effects = result.get("effects", {})
    add_labels(repo, pull_number, effects.get("labels", []), dry_run=dry_run)

    force_reply = context["trigger"] == "issue_comment"
    if result.get("decision", {}).get("action") != "ignore" or force_reply:
        create_issue_comment(repo, pull_number, comment_body, dry_run=dry_run)

    if request_changes_allowed:
        request_changes(repo, pull_number, comment_body, dry_run=dry_run)

    if close_allowed:
        close_pull_request(repo, pull_number, dry_run=dry_run)

    write_step_summary("pr_review", result, dry_run)
    print(
        json.dumps(
            {
                "pull_number": pull_number,
                "diff_truncated": diff_truncated,
                "request_changes": request_changes_allowed,
                "close_pr": close_allowed,
                "review_model_required": bool(os.environ.get("AI_REVIEW_MODEL")),
                "review_model_agreed": review_agrees,
                "decision": result.get("decision"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
