# -*- coding: utf-8 -*-
"""Regression checks for aggressive PR review guidance and close hard gates."""

from __future__ import annotations

import pathlib
import sys


FLOW_DIR = pathlib.Path(__file__).resolve().parent / ".github" / "ai-flows"
sys.path.insert(0, str(FLOW_DIR))

import pr_review  # noqa: E402


def close_candidate(*, confidence: float = 0.99) -> dict[str, object]:
    return {
        "decision": {"action": "close", "confidence": confidence, "risk": "critical"},
        "effects": {"close_pr": True, "request_changes": False},
        "analysis": {
            "evidence": [
                {
                    "hard_rule": "malicious_submission",
                    "supports_close": True,
                    "message": "The diff adds a credential exfiltration request.",
                }
            ]
        },
    }


def test_close_still_requires_second_reviewer() -> None:
    result = close_candidate()
    hard_rule = pr_review.hard_close_rule(result)
    assert hard_rule == "malicious_submission"
    assert not pr_review.should_close(result=result, hard_rule=hard_rule, review_model_agrees=False)
    assert pr_review.should_close(result=result, hard_rule=hard_rule, review_model_agrees=True)


def test_close_still_requires_primary_confidence_and_hard_rule() -> None:
    low_confidence = close_candidate(confidence=0.94)
    assert not pr_review.should_close(
        result=low_confidence,
        hard_rule=pr_review.hard_close_rule(low_confidence),
        review_model_agrees=True,
    )
    ordinary = close_candidate()
    ordinary["analysis"] = {"evidence": []}
    assert not pr_review.should_close(result=ordinary, hard_rule=None, review_model_agrees=True)


def test_prompt_requires_evidence_without_weakening_gates() -> None:
    prompt = (FLOW_DIR / "prompts" / "pr_review.md").read_text(encoding="utf-8")
    assert "Do not dismiss a real present problem" in prompt
    assert "ordinary defects, request changes rather than closure" in prompt
    assert "verify every gate before returning it" in prompt
    assert "AI_REVIEW_MODEL" in prompt


if __name__ == "__main__":
    test_close_still_requires_second_reviewer()
    test_close_still_requires_primary_confidence_and_hard_rule()
    test_prompt_requires_evidence_without_weakening_gates()
    print("AI PR review guard checks passed.")
