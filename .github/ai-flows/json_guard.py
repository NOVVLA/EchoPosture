# -*- coding: utf-8 -*-
"""JSON validation and hard safety limits for AI maintainer flows."""

from __future__ import annotations

import copy
import json
from typing import Any


ALLOWED_ACTIONS = {"comment", "request_changes", "close", "rename_branch", "ignore"}
DANGEROUS_ACTION_THRESHOLDS = {
    "close": 0.95,
    "rename_branch": 0.90,
    "request_changes": 0.80,
}
DANGEROUS_EFFECT_THRESHOLDS = {
    "close_pr": 0.95,
    "rename_branch": 0.90,
    "request_changes": 0.80,
}
SAFE_FALLBACK = {
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
        "labels": ["ai-output-invalid"],
    },
    "human_message": "AI \u8f93\u51fa\u65e0\u6cd5\u89e3\u6790\uff0c\u5df2\u964d\u7ea7\u4e3a\u4ec5\u8bc4\u8bba\u6a21\u5f0f\u3002",
}


def safe_fallback() -> dict[str, Any]:
    return copy.deepcopy(SAFE_FALLBACK)


def _as_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))


def _as_bool(value: Any) -> bool:
    return value is True


def _as_labels(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def parse_json_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("AI output must be a JSON object.")
    return parsed


def guard_result(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            candidate = parse_json_object(raw)
        except (json.JSONDecodeError, ValueError, TypeError):
            return safe_fallback()
    elif isinstance(raw, dict):
        candidate = copy.deepcopy(raw)
    else:
        return safe_fallback()

    decision = candidate.get("decision")
    if not isinstance(decision, dict):
        decision = {}

    effects = candidate.get("effects")
    if not isinstance(effects, dict):
        effects = {}

    action = decision.get("action")
    if action not in ALLOWED_ACTIONS:
        action = "comment"

    confidence = _as_confidence(decision.get("confidence"))
    risk = decision.get("risk")
    if risk not in {"low", "medium", "high", "critical"}:
        risk = "medium"

    normalized_effects = {
        "close_pr": _as_bool(effects.get("close_pr")),
        "request_changes": _as_bool(effects.get("request_changes")),
        "rename_branch": _as_bool(effects.get("rename_branch")),
        "notify_team": _as_bool(effects.get("notify_team")),
        "labels": _as_labels(effects.get("labels")),
    }

    for effect_name, threshold in DANGEROUS_EFFECT_THRESHOLDS.items():
        if normalized_effects[effect_name] and confidence < threshold:
            normalized_effects[effect_name] = False

    threshold = DANGEROUS_ACTION_THRESHOLDS.get(action)
    if threshold is not None and confidence < threshold:
        action = "comment"

    human_message = candidate.get("human_message")
    if not isinstance(human_message, str) or not human_message.strip():
        human_message = "AI maintainer framework returned a safe placeholder result."

    analysis = candidate.get("analysis")
    if not isinstance(analysis, dict):
        analysis = {}

    summary = analysis.get("summary")
    if not isinstance(summary, str):
        summary = ""

    normalized_analysis = {
        "summary": summary,
        "problems": analysis.get("problems") if isinstance(analysis.get("problems"), list) else [],
        "evidence": analysis.get("evidence") if isinstance(analysis.get("evidence"), list) else [],
        "recommended_fixes": (
            analysis.get("recommended_fixes")
            if isinstance(analysis.get("recommended_fixes"), list)
            else []
        ),
    }

    return {
        "decision": {
            "action": action,
            "confidence": confidence,
            "risk": risk,
        },
        "analysis": normalized_analysis,
        "effects": normalized_effects,
        "human_message": human_message,
    }


if __name__ == "__main__":
    import sys

    print(json.dumps(guard_result(sys.stdin.read()), ensure_ascii=False, indent=2))
