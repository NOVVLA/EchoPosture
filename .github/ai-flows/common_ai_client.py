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


class AIClientAccessBlockedError(AIClientResponseError):
    """Raised when a known Claude or gateway access block is detected."""


BACKUP_TRIGGER_MARKERS = (
    "此错误由Cloudflare代表网站所有者生成。",
    "如您对此事不知情，请首先尝试升级您的 Claude Code 客户端版本，其次请联系技术或管理员。",
)


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


def _compact_for_match(value: str) -> str:
    return "".join(value.lower().split())


def is_backup_trigger_text(value: str) -> bool:
    compact = _compact_for_match(value)
    return any(_compact_for_match(marker) in compact for marker in BACKUP_TRIGGER_MARKERS)


def backup_standby_enabled(model: str | None = None) -> bool:
    candidates = [
        model,
        _env("AI_MODEL"),
        _env("AI_REVIEW_MODEL"),
        _env("AI_FAST_MODEL"),
    ]
    return any("claude" in candidate.lower() for candidate in candidates if candidate)


def backup_configured() -> bool:
    return bool(_env("AI_BACKUP_API_URL") and _env("AI_BACKUP_MODEL"))


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


def _post_chat_completion(
    *,
    body: dict[str, Any],
    api_url: str | None,
    api_key: str | None,
    timeout: int,
) -> str:
    key = api_key or _env("AI_API_KEY")
    if not key:
        raise AIClientConfigError("AI_API_KEY is required.")

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


def _backup_request_body(body: dict[str, Any]) -> dict[str, Any]:
    backup_body = dict(body)
    backup_body["model"] = _env("AI_BACKUP_MODEL")
    return backup_body


def _try_backup_chat_completion(
    *,
    body: dict[str, Any],
    api_key: str | None,
    timeout: int,
    original_error: AIClientResponseError | None = None,
) -> str:
    if not backup_configured():
        if original_error is not None:
            raise AIClientAccessBlockedError(
                "Primary AI route was blocked and AI_BACKUP_API_URL/AI_BACKUP_MODEL "
                "are not configured."
            ) from original_error
        raise AIClientAccessBlockedError(
            "Primary AI route returned a known access-block message and backup is not configured."
        )

    try:
        content = _post_chat_completion(
            body=_backup_request_body(body),
            api_url=_env("AI_BACKUP_API_URL"),
            api_key=api_key,
            timeout=timeout,
        )
    except AIClientResponseError as exc:
        if is_backup_trigger_text(str(exc)):
            raise AIClientAccessBlockedError(
                "Backup AI route also returned a known access-block message."
            ) from exc
        raise
    if is_backup_trigger_text(content):
        raise AIClientAccessBlockedError("Backup AI route also returned a known access-block message.")
    return content


def chat_completion_raw(
    messages: list[dict[str, Any]] | None = None,
    *,
    model: str | None = None,
    request_body: dict[str, Any] | None = None,
    api_url: str | None = None,
    api_key: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    allow_backup: bool = True,
) -> str:
    body = build_request_body(messages, model=model, request_body=request_body)
    backup_ready = allow_backup and backup_standby_enabled(str(body.get("model") or model or ""))

    try:
        content = _post_chat_completion(
            body=body,
            api_url=api_url,
            api_key=api_key,
            timeout=timeout,
        )
    except AIClientResponseError as exc:
        if backup_ready and is_backup_trigger_text(str(exc)):
            return _try_backup_chat_completion(
                body=body,
                api_key=api_key,
                timeout=timeout,
                original_error=exc,
            )
        raise

    if backup_ready and is_backup_trigger_text(content):
        return _try_backup_chat_completion(
            body=body,
            api_key=api_key,
            timeout=timeout,
        )
    return content


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
