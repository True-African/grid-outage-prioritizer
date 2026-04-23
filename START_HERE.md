# Start Here

This project now has two ways to run it.

## Option 1: Easiest On Windows

Double-click:

```text
START_DASHBOARD.bat
```

It installs the small requirements, starts the local dashboard, and opens:

```text
http://127.0.0.1:8000
```

Use this option for judges or teammates who do not want to type commands.

## Option 2: Terminal

```bash
pip install -r requirements.txt
python dashboard.py
```

Then open:

```text
http://127.0.0.1:8000
```

## What To Show A Judge

1. Open the dashboard.
2. Switch between Salon, Cold room, and Tailor.
3. Show the highest-risk window.
4. Show the 24 hourly risk dots and collapsible sections.
5. Open the appliance ON/OFF heatmap.
6. Open SMS and voice only when you need those details.
7. Click **Simulate new alert** and show the dashboard updating automatically.
8. Click **Play voice prompt** so a non-reader can hear the action.
9. Click **Send SMS digest** to show the SMS outbox. In dry-run mode it logs messages instead of sending.
10. Mention that the detailed generated report is in `outputs/demo_report.json`.

## Live Updates

The dashboard checks for updates every 3 seconds.

When a new shock, neighbor report, or utility alert is posted to the local server, the server updates the report and the browser redraws itself.

Demo button:

```text
Simulate new alert
```

External alert API:

```text
POST http://127.0.0.1:8000/api/event
```

General incoming-data API:

```text
POST http://127.0.0.1:8000/api/incoming_data
```

PowerShell example:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/event" -Method POST -ContentType "application/json" -Body '{"title":"Rain shock","message":"Heavy rain reported near the feeder","p_boost":0.12,"duration_hours":4,"start_hour":"18"}'
```

PowerShell measurement example:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/incoming_data" -Method POST -ContentType "application/json" -Body '{"record_type":"grid_measurement","timestamp":"2026-04-23T18:00:00+02:00","load_mw":72,"rain_mm":18,"voltage_drop_index":0.7}'
```

Saved incoming alerts go to `data/incoming_signals.jsonl`. Saved incoming measurements go to `data/incoming_measurements.csv`. Both are ignored by Git because real field data may be private.

## SMS Sending

The SMS digest stays on the dashboard. The dashboard can also send or dry-run the same digest.

For setup, see:

```text
SMS_SETUP.md
```

## Voice Notes

The dashboard can read the current plan aloud and can save a local WAV voice note on Windows.

For setup, see:

```text
VOICE_NOTE_SETUP.md
```

## Clean Output Files

The app now keeps generated outputs small:

- `outputs/demo_report.json`: all metrics, forecast rows, appliance decisions, SMS, and business impact.
- `outputs/plans_all.csv`: one combined plan table for all businesses.
- `outputs/forecast_plan_salon.png`: chart image for the README/video.

The required source and documentation files remain in the repo because the challenge asks for them.
