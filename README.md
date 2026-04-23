
# KTT Power Plan

KTT Power Plan helps small businesses prepare for unreliable electricity. It forecasts the next 24 hours of outage risk, estimates outage duration, and converts that forecast into an appliance-by-appliance ON/OFF plan for a salon, cold room, or tailor shop.

The key product idea is simple: when risk rises, the business should not guess what to unplug. The system sheds luxury appliances first, then comfort appliances, and protects critical revenue appliances for as long as the backup power budget allows.

You do **not** need a machine-learning background to use the app. The dashboard explains the result as business risk, appliance actions, SMS messages, voice prompts, and expected RWF protected.

For details on what causes outage risk and how the ground-reality adaptations are implemented, see [OUTAGE_FACTORS_AND_IMPLEMENTATION.md](OUTAGE_FACTORS_AND_IMPLEMENTATION.md).

For the broader outage taxonomy extension, see [GRID_OUTAGE_TAXONOMY.md](GRID_OUTAGE_TAXONOMY.md).

For a direct brief-by-brief check, see [T2_3_COMPLIANCE_CHECK.md](T2_3_COMPLIANCE_CHECK.md).

## Easiest Run: Local Dashboard

On Windows, double-click:

```text
START_DASHBOARD.bat
```

It opens the dashboard at:

```text
http://127.0.0.1:8000
```

Use the business selector to switch between Salon, Cold room, and Tailor.

Terminal option:

```bash
pip install -r requirements.txt
python dashboard.py
```

## Command-Line Build Option

For technical reviewers who want the generated report files:

```bash
python run_demo.py --business salon
```

This creates or refreshes only the main generated outputs:

- `models/outage_forecaster.joblib`
- `outputs/demo_report.json`
- `outputs/plans_all.csv`
- `outputs/forecast_plan_salon.png`
- `lite_ui.html`

The required source and documentation files stay in the repo, but the generated outputs are intentionally consolidated so judges are not overwhelmed.

## Live Auto-Update Mechanism

The localhost dashboard updates automatically.

How it works:

1. `dashboard.py` serves the dashboard and the current report.
2. The browser checks `/api/report` every 3 seconds.
3. When a new shock, alert, or grid measurement is created, the server saves it and updates `outputs/demo_report.json`.
4. The browser sees a new report revision and redraws the risk chart, appliance plan, SMS window, voice prompt, incoming-data inbox, and business impact.

For a live demo, click **Simulate new alert** in the dashboard. This creates a neighbor-outage signal, raises risk in the affected window, and recalculates the appliance plan.

External tools can also create alerts by sending JSON to:

```text
POST http://127.0.0.1:8000/api/event
```

Example from PowerShell:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/event" -Method POST -ContentType "application/json" -Body '{"title":"Rain shock","message":"Heavy rain reported near the feeder","p_boost":0.12,"duration_hours":4,"start_hour":"18"}'
```

This is the mechanism to connect future inputs such as neighbor reports, a utility alert, a rain shock, or a relay-board warning.

The dashboard also accepts a more general incoming-data endpoint:

```text
POST http://127.0.0.1:8000/api/incoming_data
```

Alert example:

```json
{"type":"rain_shock","message":"Heavy rain near feeder","p_boost":0.12,"duration_hours":4,"start_hour":"18"}
```

Grid-measurement example:

```json
{"record_type":"grid_measurement","timestamp":"2026-04-23T18:00:00+02:00","load_mw":72,"rain_mm":18,"voltage_drop_index":0.7}
```

Incoming alerts are saved to `data/incoming_signals.jsonl`. Incoming measurements are saved to `data/incoming_measurements.csv`, converted into a risk signal, and applied to the current forecast and appliance plan. These runtime files are ignored by Git so private field data is not accidentally committed.

## Optional SMS Sending

The dashboard keeps showing the SMS digest, and it can also send the same digest to phone numbers.

Safe default:

- If no SMS provider is configured, the system uses **dry-run mode**.
- Dry-run mode writes attempted messages to `outputs/sms_outbox.jsonl`.
- Phone numbers and credentials are never committed to the repo.

To configure local recipients without exposing numbers, copy:

```text
sms_recipients.example.json
```

to:

```text
sms_recipients.local.json
```

Then edit the local file:

```json
{
  "recipients": ["+2507XXXXXXXX"]
}
```

That local file is ignored by Git.

Environment-variable option:

```powershell
$env:KTT_SMS_RECIPIENTS="+2507XXXXXXXX,+2507YYYYYYYY"
```

To send real SMS through Twilio-compatible SMS delivery:

```powershell
$env:KTT_SMS_PROVIDER="twilio"
$env:TWILIO_ACCOUNT_SID="ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
$env:TWILIO_AUTH_TOKEN="your_auth_token"
$env:TWILIO_FROM_NUMBER="+1XXXXXXXXXX"
$env:KTT_SMS_RECIPIENTS="+2507XXXXXXXX"
python dashboard.py
```

Then click **Send SMS digest** in the dashboard. The digest remains visible on the dashboard whether the provider is dry-run or real SMS.

## Voice Note Option

The dashboard also supports a low-literacy voice workflow.

Buttons:

- **Play voice prompt** reads the current business instruction aloud in the browser.
- **Save voice note** creates a local `.wav` file on Windows when built-in text-to-speech is available.
- If audio generation is unavailable, the transcript still appears on the dashboard.

The voice note uses the same forecast and plan as the SMS digest. It names the highest-risk window, what to switch off first, what to keep on, and the offline fallback rule.

Setup details are in `VOICE_NOTE_SETUP.md`. Generated voice files stay local in `outputs/voice_notes/`, which is ignored by Git.

## Results From The Current Run

| Metric | Value | Plain-language meaning |
|---|---:|---|
| Brier score | 0.1216 | Lower is better. This measures whether outage probabilities are calibrated against the held-out month. |
| Duration MAE | 41.22 minutes | On true outage hours, expected duration is off by about 41 minutes on average. |
| Median lead time | 24.0 hours | For detected outage hours, the model raised risk within the previous 24-hour planning window. |
| Lead-time coverage | 1.0 | All held-out outage hours had an alert at the chosen 0.10 probability threshold. |
| Forecast response | 20.25 ms | The 24-hour forecast is below the 300 ms CPU response limit after model loading. |
| Full retraining time | 2.048 s | The model retrains well below the 10-minute CPU limit. |

The strongest forecast risk in the current 24-hour salon demo is around **19:00-20:00**. In that window the salon plan switches off the hair dryer and hair straightener first, while keeping lights, clippers, phone charging, mobile money, and TV/radio running if backup capacity allows. The dashboard also explains the risk factors, such as asset health, heavy rain, voltage drop, feeder congestion, vegetation exposure, low reserve margin, or neighbor reports.

Expected saved revenue for a typical outage week:

| Business | Expected saved revenue |
|---|---:|
| Salon | 172,484 RWF |
| Cold room | 232,649 RWF |
| Tailor | 178,830 RWF |

These figures are expected preserved revenue from the 24-hour plan, scaled to a typical week. They are not a claim about real grid performance; the dataset is synthetic and should be replaced with utility logs or verified field reports before deployment.

## Project Structure

```text
grid-outage-prioritizer/
  README.md
  LICENSE
  requirements.txt
  START_DASHBOARD.bat
  START_HERE.md
  dashboard.py
  run_demo.py
  generate_data.py
  forecaster.py
  prioritizer.py
  eval.ipynb
  digest_spec.md
  process_log.md
  SIGNED.md
  MODEL_CARD.md
  VOICE_NOTE_SETUP.md
  OUTAGE_FACTORS_AND_IMPLEMENTATION.md
  GRID_OUTAGE_TAXONOMY.md
  T2_3_COMPLIANCE_CHECK.md
  VIDEO_SCRIPT.md
  LIVE_DEFENSE_QA.md
  SUBMISSION_REVIEW.md
  lite_ui.html
  voice_note.py
  data/
    grid_history.csv
    appliances.json
    businesses.json
    factor_dictionary.json
    outage_taxonomy.json
  models/
    outage_forecaster.joblib
  outputs/
    demo_report.json
    plans_all.csv
    forecast_plan_salon.png
  tests/
    test_forecaster.py
    test_prioritizer.py
```

## How It Works

### Data

`generate_data.py` creates synthetic hourly grid history using the challenge recipe:

- morning and evening load peaks
- weekly seasonality
- rainy-season noise
- outage probability driven by lagged load, rain, and hour-of-day effects
- outage duration from a LogNormal distribution with mean near 90 minutes

The generator now creates **365 days by default** while preserving every required challenge column. Use `python generate_data.py --days 180` if you want the exact brief minimum. It also writes 10 appliances, 3 business archetypes, and `data/factor_dictionary.json`.

Outage risk factors implemented in the dataset and forecast include:

- grid load stress
- rain stress
- wind stress
- feeder congestion
- voltage drops
- maintenance windows
- neighbor outage reports
- transformer age
- payment-day demand pressure
- reserve margin and fuel/hydro adequacy
- vegetation exposure and protection coordination
- SCADA/telecom visibility risk
- non-technical losses and asset health
- DER/backup readiness

### Forecast Engine

`forecaster.py` uses a lightweight CPU-only forecast engine:

- a transparent probability score implemented in `numpy` for `P(outage)`
- a transparent duration estimate for `E[duration | outage]`
- lagged time, load, rain, weather, and outage features
- a fast 24-hour forecast path using precomputed load/weather climatology

The output columns are:

- `timestamp`
- `p_outage`
- `p_low`
- `p_high`
- `expected_duration_min`
- `risk_minutes`

The uncertainty band is a practical hackathon interval based on historical residuals by hour of day.

### Prioritizer

`prioritizer.py::plan(forecast, appliances, business)` produces an hourly appliance plan.

The rule is enforced directly in the sort order:

1. keep critical appliances first
2. keep comfort appliances second
3. keep luxury appliances last

Inside each category, ties are broken by higher revenue per watt, lower startup spike, then appliance name. That makes the result deterministic and easy to defend live.

## Product Adaptation

See `digest_spec.md` for the required Product & Business artifact. It includes:

- 3 SMS messages for a salon owner, each under 160 characters
- offline behavior when internet drops at 13:00
- a 6-hour maximum stale-plan budget
- a non-reader workflow using colored relay-board LEDs, dashboard voice playback, and optional WAV voice notes
- revenue calculation for the salon plan

## Visuals

`dashboard.py` serves the main localhost dashboard. It shows:

- business selector for salon, cold room, and tailor
- compact KPI row and 24 hourly risk dots
- collapsible sections so reviewers do not need to scroll through every detail
- forecast risk band
- appliance ON/OFF heatmap
- business parameters and appliance parameters
- decision list
- SMS digest
- optional SMS sending and SMS outbox
- voice prompt playback and optional WAV voice-note generation
- offline fallback rule
- forecast quality checks for technical judges
- live update alerts when a new shock/report is posted
- incoming-data inbox for saved alerts and measurements
- top outage-risk factors such as voltage drop, heavy rain, feeder congestion, or neighbor reports

`lite_ui.html` is a static page that works by opening the file in a browser. It shows:

- outage probability line
- uncertainty band
- risk-minute bars
- appliance ON/OFF heatmap for the salon
- captions explaining how to read the visuals

`outputs/forecast_plan_salon.png` contains the same forecast plus plan overlay as a shareable chart.

## Evaluation

Run the evaluation through the main demo:

```bash
python run_demo.py --business salon
```

Or open `eval.ipynb` and run the cells. The notebook trains on the earlier history and evaluates the final 30-day held-out window.

## Tests

```bash
python -m unittest discover tests
```

The tests check that the generator, model, forecast columns, and prioritizer rule work without requiring `pytest`.

## Model / Checkpoint

Local checkpoint: `models/outage_forecaster.joblib`

Model card: `MODEL_CARD.md`

Before final submission, upload the checkpoint and model card to Hugging Face Hub or another open host, then paste the public URL here:

Model URL: **TODO - add hosted model link before submission**

The repo still runs without the hosted link because `dashboard.py` and `run_demo.py` can regenerate and retrain the model locally.

## Video

4-minute video URL: **TODO - add YouTube/Vimeo/Drive link before submission**

Use `VIDEO_SCRIPT.md` for the exact required timing.

## Known Limitations

- The data is synthetic, so performance is only a prototype signal.
- Real deployment would need utility outage logs, transformer/feeder metadata, and crowd reports.
- Duration MAE is still high because outage duration is noisy and only partly explained by weather/load features.
- The optimizer assumes each business has a small backup power budget. Those numbers should be adjusted after field interviews.
- The forecast does not yet use the optional neighbor signal stretch goal.

## Honor Code And Process

See:

- `process_log.md`
- `SIGNED.md`

AI assistance was used for planning, implementation support, documentation structure, and review. The code was run locally and the metrics above are from generated outputs.
