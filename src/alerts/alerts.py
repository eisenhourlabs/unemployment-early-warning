"""
Alerts (built, but OFF by default).

Turn on by setting ALERTS_ENABLED=true in config/.env (or as a GitHub secret), plus at least one channel:
  TEAMS_WEBHOOK_URL  - an incoming-webhook URL for a Teams channel, or
  ALERT_EMAIL_TO, SMTP_HOST, SMTP_USER, SMTP_PASSWORD - for email.

Phase 3 will call send_alert() when the early-warning score changes color or a red trigger fires.
While alerts are off, send_alert() just prints what it would have sent.
"""
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]


def _setting(name: str) -> str:
    """Read a setting from the environment first, then config/.env."""
    val = os.environ.get(name, "")
    env_file = ROOT / "config" / ".env"
    if not val and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(name + "="):
                val = line.split("=", 1)[1].strip()
    return val


def send_alert(subject: str, body: str) -> None:
    if _setting("ALERTS_ENABLED").lower() != "true":
        print(f"[alerts off] would send: {subject}\n{body}")
        return
    if webhook := _setting("TEAMS_WEBHOOK_URL"):
        requests.post(webhook, json={"text": f"**{subject}**\n\n{body}"}, timeout=30)
    if to := _setting("ALERT_EMAIL_TO"):
        msg = EmailMessage()
        msg["Subject"], msg["To"] = subject, to
        msg["From"] = _setting("SMTP_USER")
        msg.set_content(body)
        with smtplib.SMTP_SSL(_setting("SMTP_HOST") or "smtp.gmail.com", 465) as s:
            s.login(_setting("SMTP_USER"), _setting("SMTP_PASSWORD"))
            s.send_message(msg)


if __name__ == "__main__":
    send_alert("Test alert", "If alerts are off, this only prints.")
