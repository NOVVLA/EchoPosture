# -*- coding: utf-8 -*-
"""Deterministic checks for read-only AI branch and release workflows."""

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
import release_notes  # noqa: E402


MOCK_RESULT = {
    "decision": {"action": "close", "confidence": 1, "risk": "critical"},
    "analysis": {
        "summary": "The supplied context needs a maintainer review.",
        "problems": ["A generated path is present."],
        "evidence": ["dist/example.zip"],
        "recommended_fixes": ["Remove generated artifacts before staging."],
    },
    "effects": {
        "close_pr": True,
        "request_changes": True,
        "rename_branch": True,
        "notify_team": True,
        "labels": ["unsafe"],
    },
    "human_message": "## Draft\n\nNeeds confirmation before publication.",
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
        write_json(result_file, MOCK_RESULT)
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


def test_release_notes_mock_run_is_read_only() -> None:
    context = {
        "from_ref": "ga-1.2.0",
        "to_ref": "HEAD",
        "version": "1.2.2",
        "channel": "GA",
        "commit_count": 2,
        "commits": [{"sha": "abc", "subject": "feat: example", "author": "Maintainer"}],
    }
    with tempfile.TemporaryDirectory() as temporary_directory:
        directory = pathlib.Path(temporary_directory)
        context_file = directory / "release-context.json"
        result_file = directory / "result.json"
        summary_file = directory / "summary.md"
        write_json(context_file, context)
        write_json(result_file, MOCK_RESULT)
        previous_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                assert release_notes.run(
                    [
                        "--from-ref",
                        "ga-1.2.0",
                        "--version",
                        "1.2.2",
                        "--channel",
                        "GA",
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
        assert "ai-release-notes" in summary
        assert "no tag, release, asset, repository file, or audit record was changed" in summary


def test_read_only_results_clear_side_effects() -> None:
    for module in (branch_preflight, release_notes):
        result = module.read_only_result(MOCK_RESULT)
        assert result["decision"]["action"] == "comment"
        assert result["effects"] == {
            "close_pr": False,
            "request_changes": False,
            "rename_branch": False,
            "notify_team": False,
            "labels": [],
        }


if __name__ == "__main__":
    test_classify_changed_files()
    test_branch_preflight_mock_run_is_read_only()
    test_release_notes_mock_run_is_read_only()
    test_read_only_results_clear_side_effects()
    print("AI maintainer manual-flow checks passed.")
