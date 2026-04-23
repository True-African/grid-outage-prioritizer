# Grid Outage Taxonomy Extension

This file captures the broader outage-driver analysis in a compact form. It is an optional engineering appendix: the core T2.3 submission remains the 24-hour forecast, appliance plan, dashboard, SMS digest, and low-bandwidth workflow.

## Why Add This

Real outages are rarely caused by one isolated event. A generator trip, line fault, voltage dip, or weather shock becomes serious when the grid cannot contain it because reserve margin is low, protection settings are weak, assets are overloaded, control visibility is poor, or restoration is slow.

The project therefore separates:

- **Outage drivers**: why grid risk rises.
- **Appliance prioritization**: what the business should do after risk rises.

The appliances do not cause the outage in this prototype. They are the decision layer.

## MECE Driver Groups Used

| Driver group | Examples | Prototype field(s) |
|---|---|---|
| Generation adequacy | unit trips, fuel shortage, drought, auxiliary loss | `reserve_margin_index`, `fuel_supply_risk_index`, `hydro_inflow_stress_index` |
| Transmission and substations | line faults, lightning, transformer outages, corridor congestion | `asset_health_index`, `vegetation_risk_index`, `voltage_drop_index` |
| Distribution network | feeder faults, transformer burnouts, illegal tapping, phase imbalance | `feeder_congestion_index`, `non_technical_loss_index`, `voltage_drop_index` |
| System operations | low reserve, voltage collapse, relay misoperation, slow restoration | `reserve_margin_index`, `protection_miscoordination_index` |
| Environment | heavy rain, wind, flooding, vegetation contact | `rain_stress_index`, `wind_stress_index`, `vegetation_risk_index` |
| Organization and maintenance | deferred maintenance, spares shortage, operator error | `maintenance_flag`, `asset_health_index` |
| Digital and cyber-physical systems | SCADA failure, telecom failure, cyber intrusion | `scada_telecom_risk_index` |
| Policy and market architecture | underinvestment, tariff distortion, fuel-payment arrears | `fuel_supply_risk_index`, `asset_health_index` |
| Hydropower exposure | low inflow, sedimentation, gate reliability, reservoir constraints | `hydro_inflow_stress_index` |
| DER and backup systems | solar inverter trip, battery failure, diesel auto-start failure, hybrid controller failure | `der_backup_risk_index` |

## Cascading Logic

1. A primary disturbance occurs: generator trip, feeder fault, heavy rain, voltage drop, control failure, or fuel/hydro shortfall.
2. The system response depends on reserve margin, protection coordination, alternate paths, and operator visibility.
3. If containment is weak, overloads, relay misoperations, voltage collapse, or delayed restoration can widen the outage.
4. The SME action layer cannot prevent the grid outage, but it can protect revenue by keeping critical appliances running.

## Highest-Value Utility Interventions

1. Risk-based asset health management.
2. Protection coordination review.
3. Vegetation and corridor management.
4. Reserve adequacy and frequency response.
5. Transformer and feeder loading audits.
6. SCADA/telecom modernization.
7. Operator drills and restoration discipline.
8. Non-technical loss reduction.
9. Hydrology/fuel adequacy planning.
10. Backup, solar, battery, and hybrid controller testing.

## How This Is Implemented Without Compromising T2.3

The T2.3 brief is still followed directly:

- required columns are preserved in `grid_history.csv`
- `forecaster.py` still outputs 24-hour outage probability and expected duration
- `prioritizer.py` still produces ON/OFF appliance decisions
- `lite_ui.html` remains lightweight
- `digest_spec.md` remains focused on product/business adaptation

The taxonomy is added as:

- extra factor columns in the synthetic dataset
- `data/factor_dictionary.json`
- `data/outage_taxonomy.json`
- `top_risk_factor` and `risk_explanation` in each forecast hour
- the dashboard section "Why outage risk rises"

This gives evaluators a richer engineering story while keeping the working app simple.

