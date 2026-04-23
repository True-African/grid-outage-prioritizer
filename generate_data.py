"""Generate synthetic grid outage and appliance data for AIMS T2.3.

The generator follows the challenge recipe:
- 365 days of hourly grid history by default, while preserving the required
  challenge columns. Use `--days 180` if you want the exact brief minimum.
- Daily load with morning and evening peaks.
- Weekly seasonality and rainy-season noise.
- Outage probability driven by lagged load, rain, and hour-of-day effects.
- Extra ground-reality factors: feeder congestion, voltage drops, maintenance
  windows, transformer age, wind stress, and neighbor outage reports.
- Outage duration sampled from a LogNormal distribution with mean near 90 min.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_SEED = 42
END_TIMESTAMP = "2026-04-22 23:00:00"
DEFAULT_DAYS = 365


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def calibrate_intercept(linear_part: np.ndarray, target_rate: float) -> float:
    """Find an intercept that gives the requested average outage rate."""
    low, high = -10.0, 5.0
    for _ in range(80):
        mid = (low + high) / 2.0
        mean_rate = float(sigmoid(mid + linear_part).mean())
        if mean_rate < target_rate:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def make_grid_history(seed: int = DEFAULT_SEED, days: int = DEFAULT_DAYS) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    hours_total = int(days) * 24
    timestamps = pd.date_range(end=pd.Timestamp(END_TIMESTAMP), periods=hours_total, freq="h")
    df = pd.DataFrame({"timestamp": timestamps})
    df["hour"] = df["timestamp"].dt.hour
    df["dayofweek"] = df["timestamp"].dt.dayofweek
    df["day_index"] = np.arange(len(df)) // 24

    hour = df["hour"].to_numpy()
    dayofweek = df["dayofweek"].to_numpy()
    day_index = df["day_index"].to_numpy()

    morning_peak = 18.0 * np.exp(-0.5 * ((hour - 9) / 2.1) ** 2)
    evening_peak = 25.0 * np.exp(-0.5 * ((hour - 19) / 2.5) ** 2)
    weekly_factor = np.where(dayofweek >= 5, 0.90, 1.0) + 0.04 * np.sin(2 * np.pi * dayofweek / 7)
    seasonal_wave = 2.5 * np.sin(2 * np.pi * day_index / 90)

    rainy_season = 0.35 + 0.25 * np.sin(2 * np.pi * (day_index + 20) / 120)
    rain_probability = np.clip(rainy_season + 0.08 * (hour >= 14), 0.08, 0.68)
    rain_event = rng.binomial(1, rain_probability)
    rain_mm = rain_event * rng.gamma(shape=1.7, scale=3.2, size=len(df))

    temp_c = 23.5 + 4.0 * np.sin(2 * np.pi * (hour - 7) / 24) - 0.09 * rain_mm
    temp_c += rng.normal(0, 0.8, len(df))
    humidity = 55 + 22 * rain_event + 8 * np.sin(2 * np.pi * (hour + 4) / 24)
    humidity += rng.normal(0, 5.5, len(df))
    wind_ms = np.clip(2.3 + 1.0 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 0.7, len(df)), 0.1, None)

    load_mw = 37.0 + seasonal_wave + weekly_factor * (morning_peak + evening_peak)
    load_mw += 0.55 * rain_mm + rng.normal(0, 2.6, len(df))
    load_mw = np.clip(load_mw, 25.0, None)

    load_stress_index = np.clip((load_mw - 48.0) / 18.0, 0, 1)
    rain_stress_index = np.clip(rain_mm / 18.0, 0, 1)
    wind_stress_index = np.clip((wind_ms - 3.0) / 3.5, 0, 1)
    evening_peak_flag = ((hour >= 17) & (hour <= 21)).astype(int)
    feeder_congestion_index = np.clip(
        0.35 * load_stress_index
        + 0.25 * evening_peak_flag
        + 0.18 * (dayofweek < 5)
        + rng.normal(0, 0.08, len(df)),
        0,
        1,
    )
    transformer_age_years = np.clip(9.0 + 3.2 * np.sin(2 * np.pi * day_index / 180) + rng.normal(0, 0.5, len(df)), 4, 18)
    payment_day_flag = np.isin(pd.to_datetime(df["timestamp"]).dt.day.to_numpy(), [15, 30, 31]).astype(int)
    maintenance_probability = np.clip(0.008 + 0.025 * ((hour >= 10) & (hour <= 15)) + 0.01 * (dayofweek == 2), 0, 0.08)
    maintenance_flag = rng.binomial(1, maintenance_probability)
    voltage_drop_index = np.clip(
        0.42 * feeder_congestion_index
        + 0.28 * load_stress_index
        + 0.20 * rain_stress_index
        + 0.12 * wind_stress_index
        + rng.normal(0, 0.06, len(df)),
        0,
        1,
    )
    crowd_base = 0.02 + 0.25 * rain_stress_index + 0.12 * voltage_drop_index
    neighbor_outage_reports = rng.poisson(np.clip(crowd_base, 0, 1.2))
    reserve_margin_index = np.clip(
        0.48 * load_stress_index
        + 0.22 * evening_peak_flag
        + 0.18 * payment_day_flag
        + rng.normal(0, 0.07, len(df)),
        0,
        1,
    )
    fuel_supply_risk_index = np.clip(
        0.10
        + 0.18 * payment_day_flag
        + 0.12 * np.sin(2 * np.pi * (day_index + 10) / 60)
        + rng.normal(0, 0.06, len(df)),
        0,
        1,
    )
    hydro_inflow_stress_index = np.clip(
        0.55 - rainy_season + 0.12 * np.sin(2 * np.pi * day_index / 365) + rng.normal(0, 0.05, len(df)),
        0,
        1,
    )
    vegetation_risk_index = np.clip(
        0.20 + 0.35 * rain_stress_index + 0.25 * wind_stress_index + 0.08 * np.sin(2 * np.pi * day_index / 45),
        0,
        1,
    )
    protection_miscoordination_index = np.clip(
        0.10 + 0.22 * feeder_congestion_index + 0.12 * (transformer_age_years > 11) + rng.normal(0, 0.04, len(df)),
        0,
        1,
    )
    scada_telecom_risk_index = np.clip(
        0.06 + 0.12 * rain_stress_index + 0.08 * wind_stress_index + rng.normal(0, 0.035, len(df)),
        0,
        1,
    )
    non_technical_loss_index = np.clip(
        0.18 + 0.20 * payment_day_flag + 0.18 * np.sin(2 * np.pi * day_index / 30) + rng.normal(0, 0.05, len(df)),
        0,
        1,
    )
    asset_health_index = np.clip(
        transformer_age_years / 18.0 + 0.18 * voltage_drop_index + 0.12 * feeder_congestion_index,
        0,
        1,
    )
    der_backup_risk_index = np.clip(
        0.10
        + 0.25 * hydro_inflow_stress_index
        + 0.20 * fuel_supply_risk_index
        + 0.16 * scada_telecom_risk_index
        + rng.normal(0, 0.04, len(df)),
        0,
        1,
    )

    load_lag1 = pd.Series(load_mw).shift(1).bfill().to_numpy()
    load_z = (load_lag1 - load_lag1.mean()) / load_lag1.std()
    rain_z = (rain_mm - rain_mm.mean()) / max(rain_mm.std(), 1e-6)
    hour_effect = 0.45 * np.exp(-0.5 * ((hour - 18) / 3.5) ** 2)
    hour_effect += 0.25 * np.exp(-0.5 * ((hour - 13) / 2.8) ** 2)
    linear_part = (
        0.72 * load_z
        + 0.45 * rain_z
        + hour_effect
        + 0.85 * voltage_drop_index
        + 0.55 * feeder_congestion_index
        + 0.45 * maintenance_flag
        + 0.32 * wind_stress_index
        + 0.14 * neighbor_outage_reports
        + 0.08 * payment_day_flag
        + 0.42 * reserve_margin_index
        + 0.24 * fuel_supply_risk_index
        + 0.25 * hydro_inflow_stress_index
        + 0.30 * vegetation_risk_index
        + 0.34 * protection_miscoordination_index
        + 0.18 * scada_telecom_risk_index
        + 0.28 * non_technical_loss_index
        + 0.36 * asset_health_index
        + 0.16 * der_backup_risk_index
    )
    intercept = calibrate_intercept(linear_part, target_rate=0.04)
    outage_probability = sigmoid(intercept + linear_part)
    outage = rng.binomial(1, outage_probability)

    primary_driver = np.select(
        [
            maintenance_flag == 1,
            voltage_drop_index >= 0.62,
            rain_stress_index >= 0.40,
            feeder_congestion_index >= 0.58,
            neighbor_outage_reports >= 2,
            reserve_margin_index >= 0.60,
            asset_health_index >= 0.68,
            vegetation_risk_index >= 0.60,
            hydro_inflow_stress_index >= 0.55,
            non_technical_loss_index >= 0.62,
            protection_miscoordination_index >= 0.55,
            der_backup_risk_index >= 0.55,
            wind_stress_index >= 0.35,
        ],
        [
            "maintenance",
            "voltage_drop",
            "heavy_rain",
            "feeder_congestion",
            "neighbor_reports",
            "low_reserve_margin",
            "asset_health",
            "vegetation_exposure",
            "hydro_inflow_stress",
            "non_technical_losses",
            "protection_coordination",
            "der_backup_readiness",
            "wind_stress",
        ],
        default="routine_load",
    )

    sigma = 0.6
    mu = math.log(90.0) - (sigma**2) / 2.0
    duration = rng.lognormal(mean=mu, sigma=sigma, size=len(df))
    duration_multiplier = 1 + 0.55 * maintenance_flag + 0.35 * voltage_drop_index + 0.22 * rain_stress_index
    duration_min = np.where(outage == 1, np.clip(duration * duration_multiplier, 15, 420), 0.0)

    out = pd.DataFrame(
        {
            "timestamp": df["timestamp"],
            "load_mw": np.round(load_mw, 3),
            "temp_c": np.round(temp_c, 2),
            "humidity": np.round(np.clip(humidity, 20, 100), 2),
            "wind_ms": np.round(wind_ms, 2),
            "rain_mm": np.round(rain_mm, 2),
            "load_stress_index": np.round(load_stress_index, 3),
            "rain_stress_index": np.round(rain_stress_index, 3),
            "wind_stress_index": np.round(wind_stress_index, 3),
            "feeder_congestion_index": np.round(feeder_congestion_index, 3),
            "voltage_drop_index": np.round(voltage_drop_index, 3),
            "maintenance_flag": maintenance_flag.astype(int),
            "neighbor_outage_reports": neighbor_outage_reports.astype(int),
            "transformer_age_years": np.round(transformer_age_years, 1),
            "payment_day_flag": payment_day_flag.astype(int),
            "reserve_margin_index": np.round(reserve_margin_index, 3),
            "fuel_supply_risk_index": np.round(fuel_supply_risk_index, 3),
            "hydro_inflow_stress_index": np.round(hydro_inflow_stress_index, 3),
            "vegetation_risk_index": np.round(vegetation_risk_index, 3),
            "protection_miscoordination_index": np.round(protection_miscoordination_index, 3),
            "scada_telecom_risk_index": np.round(scada_telecom_risk_index, 3),
            "non_technical_loss_index": np.round(non_technical_loss_index, 3),
            "asset_health_index": np.round(asset_health_index, 3),
            "der_backup_risk_index": np.round(der_backup_risk_index, 3),
            "primary_outage_driver": primary_driver,
            "outage": outage.astype(int),
            "duration_min": np.round(duration_min, 1),
        }
    )
    return out


def appliance_catalog() -> list[dict]:
    return [
        {
            "name": "LED lighting",
            "category": "critical",
            "watts_avg": 45,
            "start_up_spike_w": 50,
            "revenue_if_running_rwf_per_h": 1200,
        },
        {
            "name": "Phone charging",
            "category": "critical",
            "watts_avg": 20,
            "start_up_spike_w": 25,
            "revenue_if_running_rwf_per_h": 800,
        },
        {
            "name": "Mobile money router",
            "category": "critical",
            "watts_avg": 18,
            "start_up_spike_w": 30,
            "revenue_if_running_rwf_per_h": 900,
        },
        {
            "name": "Hair clippers",
            "category": "critical",
            "watts_avg": 35,
            "start_up_spike_w": 70,
            "revenue_if_running_rwf_per_h": 2600,
        },
        {
            "name": "Hair dryer",
            "category": "comfort",
            "watts_avg": 1200,
            "start_up_spike_w": 1600,
            "revenue_if_running_rwf_per_h": 3500,
        },
        {
            "name": "Hair straightener",
            "category": "comfort",
            "watts_avg": 650,
            "start_up_spike_w": 800,
            "revenue_if_running_rwf_per_h": 2800,
        },
        {
            "name": "Chest freezer",
            "category": "critical",
            "watts_avg": 220,
            "start_up_spike_w": 850,
            "revenue_if_running_rwf_per_h": 5600,
        },
        {
            "name": "Sewing machine",
            "category": "critical",
            "watts_avg": 140,
            "start_up_spike_w": 360,
            "revenue_if_running_rwf_per_h": 3200,
        },
        {
            "name": "Electric iron",
            "category": "comfort",
            "watts_avg": 1000,
            "start_up_spike_w": 1300,
            "revenue_if_running_rwf_per_h": 2400,
        },
        {
            "name": "TV/radio",
            "category": "luxury",
            "watts_avg": 90,
            "start_up_spike_w": 120,
            "revenue_if_running_rwf_per_h": 300,
        },
    ]


def business_archetypes() -> list[dict]:
    return [
        {
            "name": "salon",
            "display_name": "Neighborhood salon",
            "backup_limit_w": 700,
            "risk_threshold": 0.11,
            "appliances": [
                "LED lighting",
                "Phone charging",
                "Mobile money router",
                "Hair clippers",
                "Hair dryer",
                "Hair straightener",
                "TV/radio",
            ],
            "notes": "Small inverter can keep clippers, lights, payments, and one mid-load tool, but not the dryer.",
        },
        {
            "name": "cold_room",
            "display_name": "Cold room kiosk",
            "backup_limit_w": 360,
            "risk_threshold": 0.09,
            "appliances": ["Chest freezer", "LED lighting", "Phone charging", "Mobile money router"],
            "notes": "Backup is reserved for the freezer and payment/lighting basics.",
        },
        {
            "name": "tailor",
            "display_name": "Tailor shop",
            "backup_limit_w": 500,
            "risk_threshold": 0.10,
            "appliances": [
                "Sewing machine",
                "Electric iron",
                "LED lighting",
                "Phone charging",
                "Mobile money router",
                "TV/radio",
            ],
            "notes": "Sewing continues on backup; ironing is delayed during high-risk hours.",
        },
    ]


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def factor_dictionary() -> dict:
    return {
        "required_columns": [
            "timestamp",
            "load_mw",
            "temp_c",
            "humidity",
            "wind_ms",
            "rain_mm",
            "outage",
            "duration_min",
        ],
        "extra_outage_factors": {
            "load_stress_index": "How close demand is to local grid stress; higher demand increases outage risk.",
            "rain_stress_index": "Heavy rain can trigger line faults and access delays.",
            "wind_stress_index": "Wind increases line-fault risk.",
            "feeder_congestion_index": "Local feeder stress from evening and weekday demand.",
            "voltage_drop_index": "Proxy for low-voltage/overloaded feeder conditions.",
            "maintenance_flag": "Planned or emergency maintenance window.",
            "neighbor_outage_reports": "Optional stretch signal: simulated nearby outage reports.",
            "transformer_age_years": "Older equipment has higher fault risk.",
            "payment_day_flag": "Demand/load pressure around salary/payment days.",
            "reserve_margin_index": "Low reserve margin means one generator or feeder disturbance is harder to absorb.",
            "fuel_supply_risk_index": "Fuel shortages or payment arrears can reduce available generation.",
            "hydro_inflow_stress_index": "Drought or low inflow can reduce hydropower availability.",
            "vegetation_risk_index": "Tree/vegetation exposure increases line fault risk.",
            "protection_miscoordination_index": "Weak relay/protection coordination can make small faults trip wider areas.",
            "scada_telecom_risk_index": "Control-center, telecom, or visibility problems delay response.",
            "non_technical_loss_index": "Illegal tapping and hidden load can overload transformers/feeders.",
            "asset_health_index": "Aging or stressed equipment is more likely to fail.",
            "der_backup_risk_index": "Backup, solar, battery, or hybrid-system readiness can affect resilience during grid stress.",
            "primary_outage_driver": "Plain-language top driver for dashboards and review.",
        },
        "ground_reality_note": "The required brief columns are preserved; extra columns make outage causes visible and defendable.",
    }


def outage_taxonomy() -> dict:
    """Compact taxonomy distilled from broader grid-outage engineering analysis."""
    return {
        "purpose": "Keep the hackathon workflow simple while acknowledging real outage mechanisms.",
        "driver_groups": [
            {"group": "Generation adequacy", "examples": ["unit trips", "fuel shortage", "drought", "auxiliary loss"], "prototype_fields": ["reserve_margin_index", "fuel_supply_risk_index", "hydro_inflow_stress_index"]},
            {"group": "Transmission and substations", "examples": ["line faults", "lightning", "transformer outages", "corridor congestion"], "prototype_fields": ["asset_health_index", "vegetation_risk_index", "voltage_drop_index"]},
            {"group": "Distribution network", "examples": ["feeder faults", "transformer burnouts", "illegal tapping", "phase imbalance"], "prototype_fields": ["feeder_congestion_index", "non_technical_loss_index", "voltage_drop_index"]},
            {"group": "System operations", "examples": ["low reserve", "voltage collapse", "relay misoperation", "slow restoration"], "prototype_fields": ["reserve_margin_index", "protection_miscoordination_index"]},
            {"group": "Environment", "examples": ["heavy rain", "wind", "flooding", "vegetation contact"], "prototype_fields": ["rain_stress_index", "wind_stress_index", "vegetation_risk_index"]},
            {"group": "Organization and maintenance", "examples": ["deferred maintenance", "spares shortage", "operator error"], "prototype_fields": ["maintenance_flag", "asset_health_index"]},
            {"group": "Digital and cyber-physical systems", "examples": ["SCADA failure", "telecom failure", "cyber intrusion"], "prototype_fields": ["scada_telecom_risk_index"]},
            {"group": "Policy and market architecture", "examples": ["underinvestment", "tariff distortion", "fuel-payment arrears"], "prototype_fields": ["fuel_supply_risk_index", "asset_health_index"]},
            {"group": "Hydropower exposure", "examples": ["low inflow", "sedimentation", "gate reliability", "reservoir constraints"], "prototype_fields": ["hydro_inflow_stress_index"]},
            {"group": "DER and backup systems", "examples": ["solar inverter trip", "battery failure", "diesel auto-start failure", "hybrid controller failure"], "prototype_fields": ["der_backup_risk_index"]},
        ],
        "cascade_logic": [
            "A primary disturbance occurs, such as generator trip, feeder fault, weather shock, or voltage drop.",
            "The grid response depends on reserve margin, protection settings, alternate paths, and operator visibility.",
            "If containment is weak, overloads, misoperations, or delayed restoration can widen the outage.",
            "The SME action layer cannot prevent the grid outage, but it can protect revenue by prioritizing critical appliances.",
        ],
        "top_interventions": [
            "risk-based asset health management",
            "protection coordination review",
            "vegetation and corridor management",
            "reserve adequacy and frequency response",
            "transformer and feeder loading audits",
            "SCADA/telecom modernization",
            "operator drills and restoration discipline",
            "non-technical loss reduction",
            "hydrology/fuel adequacy planning",
            "backup, solar, battery, and hybrid controller testing",
        ],
        "scope_note": "The T2.3 brief requires an SME forecast-and-prioritization prototype. This taxonomy is used to select representative factors and to guide future utility-grade analytics.",
    }


def generate_all(output_dir: str | Path = "data", seed: int = DEFAULT_SEED, days: int = DEFAULT_DAYS) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    history = make_grid_history(seed=seed, days=days)
    history.to_csv(output_path / "grid_history.csv", index=False)
    write_json(output_path / "appliances.json", appliance_catalog())
    write_json(output_path / "businesses.json", business_archetypes())
    write_json(output_path / "factor_dictionary.json", factor_dictionary())
    write_json(output_path / "outage_taxonomy.json", outage_taxonomy())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic AIMS T2.3 data.")
    parser.add_argument("--output-dir", default="data")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = parser.parse_args()
    generate_all(args.output_dir, args.seed, args.days)
    print(f"Wrote {args.days} days of grid history, appliances, businesses, factor dictionary, and outage taxonomy to {args.output_dir}")


if __name__ == "__main__":
    main()
