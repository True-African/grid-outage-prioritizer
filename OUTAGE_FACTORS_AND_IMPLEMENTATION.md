# Outage Factors And Implementation

This project is not only an appliance prioritizer. The appliance plan is the final action, but the outage risk is driven by grid, weather, and local operating conditions.

## How The Grid Outage Forecaster Is Implemented

The forecast engine is in `forecaster.py`.

Plain-language flow:

1. Read hourly grid history from `data/grid_history.csv`.
2. Build time, load, weather, and grid-stress features.
3. Estimate hourly outage probability for the next 24 hours.
4. Estimate expected outage duration if an outage happens.
5. Explain the top risk factor for each forecast hour.
6. Send the forecast to `prioritizer.py`, which decides which appliances stay ON or go OFF.

The implementation is CPU-only and avoids heavy packages. It uses:

- a lightweight probability score for `P(outage)`
- a lightweight duration estimate for `E[duration | outage]`
- historical residuals to form a practical uncertainty band
- a fast 24-hour forecast path that responds in under 300 ms

For non-ML reviewers, the important point is this:

> The dashboard does not ask a business owner to understand the model. It shows the risk window, the reason risk is high, and what to switch ON or OFF.

## Factors That Lead To Outage

The generator keeps the required challenge columns:

- `timestamp`
- `load_mw`
- `temp_c`
- `humidity`
- `wind_ms`
- `rain_mm`
- `outage`
- `duration_min`

It also adds explicit outage-cause factors:

| Factor | Why it matters |
|---|---|
| `load_stress_index` | Demand close to local grid limits increases stress. |
| `rain_stress_index` | Heavy rain can cause line faults and repair delays. |
| `wind_stress_index` | Wind can disturb lines and outdoor connections. |
| `feeder_congestion_index` | Evening/weekday feeder congestion increases risk. |
| `voltage_drop_index` | Low-voltage conditions proxy overloaded local equipment. |
| `maintenance_flag` | Planned or emergency maintenance may interrupt power. |
| `neighbor_outage_reports` | Simulated crowd reports from nearby businesses re-rank future risk. |
| `transformer_age_years` | Older equipment has higher fault risk. |
| `payment_day_flag` | Demand can rise around salary/payment days. |
| `reserve_margin_index` | Low reserve margin makes disturbances harder to absorb. |
| `fuel_supply_risk_index` | Fuel shortage or payment arrears can reduce available generation. |
| `hydro_inflow_stress_index` | Drought or low inflow can reduce hydropower availability. |
| `vegetation_risk_index` | Vegetation exposure increases line fault risk. |
| `protection_miscoordination_index` | Weak relay coordination can turn a small fault into a wider outage. |
| `scada_telecom_risk_index` | Loss of visibility/control delays containment and restoration. |
| `non_technical_loss_index` | Illegal tapping or hidden load can overload distribution assets. |
| `asset_health_index` | Aging or stressed equipment has higher failure risk. |
| `der_backup_risk_index` | Solar, battery, diesel, or hybrid backup readiness affects resilience. |
| `primary_outage_driver` | Plain-language top driver saved for dashboard/review. |

These factors are actually used by `forecaster.py` as input features. The future forecast also includes:

- `top_risk_factor`
- `risk_explanation`

The dashboard displays these explanations under **Why outage risk rises**.

For the broader engineering taxonomy, see `GRID_OUTAGE_TAXONOMY.md`. It covers generation, transmission, distribution, operations, environment, organization, digital/cyber, policy, hydropower, and distributed/backup energy systems.

## Dataset Growth

The brief minimum is 180 days of hourly data. This repo now generates **365 days** by default, while keeping all required columns. This gives more examples of rainy periods, maintenance windows, voltage drops, and neighbor reports.

To regenerate exactly the brief minimum:

```bash
python generate_data.py --days 180
```

To regenerate the richer default:

```bash
python generate_data.py --days 365
```

## Ground-Reality Adaptation Implemented

| Reality | Implementation |
|---|---|
| Low bandwidth | `lite_ui.html` is static and small; dashboard outputs are consolidated into one report file. |
| Intermittent internet/power | The cached plan is trusted for 6 hours, then the device switches to critical-only mode. |
| Non-smartphone users | Salon owner gets 3 SMS messages, each under 160 characters. |
| Multiple languages | Report includes simple English and simple Kinyarwanda message templates. |
| Illiteracy | Non-reader workflow uses colored LEDs plus voice prompt: green ON, red OFF, amber prepare. |
| Live local shocks | `dashboard.py` accepts `POST /api/event` and updates the plan automatically. |

## Concrete Users And Workflows

Salon owner:

- Gets a morning SMS.
- Checks worst window and appliance instructions.
- If risk is red, dryer/straightener/TV are switched OFF first.
- If internet drops at 13:00, use the cached plan until it is 6 hours old.
- After 6 hours, use critical-only mode: lights, clippers, phone charging, and mobile money.

Cold room operator:

- Freezer is protected first.
- Payment and lighting stay ON if backup power allows.
- Comfort/luxury loads are not allowed to displace freezer protection.

Tailor:

- Sewing and lighting continue.
- Ironing is delayed in high-risk windows.

Non-reader:

- Green LED = keep appliance ON.
- Red LED = switch appliance OFF.
- Amber LED = prepare to switch OFF.
- Voice prompt example: "Dryer off. Clippers on. Lights on."
