"""Optional SMS delivery for KTT Power Plan.

Default behavior is safe dry-run logging. Real SMS sending is enabled only when
environment variables provide a supported provider and credentials.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib import parse, request


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "outputs"
OUTBOX_PATH = OUTPUT_DIR / "sms_outbox.jsonl"
LOCAL_RECIPIENTS_PATH = ROOT / "sms_recipients.local.json"


def _split_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def load_recipients() -> list[str]:
    """Load recipients without committing phone numbers to the repo."""
    env_recipients = _split_recipients(os.getenv("KTT_SMS_RECIPIENTS"))
    if env_recipients:
        return env_recipients
    if LOCAL_RECIPIENTS_PATH.exists():
        payload = json.loads(LOCAL_RECIPIENTS_PATH.read_text(encoding="utf-8"))
        return [str(item).strip() for item in payload.get("recipients", []) if str(item).strip()]
    return []


def outbox_entries(limit: int = 30) -> list[dict]:
    if not OUTBOX_PATH.exists():
        return []
    rows = []
    for line in OUTBOX_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows[-limit:]


def _write_outbox(entry: dict) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with OUTBOX_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def _twilio_send(to_number: str, message: str) -> dict:
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number = os.getenv("TWILIO_FROM_NUMBER")
    messaging_service_sid = os.getenv("TWILIO_MESSAGING_SERVICE_SID")
    if not account_sid or not auth_token or (not from_number and not messaging_service_sid):
        raise RuntimeError("Twilio is selected but TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER or TWILIO_MESSAGING_SERVICE_SID are not fully configured.")

    form = {"To": to_number, "Body": message}
    if messaging_service_sid:
        form["MessagingServiceSid"] = messaging_service_sid
    else:
        form["From"] = from_number

    body = parse.urlencode(form).encode("utf-8")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    req = request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with request.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {"provider": "twilio", "provider_status": payload.get("status"), "sid": payload.get("sid")}


def send_sms(to_number: str, message: str) -> dict:
    """Send one SMS or log it in dry-run mode."""
    provider = os.getenv("KTT_SMS_PROVIDER", "dry_run").strip().lower()
    entry = {
        "provider": provider,
        "to": to_number,
        "message": message,
        "characters": len(message),
    }
    if len(message) > 160:
        entry["status"] = "blocked"
        entry["error"] = "Message is longer than 160 characters."
        _write_outbox(entry)
        return entry

    try:
        if provider in {"", "dry_run", "dry-run", "log"}:
            entry["status"] = "dry_run"
        elif provider == "twilio":
            entry.update(_twilio_send(to_number, message))
            entry["status"] = "sent"
        else:
            entry["status"] = "blocked"
            entry["error"] = f"Unsupported KTT_SMS_PROVIDER: {provider}"
    except Exception as exc:  # noqa: BLE001 - keep dashboard resilient.
        entry["status"] = "failed"
        entry["error"] = str(exc)
    _write_outbox(entry)
    return entry


def send_digest(messages: list[dict | str], recipients: list[str] | None = None) -> dict:
    """Send the full morning digest to every configured recipient."""
    recipients = recipients if recipients is not None else load_recipients()
    normalized_messages = [
        item.get("message", "") if isinstance(item, dict) else str(item)
        for item in messages
    ]
    if not recipients:
        return {
            "status": "no_recipients",
            "provider": os.getenv("KTT_SMS_PROVIDER", "dry_run"),
            "sent_count": 0,
            "results": [],
            "message": "No recipients configured. Set KTT_SMS_RECIPIENTS or create sms_recipients.local.json.",
        }
    results = []
    for recipient in recipients:
        for message in normalized_messages:
            results.append(send_sms(recipient, message))
    sent_count = sum(1 for result in results if result.get("status") in {"sent", "dry_run"})
    return {
        "status": "ok",
        "provider": os.getenv("KTT_SMS_PROVIDER", "dry_run"),
        "recipients": recipients,
        "sent_count": sent_count,
        "results": results,
    }


if __name__ == "__main__":
    sample = [
        "KTT Power: Salon today. Highest risk 19:00-20:00. Keep lights, clippers and payments ready; delay dryer when alert is red.",
        "If outage hits: OFF dryer and straightener first. Keep lights, clippers, phone charging, payments; TV only if backup allows.",
        "No internet at 13:00? Use cached plan until 6h old. After that run critical-only mode: lights, clippers, phone and payments.",
    ]
    print(json.dumps(send_digest(sample), indent=2))
