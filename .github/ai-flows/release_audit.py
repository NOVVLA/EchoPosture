# -*- coding: utf-8 -*-
"""Strict, bounded post-publication audit for GitHub Releases."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from common_ai_client import AIClientAccessBlockedError, AIClientError, chat_completion_raw
from github_ops import emit_result, env_flag, load_event_payload, load_prompt
from json_guard import parse_json_object


MAX_BODY_CHARS = 12000
MAX_ASSETS = 20
MAX_FINDINGS = 12
AI_CONFIDENCE_TO_OPEN_ISSUE = 0.70
GA_TAG = re.compile(r"^ga-(\d+\.\d+\.\d+)$")
TEAM_ALPHA_TAG = re.compile(r"^team-alpha-(\d{8}-\d{6})$")
MARKER_PREFIX = "[release-audit:"
ALLOWED_AI_FINDINGS = {
    "user_impact_unclear",
    "upgrade_guidance_missing",
    "verification_scope_unclear",
    "known_limitations_missing",
}


class FlowError(RuntimeError):
    """Raised when a release audit cannot obtain safe input."""


def trim(value: Any, limit: int) -> str:
    text = value if isinstance(value, str) else ""
    return text if len(text) <= limit else text[: limit - 43] + "\n\n[content truncated by ai-release-audit]"


def github_request(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise FlowError("GITHUB_TOKEN is required for GitHub API access.")
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    request = urllib.request.Request(
        f"{base}/{path.lstrip('/')}",
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
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise FlowError(f"GitHub API HTTP {exc.code} for {method} {path}.") from None
    except urllib.error.URLError as exc:
        raise FlowError(f"GitHub API request failed: {exc.reason}") from None
    return json.loads(text) if text else {}


def release_context(release: dict[str, Any], repository: str) -> dict[str, Any]:
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    normalized_assets = []
    for asset in assets[:MAX_ASSETS]:
        if not isinstance(asset, dict):
            continue
        normalized_assets.append(
            {
                "name": trim(asset.get("name"), 300),
                "size": asset.get("size") if isinstance(asset.get("size"), int) else 0,
                "digest": trim(asset.get("digest"), 200),
                "state": trim(asset.get("state"), 50),
                "url": trim(asset.get("browser_download_url"), 1000),
            }
        )
    author = release.get("author") if isinstance(release.get("author"), dict) else {}
    return {
        "repository": repository,
        "release_id": release.get("id") if isinstance(release.get("id"), int) else 0,
        "tag_name": trim(release.get("tag_name"), 160),
        "title": trim(release.get("name"), 300),
        "body": trim(release.get("body"), MAX_BODY_CHARS),
        "draft": release.get("draft") is True,
        "prerelease": release.get("prerelease") is True,
        "target_commitish": trim(release.get("target_commitish"), 160),
        "url": trim(release.get("html_url"), 1000),
        "author_login": trim(author.get("login"), 100),
        "assets": normalized_assets,
    }


def channel_and_version(tag: str) -> tuple[str, str]:
    ga = GA_TAG.fullmatch(tag)
    if ga:
        return "GA", ga.group(1)
    alpha = TEAM_ALPHA_TAG.fullmatch(tag)
    if alpha:
        return "TEAM_ALPHA", alpha.group(1)
    return "UNKNOWN", ""


def finding(rule_id: str, message: str, evidence: str) -> dict[str, str]:
    return {"id": rule_id, "message": message, "evidence": evidence}


def has_any(text: str, terms: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(term.casefold() in folded for term in terms)


def deterministic_findings(context: dict[str, Any]) -> list[dict[str, str]]:
    tag = context["tag_name"]
    title = context["title"]
    body = context["body"]
    channel, version = channel_and_version(tag)
    findings: list[dict[str, str]] = []
    if context["draft"]:
        findings.append(finding("release_is_draft", "正式发布事件不应指向草稿 Release。", "draft=true"))
    if channel == "UNKNOWN":
        findings.append(finding("tag_format_invalid", "Tag 不符合 GA 或 TEAM_ALPHA 发布命名规范。", tag))
    elif channel == "GA":
        expected_title = f"EchoPosture GA-{version}"
        expected_asset = f"EchoPosture-GA-{version}-win-x64.zip"
        if context["prerelease"]:
            findings.append(finding("channel_state_mismatch", "GA Release 不能标记为 prerelease。", "prerelease=true"))
        if title != expected_title:
            findings.append(finding("title_mismatch", "GA 标题必须与 Tag 中的版本一致。", f"expected: {expected_title}"))
    else:
        expected_title = f"EchoPosture TEAM_ALPHA {version}"
        expected_asset = f"EchoPosture-TEAM_ALPHA-{version}-win-x64.zip"
        if not context["prerelease"]:
            findings.append(
                finding("channel_state_mismatch", "TEAM_ALPHA Release 必须标记为 prerelease。", "prerelease=false")
            )
        if title != expected_title:
            findings.append(finding("title_mismatch", "TEAM_ALPHA 标题必须与 Tag 中的时间戳一致。", f"expected: {expected_title}"))
    if not body.strip():
        findings.append(finding("release_body_missing", "Release 正文不能为空。", "body is empty"))
    elif not has_any(body, ("新增", "修复", "变更", "changed", "added", "fixed", "what's new")):
        findings.append(finding("user_changes_missing", "Release 正文缺少用户可见变更说明。", "no change section found"))
    if body.strip() and not has_any(body, ("验证", "测试", "verify", "test", "self-test")):
        findings.append(finding("verification_missing", "Release 正文未说明验证范围或已知验证缺口。", "no verification terms found"))
    if body.strip() and not has_any(
        body,
        ("升级", "兼容", "安装", "限制", "下载", "upgrade", "compatib", "install", "download", "known issue"),
    ):
        findings.append(
            finding("upgrade_context_missing", "Release 正文未提供升级、兼容性、安装或已知限制信息。", "no lifecycle guidance found")
        )
    assets = context["assets"]
    package_assets = [asset for asset in assets if asset["name"] == expected_asset] if channel != "UNKNOWN" else []
    if channel != "UNKNOWN" and not package_assets:
        findings.append(finding("package_asset_missing", "未找到与发布版本对应的 Windows x64 ZIP 资产。", expected_asset))
    for asset in package_assets:
        if asset["size"] <= 0 or asset["state"] not in {"uploaded", "open"}:
            findings.append(finding("package_asset_incomplete", "发布 ZIP 资产未处于完整上传状态。", asset["name"]))
        if not asset["digest"].startswith("sha256:"):
            findings.append(finding("package_digest_missing", "发布 ZIP 缺少 GitHub 报告的 SHA-256 摘要。", asset["name"]))
    if has_any(body, ("c:\\users\\", "/users/", "api_key", "authorization: bearer")):
        findings.append(finding("possible_sensitive_disclosure", "Release 正文疑似包含本机路径或凭据线索。", "sensitive-pattern match"))
    return findings[:MAX_FINDINGS]


def normalize_ai_result(raw: str | dict[str, Any]) -> dict[str, Any]:
    try:
        data = parse_json_object(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        data = {}
    decision = data.get("decision") if isinstance(data, dict) else {}
    analysis = data.get("analysis") if isinstance(data, dict) else {}
    confidence = decision.get("confidence", 0) if isinstance(decision, dict) else 0
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    raw_findings = analysis.get("findings") if isinstance(analysis, dict) else []
    findings = []
    for item in raw_findings if isinstance(raw_findings, list) else []:
        if not isinstance(item, dict) or item.get("id") not in ALLOWED_AI_FINDINGS:
            continue
        evidence = trim(item.get("evidence"), 500).strip()
        required_fix = trim(item.get("required_fix"), 500).strip()
        if evidence and required_fix:
            findings.append({"id": item["id"], "message": required_fix, "evidence": evidence})
    return {
        "decision": {
            "action": "create_issue" if decision.get("action") == "create_issue" else "ignore",
            "confidence": confidence,
        },
        "findings": findings[:MAX_FINDINGS],
        "human_message": trim(data.get("human_message") if isinstance(data, dict) else "", 2000),
    }


def build_messages(prompt: str, context: dict[str, Any], rules: list[dict[str, str]]) -> list[dict[str, str]]:
    payload = {
        "flow": "release_audit",
        "mode": "strict_post_publication",
        "context": context,
        "deterministic_findings": rules,
    }
    return [{"role": "system", "content": prompt}, {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]


def audit_with_ai(prompt: str, context: dict[str, Any], rules: list[dict[str, str]]) -> dict[str, Any]:
    try:
        return normalize_ai_result(chat_completion_raw(build_messages(prompt, context, rules)))
    except (AIClientAccessBlockedError, AIClientError) as exc:
        return {
            "decision": {"action": "ignore", "confidence": 0.0},
            "findings": [],
            "human_message": f"AI unavailable: {exc}",
        }


def issue_marker(tag: str) -> str:
    return f"{MARKER_PREFIX}{tag}]"


def find_open_audit_issue(repo: str, marker: str) -> dict[str, Any] | None:
    issues = github_request("GET", f"repos/{repo}/issues?state=open&per_page=100")
    if not isinstance(issues, list):
        return None
    return next((item for item in issues if isinstance(item, dict) and marker in str(item.get("title", ""))), None)


def build_issue(context: dict[str, Any], findings: list[dict[str, str]]) -> dict[str, str]:
    marker = issue_marker(context["tag_name"])
    lines = [
        f"## Release information needs completion {marker}",
        "",
        f"Published Release: {context['url']}",
        f"Tag: `{context['tag_name']}`",
        f"Publisher: @{context['author_login'] or 'unknown'}",
        "",
        "The automated post-publication audit found the following required follow-ups:",
        "",
    ]
    for item in findings:
        lines.extend((f"- **{item['id']}**: {item['message']}", f"  Evidence: `{item['evidence']}`"))
    lines.extend(
        (
            "",
            "Please update the published Release information or assets, then manually rerun "
            "`ai-release-audit` to verify the correction.",
            "",
            "This Issue does not modify or withdraw the Release automatically.",
        )
    )
    return {"title": f"{marker} 发布信息待补充", "body": "\n".join(lines)}


def write_summary(context: dict[str, Any], findings: list[dict[str, str]], outcome: str, dry_run: bool) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "## ai-release-audit",
        "",
        f"- release: `{context['tag_name']}`",
        f"- dry_run: `{str(dry_run).lower()}`",
        f"- outcome: `{outcome}`",
        "",
    ]
    if findings:
        lines.append("### Required findings")
        lines.extend(f"- `{item['id']}`: {item['message']}" for item in findings)
    else:
        lines.append("No issue-opening findings were retained.")
    pathlib.Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def get_context(args: argparse.Namespace, dry_run: bool) -> dict[str, Any]:
    if args.mock_context_file:
        data = json.loads(pathlib.Path(args.mock_context_file).read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise FlowError("Mock context must be a JSON object.")
        return data
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not repository:
        raise FlowError("GITHUB_REPOSITORY is required.")
    event = load_event_payload()
    release = event.get("release") if isinstance(event.get("release"), dict) else None
    if release is None:
        if not args.release_tag:
            raise FlowError("release_tag is required for a manual audit.")
        encoded_tag = urllib.parse.quote(args.release_tag, safe="")
        release = github_request("GET", f"repos/{repository}/releases/tags/{encoded_tag}")
    if not isinstance(release, dict):
        raise FlowError("Release payload was not returned as an object.")
    return release_context(release, repository)


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict AI audit for published GitHub Releases")
    parser.add_argument("--release-tag", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mock-context-file")
    parser.add_argument("--mock-ai-output")
    args = parser.parse_args(argv)
    dry_run = args.dry_run or env_flag("AI_MAINTAINER_DRY_RUN", default=False)
    context = get_context(args, dry_run)
    rules = deterministic_findings(context)
    prompt = load_prompt("release_audit.md")
    raw = pathlib.Path(args.mock_ai_output).read_text(encoding="utf-8-sig") if args.mock_ai_output else None
    ai = normalize_ai_result(raw) if raw is not None else audit_with_ai(prompt, context, rules)
    ai_is_actionable = (
        ai["decision"]["action"] == "create_issue"
        and ai["decision"]["confidence"] >= AI_CONFIDENCE_TO_OPEN_ISSUE
        and bool(ai["findings"])
    )
    should_open = bool(rules) or ai_is_actionable
    findings = (rules + ai["findings"])[:MAX_FINDINGS]
    outcome = "no_issue_required"
    issue: dict[str, Any] | None = None
    if should_open:
        marker = issue_marker(context["tag_name"])
        existing = None if dry_run else find_open_audit_issue(context["repository"], marker)
        if existing:
            outcome = "duplicate_issue_exists"
            issue = {"number": existing.get("number"), "url": existing.get("html_url")}
        else:
            payload = build_issue(context, findings)
            if dry_run:
                outcome = "issue_planned"
                issue = payload
            else:
                created = github_request("POST", f"repos/{context['repository']}/issues", payload)
                outcome = "issue_created"
                issue = {"number": created.get("number"), "url": created.get("html_url")}
    result = {"context": context, "deterministic_findings": rules, "ai": ai, "outcome": outcome, "issue": issue}
    emit_result(result)
    write_summary(context, findings if should_open else [], outcome, dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
