"""Voice-note support for low-literacy workflows.

The dashboard can always play a prompt in the browser using Web Speech. On
Windows, this module can also generate a local WAV file using built-in SAPI
text-to-speech through PowerShell. No internet service is required.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
VOICE_DIR = ROOT / "outputs" / "voice_notes"


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
    """Build a short voice prompt from the current forecast and plan."""
    businesses = report.get("businesses", {})
    business_info = businesses.get(business, {"display_name": business})
    display_name = business_info.get("display_name", business.replace("_", " "))
    worst = report.get("worst_forecast_window", {})
    worst_label = worst.get("label", "the highest risk hour")

    decisions = report.get("decision_summary", {}).get(business, [])
    high_risk_decision = next((row for row in decisions if row.get("off")), decisions[0] if decisions else {})
    off_items = high_risk_decision.get("off", [])
    on_items = high_risk_decision.get("on", [])
    if not on_items:
        plans = report.get("plans", {}).get(business, [])
        if plans:
            first_ts = plans[0]["timestamp"]
            on_items = [row["appliance"] for row in plans if row["timestamp"] == first_ts and row["status"] == "ON"]

    offline = report.get("offline_policy", {})
    stale_hours = offline.get("maximum_staleness_hours", 6)

    transcript = (
        f"KTT Power voice note for {display_name}. "
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
    """Generate a local WAV voice note when Windows SAPI is available."""
    prompt = build_voice_prompt(report, business)
    VOICE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = pd.Timestamp.now(tz="UTC").strftime("%Y%m%d_%H%M%S")
    base_name = f"{_clean_name(business)}_{timestamp}"
    wav_path = VOICE_DIR / f"{base_name}.wav"
    manifest_path = VOICE_DIR / f"{base_name}.json"

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
