# 4-Minute Video Script

Use this as a timing guide. Speak naturally and keep the repo, terminal, and browser visible.

## 0:00-0:30 - On-Camera Intro

Say:

"My name is Simeon. My challenge is T2.3, Grid Outage Forecaster plus Appliance Prioritizer. My held-out Brier score is **0.1216**. The goal is to forecast the next 24 hours of outage risk and turn that into a simple ON/OFF appliance plan for small businesses like salons, cold rooms, and tailor shops."

Then add:

"The current salon demo identifies the strongest risk around **19:00-20:00**."

## 0:30-1:30 - Live Code Walkthrough

Show `forecaster.py`.

Say:

"The forecast engine uses lagged load, rain, wind, voltage drops, feeder congestion, maintenance windows, neighbor reports, time of day, and recent outage features. For a non-technical user, the dashboard translates this into a risk window, top risk reason, and appliance actions."

Show `forecast_next_24`.

Say:

"The fast forecast path precomputes a 21-day hourly climatology and then rolls forward 24 hours. The measured response time is **20.25 ms**, below the 300 ms limit."

Show `prioritizer.py::plan(forecast, appliances, business)`.

Say:

"This function converts forecast risk into appliance actions. In high-risk hours it uses the business backup limit. The category order is critical, comfort, luxury. That enforces the rule: luxury is shed first, then comfort, then critical only as a last resort. Ties use revenue per watt, startup spike, then appliance name."

## 1:30-2:30 - Live Demo

Run or show:

```bash
python run_demo.py --business salon
```

Open `lite_ui.html` in a browser.

Point to:

- forecast risk band
- risk-minute bars
- appliance heatmap
- red OFF blocks for dryer and straightener
- green ON blocks for lights, clippers, phone charging, mobile money, and TV/radio when backup allows

Say:

"This is a static page. It does not need a backend, so it is suitable for low-bandwidth review and can be cached."

Optional extra if time allows:

"For a richer local review, the repo also has `dashboard.py`, which runs at localhost and lets the judge switch between salon, cold room, and tailor without typing separate commands. It also has a live-update button: when a new alert comes in, the chart and appliance plan update automatically."

"The same SMS digest can be sent from the dashboard. For the demo, dry-run mode logs the message in the outbox; in deployment we configure an SMS provider and recipients through environment variables."

"For customers who cannot read, I also added a voice option. The dashboard can play the current plan aloud or save a WAV voice note using Windows text-to-speech."

## 2:30-3:30 - Product Artifact

Open `digest_spec.md`.

Read the three SMS messages aloud:

1. "KTT Power: Salon today. Highest risk 19:00-20:00. Keep lights, clippers and payments ready; delay dryer when alert is red."
2. "If outage hits: OFF dryer and straightener first. Keep lights, clippers, phone charging, payments; TV only if backup allows."
3. "No internet at 13:00? Use cached plan until 6h old. After that run critical-only mode: lights, clippers, phone and payments."

Say:

"Each message is under 160 characters. The product artifact also explains offline behavior and a non-reader LED plus voice workflow."

## 3:30-4:00 - Required Questions

Technical:

"The worst held-out forecast hour is **2026-04-21 20:00**. The system predicted very high risk because voltage drop, feeder congestion, load and rain were all high, but no outage happened. This false alarm shows I need real feeder outcome data to calibrate the risk better."

Product/Business:

"For the salon, the current plan saves an expected **24,641 RWF per day**, scaled to **172,484 RWF per typical outage week**. That is computed as the sum of P(outage) times expected revenue from appliances kept ON, multiplied by seven."

Local context:

"If the salon has no internet at 13:00, the owner sees the cached plan timestamp and a green, amber, or red stale-plan status. We trust the cached plan for up to **6 hours**. After that, the device switches to critical-only mode: lights, clippers, phone charging, and mobile money stay on; dryer, straightener, and TV stay off."
