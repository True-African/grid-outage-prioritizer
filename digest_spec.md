# Product And Business Digest Specification

Challenge: **T2.3 Grid Outage Forecaster + Appliance Prioritizer**

This artifact explains how the forecast becomes an action that a real small business can use under low bandwidth, intermittent power, and mixed literacy conditions.

## 1. Users And Context

| User | Main risk | Practical need |
|---|---|---|
| Salon owner | Hair services stop when high-watt tools overload backup power | Know when to delay dryer/straightener and protect clippers, lights, and payments |
| Cold room operator | Stock spoils if freezer is not protected | Keep freezer running before any comfort load |
| Tailor | Sewing can continue on small backup, but ironing draws too much power | Continue sewing and delay ironing in high-risk windows |

Assumptions used in this prototype:

- The salon has a 700 W backup/inverter budget.
- The cold room has a 360 W backup budget.
- The tailor has a 500 W backup budget.
- The current demo forecast shows highest salon risk around **19:00-20:00**.
- The system is decision support, not a guaranteed outage announcement.

## 2. Morning Digest For Salon Owner

Delivery channel: feature-phone SMS.

Maximum: 3 SMS, 160 characters each.

| SMS | Characters | Message |
|---:|---:|---|
| 1 | 122 | KTT Power: Salon today. Highest risk 19:00-20:00. Keep lights, clippers and payments ready; delay dryer when alert is red. |
| 2 | 124 | If outage hits: OFF dryer and straightener first. Keep lights, clippers, phone charging, payments; TV only if backup allows. |
| 3 | 124 | No internet at 13:00? Use cached plan until 6h old. After that run critical-only mode: lights, clippers, phone and payments. |

Language strategy:

- Default SMS is simple English because appliance names are common business terms.
- A Kinyarwanda version can be sent from the same plan template for owners who prefer it.
- The wording avoids probabilities and model jargon. It gives a time window and specific appliance actions.

Simple Kinyarwanda templates used in the report:

| Situation | Message |
|---|---|
| Dryer alert | Funga dryer niba ibara ritukura. |
| Critical appliances | Cana amatara, clippers, telefone na mobile money. |
| Offline fallback | Nta internet: koresha plan ibitswe amasaha 6, nyuma ukoreshe ibya ngombwa gusa. |

## 3. Mid-Day Internet Drop

Scenario: the salon has no internet at **13:00** and the forecast cannot refresh.

What the device or page shows:

- Last plan timestamp, for example: "Plan cached at 07:00."
- A status color:
  - green: plan is under 3 hours old
  - amber: plan is 3-6 hours old
  - red: plan is over 6 hours old
- Current instruction:
  - under 6 hours old: continue using cached appliance plan
  - over 6 hours old: switch to critical-only mode

Risk budget:

- Maximum acceptable staleness: **6 hours**.
- Maximum tolerated stale-plan error: about **15 percentage points** of outage probability or **30 risk-minutes**.
- After 6 hours, the plan stops pretending to be fresh. The business sees:
  "Forecast old. Use critical-only mode until refresh."

Why 6 hours:

- It is short enough for morning weather/load assumptions to remain useful through the business day.
- It is long enough for feature-phone and intermittent-internet users to avoid constant refresh dependence.
- It is easy to explain during live defense.

## 4. Non-Reader Adaptation

Chosen approach: **colored LEDs on a small relay board plus optional voice prompt**.

Workflow:

- Each controllable plug or relay line has a colored LED.
- Green LED means keep the appliance ON.
- Red LED means switch the appliance OFF first.
- Amber LED means "prepare to switch off if outage starts."
- A simple voice prompt can play in Kinyarwanda or English:
  "Dryer off. Clippers on. Lights on."
- The dashboard implements this with **Play voice prompt**, which reads the latest plan aloud in the browser.
- The dashboard also implements **Save voice note**, which creates a local WAV file on Windows when built-in text-to-speech is available.
- The voice transcript is generated from the same forecast, appliance plan, and 6-hour stale-plan rule used for SMS.

Why this is appropriate:

- A non-reader does not need to interpret text or charts.
- It works when the owner has no smartphone.
- LED status remains visible during low bandwidth.
- The same ON/OFF plan from `prioritizer.py` can drive the relay/LED state.

## 5. Business Impact

The current run estimates expected protected revenue by scaling the 24-hour salon plan to a typical outage week.

Salon result:

- Daily expected saved revenue: **24,641 RWF**
- Weekly expected saved revenue: **172,484 RWF**

Simple arithmetic:

```text
daily expected saved revenue = sum over 24 hours of
P(outage) x expected revenue from appliances kept ON

weekly estimate = daily expected saved revenue x 7
                = 24,641 RWF x 7
                = 172,484 RWF
```

Interpretation for judges:

The plan does not create new electricity. It protects the revenue that can still continue under a small backup power limit by choosing clippers, lights, phone charging, and mobile money before high-watt comfort/luxury loads.

## 6. Operational Risks And Mitigations

| Risk | Mitigation |
|---|---|
| Forecast is wrong | Show uncertainty band and use conservative critical-only fallback after stale limit |
| Internet drops | Cache the latest 24-hour plan locally and show its timestamp |
| Owner misunderstands OFF recommendation | Use direct appliance names, LEDs, and voice prompts instead of only probabilities |
| Startup spike trips backup | Tie-breaker penalizes high startup spike; dryer/iron are shed in high-risk windows |
| Synthetic model underfits real grid behavior | Replace generator with utility logs, outage reports, and optional neighbor signal |

## 7. Adaptation For Other Businesses

Cold room:

- Critical appliance is the freezer.
- SMS should focus on keeping the freezer and payment line on.
- Luxury/comfort loads are almost irrelevant compared with spoilage risk.

Tailor:

- Sewing machine and lighting are protected.
- Ironing is delayed during high-risk windows.
- Voice/LED output can say: "Sew now. Iron later."
