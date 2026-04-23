# Live Defense Q&A

## 1. Why this model instead of deep learning?

The generated dataset now has 365 days of hourly data while preserving the required challenge columns. A deep model would add setup risk without improving the live demonstration. I used a CPU-only forecast engine because it trains fast, is explainable, and meets the response-time constraint.

## 2. What does Brier score mean?

Brier score measures the average squared error of probability forecasts. If the system says 20 percent outage risk and the true outcome is no outage, that error is counted. Lower is better. The current held-out Brier score is **0.1216**.

## 3. How is duration MAE computed?

Duration MAE is computed only on held-out hours where an outage actually occurred. It compares the predicted expected duration against the observed outage duration. The current value is **41.22 minutes**.

## 4. What is the worst forecast case?

The worst held-out case is **2026-04-21 20:00**. The system predicted a very high outage probability because load, rain, voltage drop, and feeder congestion were all high, but no outage happened. This is a false alarm. I would improve it with real feeder outcomes and better calibration from utility logs.

## 5. How does the optimizer enforce "drop luxury before critical"?

In `prioritizer.py::plan`, high-risk hours call `_choose_on`. That function sorts appliances by category priority: critical first, comfort second, luxury last. Only after category order does it consider revenue per watt, startup spike, and name. So a luxury appliance cannot be kept ahead of a critical appliance just because it is profitable or small.

## 6. What happens if internet drops at 13:00?

The owner sees the cached plan and the timestamp of the last refresh. The plan is trusted for up to **6 hours**. If it becomes older than 6 hours, the UI or device switches to critical-only mode.

## 7. What is critical-only mode for the salon?

Keep ON:

- LED lighting
- Phone charging
- Mobile money router
- Hair clippers

Switch OFF:

- Hair dryer
- Hair straightener
- TV/radio

## 8. How does this help feature-phone users?

The morning output can be sent as three SMS messages under 160 characters each. The messages avoid probability jargon and say exactly which appliances to delay or keep running.

## 9. How would a non-reader use it?

The product artifact proposes colored LEDs on relay-board lines plus a voice prompt. Green means ON, red means OFF, amber means prepare. In the dashboard, `Play voice prompt` reads the current plan aloud, and `Save voice note` can create a local WAV file. A prompt can say: "Dryer off. Clippers on. Lights on."

## 10. What is the revenue impact?

Expected saved revenue from the current synthetic run:

| Business | Expected saved revenue per typical week |
|---|---:|
| Salon | 172,484 RWF |
| Cold room | 232,649 RWF |
| Tailor | 178,830 RWF |

These are expected protected revenue estimates, not real-world guarantees.

## 11. What would you improve next week?

I would add a neighbor signal from crowd reports, real outage logs from the utility or local feeders, and calibration by neighborhood. I would also tune the stale-plan threshold using field data from businesses.

## 12. What did LLMs help with, and what did you verify?

LLMs helped with planning, code structure, documentation, and defense preparation. I ran the code locally, checked generated metrics, reviewed the prioritizer rule, optimized forecast latency, and verified the output files.

## 13. What is the biggest limitation?

The data is synthetic. It follows the challenge recipe, but real grid outages may depend on feeder faults, maintenance, payment load, or transformer-level events not present in this dataset.

## 14. Why is forecast response measured separately from training?

The challenge requires retraining under 10 minutes and forecast API response under 300 ms after model loading. Training currently takes about **2.048 seconds**, while the 24-hour forecast response takes about **20.25 ms**.

## 15. What if the backup watt limit is wrong?

The business JSON stores `backup_limit_w`. If the owner has a bigger or smaller inverter, the value can be changed and the plan regenerates. The shedding rule still holds.

## 16. How does the dashboard update when a new shock or alert arrives?

The local dashboard uses a lightweight polling loop. The browser checks `/api/report` every 3 seconds. New alerts can be posted to `/api/event`, or simulated with `/api/simulate_event`. When the server receives an alert, it raises the affected risk window, recalculates the appliance plan for each business, increments the report revision, and the browser redraws automatically.

## 17. Why polling instead of a more complex live system?

Polling is simple, reliable, and easy to defend in a hackathon. It works on localhost, needs no extra libraries, and is enough for low-frequency events such as neighbor reports, weather shocks, or utility alerts.

## 18. Can the dashboard really send the SMS digest?

Yes. The dashboard keeps the SMS visible and also has a `Send SMS digest` button. By default it runs in dry-run mode and logs messages to `outputs/sms_outbox.jsonl`. For real sending, we set `KTT_SMS_PROVIDER=twilio`, Twilio credentials, and `KTT_SMS_RECIPIENTS` outside the repo. We never commit phone numbers or API keys.

## 19. How is the voice-note option implemented?

The dashboard has `Play voice prompt` and `Save voice note` buttons. Browser playback uses the built-in Web Speech API, so it can read the current instruction aloud without an external audio provider. Saved audio uses Windows text-to-speech when available and writes a local WAV file under `outputs/voice_notes/`. The transcript is generated from the current forecast, appliance plan, and stale-plan rule, so it changes when a new alert changes the plan.
