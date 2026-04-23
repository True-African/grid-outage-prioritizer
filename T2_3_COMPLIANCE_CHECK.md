# T2.3 Compliance Check

Source checked: `T2.3_Grid_Outage_Forecaster_Appliance_Prioritizer.pdf`

Last rerun:

```bash
python run_demo.py --business salon --regenerate-data
python -m unittest discover tests
python -m py_compile dashboard.py run_demo.py forecaster.py prioritizer.py generate_data.py
```

## Technical Task Coverage

| Brief requirement | Implementation | Status |
|---|---|---|
| 24-hour hourly outage forecast | `forecaster.py::forecast_next_24` outputs 24 rows | PASS |
| Output `P(outage)` | `p_outage` in forecast/report/dashboard | PASS |
| Output `E[duration | outage]` | `expected_duration_min` in forecast/report/dashboard | PASS |
| Rolling 30-day evaluation | `evaluate_holdout` evaluates final 30 days; `eval.ipynb` exposes it | PASS |
| Brier score | Current run: `0.1216` | PASS |
| Duration MAE | Current run: `41.22` minutes | PASS |
| Lead time | Current run: median `24.0` hours, coverage `1.0` at threshold `0.10` | PASS |
| Appliance ON/OFF plan | `prioritizer.py::plan(forecast, appliances, business)` | PASS |
| Drop luxury before critical | Category order is critical, comfort, luxury in `_choose_on` | PASS |
| Tie-breaking | Revenue/W, startup spike, then appliance name | PASS |
| Forecast uncertainty band | `p_low` and `p_high` shown in `lite_ui.html` and dashboard | PASS |
| Plan overlay/chart | `lite_ui.html`, dashboard heatmap, and `outputs/forecast_plan_salon.png` | PASS |
| Incoming data is saved and used | `/api/incoming_data` saves alerts/measurements and applies them to forecast and plan | PASS |

## Data And Outage Factors

| Brief/data need | Implementation | Status |
|---|---|---|
| Required `grid_history.csv` columns | Required columns preserved | PASS |
| 180-day minimum | Generator can produce `--days 180`; default expanded to 365 days | PASS |
| Dataset regenerated under 2 minutes | Current generation/training pipeline completes in seconds | PASS |
| Morning/evening load peaks | Implemented in `generate_data.py` | PASS |
| Weekly seasonality | Implemented in `generate_data.py` | PASS |
| Rainy-season noise | Implemented in `generate_data.py` | PASS |
| Base outage rate about 4 percent | Current generated rate: `0.0410` | PASS |
| Duration LogNormal near 90 min | Implemented with LogNormal plus local stress multiplier | PASS |
| Outage factors beyond appliances | Load stress, rain stress, wind stress, feeder congestion, voltage drop, maintenance, transformer age, payment-day pressure, neighbor reports, reserve margin, fuel/hydro stress, vegetation, protection, SCADA/telecom, non-technical losses, asset health, DER/backup readiness | PASS |
| Factor explanation | Forecast includes `top_risk_factor` and `risk_explanation` | PASS |
| Factor dictionary | `data/factor_dictionary.json` and `OUTAGE_FACTORS_AND_IMPLEMENTATION.md` | PASS |
| Broader outage taxonomy | `data/outage_taxonomy.json` and `GRID_OUTAGE_TAXONOMY.md` | PASS |

## Product And Business Adaptation

| Required reality | Implementation | Concrete detail | Status |
|---|---|---|---|
| Low bandwidth | Static `lite_ui.html`; consolidated report | `lite_ui.html` is about 13 KB; outputs are 3 files | PASS |
| Intermittent power/internet | Cached plan and stale-plan policy | Trust cached plan for 6 hours, then critical-only mode | PASS |
| Non-smartphone users | Morning SMS digest | 3 SMS messages, 122/124/124 characters | PASS |
| SMS delivery workflow | Optional provider with dry-run fallback | Dashboard button sends/logs same digest; real numbers stay local | PASS |
| Voice note implementation | Browser playback plus optional local WAV | Dashboard buttons `Play voice prompt` and `Save voice note` | PASS |
| Multiple languages | Simple English plus simple Kinyarwanda templates | Stored in `outputs/demo_report.json` and documented in `digest_spec.md` | PASS |
| Illiteracy | LED and voice workflow | Green ON, red OFF, amber prepare; voice prompt: "Dryer off. Clippers on. Lights on." | PASS |
| Local live shocks | Dashboard accepts live alert events | `POST /api/event`; demo button `Simulate new alert` | PASS |
| Saved incoming-data workflow | Alerts to `data/incoming_signals.jsonl`; measurements to `data/incoming_measurements.csv` | Runtime files are Git-ignored and shown in dashboard inbox | PASS |
| Users named | Salon owner, cold room operator, tailor | Documented in `digest_spec.md` and dashboard | PASS |
| Workflows named | SMS, cached plan, critical-only mode, LED/voice non-reader mode | Implemented in report/dashboard/docs | PASS |
| RWF impact | Current salon estimate | 24,641 RWF/day; 172,484 RWF/week | PASS |

## Deliverables

| Deliverable | File/location | Status |
|---|---|---|
| `forecaster.py` | Present | PASS |
| `prioritizer.py` | Present | PASS |
| `eval.ipynb` | Present | PASS |
| `lite_ui.html` | Present, static, lightweight | PASS |
| `digest_spec.md` | Present | PASS |
| `process_log.md` | Present | PASS |
| `SIGNED.md` | Present; update full legal name if needed | PASS / CHECK NAME |
| README | Present | PASS |
| LICENSE | Present | PASS |
| Dataset/generator | `generate_data.py`, `data/grid_history.csv`, JSON files | PASS |
| Model/checkpoint | `models/outage_forecaster.joblib`, `MODEL_CARD.md` | PASS locally |
| Model hosted link | Add Hugging Face/Drive URL before final submission | EXTERNAL TODO |
| Public GitHub/GitLab repo | Push before final submission | EXTERNAL TODO |
| 4-minute video URL | Record/upload and paste in README | EXTERNAL TODO |

## Final Metrics From Current Run

| Metric | Value |
|---|---:|
| Dataset rows | 8,760 |
| Dataset days | 365 |
| Outage rate | 0.0410 |
| Held-out outage hours | 30 |
| Brier score | 0.1216 |
| Duration MAE | 41.22 minutes |
| Median lead time | 24.0 hours |
| Forecast response | 20.25 ms |
| Full retraining time | 2.048 s |
| Salon weekly expected saved revenue | 172,484 RWF |
| `lite_ui.html` size | about 13 KB |

## What To Say In Defense

"The outage forecast is not based on appliances. Appliances are only the final action layer. The risk score is driven by grid and weather factors: load stress, rain, wind, voltage drop, feeder congestion, maintenance windows, transformer age, payment-day demand, and neighbor reports. The dashboard shows the top risk factor for each high-risk hour, then turns that risk into plain ON/OFF appliance decisions."
