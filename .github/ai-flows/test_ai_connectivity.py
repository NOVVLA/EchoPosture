# -*- coding: utf-8 -*-
"""Connectivity smoke test for the AI maintainer OpenAI-compatible endpoint."""

from __future__ import annotations

import argparse
import json
import os
from typing import Any

from common_ai_client import chat_completion, chat_completion_raw, chat_completions_url


def env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value


def mask_secret(value: str | None) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "***"
    return f"{value[:3]}...{value[-4:]}"


def assert_json_reply(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AssertionError("JSON test did not return a JSON object.")
    return value


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Test AI API connectivity.")
    parser.add_argument("--api-url", default=env("AI_API_URL"), help="OpenAI-compatible base URL.")
    parser.add_argument("--api-key", default=env("AI_API_KEY"), help="API key.")
    parser.add_argument("--model", default=env("AI_MODEL"), help="Model name.")
    parser.add_argument("--timeout", type=int, default=60, help="Request timeout in seconds.")
    args = parser.parse_args(argv)

    missing = [
        name
        for name, value in (
            ("AI_API_URL", args.api_url),
            ("AI_API_KEY", args.api_key),
            ("AI_MODEL", args.model),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"Missing required configuration: {', '.join(missing)}")

    print("AI connectivity smoke test")
    print(f"Endpoint: {chat_completions_url(args.api_url)}")
    print(f"Model: {args.model or 'not set'}")
    print(f"API key: {mask_secret(args.api_key)}")

    json_reply = chat_completion(
        [
            {
                "role": "system",
                "content": "Return only one JSON object. No Markdown.",
            },
            {
                "role": "user",
                "content": 'Return exactly a tiny JSON object like {"ok": true, "kind": "json"}.',
            },
        ],
        model=args.model,
        api_url=args.api_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    json_reply = assert_json_reply(json_reply)
    print("JSON reply parsed: yes")
    print(json.dumps(json_reply, ensure_ascii=False, indent=2))

    natural_reply = chat_completion_raw(
        request_body={
            "model": args.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": "Reply in plain natural language. Do not return JSON.",
                },
                {
                    "role": "user",
                    "content": "Say one short sentence confirming the connection works.",
                },
            ],
        },
        api_url=args.api_url,
        api_key=args.api_key,
        timeout=args.timeout,
    )
    if not isinstance(natural_reply, str) or not natural_reply.strip():
        raise AssertionError("Natural-language test returned an empty response.")

    print("Natural-language reply received: yes")
    print(natural_reply.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
