"""Localhost dashboard for Grid Outage Planner.

Run:
    python dashboard.py

Then open:
    http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import platform
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse as urlparse_module
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlparse

import pandas as pd

from prioritizer import estimate_weekly_savings, plan, summarize_plan
from run_demo import OUTPUT_DIR, run_pipeline


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
REPORT_PATH = OUTPUT_DIR / "demo_report.json"
PLANS_PATH = OUTPUT_DIR / "plans_all.csv"
OUTBOX_PATH = OUTPUT_DIR / "sms_outbox.jsonl"
LOCAL_RECIPIENTS_PATH = ROOT / "sms_recipients.local.json"
VOICE_DIR = OUTPUT_DIR / "voice_notes"
INCOMING_SIGNALS_PATH = DATA_DIR / "incoming_signals.jsonl"
INCOMING_MEASUREMENTS_PATH = DATA_DIR / "incoming_measurements.csv"
REPORT_LOCK = threading.RLock()


def _split_recipients(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]


def load_recipients() -> list[str]:
    env_recipients = _split_recipients(os.getenv("POWERPLAN_SMS_RECIPIENTS"))
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
        raise RuntimeError("Twilio credentials are incomplete.")

    form = {"To": to_number, "Body": message}
    if messaging_service_sid:
        form["MessagingServiceSid"] = messaging_service_sid
    else:
        form["From"] = from_number

    body = urlparse_module.urlencode(form).encode("utf-8")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    auth = base64.b64encode(f"{account_sid}:{auth_token}".encode("utf-8")).decode("ascii")
    req = urlrequest.Request(
        url,
        data=body,
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {"provider": "twilio", "provider_status": payload.get("status"), "sid": payload.get("sid")}


def send_sms(to_number: str, message: str) -> dict:
    provider = os.getenv("POWERPLAN_SMS_PROVIDER", "dry_run").strip().lower()
    entry = {"provider": provider, "to": to_number, "message": message, "characters": len(message)}
    if len(message) > 160:
        entry.update({"status": "blocked", "error": "Message is longer than 160 characters."})
        _write_outbox(entry)
        return entry

    try:
        if provider in {"", "dry_run", "dry-run", "log"}:
            entry["status"] = "dry_run"
        elif provider == "twilio":
            entry.update(_twilio_send(to_number, message))
            entry["status"] = "sent"
        else:
            entry.update({"status": "blocked", "error": f"Unsupported POWERPLAN_SMS_PROVIDER: {provider}"})
    except Exception as exc:
        entry.update({"status": "failed", "error": str(exc)})
    _write_outbox(entry)
    return entry


def send_digest(messages: list[dict | str], recipients: list[str] | None = None) -> dict:
    recipients = recipients if recipients is not None else load_recipients()
    normalized_messages = [item.get("message", "") if isinstance(item, dict) else str(item) for item in messages]
    if not recipients:
        return {
            "status": "no_recipients",
            "provider": os.getenv("POWERPLAN_SMS_PROVIDER", "dry_run"),
            "sent_count": 0,
            "results": [],
            "message": "No recipients configured. Set POWERPLAN_SMS_RECIPIENTS or create sms_recipients.local.json.",
        }
    results = []
    for recipient in recipients:
        for message in normalized_messages:
            results.append(send_sms(recipient, message))
    sent_count = sum(1 for result in results if result.get("status") in {"sent", "dry_run"})
    return {
        "status": "ok",
        "provider": os.getenv("POWERPLAN_SMS_PROVIDER", "dry_run"),
        "recipients": recipients,
        "sent_count": sent_count,
        "results": results,
    }


def _clean_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_") or "business"


def _format_list(items: list[str]) -> str:
    if not items:
        return "nothing"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return items[0] + " and " + items[1]
    return ", ".join(items[:-1]) + ", and " + items[-1]


def build_voice_prompt(report: dict, business: str = "salon") -> dict:
    businesses = report.get("businesses", {})
    business_info = businesses.get(business, {"display_name": business})
    display_name = business_info.get("display_name", business.replace("_", " "))
    worst_label = report.get("worst_forecast_window", {}).get("label", "the highest risk hour")
    decisions = report.get("decision_summary", {}).get(business, [])
    high_risk_decision = next((row for row in decisions if row.get("off")), decisions[0] if decisions else {})
    off_items = high_risk_decision.get("off", [])
    on_items = high_risk_decision.get("on", [])
    if not on_items:
        plans = report.get("plans", {}).get(business, [])
        if plans:
            first_ts = plans[0]["timestamp"]
            on_items = [row["appliance"] for row in plans if row["timestamp"] == first_ts and row["status"] == "ON"]

    stale_hours = report.get("offline_policy", {}).get("maximum_staleness_hours", 6)
    transcript = (
        f"Power Plan voice note for {display_name}. "
        f"Highest outage risk is {worst_label}. "
        f"Switch off {_format_list(off_items)} first. "
        f"Keep {_format_list(on_items)} on. "
        f"If internet is not available, use the cached plan for {stale_hours} hours. "
        "After that, use critical only mode."
    )
    return {
        "business": business,
        "display_name": display_name,
        "transcript": transcript,
        "characters": len(transcript),
        "offline_mode": f"cached plan for {stale_hours} hours, then critical-only mode",
    }


def _sapi_script(transcript: str, output_path: Path) -> str:
    safe_text = transcript.replace("'", "''")
    safe_path = str(output_path).replace("'", "''")
    return (
        "Add-Type -AssemblyName System.Speech; "
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$synth.Rate = -1; $synth.Volume = 100; "
        f"$synth.SetOutputToWaveFile('{safe_path}'); "
        f"$synth.Speak('{safe_text}'); "
        "$synth.Dispose();"
    )


def generate_voice_note(report: dict, business: str = "salon") -> dict:
    prompt = build_voice_prompt(report, business)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    wav_path = VOICE_DIR / f"{_clean_name(business)}_{timestamp}.wav"
    manifest_path = wav_path.with_suffix(".json")
    result = {
        **prompt,
        "status": "transcript_only",
        "audio_path": None,
        "audio_url": None,
        "manifest_path": str(manifest_path),
        "engine": "browser_speech_or_transcript",
    }
    if platform.system().lower() == "windows":
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _sapi_script(prompt["transcript"], wav_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode == 0 and wav_path.exists():
            result.update(
                {
                    "status": "audio_generated",
                    "audio_path": str(wav_path),
                    "audio_url": f"/voice_notes/{wav_path.name}",
                    "engine": "windows_sapi",
                }
            )
        else:
            result["error"] = (completed.stderr or completed.stdout or "Windows speech synthesis failed.").strip()
    manifest_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def _atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def _read_report_file() -> dict:
    raw = REPORT_PATH.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError("Report file is empty")
    return json.loads(raw)


def _load_or_build_report_unlocked(rebuild: bool = False) -> dict:
    if rebuild or not REPORT_PATH.exists():
        report = ensure_runtime_fields(run_pipeline(clean=True))
        report = apply_saved_incoming_signals(report)
        save_report(report)
        return report
    try:
        report = _read_report_file()
    except (OSError, ValueError, json.JSONDecodeError):
        report = ensure_runtime_fields(run_pipeline(clean=True))
        report = apply_saved_incoming_signals(report)
        save_report(report)
    return ensure_runtime_fields(report)


def load_or_build_report(rebuild: bool = False) -> dict:
    with REPORT_LOCK:
        return _load_or_build_report_unlocked(rebuild=rebuild)


def rebuild_report(regenerate_data: bool = False) -> dict:
    with REPORT_LOCK:
        report = ensure_runtime_fields(run_pipeline(regenerate_data=regenerate_data, clean=True))
        report = apply_saved_incoming_signals(report)
        save_report(report)
        return report


def save_report(report: dict) -> None:
    _atomic_write_json(REPORT_PATH, report)


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def load_incoming_signals(limit: int = 40) -> list[dict]:
    if not INCOMING_SIGNALS_PATH.exists():
        return []
    rows = []
    for line in INCOMING_SIGNALS_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]


def _as_float(payload: dict, key: str, default: float = 0.0) -> float:
    try:
        return float(payload.get(key, default))
    except (TypeError, ValueError):
        return default


def save_grid_measurement(payload: dict) -> dict:
    timestamp = payload.get("timestamp") or pd.Timestamp.now(tz="UTC").isoformat()
    fields = [
        "received_at",
        "timestamp",
        "load_mw",
        "temp_c",
        "humidity",
        "wind_ms",
        "rain_mm",
        "voltage_drop_index",
        "feeder_congestion_index",
        "maintenance_flag",
        "neighbor_outage_reports",
        "reserve_margin_index",
        "asset_health_index",
        "source",
        "notes",
    ]
    row = {field: payload.get(field, "") for field in fields}
    row["received_at"] = pd.Timestamp.now(tz="UTC").isoformat()
    row["timestamp"] = timestamp
    row["source"] = payload.get("source", "incoming_api")
    INCOMING_MEASUREMENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_header = not INCOMING_MEASUREMENTS_PATH.exists()
    with INCOMING_MEASUREMENTS_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    return row


def measurement_to_event(row: dict, payload: dict) -> dict:
    try:
        ts = pd.Timestamp(row.get("timestamp") or pd.Timestamp.now(tz="UTC"))
    except (TypeError, ValueError):
        ts = pd.Timestamp.now(tz="UTC")
    load_boost = max(0.0, (_as_float(payload, "load_mw", 50.0) - 58.0) / 35.0) * 0.06
    rain_boost = min(_as_float(payload, "rain_mm", 0.0) / 30.0, 1.0) * 0.06
    voltage_boost = min(_as_float(payload, "voltage_drop_index", 0.0), 1.0) * 0.10
    feeder_boost = min(_as_float(payload, "feeder_congestion_index", 0.0), 1.0) * 0.08
    neighbor_boost = min(_as_float(payload, "neighbor_outage_reports", 0.0) / 3.0, 1.0) * 0.08
    maintenance_boost = min(_as_float(payload, "maintenance_flag", 0.0), 1.0) * 0.06
    p_boost = min(0.25, max(0.04, load_boost + rain_boost + voltage_boost + feeder_boost + neighbor_boost + maintenance_boost))
    parts = []
    if payload.get("load_mw") is not None:
        parts.append(f"load {payload.get('load_mw')} MW")
    if payload.get("rain_mm") is not None:
        parts.append(f"rain {payload.get('rain_mm')} mm")
    if payload.get("voltage_drop_index") is not None:
        parts.append(f"voltage stress {payload.get('voltage_drop_index')}")
    return {
        "type": payload.get("type", "incoming_measurement"),
        "title": payload.get("title", "Incoming grid measurement"),
        "message": payload.get("message", "Saved incoming grid data: " + (", ".join(parts) if parts else "new measurement")),
        "duration_hours": int(payload.get("duration_hours", 2)),
        "p_boost": float(payload.get("p_boost", p_boost)),
        "start_hour": payload.get("start_hour", f"{ts.hour:02d}"),
        "source": payload.get("source", "incoming_measurement"),
    }


def is_measurement_payload(payload: dict) -> bool:
    measurement_keys = {"load_mw", "temp_c", "humidity", "wind_ms", "rain_mm", "voltage_drop_index", "feeder_congestion_index"}
    return payload.get("record_type") == "grid_measurement" or bool(measurement_keys.intersection(payload))


def ensure_runtime_fields(report: dict) -> dict:
    report.setdefault("revision", 1)
    report.setdefault("live_events", [])
    report.setdefault("last_event", None)
    report["incoming_signals"] = load_incoming_signals()
    return report


def worst_window(forecast: list[dict]) -> dict:
    row = max(forecast, key=lambda item: float(item["risk_minutes"]))
    ts = pd.Timestamp(row["timestamp"])
    return {
        "start": ts.strftime("%H:%M"),
        "end": (ts + pd.Timedelta(hours=1)).strftime("%H:%M"),
        "label": f"{ts:%H:%M}-{(ts + pd.Timedelta(hours=1)):%H:%M}",
        "p_outage": round(float(row["p_outage"]), 4),
        "risk_minutes": round(float(row["risk_minutes"]), 2),
    }


def sms_digest(worst: dict) -> list[dict]:
    messages = [
        f"Power Plan: Salon today. Highest risk {worst['label']}. Keep lights, clippers and payments ready; delay dryer when alert is red.",
        "If outage hits: OFF dryer and straightener first. Keep lights, clippers, phone charging, payments; TV only if backup allows.",
        "No internet at 13:00? Use cached plan until 6h old. After that run critical-only mode: lights, clippers, phone and payments.",
    ]
    return [{"message": message, "characters": len(message)} for message in messages]


def decision_summary(plan_df: pd.DataFrame) -> list[dict]:
    grouped = []
    for ts, rows in plan_df.groupby("timestamp"):
        off = rows[rows["status"] == "OFF"]["appliance"].tolist()
        on = rows[rows["status"] == "ON"]["appliance"].tolist()
        grouped.append(
            {
                "timestamp": pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M"),
                "off": off,
                "on": on,
                "action": "All appliances ON" if not off else "Switch OFF: " + ", ".join(off),
            }
        )
    return grouped


def records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")
    return out.to_dict(orient="records")


def event_start_index(forecast: list[dict], event: dict) -> int:
    if event.get("start_index") is not None:
        return max(0, min(int(event["start_index"]), len(forecast) - 1))
    if event.get("start_hour") is not None:
        target = str(event["start_hour"])[:2]
        for idx, row in enumerate(forecast):
            if row["timestamp"][11:13] == target:
                return idx
    return max(range(len(forecast)), key=lambda idx: float(forecast[idx]["risk_minutes"]))


def apply_event_to_forecast(report: dict, event: dict) -> None:
    forecast = report["forecast"]
    start = event_start_index(forecast, event)
    duration = max(1, min(int(event.get("duration_hours", 3)), 24))
    boost = float(event.get("p_boost", 0.18))
    for offset, idx in enumerate(range(start, min(start + duration, len(forecast)))):
        decay = max(0.45, 1.0 - 0.18 * offset)
        row = forecast[idx]
        old_p = float(row["p_outage"])
        new_p = min(0.98, max(0.0, old_p + boost * decay))
        row["p_outage"] = round(new_p, 4)
        row["p_low"] = round(max(0.0, float(row["p_low"]) + boost * decay * 0.55), 4)
        row["p_high"] = round(min(1.0, float(row["p_high"]) + boost * decay), 4)
        row["risk_minutes"] = round(new_p * float(row["expected_duration_min"]), 2)
        row["top_risk_factor"] = event.get("type", "live_alert")
        row["risk_explanation"] = f"Live alert added: {event.get('message', 'new local signal')}"


def rebuild_decisions(report: dict) -> None:
    forecast_df = pd.DataFrame(report["forecast"])
    appliances = report["appliances"]
    businesses = report["businesses"]
    plans = {}
    summaries = {}
    impact = {}
    all_plans = []
    for name, business in businesses.items():
        plan_df = plan(forecast_df, appliances, business)
        plan_df.insert(0, "business", name)
        plans[name] = records(plan_df)
        summaries[name] = summarize_plan(plan_df)
        impact[name] = estimate_weekly_savings(plan_df)
        all_plans.append(plan_df)
    report["plans"] = plans
    report["summaries"] = summaries
    report["impact"] = impact
    report["decision_summary"] = {name: decision_summary(pd.DataFrame(rows)) for name, rows in plans.items()}
    report["worst_forecast_window"] = worst_window(report["forecast"])
    report["sms_digest"] = sms_digest(report["worst_forecast_window"])
    pd.concat(all_plans, ignore_index=True).to_csv(PLANS_PATH, index=False)


def apply_saved_incoming_signals(report: dict, limit: int = 8) -> dict:
    signals = [row for row in load_incoming_signals(limit) if row.get("source") != "dashboard_simulation"]
    if not signals:
        return ensure_runtime_fields(report)
    report["live_events"] = []
    for idx, signal in enumerate(signals, start=1):
        event = dict(signal)
        event["id"] = f"saved-{idx}"
        apply_event_to_forecast(report, event)
        report["live_events"].append(event)
    report["last_event"] = report["live_events"][-1]
    report["incoming_signals"] = load_incoming_signals()
    report["revision"] = int(report.get("revision", 1)) + 1
    rebuild_decisions(report)
    return ensure_runtime_fields(report)


def add_live_event(event: dict, persist: bool = True) -> dict:
    with REPORT_LOCK:
        report = _load_or_build_report_unlocked()
        now = pd.Timestamp.now(tz="UTC").isoformat()
        event = {
            "id": f"event-{len(report.get('live_events', [])) + 1}",
            "created_at": now,
            "type": event.get("type", "neighbor_outage"),
            "title": event.get("title", "Live outage alert"),
            "message": event.get("message", "New local signal raised outage risk in the planning window."),
            "duration_hours": int(event.get("duration_hours", 3)),
            "p_boost": float(event.get("p_boost", 0.18)),
            "start_hour": event.get("start_hour"),
            "start_index": event.get("start_index"),
            "source": event.get("source", "dashboard_api"),
        }
        if persist:
            _append_jsonl(INCOMING_SIGNALS_PATH, event)
        apply_event_to_forecast(report, event)
        report["live_events"].append(event)
        report["last_event"] = event
        report["incoming_signals"] = load_incoming_signals()
        report["revision"] = int(report.get("revision", 1)) + 1
        report["generated_at"] = now
        rebuild_decisions(report)
        save_report(report)
        return report


def ingest_incoming_data(payload: dict) -> dict:
    if is_measurement_payload(payload):
        measurement = save_grid_measurement(payload)
        event = measurement_to_event(measurement, payload)
        report = add_live_event(event, persist=True)
        report["ingestion_status"] = {
            "status": "saved_and_applied",
            "record_type": "grid_measurement",
            "saved_to": str(INCOMING_MEASUREMENTS_PATH),
            "event": report.get("last_event"),
        }
        return report
    event = dict(payload)
    event.setdefault("source", "incoming_api")
    report = add_live_event(event, persist=True)
    report["ingestion_status"] = {
        "status": "saved_and_applied",
        "record_type": "alert",
        "saved_to": str(INCOMING_SIGNALS_PATH),
        "event": report.get("last_event"),
    }
    return report


def dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grid Outage Planner Dashboard</title>
<style>
:root{--ink:#17212b;--muted:#60707d;--line:#d9e2e8;--panel:#fff;--bg:#f4f7f8;--rail:#11191f;--rail2:#172229;--teal:#006d77;--green:#2a9d8f;--red:#d95f5f;--amber:#f4a261;--blue:#457b9d}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Arial,Helvetica,sans-serif;color:var(--ink);background:var(--bg)}header{background:#fff;border-bottom:1px solid var(--line);padding:12px 18px;position:sticky;top:0;z-index:5}h1{font-size:22px;margin:0 0 3px;letter-spacing:0}h2{font-size:17px;margin:0}h3{font-size:14px;margin:12px 0 7px}p{line-height:1.42}.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.controls{display:flex;gap:7px;align-items:center;flex-wrap:wrap}select,button{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:#fff}button{background:var(--teal);color:#fff;border-color:var(--teal);cursor:pointer}main{max-width:1440px;margin:0 auto;padding:12px}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.tabs a{font-size:13px;text-decoration:none;color:#15323a;background:#e9f2f3;border:1px solid #d0e2e5;padding:6px 10px;border-radius:6px}.layout{display:grid;grid-template-columns:250px 1fr;gap:12px}.side{background:var(--rail);color:#dce7eb;border-radius:8px;padding:12px;position:sticky;top:92px;align-self:start;max-height:calc(100vh - 105px);overflow:auto}.side h2,.side h3{color:#fff}.side .muted{color:#9eb1bb}.content{min-width:0}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:9px}.two{display:grid;grid-template-columns:1.35fr .65fr;gap:12px}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:0;margin-bottom:10px;overflow:hidden}.panel>summary{list-style:none;cursor:pointer;padding:12px 14px;font-weight:bold;display:flex;justify-content:space-between;gap:12px;align-items:center;background:#fbfdfe;border-bottom:1px solid var(--line)}.panel>summary::-webkit-details-marker{display:none}.panel>summary:after{content:"+";font-size:18px;color:var(--teal)}.panel[open]>summary:after{content:"-"}details.panel>*:not(summary){margin-left:14px;margin-right:14px}.panel-pad{padding:12px 14px}.kpi{background:#fff;border:1px solid var(--line);border-left:5px solid var(--teal);padding:9px;border-radius:7px}.kpi b{display:block;font-size:19px;margin-top:3px}.muted{color:var(--muted);font-size:13px}.caption{color:var(--muted);font-size:13px;margin:8px 0 12px}.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#edf5f6;color:#124f57;font-size:12px;margin:2px}.risk-high{background:#ffe9e4;color:#8a231a}.risk-ok{background:#e7f6f2;color:#1d6a60}canvas{width:100%;height:260px;border:1px solid var(--line);border-radius:6px;background:#fff}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}th{background:#f2f6f8}.heat th,.heat td{text-align:center;white-space:nowrap}.heat th:first-child,.heat td:first-child{position:sticky;left:0;background:#fff;text-align:left;z-index:1}.on{background:var(--green);color:#fff;font-weight:bold}.off{background:var(--red);color:#fff;font-weight:bold}.sms{font-family:Consolas,monospace;background:#f3f6f7;padding:9px;border-radius:6px}.decision,.signal{border-left:4px solid var(--amber);padding:8px 10px;background:#fffaf3;margin:8px 0}.signal{background:#152229;border-color:#2a9d8f;color:#dce7eb}.signal b{color:#fff}.small-list{max-height:300px;overflow:auto}.status-strip{display:grid;grid-template-columns:repeat(12,1fr);gap:5px;margin:8px 0 12px}.dot{width:12px;height:12px;border-radius:50%;display:inline-block;background:#2a9d8f}.dot.amber{background:#f4a261}.dot.red{background:#d95f5f}.side-note{font-size:12px;border-top:1px solid #2d3b44;border-bottom:1px solid #2d3b44;padding:9px 0;margin:8px 0 12px}.summary-note{font-weight:normal;color:var(--muted);font-size:12px}@media(max-width:980px){.grid,.two,.layout{grid-template-columns:1fr}.side{position:static;max-height:none}header{position:static}canvas{height:230px}}
</style>
</head>
<body>
<header>
  <div class="top">
    <div>
      <h1>Grid Outage Planner Dashboard</h1>
      <div class="muted">Local dashboard for outage risk, appliance decisions, SMS digest, and business impact.</div>
    </div>
    <div class="controls">
      <label for="business">Business</label>
      <select id="business"></select>
      <button id="simulate">Simulate new alert</button>
      <button id="playVoice">Play voice prompt</button>
      <button id="saveVoice">Save voice note</button>
      <button id="sendSms">Send SMS digest</button>
      <button id="refresh">Clear/rebuild</button>
    </div>
    <div class="muted" id="liveStatus">Auto update: waiting</div>
  </div>
</header>
<main>
  <section class="grid" id="kpis"></section>
  <nav class="tabs" aria-label="Dashboard sections">
    <a href="#overview">Overview</a>
    <a href="#plan">Appliance plan</a>
    <a href="#channels">SMS and voice</a>
    <a href="#signals">Incoming data</a>
    <a href="#evidence">Evidence</a>
    <a href="#technical">Technical checks</a>
  </nav>
  <div class="layout">
    <aside class="side">
      <h2>Live monitor</h2>
      <div class="muted">24 hourly risk dots</div>
      <div id="statusStrip" class="status-strip"></div>
      <div class="side-note">Green is low risk, amber is prepare, red is high risk. The dashboard checks for updates every 3 seconds.</div>
      <h3>Incoming data inbox</h3>
      <div id="incoming"></div>
      <h3>Active alerts</h3>
      <div id="events"></div>
    </aside>
    <section class="content">
      <details class="panel" id="overview" open>
        <summary>Overview <span class="summary-note">Forecast, business risk, and highest-risk window</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>24-hour risk forecast</h2>
            <canvas id="forecast" width="1000" height="300"></canvas>
            <p class="caption">Plain meaning: the line shows outage risk. The shaded band shows uncertainty. Orange bars show expected minutes at risk.</p>
          </div>
          <div>
            <h2>Today's main insight</h2>
            <div id="insight"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="plan" open>
        <summary>Appliance ON/OFF plan <span class="summary-note">Actionable decisions for each hour</span></summary>
        <div class="panel-pad">
          <div class="table-wrap heat" id="heat"></div>
          <p class="caption">Green means keep ON. Red means switch OFF first. The rule is fixed: luxury before comfort before critical.</p>
        </div>
      </details>
      <details class="panel" id="channels">
        <summary>SMS and voice actions <span class="summary-note">Feature-phone and non-reader workflow</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>SMS digest</h2>
            <div id="sms"></div>
            <div id="smsStatus" class="muted"></div>
            <h3>SMS outbox</h3>
            <div id="outbox"></div>
          </div>
          <div>
            <h2>Voice note</h2>
            <div id="voiceStatus" class="decision">Voice prompt not played yet.</div>
            <h3>Offline rule</h3>
            <div id="offline"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="signals">
        <summary>Incoming data and alert API <span class="summary-note">Saved and applied to the current plan</span></summary>
        <div class="panel-pad">
          <p>Incoming alerts are saved to <b>data/incoming_signals.jsonl</b>. Incoming grid measurements are saved to <b>data/incoming_measurements.csv</b> and converted into a risk signal.</p>
          <pre class="sms">POST http://127.0.0.1:8000/api/incoming_data
{"type":"rain_shock","message":"Heavy rain near feeder","p_boost":0.12,"duration_hours":4,"start_hour":"18"}</pre>
          <pre class="sms">POST http://127.0.0.1:8000/api/incoming_data
{"record_type":"grid_measurement","timestamp":"2026-04-23T18:00:00+02:00","load_mw":72,"rain_mm":18,"voltage_drop_index":0.7}</pre>
        </div>
      </details>
      <details class="panel" id="evidence">
        <summary>Evidence and ground realities <span class="summary-note">Why risk rises and how local constraints are handled</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>Why outage risk rises</h2>
            <div id="factors"></div>
          </div>
          <div>
            <h2>Ground realities implemented</h2>
            <div id="realities"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="technical">
        <summary>Technical checks and parameters <span class="summary-note">For evaluators who want detail</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>Decision list</h2>
            <div class="small-list" id="decisions"></div>
            <h2>Forecast quality checks</h2>
            <div id="quality"></div>
            <p class="caption">These numbers are included for technical judges. A business owner only needs the time window and appliance actions.</p>
          </div>
          <div>
            <h2>Business parameters</h2>
            <div id="businessParams"></div>
            <h3>Appliance parameters</h3>
            <div class="table-wrap" id="applianceParams"></div>
          </div>
        </div>
      </details>
    </section>
  </div>
</main>
<script>
let report=null,lastRevision=null,isBusy=false;
function fmt(n,d=0){return Number(n).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d})}
function money(n){return fmt(n,0)+" RWF"}
function byId(id){return document.getElementById(id)}
async function loadReport(rebuild=false){
  if(isBusy){return}
  isBusy=true;
  byId("liveStatus").textContent=rebuild?"Rebuilding forecast and appliance plans...":"Loading dashboard report...";
  try{
    const res=await fetch(rebuild?"/api/rebuild":"/api/report");
    if(!res.ok){throw new Error("HTTP "+res.status)}
    report=await res.json();
    setupBusiness();
    lastRevision=report.revision||1;
    render();
    byId("liveStatus").textContent=(rebuild?"Rebuild complete. ":"Auto update: connected. ")+"Last revision "+lastRevision;
  }catch(err){
    byId("liveStatus").textContent="Could not load report: "+err.message;
  }finally{
    isBusy=false;
  }
}
async function pollReport(){
  if(isBusy){return}
  try{
    const res=await fetch("/api/report");
    if(!res.ok){throw new Error("HTTP "+res.status)}
    const next=await res.json();
    if(!report || (next.revision||1)!==lastRevision){
      const current=byId("business").value;
      report=next; lastRevision=next.revision||1; setupBusiness(); byId("business").value=report.businesses[current]?current:"salon"; render();
      byId("liveStatus").textContent="Auto update: refreshed revision "+lastRevision+" at "+new Date().toLocaleTimeString();
    }
  }catch(err){
    byId("liveStatus").textContent="Auto update: waiting; last request failed: "+err.message;
  }
}
async function simulateEvent(){
  const res=await fetch("/api/simulate_event");
  report=await res.json();
  setupBusiness();
  lastRevision=report.revision||1;
  render();
  byId("liveStatus").textContent="Auto update: new alert applied at "+new Date().toLocaleTimeString();
}
async function sendSmsDigest(){
  byId("smsStatus").textContent="Sending SMS digest...";
  const res=await fetch("/api/send_sms_digest",{method:"POST"});
  const payload=await res.json();
  byId("smsStatus").textContent=payload.message||("SMS status: "+payload.status+", provider "+payload.provider+", count "+payload.sent_count);
  renderOutbox(payload.outbox||[]);
}
async function playVoicePrompt(){
  const b=byId("business").value;
  const res=await fetch("/api/voice_prompt?business="+encodeURIComponent(b));
  const payload=await res.json();
  byId("voiceStatus").innerHTML="<b>Voice transcript</b><br>"+payload.transcript;
  if("speechSynthesis" in window){
    window.speechSynthesis.cancel();
    const utterance=new SpeechSynthesisUtterance(payload.transcript);
    utterance.rate=.92;
    utterance.lang="en-US";
    window.speechSynthesis.speak(utterance);
  }else{
    byId("voiceStatus").innerHTML+="<br><span class='muted'>Browser speech is not available. Read this transcript aloud.</span>";
  }
}
async function saveVoiceNote(){
  const b=byId("business").value;
  byId("voiceStatus").textContent="Generating voice note...";
  const res=await fetch("/api/generate_voice_note?business="+encodeURIComponent(b),{method:"POST"});
  const payload=await res.json();
  const link=payload.audio_url?`<p><audio controls src="${payload.audio_url}"></audio></p><p><a href="${payload.audio_url}" download>Download WAV voice note</a></p>`:"<p class='muted'>Audio file was not generated on this machine; transcript is ready for browser speech or manual recording.</p>";
  byId("voiceStatus").innerHTML=`<b>${payload.status}</b><br>${payload.transcript}${link}`;
}
function setupBusiness(){
  const sel=byId("business");
  const current=sel.value||"salon";
  sel.innerHTML=Object.keys(report.businesses).map(k=>`<option value="${k}">${report.businesses[k].display_name||k}</option>`).join("");
  sel.value=report.businesses[current]?current:"salon";
}
function riskClass(p){return p>=0.1?"risk-high":"risk-ok"}
function render(){
  const b=byId("business").value;
  const biz=report.businesses[b], impact=report.impact[b], summary=report.summaries[b];
  byId("kpis").innerHTML=[
    ["Worst risk window",report.worst_forecast_window.label,Math.round(report.worst_forecast_window.p_outage*100)+"% outage risk"],
    ["Weekly value protected",money(impact.weekly_expected_saved_rwf),"Expected preserved revenue"],
    ["Actions produced",summary.off_appliance_hours+" OFF blocks",summary.appliance_hours+" appliance-hours checked"],
    ["Live alerts",String((report.live_events||[]).length),"Dashboard checks for updates every 3 seconds"]
  ].map(k=>`<div class="kpi"><span>${k[0]}</span><b>${k[1]}</b><div class="muted">${k[2]}</div></div>`).join("");
  renderStatusStrip();
  renderForecast();
  renderInsight(b);
  renderHeat(b);
  renderIncoming();
  renderEvents();
  renderOutbox(report.sms_outbox||[]);
  renderFactors();
  renderRealities();
  renderDecisions(b);
  renderParams(b);
  renderQuality();
  renderOffline();
}
function renderInsight(b){
  const worst=report.worst_forecast_window;
  const impact=report.impact[b];
  byId("insight").innerHTML=`<p><span class="pill ${riskClass(worst.p_outage)}">Highest risk ${worst.label}</span></p>
  <p>The dashboard recommends preparing for the highest-risk hour by protecting critical appliances and delaying high-power comfort/luxury appliances.</p>
  <p><b>Expected weekly value protected:</b> ${money(impact.weekly_expected_saved_rwf)}.</p>`;
  byId("sms").innerHTML=report.sms_digest.map((s,i)=>`<p class="sms">${i+1}. ${s.message}<br><span class="muted">${s.characters}/160 characters</span></p>`).join("");
}
function renderEvents(){
  const events=(report.live_events||[]).slice(-4).reverse();
  byId("events").innerHTML=events.length?events.map(e=>`<div class="decision"><b>${e.title}</b><br>${e.message}<br><span class="muted">${e.created_at}; +${Math.round(e.p_boost*100)} points for ${e.duration_hours}h</span></div>`).join(""):"<p class='muted'>No live alert yet. Click Simulate new alert or POST to /api/event.</p>";
}
function renderIncoming(){
  const rows=(report.incoming_signals||[]).slice(-8).reverse();
  byId("incoming").innerHTML=rows.length?rows.map(e=>`<div class="signal"><b>${e.type||"signal"}</b><br>${e.message||e.title||"Incoming data saved"}<br><span class="muted">${e.created_at||""} ${e.source?("source: "+e.source):""}</span></div>`).join(""):"<p class='muted'>No saved incoming data yet. Use /api/incoming_data or Simulate new alert.</p>";
}
function renderStatusStrip(){
  byId("statusStrip").innerHTML=report.forecast.map(row=>{
    const p=Number(row.p_outage||0);
    const cls=p>=0.35?"red":(p>=0.10?"amber":"");
    return `<span class="dot ${cls}" title="${row.timestamp.slice(11)} risk ${Math.round(p*100)}%"></span>`;
  }).join("");
}
function renderOutbox(entries){
  const rows=(entries||[]).slice(-6).reverse();
  byId("outbox").innerHTML=rows.length?rows.map(e=>`<div class="decision"><b>${e.status}</b> to ${e.to||"not set"}<br>${e.message||""}<br><span class="muted">${e.provider||""} ${e.error?("error: "+e.error):""}</span></div>`).join(""):"<p class='muted'>No SMS sent yet. Dry-run mode logs messages here.</p>";
}
function renderFactors(){
  const worst=report.forecast.slice().sort((a,b)=>b.risk_minutes-a.risk_minutes).slice(0,6);
  const counts=report.factor_summary.driver_counts_on_outage_hours||{};
  const countRows=Object.entries(counts).map(([k,v])=>`<tr><td>${k.replaceAll("_"," ")}</td><td>${v}</td></tr>`).join("")||"<tr><td>No outage drivers recorded</td><td>0</td></tr>";
  const groups=((report.outage_taxonomy||{}).driver_groups||[]).slice(0,10);
  const groupRows=groups.map(g=>`<tr><td>${g.group}</td><td>${g.prototype_fields.join(", ")}</td></tr>`).join("");
  byId("factors").innerHTML=`<p>Outage risk is not based on appliances. It uses grid and weather signals such as load, rain, wind, voltage drops, feeder congestion, maintenance, and neighbor reports.</p>
  <h3>Top future drivers</h3>
  <div class="small-list">${worst.map(r=>`<div class="decision"><b>${r.timestamp.slice(11)}</b>: ${String(r.top_risk_factor||"routine").replaceAll("_"," ")}<br><span class="muted">${r.risk_explanation||""}</span></div>`).join("")}</div>
  <h3>Broader taxonomy mapped into this prototype</h3>
  <table><tbody>${groupRows}</tbody></table>
  <h3>Drivers seen in outage history</h3>
  <table><tbody>${countRows}</tbody></table>`;
}
function renderRealities(){
  byId("realities").innerHTML=`<table><tbody>
  <tr><th>Low bandwidth</th><td>Static lite page under 50 KB plus SMS digest. Consolidated report avoids many files.</td></tr>
  <tr><th>Intermittent power/internet</th><td>Plan is cached. It is trusted for 6 hours, then switches to critical-only mode.</td></tr>
  <tr><th>Non-smartphone user</th><td>Salon owner receives 3 SMS messages, each under 160 characters.</td></tr>
  <tr><th>Multiple languages</th><td>Messages use simple appliance names and support English/Kinyarwanda templates. Dashboard avoids jargon.</td></tr>
  <tr><th>Illiteracy</th><td>Workflow supports colored LEDs and voice prompt: green ON, red OFF, amber prepare.</td></tr>
  </tbody></table>`;
}
function renderForecast(){
  const c=byId("forecast"),ctx=c.getContext("2d"),w=c.width,h=c.height,pad=44,f=report.forecast;
  ctx.clearRect(0,0,w,h); ctx.font="12px Arial"; ctx.strokeStyle="#d9e1e7"; ctx.lineWidth=1;
  for(let i=0;i<=4;i++){let y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke();ctx.fillStyle="#5a6772";ctx.fillText(((4-i)*25)+"%",8,y+4)}
  const maxRisk=Math.max(...f.map(x=>x.risk_minutes),1), sx=i=>pad+i*(w-2*pad)/(f.length-1), sy=p=>h-pad-p*(h-2*pad);
  f.forEach((row,i)=>{let bh=(row.risk_minutes/maxRisk)*(h-2*pad)*.45;ctx.fillStyle="rgba(244,162,97,.45)";ctx.fillRect(sx(i)-8,h-pad-bh,16,bh)});
  ctx.beginPath();f.forEach((row,i)=>{let y=sy(row.p_high);if(i===0)ctx.moveTo(sx(i),y);else ctx.lineTo(sx(i),y)});
  [...f].reverse().forEach((row,j)=>{let i=f.length-1-j;ctx.lineTo(sx(i),sy(row.p_low))});ctx.closePath();ctx.fillStyle="rgba(168,218,220,.6)";ctx.fill();
  ctx.beginPath();f.forEach((row,i)=>{let y=sy(row.p_outage);if(i===0)ctx.moveTo(sx(i),y);else ctx.lineTo(sx(i),y)});ctx.strokeStyle="#006d77";ctx.lineWidth=3;ctx.stroke();
  ctx.fillStyle="#16202a";f.forEach((row,i)=>{if(i%3===0){ctx.fillText(row.timestamp.slice(11),sx(i)-14,h-15)}});
}
function renderHeat(b){
  const plan=report.plans[b], hours=report.forecast.map(f=>f.timestamp.slice(11)), apps=[...new Set(plan.map(p=>p.appliance))];
  const byApp=Object.fromEntries(apps.map(a=>[a,plan.filter(p=>p.appliance===a)]));
  let html="<table><thead><tr><th>Appliance</th>"+hours.map(h=>`<th>${h}</th>`).join("")+"</tr></thead><tbody>";
  for(const a of apps){html+=`<tr><td>${a}</td>`+byApp[a].map(r=>`<td class="${r.status==="ON"?"on":"off"}">${r.status}</td>`).join("")+"</tr>"}
  byId("heat").innerHTML=html+"</tbody></table>";
}
function renderDecisions(b){
  const rows=report.decision_summary[b].filter(d=>d.off.length>0).slice(0,12);
  byId("decisions").innerHTML=(rows.length?rows:report.decision_summary[b].slice(0,6)).map(d=>`<div class="decision"><b>${d.timestamp.slice(11)}</b>: ${d.action}<br><span class="muted">Kept ON: ${d.on.join(", ")}</span></div>`).join("");
}
function renderParams(b){
  const biz=report.businesses[b];
  byId("businessParams").innerHTML=`<p><b>${biz.display_name||b}</b></p><p>Backup limit: <b>${biz.backup_limit_w} W</b><br>Risk threshold: <b>${Math.round(biz.risk_threshold*100)}%</b></p><p class="muted">${biz.notes||""}</p>`;
  const names=new Set(biz.appliances);
  const rows=report.appliances.filter(a=>names.has(a.name));
  byId("applianceParams").innerHTML="<table><thead><tr><th>Appliance</th><th>Type</th><th>Watts</th><th>Revenue/h</th></tr></thead><tbody>"+rows.map(a=>`<tr><td>${a.name}</td><td>${a.category}</td><td>${a.watts_avg}</td><td>${money(a.revenue_if_running_rwf_per_h)}</td></tr>`).join("")+"</tbody></table>";
}
function renderQuality(){
  const m=report.metrics,w=report.worst_holdout_cases[0];
  byId("quality").innerHTML=`<table><tbody>
  <tr><th>Probability accuracy score</th><td>${m.brier_score}</td></tr>
  <tr><th>Duration error</th><td>${m.duration_mae_min} minutes</td></tr>
  <tr><th>Warning lead time</th><td>${m.median_lead_time_hours} hours</td></tr>
  <tr><th>Training time</th><td>${m.full_train_seconds} seconds</td></tr>
  <tr><th>Worst held-out hour</th><td>${w.timestamp}: predicted ${Math.round(w.p_outage*100)}%, outage happened=${w.outage}</td></tr>
  </tbody></table>`;
}
function renderOffline(){
  const o=report.offline_policy;
  byId("offline").innerHTML=`<p><b>Maximum stale plan:</b> ${o.maximum_staleness_hours} hours</p><p><b>Fallback:</b> ${o.fallback}</p><p class="muted">${o.risk_budget}</p>`;
}
byId("business").addEventListener("change",render);
byId("refresh").addEventListener("click",()=>loadReport(true));
byId("simulate").addEventListener("click",simulateEvent);
byId("sendSms").addEventListener("click",sendSmsDigest);
byId("playVoice").addEventListener("click",playVoicePrompt);
byId("saveVoice").addEventListener("click",saveVoiceNote);
loadReport();
setInterval(pollReport,3000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, content: str | bytes, content_type: str) -> None:
        body = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, dashboard_html(), "text/html; charset=utf-8")
            return
        if parsed.path == "/api/report":
            report = load_or_build_report()
            report["sms_recipients_configured"] = len(load_recipients())
            report["sms_outbox"] = outbox_entries()
            self._send(200, json.dumps(report), "application/json")
            return
        if parsed.path == "/api/rebuild":
            query = parse_qs(parsed.query)
            regenerate = query.get("regenerate", ["0"])[0] == "1"
            report = rebuild_report(regenerate_data=regenerate)
            self._send(200, json.dumps(report), "application/json")
            return
        if parsed.path == "/api/simulate_event":
            report = add_live_event(
                {
                    "type": "neighbor_outage",
                    "title": "Neighbor outage report",
                    "message": "A nearby business reported power loss, so the next high-risk window is raised automatically.",
                    "duration_hours": 3,
                    "p_boost": 0.18,
                    "source": "dashboard_simulation",
                },
                persist=False,
            )
            self._send(200, json.dumps(report), "application/json")
            return
        if parsed.path == "/api/incoming_data":
            self._send(200, json.dumps({"incoming_signals": load_incoming_signals()}), "application/json")
            return
        if parsed.path == "/api/voice_prompt":
            query = parse_qs(parsed.query)
            business = query.get("business", ["salon"])[0]
            self._send(200, json.dumps(build_voice_prompt(load_or_build_report(), business)), "application/json")
            return
        if parsed.path == "/lite_ui.html":
            path = ROOT / "lite_ui.html"
            if path.exists():
                self._send(200, path.read_text(encoding="utf-8"), "text/html; charset=utf-8")
                return
        if parsed.path.startswith("/voice_notes/"):
            name = Path(parsed.path).name
            path = VOICE_DIR / name
            if path.exists() and path.suffix.lower() == ".wav":
                self._send(200, path.read_bytes(), "audio/wav")
                return
        self._send(404, "Not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/send_sms_digest":
            report = load_or_build_report()
            result = send_digest(report.get("sms_digest", []))
            result["outbox"] = outbox_entries()
            self._send(200, json.dumps(result), "application/json")
            return
        if parsed.path == "/api/generate_voice_note":
            query = parse_qs(parsed.query)
            business = query.get("business", ["salon"])[0]
            result = generate_voice_note(load_or_build_report(), business)
            self._send(200, json.dumps(result), "application/json")
            return
        if parsed.path not in {"/api/event", "/api/incoming_data"}:
            self._send(404, "Not found", "text/plain; charset=utf-8")
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            self._send(400, json.dumps({"error": "Body must be JSON"}), "application/json")
            return
        report = ingest_incoming_data(event)
        self._send(200, json.dumps(report), "application/json")

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the Grid Outage Planner dashboard on localhost.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the report before starting the server.")
    args = parser.parse_args()
    load_or_build_report(rebuild=args.rebuild)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Grid Outage Planner dashboard running at http://127.0.0.1:{args.port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
