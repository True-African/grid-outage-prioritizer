---
title: Grid Outage Planner
sdk: static
app_file: lite_ui.html
colorFrom: green
colorTo: blue
short_description: 24-hour outage risk and appliance planning for SMEs.
---

# Grid Outage Planner

Grid Outage Planner forecasts 24-hour grid-outage risk and converts it into a practical appliance ON/OFF plan for small businesses such as salons, cold rooms, and tailor shops.

The dashboard is designed for non-ML users: it shows the highest-risk hour, why risk is rising, which appliances to keep ON or switch OFF, SMS/voice instructions, and expected revenue protected.

## Quick Start

Clone from GitHub:

```bash
git clone https://github.com/True-African/Your_grid_outage_prioritizer.git
cd Your_grid_outage_prioritizer
```

Alternative clone from Hugging Face Spaces:

```bash
git clone https://huggingface.co/spaces/Iyumva/Your_grid_outage_prioritizer
cd Your_grid_outage_prioritizer
```

Windows users can double-click:

```text
START_DASHBOARD.bat
```

Terminal users can create the virtual environment with:

```bash
python -m venv venv
```

Then activate it in the shell you are using:

```powershell
# Windows PowerShell
.\venv\Scripts\Activate.ps1
```

```cmd
:: Windows Command Prompt
venv\Scripts\activate.bat
```

```bash
# Git Bash on Windows
source venv/Scripts/activate
```

After activation, install dependencies and start the local dashboard:

```bash
pip install -r requirements.txt
python dashboard.py
```

On macOS/Linux, activate the environment with:

```bash
source venv/bin/activate
```

Then open:

```text
http://127.0.0.1:8000
```

## What To Try

- Switch between `salon`, `cold room`, and `tailor`.
- Click `Simulate new alert` to see the forecast and plan update.
- Open the collapsible `Incoming data` section for the local alert API.
- Click `Play voice prompt` for the non-reader workflow.
- Click `Send SMS digest` to dry-run SMS delivery into the local outbox.

## Command-Line Demo

```bash
python run_demo.py --business salon
```

This regenerates the synthetic dataset if needed, trains the CPU-only forecaster, evaluates the held-out window, builds appliance plans, refreshes `lite_ui.html`, and writes consolidated outputs.

## Current Results

| Metric | Value |
|---|---:|
| Brier score | 0.1216 |
| Duration MAE | 41.22 minutes |
| Median lead time | 24.0 hours |
| Forecast response | 11.34 ms |
| Full retraining time | 2.345 s |

Expected saved revenue for a typical outage week:

| Business | Expected saved revenue |
|---|---:|
| Salon | 172,484 RWF |
| Cold room | 232,649 RWF |
| Tailor | 178,830 RWF |

## Project Files

| Path | Purpose |
|---|---|
| [dashboard.py](dashboard.py) | Localhost dashboard, SMS/voice actions, and incoming-data API |
| [run_demo.py](run_demo.py) | End-to-end data, model, evaluation, and output runner |
| [generate_data.py](generate_data.py) | Reproducible synthetic grid, appliance, and business data |
| [forecaster.py](forecaster.py) | 24-hour outage probability and duration forecaster |
| [prioritizer.py](prioritizer.py) | Appliance ON/OFF planner |
| [lite_ui.html](lite_ui.html) | Static lightweight demo page |
| [PROJECT_GUIDE.md](PROJECT_GUIDE.md) | Implementation notes, APIs, SMS/voice, and product adaptation |
| [MODEL_CARD.md](MODEL_CARD.md) | Local model documentation |
| [digest_spec.md](digest_spec.md) | Product and business digest required by the challenge |

## Incoming Data

The dashboard accepts new local signals and uses them immediately:

```text
POST http://127.0.0.1:8000/api/incoming_data
```

Alert example:

```json
{"type":"rain_shock","message":"Heavy rain near feeder","p_boost":0.12,"duration_hours":4,"start_hour":"18"}
```

Measurement example:

```json
{"record_type":"grid_measurement","timestamp":"2026-04-23T18:00:00+02:00","load_mw":72,"rain_mm":18,"voltage_drop_index":0.7}
```

Runtime incoming files are ignored by Git:

- `data/incoming_signals.jsonl`
- `data/incoming_measurements.csv`

## Tests

```bash
python -m unittest discover tests
```

## Model

The local checkpoint is generated at:

```text
models/outage_forecaster.joblib
```

The repo does not require a prebuilt checkpoint because `run_demo.py` retrains the model locally in a few seconds.

## Repository Links

- GitHub: `https://github.com/True-African/Your_grid_outage_prioritizer`
- Hugging Face Space: `https://huggingface.co/spaces/Iyumva/Your_grid_outage_prioritizer`

The Hugging Face Space is used as a hosted project mirror for the submission files. The local dashboard still runs with `python dashboard.py`.

## Push Commands

From the project folder:

```bash
git init
git add .
git commit -m "Initial Grid Outage Planner submission"
git branch -M main
```

Push to GitHub:

```bash
git remote add origin https://github.com/True-African/Your_grid_outage_prioritizer.git
git push -u origin main
```

Push the same commit to Hugging Face Spaces:

```bash
git remote add hf https://huggingface.co/spaces/Iyumva/Your_grid_outage_prioritizer
git push hf main
```

If the Hugging Face CLI is installed, authenticate first:

```bash
hf auth login
```

## Demo Video

4-minute demo:

```text
https://drive.google.com/file/d/1ZDblyOTrFII-JmWbkfPFF3NVkL1pZmZI/view?usp=sharing
```

## Limitations

- The dataset is synthetic; deployment requires verified utility or feeder logs.
- The model is decision support, not a guaranteed outage notice.
- Backup power limits are assumptions; field setup requires business-specific values.

## License

MIT. See [LICENSE](LICENSE).
