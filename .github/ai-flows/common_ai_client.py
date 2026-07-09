# -*- coding: utf-8 -*-
"""Small OpenAI-compatible chat completions client for AI maintainer flows."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.error
import urllib.request
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_TEMPERATURE = 0
DEFAULT_RESPONSE_FORMAT = {"type": "json_object"}
DEFAULT_USER_AGENT = "EchoPosture-AI-Maintainer/1.0"


class AIClientError(RuntimeError):
    """Base error for AI client failures."""


class AIClientConfigError(AIClientError):
    """Raised when required AI client configuration is missing."""


class AIClientResponseError(AIClientError):
    """Raised when the AI response is missing or cannot be parsed."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value


def chat_completions_url(api_url: str | None = None) -> str:
    configured = _env("AI_CHAT_COMPLETIONS_URL") or api_url or _env("AI_API_URL")
    if not configured:
        raise AIClientConfigError("AI_API_URL is required.")

    configured = configured.strip()
    if "://" not in configured:
        configured = f"https://{configured}"

    parsed = urllib.parse.urlparse(configured)
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        final_path = path
    elif path in {"", "/"}:
        final_path = "/v1/chat/completions"
    elif path.endswith("/v1"):
        final_path = f"{path}/chat/completions"
    else:
        final_path = f"{path}/v1/chat/completions"

    return urllib.parse.urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            final_path,
            "",
            parsed.query,
            "",
        )
    )


def build_request_body(
    messages: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    request_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if request_body is not None:
        body = dict(request_body)
        body.setdefault("model", model or _env("AI_MODEL"))
        body.setdefault("temperature", DEFAULT_TEMPERATURE)
    else:
        body = {
            "messages": messages or [],
        }
        body.setdefault("model", model or _env("AI_MODEL"))
        body.setdefault("temperature", DEFAULT_TEMPERATURE)
        body.setdefault("response_format", DEFAULT_RESPONSE_FORMAT)

    if not body.get("model"):
        raise AIClientConfigError("AI_MODEL is required.")
    return body


def chat_completion_raw(
    messages: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    request_body: dict[str, Any] | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    key = api_key or _env("AI_API_KEY")
    if not key:
        raise AIClientConfigError("AI_API_KEY is required.")

    body = build_request_body(messages, model=model, request_body=request_body)
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        chat_completions_url(api_url),
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": _env("AI_USER_AGENT", DEFAULT_USER_AGENT) or DEFAULT_USER_AGENT,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise AIClientResponseError(f"AI API HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise AIClientResponseError(f"AI API request failed: {exc}") from exc

    try:
        data = json.loads(response_payload)
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise AIClientResponseError("AI API response did not contain message content.") from exc


def chat_completion(
    messages: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    request_body: dict[str, Any] | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    content = chat_completion_raw(
        messages,
        model=model,
        request_body=request_body,
        api_url=api_url,
        api_key=api_key,
        timeout=timeout,
    )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIClientResponseError("AI message content was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise AIClientResponseError("AI message content must be a JSON object.")
    return parsed
