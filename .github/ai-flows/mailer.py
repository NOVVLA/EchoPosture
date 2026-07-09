# -*- coding: utf-8 -*-
"""Optional SMTP helper skeleton for AI maintainer flows."""

from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


def smtp_configured() -> bool:
    required = ["TEAM_EMAILS", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS"]
    return all(os.environ.get(name) for name in required)


def send_team_notification(subject: str, body: str, *, dry_run: bool = True) -> dict[str, object]:
    if dry_run:
        return {"dry_run": True, "sent": False}

    if not smtp_configured():
        return {"skipped": True, "sent": False, "reason": "SMTP configuration is incomplete."}

    recipients = [
        item.strip()
        for item in os.environ["TEAM_EMAILS"].split(",")
        if item.strip()
    ]
    if not recipients:
        return {"skipped": True, "sent": False, "reason": "TEAM_EMAILS is empty."}

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USER"]
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as smtp:
        smtp.starttls()
        smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        smtp.send_message(message)

    return {"sent": True, "recipients": recipients}
