# -*- coding: utf-8 -*-
"""Deterministic checks for AI branch preflight and release audit workflows."""

from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import sys
import tempfile


FLOW_DIR = pathlib.Path(__file__).resolve().parent / ".github" / "ai-flows"
sys.path.insert(0, str(FLOW_DIR))

import branch_preflight  # noqa: E402
import release_audit  # noqa: E402


BRANCH_MOCK_RESULT = {
    "decision": {"action": "ignore", "confidence": 1, "risk": "low"},
    "analysis": {},
    "effects": {},
    "human_message": "No branch write action is permitted.",
}


def write_json(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_classify_changed_files() -> None:
    flags = branch_preflight.classify_changed_files(
        ["dist/example.zip", "ui/index.html", "launcher/EchoPostureLauncher.cs", "private-key.pem"]
    )
    assert flags["generated_or_local_only"] == ["dist/example.zip"]
    assert flags["frozen_reference"] == ["ui/index.html"]
    assert flags["audit_sensitive"] == ["ui/index.html", "launcher/EchoPostureLauncher.cs"]
    assert flags["potentially_sensitive"] == ["private-key.pem"]


def test_branch_preflight_mock_run_is_read_only() -> None:
    context = {
        "base_ref": "main",
        "target_ref": "HEAD",
        "changed_files": ["dist/example.zip"],
        "policy_flags": branch_preflight.classify_changed_files(["dist/example.zip"]),
    }
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = pathlib.Path(temporary_directory)
        context_file = directory / "preflight-context.json"
        result_file = directory / "result.json"
        summary_file = directory / "summary.md"
        write_json(context_file, context)
        write_json(result_file, BRANCH_MOCK_RESULT)
        previous_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert branch_preflight.run(
                    [
                        "--dry-run",
                        "--mock-context-file",
                        str(context_file),
                        "--mock-ai-output",
                        str(result_file),
                    ]
                ) == 0
        finally:
            if previous_summary is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = previous_summary
        summary = summary_file.read_text(encoding="utf-8")
        assert "ai-branch-preflight" in summary
        assert "generated or local-only paths: 1" in summary


def release_context(**overrides: object) -> dict[str, object]:
    context: dict[str, object] = {
        "repository": "NOVVLA/EchoPosture",
        "release_id": 1,
        "tag_name": "ga-1.2.2",
        "title": "EchoPosture GA-1.2.2",
        "body": "## 新增\n- 改进体验\n\n## 验证\n- 已测试\n\n## 安装与兼容性\n- 正常升级。",
        "draft": False,
        "prerelease": False,
        "target_commitish": "abc",
        "url": "https://example.invalid/releases/tag/ga-1.2.2",
        "author_login": "maintainer",
        "assets": [
            {
                "name": "EchoPosture-GA-1.2.2-win-x64.zip",
                "size": 42,
                "digest": "sha256:abc",
                "state": "uploaded",
                "url": "https://example.invalid/file.zip",
            }
        ],
    }
    context.update(overrides)
    return context


def test_release_audit_clean_mock_run_creates_no_issue() -> None:
    context = release_context()
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = pathlib.Path(temporary_directory)
        context_file = directory / "release-context.json"
        result_file = directory / "result.json"
        summary_file = directory / "summary.md"
        write_json(context_file, context)
        write_json(result_file, {"decision": {"action": "ignore", "confidence": 1}, "analysis": {"findings": []}})
        previous_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert release_audit.run(
                    ["--dry-run", "--mock-context-file", str(context_file), "--mock-ai-output", str(result_file)]
                ) == 0
        finally:
            if previous_summary is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = previous_summary
        assert "outcome: `no_issue_required`" in summary_file.read_text(encoding="utf-8")


def test_release_audit_missing_required_information_plans_one_issue() -> None:
    context = release_context(body="", assets=[])
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = pathlib.Path(temporary_directory)
        context_file = directory / "release-context.json"
        result_file = directory / "result.json"
        summary_file = directory / "summary.md"
        write_json(context_file, context)
        write_json(result_file, {"decision": {"action": "ignore", "confidence": 1}, "analysis": {"findings": []}})
        previous_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert release_audit.run(
                    [
                        "--dry-run",
                        "--mock-context-file",
                        str(context_file),
                        "--mock-ai-output",
                        str(result_file),
                    ]
                ) == 0
        finally:
            if previous_summary is None:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)
            else:
                os.environ["GITHUB_STEP_SUMMARY"] = previous_summary
        summary = summary_file.read_text(encoding="utf-8")
        assert "ai-release-audit" in summary
        assert "outcome: `issue_planned`" in summary
        assert "release_body_missing" in summary


def test_release_audit_rejects_ungated_ai_findings() -> None:
    result = release_audit.normalize_ai_result({
        "decision": {"action": "create_issue", "confidence": 1},
        "analysis": {"findings": [{"id": "arbitrary", "evidence": "x", "required_fix": "y"}]},
    })
    assert result["findings"] == []
    assert release_audit.issue_marker("ga-1.2.2") == "[release-audit:ga-1.2.2]"


def test_release_audit_detects_existing_issue_before_creation() -> None:
    def fake_request(*_args: object, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "title": "[release-audit:ga-1.2.2] 发布信息待补充",
                "number": 12,
                "html_url": "https://example.invalid/issues/12",
            }
        ]

    original_request = release_audit.github_request
    release_audit.github_request = fake_request
    try:
        existing = release_audit.find_open_audit_issue(
            "NOVVLA/EchoPosture", release_audit.issue_marker("ga-1.2.2")
        )
    finally:
        release_audit.github_request = original_request
    assert existing and existing["number"] == 12


if __name__ == "__main__":
    test_classify_changed_files()
    test_branch_preflight_mock_run_is_read_only()
    test_release_audit_clean_mock_run_creates_no_issue()
    test_release_audit_missing_required_information_plans_one_issue()
    test_release_audit_rejects_ungated_ai_findings()
    test_release_audit_detects_existing_issue_before_creation()
    print("AI maintainer release-audit checks passed.")
