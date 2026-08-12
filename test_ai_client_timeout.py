# -*- coding: utf-8 -*-
"""Regression checks for AI endpoint timeout handling."""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import patch


FLOW_DIR = pathlib.Path(__file__).resolve().parent / ".github" / "ai-flows"
sys.path.insert(0, str(FLOW_DIR))

import common_ai_client  # noqa: E402
import pr_review  # noqa: E402


class TimeoutResponse:
    def __enter__(self) -> "TimeoutResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        raise TimeoutError("read timed out")


def test_timeout_is_wrapped_as_ai_client_error() -> None:
    with patch.object(common_ai_client.urllib.request, "urlopen", return_value=TimeoutResponse()):
        try:
            common_ai_client.chat_completion_raw(
                model="test-model",
                api_url="https://example.invalid",
                api_key="test-key",
                timeout=7,
                allow_backup=False,
            )
        except common_ai_client.AIClientTimeoutError as exc:
            assert "7 seconds" in str(exc)
        else:
            raise AssertionError("TimeoutError escaped the AI client")


def test_pr_review_timeout_configuration_is_bounded() -> None:
    with patch.dict(pr_review.os.environ, {"TEST_TIMEOUT": "600"}):
        assert pr_review._positive_int_env("TEST_TIMEOUT", 300) == 600
    for invalid_value in ("", "invalid", "0", "-1"):
        with patch.dict(pr_review.os.environ, {"TEST_TIMEOUT": invalid_value}):
            assert pr_review._positive_int_env("TEST_TIMEOUT", 300) == 300


def test_pr_review_timeout_returns_safe_fallback() -> None:
    assert pr_review.PRIMARY_REVIEW_TIMEOUT_SECONDS == 300

    def fail_with_timeout(*_args: object, **kwargs: object) -> str:
        assert kwargs["timeout"] == pr_review.PRIMARY_REVIEW_TIMEOUT_SECONDS
        raise common_ai_client.AIClientTimeoutError("timed out")

    with patch.object(pr_review, "chat_completion_raw", side_effect=fail_with_timeout):
        result = pr_review.ai_review([{"role": "user", "content": "test"}])

    assert result["decision"]["action"] == "comment"
    assert result["effects"]["close_pr"] is False
    assert result["effects"]["request_changes"] is False
    assert result["effects"]["labels"] == ["ai-client-error"]
    assert "timed out" in result["human_message"]


if __name__ == "__main__":
    test_timeout_is_wrapped_as_ai_client_error()
    test_pr_review_timeout_configuration_is_bounded()
    test_pr_review_timeout_returns_safe_fallback()
    print("AI client timeout checks passed.")
