# process_log.md

Candidate: Simeon
Challenge: Grid Outage Forecaster + Appliance Prioritizer
Date: 23 April 2026

## Timeline

| Time | Work done |
|---|---|
| 00:00-00:15 | Read the challenge brief, confirmed required files, scoring weights, video structure, and product adaptation requirements |
| 00:15-00:45 | Created repo structure and wrote `generate_data.py` for reproducible grid, outage-factor, appliance, business, and outage-taxonomy data |
| 00:45-01:45 | Implemented `forecaster.py` with CPU-only probability and duration estimates plus risk-factor explanations |
| 01:45-02:30 | Implemented `prioritizer.py` and `plan(forecast, appliances)` with luxury-before-critical shedding rule |
| 02:30-03:00 | Built `run_demo.py`, evaluation metrics, CSV outputs, model checkpoint, and chart output |
| 03:00-03:25 | Built `lite_ui.html` and `dashboard.py` for static and localhost visual review |
| 03:25-03:40 | Wrote `digest_spec.md` with SMS digest, offline behavior, stale-plan risk budget, and non-reader adaptation |
| 03:40-03:55 | Prepared temporary demo and defense notes for the required 4-minute presentation |
| 03:55-04:00 | Added the broader grid-outage taxonomy, reran against the PDF checklist, consolidated outputs, checked metrics, and verified forecast response below 300 ms |
| Post-build refinement | Added localhost auto-update alerts, optional SMS sending with dry-run fallback, and a voice-note workflow for non-reader users |
| Dashboard hardening | Fixed Matplotlib backend warning, made report writes atomic, added a dashboard rebuild lock, and verified `Clear/rebuild` under concurrent polling |
| Dashboard usability | Added durable incoming-data ingestion and reworked the dashboard into compact KPIs, risk dots, a side inbox, and collapsible sections |

## Declared LLM / Assistant Tools

| Tool | Purpose | What I changed or verified myself |
|---|---|---|
| Codex / ChatGPT | Challenge interpretation, implementation support, documentation structure, debugging, and live-defense preparation | I ran the scripts locally, checked generated outputs, verified metrics, and reviewed the prioritizer rule and product assumptions |

## Three Sample Prompts I Used

1. "Help me interpret the Grid Outage Forecaster brief and turn it into a four-hour execution plan."
2. "Build a complete CPU-only baseline project with generator, forecaster, prioritizer, evaluation, lite UI, README, and defense notes."
3. "Implement SMS and voice-note workflows while keeping phone numbers, credentials, and generated audio files outside Git."

## One Discarded Prompt

Discarded prompt: "Write a polished final submission that hides AI involvement."

Reason: The challenge explicitly allowed LLM tools only when they were declared. Hidden assistance made live defense dishonest and violated the honor code.

## Hardest Decision

The hardest decision was choosing a lightweight custom forecast engine instead of installing XGBoost, LightGBM, or Prophet. The local environment did not have scikit-learn or pytest, and network installation was risky during a timed hackathon. I chose a transparent `numpy` logistic probability score plus ridge duration estimate because it trained quickly, ran under the CPU latency limit, and was explainable to both technical and non-technical judges through the dashboard.
