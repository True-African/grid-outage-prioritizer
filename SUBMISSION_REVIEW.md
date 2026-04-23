# Submission Review

This is a pre-submission review of the current repo state.

## README Review

Status: strong baseline, but two links must be added before final submission.

What works:

- The problem is explained in plain language.
- The dashboard run path is clear, including a Windows double-click option.
- The live-update mechanism is documented and demoable with one button.
- The dashboard now uses collapsible sections and a side incoming-data inbox to reduce scrolling.
- Incoming alerts and measurements can be saved locally and applied to the current forecast/plan.
- Actual measured metrics are included.
- Brier score, duration MAE, lead time, retraining time, and forecast latency are explained for non-experts.
- The repo structure is visible.
- Product adaptation and visual outputs are linked.

Before submission:

- Replace the video placeholder with the real 4-minute video URL.
- Upload `models/outage_forecaster.joblib` and `MODEL_CARD.md` to Hugging Face Hub or another open host, then add the model URL.
- Update `SIGNED.md` with the candidate's full legal name if "Simeon" is incomplete.

## Demo Video Script Review

Status: matches the required 4-minute structure.

Strengths:

- Starts with name, challenge ID, and Brier score.
- Shows `forecaster.py` and `prioritizer.py`.
- Specifically walks through `prioritizer.py::plan`.
- Opens `lite_ui.html`.
- Reads the exact SMS messages from `digest_spec.md`.
- Answers the three required defense questions with real metrics and worst-case details.

Recording reminders:

- Keep camera on for the intro and outro.
- Make terminal text large enough to read.
- Keep audio clear and do a 10-second sound test.
- Do not read every line mechanically. Use the script as memory support.

## Live Defense Answer Review

Status: ready for a short evaluator call.

Strong points:

- The model choice is defensible under CPU and time limits.
- Brier score and duration MAE have simple explanations.
- The worst forecast hour is specific: 2026-04-21 20:00.
- The missing feature is plausible: feeder/neighbor signal.
- The product fallback is concrete: cached plan for 6 hours, then critical-only mode.
- The prioritizer rule is easy to explain from code.

Risk points:

- Duration MAE is not very low. Explain honestly that duration is noisy and synthetic.
- The lead time looks very strong because the threshold is low at 0.10. Say that this favors coverage over precision.
- Revenue savings are expected values from synthetic data, not field-validated income.

## Pass/Fail Checklist

| Item | Status |
|---|---|
| Public GitHub/GitLab repo opens in incognito | TODO after upload |
| README has dashboard and two-command run path | PASS |
| README has 4-minute video URL | TODO after recording |
| README has model/checkpoint link | TODO after hosting |
| Local model checkpoint exists | PASS |
| Localhost dashboard exists | PASS |
| Dashboard auto-updates from simulated or posted alerts | PASS |
| Incoming-data API saves and applies alerts/measurements | PASS |
| Dashboard has collapsible sections to reduce page overload | PASS |
| SMS digest can be sent or dry-run logged from dashboard | PASS |
| Voice prompt and local WAV voice-note option exist | PASS |
| `forecaster.py` exists and runs | PASS |
| `prioritizer.py` contains `plan(forecast, appliances)` | PASS |
| `eval.ipynb` reports required metrics | PASS |
| `lite_ui.html` opens locally | PASS |
| `digest_spec.md` includes SMS, offline behavior, risk budget, stale limit, and non-reader adaptation | PASS |
| `process_log.md` is complete | PASS |
| `SIGNED.md` is present | PASS |
| Data generator is present | PASS |
| Forecast response under 300 ms | PASS, 20.25 ms |
| Retraining under 10 minutes | PASS, 2.048 s |
| Visuals have plain-language captions | PASS |

Detailed PDF compliance check: see `T2_3_COMPLIANCE_CHECK.md`.
