# Project Guide

This guide keeps the useful implementation details that do not need to crowd the README.

## How The System Works

1. `generate_data.py` creates reproducible hourly grid history, appliances, and business archetypes.
2. `forecaster.py` estimates `P(outage)` and expected duration for the next 24 hours.
3. `prioritizer.py` converts the forecast into appliance ON/OFF decisions.
4. `dashboard.py` shows the plan, accepts incoming alerts, and exposes SMS/voice actions.
5. `run_demo.py` refreshes the full local demo and consolidated outputs.

## Outage Factors Used

The forecast is not based on appliances. Appliances are only the action layer.

Implemented grid and local-risk factors include:

- grid load stress
- rain and wind stress
- feeder congestion
- voltage drops
- maintenance windows
- neighbor outage reports
- transformer age
- payment-day demand pressure
- reserve margin, fuel risk, and hydro inflow stress
- vegetation exposure and protection coordination risk
- SCADA/telecom risk
- non-technical losses and asset health
- DER or backup readiness

The dashboard shows `top_risk_factor` and `risk_explanation` for high-risk hours.

## Data

Required challenge columns are preserved in `data/grid_history.csv`:

- `timestamp`
- `load_mw`
- `temp_c`
- `humidity`
- `wind_ms`
- `rain_mm`
- `outage`
- `duration_min`

The default generator creates 365 days of data. To create the 180-day challenge minimum:

```bash
python generate_data.py --days 180
```

## Incoming Data API

The dashboard accepts incoming field signals while running locally.

```text
POST http://127.0.0.1:8000/api/incoming_data
```

Alert payload:

```json
{"type":"utility_alert","message":"Utility notice for feeder maintenance","p_boost":0.10,"duration_hours":3,"start_hour":"14"}
```

Grid measurement payload:

```json
{"record_type":"grid_measurement","load_mw":72,"rain_mm":18,"voltage_drop_index":0.7,"feeder_congestion_index":0.6}
```

Saved runtime files:

- `data/incoming_signals.jsonl`
- `data/incoming_measurements.csv`

These files are ignored by Git because real field data may be private.

## Appliance Planner

`prioritizer.py::plan(forecast, appliances, business)` returns a 24-hour appliance table.

The shedding rule is deterministic:

1. keep critical appliances first
2. keep comfort appliances second
3. keep luxury appliances last

Within each category, ties are broken by:

1. higher revenue per watt
2. lower startup spike
3. appliance name

Plain-language rule: the algorithm does not turn off a critical appliance while a luxury appliance is still kept on just to save power.

## SMS And Voice

SMS delivery is safe by default.

- Without SMS credentials, the dashboard uses dry-run mode.
- Dry-run messages go to `outputs/sms_outbox.jsonl`.
- Real phone numbers belong in `sms_recipients.local.json` or `POWERPLAN_SMS_RECIPIENTS`.
- Credentials belong in environment variables, not in Git.

Twilio-compatible environment variables:

```powershell
$env:POWERPLAN_SMS_PROVIDER="twilio"
$env:TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWILIO_AUTH_TOKEN="your_auth_token"
$env:TWILIO_FROM_NUMBER="+1XXXXXXXXXX"
$env:POWERPLAN_SMS_RECIPIENTS="+2507XXXXXXXX"
python dashboard.py
```

Voice support:

- `Play voice prompt` reads the current instruction in the browser.
- `Save voice note` creates a local WAV on Windows when text-to-speech is available.
Honor code:

"I will use any LLM or coding-assistant tool I find useful, and I will declare each tool I use, why I used it, and three sample prompts in my process_log.md. I will not have another human do my work. I will defend my own code in the Live Defense session. I understand undeclared LLM or human assistance is grounds for disqualification."
 and are ignored by Git.

## Product Adaptation

The product is designed for low-bandwidth and mixed-literacy use:

- feature-phone SMS messages, each under 160 characters
- cached plan trusted for 6 hours
- critical-only fallback after the stale-plan limit
- simple English with Kinyarwanda-friendly templates
- colored LED workflow for non-readers
- browser voice prompt and optional WAV voice note

Business assumptions:

| Business | Backup limit | Protected priority |
|---|---:|---|
| Salon | 700 W | lights, clippers, phone charging, mobile money |
| Cold room | 360 W | freezer first |
| Tailor | 500 W | sewing machine and lighting |

## Outputs

Generated files are consolidated to avoid clutter:

- `outputs/demo_report.json`
- `outputs/plans_all.csv`
- `outputs/forecast_plan_salon.png`
- `lite_ui.html`
- `models/outage_forecaster.joblib`

Most generated outputs are ignored by Git. Recreate them with:

```bash
python run_demo.py --business salon
```

## Local Model File

The trained checkpoint is generated locally at:

```text
models/outage_forecaster.joblib
```

This file is ignored by Git because it is recreated quickly:

```bash
python run_demo.py --business salon
```

`MODEL_CARD.md` documents the model inputs, outputs, metrics, limitations, and reproduction steps.
