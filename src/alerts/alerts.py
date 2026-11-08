"""
Alerts (built, but OFF by default).

Turn on by setting ALERTS_ENABLED=true in config/.env (or as a GitHub secret), plus at least one channel:
  TEAMS_WEBHOOK_URL  - an incoming-webhook URL for a Teams channel, or
  ALERT_EMAIL_TO, SMTP_HOST, SMTP_USER, SMTP_PASSWORD - for email.

Two alerts are wired (Phase 3e):
  - colour change of the early-warning score under the hysteresis rule: src/model/live.py calls send_alert();
  - failed refresh: the "Refresh data" workflow runs  python src/alerts/alerts.py --refresh-failed  when a step fails
    (it reads the workflow's step results from STEPS_JSON and the run link from RUN_URL).
While alerts are off, send_alert() just prints what it would have sent, so the workflow log shows the exact text.
In GitHub, alerts follow the repository VARIABLE ALERTS_ENABLED (Settings -> Secrets and variables -> Actions ->
Variables); when it is not set they are off.
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


def refresh_failed_message() -> tuple[str, str]:
    """The failed-refresh alert (design brief text): which step failed, and the date of the results still shown."""
    import json
    from datetime import datetime, timezone
    steps = json.loads(os.environ.get("STEPS_JSON") or "{}")
    failed = [name.replace("_", " ") for name, st in steps.items() if st.get("outcome") == "failure"]
    where = f'step "{failed[0]}"' + (f" (and {len(failed) - 1} more)" if len(failed) > 1 else "") if failed else "a step"
    try:
        last = json.loads((ROOT / "data" / "model" / "live_latest.json").read_text(encoding="utf-8"))["asof"]
        last_good = datetime.strptime(last, "%Y-%m-%d").strftime("%a %d %b %Y")
    except (OSError, ValueError, KeyError):
        last_good = "the last successful run"
    today = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    body = (f"The refresh run of {today} failed at {where}. The site still shows the results as of {last_good}.\n"
            f"Run log: {os.environ.get('RUN_URL', '(link not available)')}")
    return "Unemployment Watch: weekly refresh failed", body


if __name__ == "__main__":
    import sys
    if "--refresh-failed" in sys.argv:
        send_alert(*refresh_failed_message())
    else:
        send_alert("Test alert", "If alerts are off, this only prints.")
