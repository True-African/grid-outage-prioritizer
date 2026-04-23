"""End-to-end demo runner for AIMS T2.3.

Usage:
    python run_demo.py --business salon

This script generates data if needed, trains the CPU-only model, evaluates the
held-out month, writes the 24-hour forecast, builds appliance plans, saves a
chart, and creates the static lite UI.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg", force=True)
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np
import pandas as pd

from forecaster import evaluate_holdout, forecast_next_24, load_history, save_model, train
from generate_data import generate_all
from prioritizer import estimate_weekly_savings, plan, summarize_plan


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "outputs"
MODEL_DIR = ROOT / "models"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    tmp_path.replace(path)


def ensure_data(regenerate: bool = False) -> None:
    if regenerate or not (DATA_DIR / "grid_history.csv").exists():
        generate_all(DATA_DIR)


def clean_outputs() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for path in OUTPUT_DIR.iterdir():
        if path.is_file():
            path.unlink()


def save_forecast_chart(forecast: pd.DataFrame, salon_plan: pd.DataFrame, path: Path) -> None:
    forecast = forecast.copy()
    forecast["timestamp"] = pd.to_datetime(forecast["timestamp"])
    x = np.arange(len(forecast))
    hour_labels = forecast["timestamp"].dt.strftime("%H:%M").tolist()
    pivot = salon_plan.pivot(index="appliance", columns="timestamp", values="status")
    pivot = pivot.loc[sorted(pivot.index)]
    heat = (pivot == "ON").astype(int).to_numpy()

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={"height_ratios": [2, 1.4]})
    ax = axes[0]
    ax.fill_between(x, forecast["p_low"], forecast["p_high"], color="#a8dadc", alpha=0.55, label="uncertainty band")
    ax.plot(x, forecast["p_outage"], color="#006d77", linewidth=2.5, label="P(outage)")
    ax.bar(x, forecast["risk_minutes"] / max(forecast["risk_minutes"].max(), 1), color="#f4a261", alpha=0.35, label="risk minutes scaled")
    ax.set_title("24-hour outage risk forecast")
    ax.set_ylabel("Probability")
    ax.set_ylim(0, max(0.25, min(1.0, float(forecast["p_high"].max()) + 0.08)))
    ax.set_xticks(x[::2])
    ax.set_xticklabels(hour_labels[::2], rotation=0)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(loc="upper left")
    ax.text(
        0,
        -0.34,
        "Caption: the shaded band shows uncertainty. Higher probability and risk-minute bars trigger a more conservative appliance plan.",
        transform=ax.transAxes,
        fontsize=9,
    )

    ax2 = axes[1]
    ax2.imshow(heat, aspect="auto", cmap=ListedColormap(["#d95f5f", "#2a9d8f"]), vmin=0, vmax=1)
    ax2.set_title("Salon appliance plan overlay")
    ax2.set_yticks(np.arange(len(pivot.index)))
    ax2.set_yticklabels(pivot.index)
    ax2.set_xticks(x[::2])
    ax2.set_xticklabels(hour_labels[::2], rotation=0)
    ax2.set_xlabel("Hour")
    ax2.text(
        0,
        -0.42,
        "Caption: green means keep ON. Red means switch OFF first so critical appliances can keep earning revenue.",
        transform=ax2.transAxes,
        fontsize=9,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)


def _json_records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"]).dt.strftime("%Y-%m-%d %H:%M")
    return out.to_dict(orient="records")


def build_lite_ui(forecast: pd.DataFrame, salon_plan: pd.DataFrame, metrics: dict, impact: dict, path: Path) -> None:
    forecast_records = _json_records(forecast)
    appliances = sorted(salon_plan["appliance"].unique().tolist())
    timestamps = pd.to_datetime(forecast["timestamp"]).dt.strftime("%H:%M").tolist()
    plan_compact = {}
    for appliance in appliances:
        rows = salon_plan[salon_plan["appliance"] == appliance].copy()
        rows["timestamp"] = pd.to_datetime(rows["timestamp"])
        rows = rows.sort_values("timestamp")
        plan_compact[appliance] = rows["status"].tolist()
    metric_text = (
        f"Brier {metrics['brier_score']}, duration MAE {metrics['duration_mae_min']} min, "
        f"median lead {metrics['median_lead_time_hours']} h"
    )
    weekly_saved = int(impact["salon"]["weekly_expected_saved_rwf"])

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KTT Power Plan</title>
<style>
:root{{--ink:#19212a;--muted:#5f6c75;--line:#dce3e8;--green:#2a9d8f;--red:#d95f5f;--teal:#006d77;--amber:#f4a261;--bg:#f7fafb;}}
*{{box-sizing:border-box}}body{{margin:0;font-family:Arial,Helvetica,sans-serif;color:var(--ink);background:var(--bg)}}header{{padding:18px 20px;background:#fff;border-bottom:1px solid var(--line)}}h1{{margin:0 0 5px;font-size:24px;letter-spacing:0}}p{{line-height:1.45}}main{{max-width:1120px;margin:0 auto;padding:16px}}section{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:14px}}.kpis{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.kpi{{border-left:5px solid var(--teal);padding:8px 10px;background:#f8fbfc}}.kpi b{{display:block;font-size:18px}}canvas{{width:100%;height:260px;border:1px solid var(--line);border-radius:6px;background:#fff}}.heat{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:12px}}th,td{{border:1px solid var(--line);padding:6px;text-align:center;white-space:nowrap}}th:first-child,td:first-child{{position:sticky;left:0;background:#fff;text-align:left;z-index:1}}.on{{background:var(--green);color:#fff;font-weight:bold}}.off{{background:var(--red);color:#fff;font-weight:bold}}.caption{{color:var(--muted);font-size:13px;margin-top:8px}}.sms{{font-family:Consolas,monospace;background:#f3f6f7;padding:8px;border-radius:6px}}@media(max-width:760px){{.kpis{{grid-template-columns:1fr}}h1{{font-size:21px}}canvas{{height:230px}}}}
</style>
</head>
<body>
<header>
  <h1>KTT Power Plan: Salon</h1>
  <p>24-hour outage forecast and appliance plan for a low-bandwidth small business workflow.</p>
</header>
<main>
  <section class="kpis">
    <div class="kpi"><span>Model check</span><b>{metric_text}</b></div>
    <div class="kpi"><span>Worst window</span><b id="worstWindow">loading</b></div>
    <div class="kpi"><span>Expected weekly saved</span><b>{weekly_saved:,} RWF</b></div>
  </section>
  <section>
    <h2>Forecast risk band</h2>
    <canvas id="forecast" width="1000" height="280"></canvas>
    <p class="caption">The teal line is P(outage). The blue band is uncertainty. Amber bars are risk minutes, combining outage probability with expected duration.</p>
  </section>
  <section>
    <h2>Appliance plan overlay</h2>
    <div class="heat" id="heat"></div>
    <p class="caption">Green means keep ON. Red means switch OFF first. The rule is fixed: shed luxury before comfort, and critical appliances last.</p>
  </section>
  <section>
    <h2>Morning SMS for the salon owner</h2>
    <p class="sms">KTT Power: Salon today. High risk <span id="smsWindow">loading</span>. Keep clippers/lights ready. Delay dryer if alert turns red.</p>
  </section>
</main>
<script>
const forecast={json.dumps(forecast_records, separators=(",", ":"))};
const appliances={json.dumps(appliances, separators=(",", ":"))};
const hours={json.dumps(timestamps, separators=(",", ":"))};
const plan={json.dumps(plan_compact, separators=(",", ":"))};
function worstWindow(){{
  let best=forecast[0]; for(const f of forecast) if(f.risk_minutes>best.risk_minutes) best=f;
  const dt=new Date(best.timestamp.replace(" ","T")); const h=String(dt.getHours()).padStart(2,"0");
  const label=h+":00-"+String((dt.getHours()+1)%24).padStart(2,"0")+":00";
  document.getElementById("worstWindow").textContent=label+" ("+Math.round(best.p_outage*100)+"%)";
  document.getElementById("smsWindow").textContent=label;
}}
function drawForecast(){{
  const c=document.getElementById("forecast"),ctx=c.getContext("2d"),w=c.width,h=c.height,pad=42;
  ctx.clearRect(0,0,w,h); ctx.strokeStyle="#dce3e8"; ctx.lineWidth=1; ctx.font="12px Arial";
  for(let i=0;i<=4;i++){{let y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke();ctx.fillStyle="#5f6c75";ctx.fillText(((4-i)*25)+"%",8,y+4);}}
  const maxRisk=Math.max(...forecast.map(f=>f.risk_minutes),1), sx=i=>pad+i*(w-2*pad)/(forecast.length-1), sy=p=>h-pad-p*(h-2*pad);
  forecast.forEach((f,i)=>{{let bh=(f.risk_minutes/maxRisk)*(h-2*pad)*.45;ctx.fillStyle="rgba(244,162,97,.45)";ctx.fillRect(sx(i)-8,h-pad-bh,16,bh);}});
  ctx.beginPath(); forecast.forEach((f,i)=>{{let y=sy(f.p_high); if(i===0)ctx.moveTo(sx(i),y); else ctx.lineTo(sx(i),y);}});
  [...forecast].reverse().forEach((f,j)=>{{let i=forecast.length-1-j;ctx.lineTo(sx(i),sy(f.p_low));}}); ctx.closePath(); ctx.fillStyle="rgba(168,218,220,.6)"; ctx.fill();
  ctx.beginPath(); forecast.forEach((f,i)=>{{let y=sy(f.p_outage); if(i===0)ctx.moveTo(sx(i),y); else ctx.lineTo(sx(i),y);}}); ctx.strokeStyle="#006d77"; ctx.lineWidth=3; ctx.stroke();
  ctx.fillStyle="#19212a"; hours.forEach((hr,i)=>{{if(i%3===0)ctx.fillText(hr,sx(i)-13,h-14);}});
}}
function drawHeat(){{
  let html="<table><thead><tr><th>Appliance</th>"+hours.map(h=>"<th>"+h+"</th>").join("")+"</tr></thead><tbody>";
  for(const a of appliances){{html+="<tr><td>"+a+"</td>"; for(const st of plan[a]){{html+="<td class='"+(st==="ON"?"on":"off")+"'>"+st+"</td>";}} html+="</tr>";}}
  document.getElementById("heat").innerHTML=html+"</tbody></table>";
}}
worstWindow(); drawForecast(); drawHeat();
</script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def write_model_card(path: Path, metrics: dict) -> None:
    text = f"""# AIMS T2.3 Outage Forecaster Model Card

## Intended Use
This CPU-only model forecasts 24-hour hourly outage risk for SME appliance planning.

## Data
Synthetic data generated by `generate_data.py` from the challenge recipe: daily load peaks, weekly seasonality, rain noise, Bernoulli outage sampling, and LogNormal outage durations. The default dataset has 365 days while preserving the required challenge columns.

## Inputs
Hourly load, weather, rain, outage lags, rolling load/rain features, time-of-day features, voltage drop, feeder congestion, wind stress, maintenance flag, transformer age, payment-day flag, neighbor outage reports, reserve margin, fuel supply risk, hydro inflow stress, vegetation exposure, protection coordination risk, SCADA/telecom risk, non-technical losses, asset health, and DER/backup readiness.

## Outputs
`p_outage`, `p_low`, `p_high`, `expected_duration_min`, and `risk_minutes`.

## Metrics
- Brier score: {metrics['brier_score']}
- Duration MAE on true outage hours: {metrics['duration_mae_min']} minutes
- Median lead time: {metrics['median_lead_time_hours']} hours
- Lead-time coverage: {metrics['lead_time_coverage']}

## Limitations
The data is synthetic. This is a decision-support prototype, not a guarantee of grid behavior. Before deployment, it should be calibrated with utility outage logs, transformer-level events, and verified crowd reports.

## Reproduce
Run `python run_demo.py --business salon` from the repository root.
"""
    path.write_text(text, encoding="utf-8")


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for column in out.columns:
        if column == "timestamp":
            out[column] = pd.to_datetime(out[column]).dt.strftime("%Y-%m-%d %H:%M")
    return out.to_dict(orient="records")


def _worst_window(forecast: pd.DataFrame) -> dict:
    row = forecast.sort_values("risk_minutes", ascending=False).iloc[0]
    ts = pd.Timestamp(row["timestamp"])
    return {
        "start": ts.strftime("%H:%M"),
        "end": (ts + pd.Timedelta(hours=1)).strftime("%H:%M"),
        "label": f"{ts:%H:%M}-{(ts + pd.Timedelta(hours=1)):%H:%M}",
        "p_outage": round(float(row["p_outage"]), 4),
        "risk_minutes": round(float(row["risk_minutes"]), 2),
    }


def _demo_sms(worst: dict) -> list[dict]:
    messages = [
        f"KTT Power: Salon today. Highest risk {worst['label']}. Keep lights, clippers and payments ready; delay dryer when alert is red.",
        "If outage hits: OFF dryer and straightener first. Keep lights, clippers, phone charging, payments; TV only if backup allows.",
        "No internet at 13:00? Use cached plan until 6h old. After that run critical-only mode: lights, clippers, phone and payments.",
    ]
    return [{"message": message, "characters": len(message)} for message in messages]


def _factor_summary(history: pd.DataFrame) -> dict:
    outage_rows = history[history["outage"] == 1].copy()
    if outage_rows.empty or "primary_outage_driver" not in outage_rows.columns:
        driver_counts = {}
    else:
        driver_counts = outage_rows["primary_outage_driver"].value_counts().to_dict()
    factor_columns = [
        "load_stress_index",
        "rain_stress_index",
        "wind_stress_index",
        "feeder_congestion_index",
        "voltage_drop_index",
        "maintenance_flag",
        "neighbor_outage_reports",
        "transformer_age_years",
        "payment_day_flag",
        "reserve_margin_index",
        "fuel_supply_risk_index",
        "hydro_inflow_stress_index",
        "vegetation_risk_index",
        "protection_miscoordination_index",
        "scada_telecom_risk_index",
        "non_technical_loss_index",
        "asset_health_index",
        "der_backup_risk_index",
    ]
    means = {}
    for column in factor_columns:
        if column in history.columns:
            means[column] = round(float(history[column].mean()), 3)
    return {
        "history_rows": int(len(history)),
        "history_days": round(float(len(history) / 24), 1),
        "outage_hours": int(history["outage"].sum()),
        "outage_rate": round(float(history["outage"].mean()), 4),
        "driver_counts_on_outage_hours": driver_counts,
        "average_factor_values": means,
    }


def _decision_summary(plan_df: pd.DataFrame) -> list[dict]:
    grouped = []
    for ts, rows in plan_df.groupby("timestamp"):
        off = rows[rows["status"] == "OFF"]["appliance"].tolist()
        on = rows[rows["status"] == "ON"]["appliance"].tolist()
        grouped.append(
            {
                "timestamp": pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M"),
                "off": off,
                "on": on,
                "action": "All appliances ON" if not off else "Switch OFF: " + ", ".join(off),
            }
        )
    return grouped


def build_report(
    metrics: dict,
    history: pd.DataFrame,
    forecast: pd.DataFrame,
    worst_cases: pd.DataFrame,
    appliances: list[dict],
    businesses: list[dict],
    factor_dictionary: dict,
    outage_taxonomy: dict,
    plan_map: dict[str, pd.DataFrame],
    summaries: dict[str, dict],
    impact: dict[str, dict],
) -> dict:
    worst = _worst_window(forecast)
    return {
        "revision": 1,
        "live_events": [],
        "last_event": None,
        "generated_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "challenge": "AIMS KTT T2.3 Grid Outage Forecaster + Appliance Prioritizer",
        "plain_language": {
            "what_it_does": "Shows when outage risk is high and tells each small business what to keep ON or switch OFF.",
            "decision_rule": "Protect critical revenue appliances first. Shed luxury first, then comfort, then critical only if power is still not enough.",
            "no_ml_background_needed": "The dashboard explains the forecast as risk, duration, and appliance actions. The technical metrics are included for judges but not required to use the plan.",
        },
        "factor_dictionary": factor_dictionary,
        "outage_taxonomy": outage_taxonomy,
        "factor_summary": _factor_summary(history),
        "metrics": metrics,
        "forecast": _records(forecast),
        "appliances": appliances,
        "businesses": {business["name"]: business for business in businesses},
        "plans": {name: _records(plan_df) for name, plan_df in plan_map.items()},
        "decision_summary": {name: _decision_summary(plan_df) for name, plan_df in plan_map.items()},
        "summaries": summaries,
        "impact": impact,
        "worst_forecast_window": worst,
        "worst_holdout_cases": _records(worst_cases),
        "sms_digest": _demo_sms(worst),
        "localized_messages": {
            "en": [
                "Dryer OFF when alert is red.",
                "Keep lights, clippers, phone charging and payments ON.",
                "No internet: use cached plan for 6 hours, then critical-only mode.",
            ],
            "rw_simple": [
                "Funga dryer niba ibara ritukura.",
                "Cana amatara, clippers, telefone na mobile money.",
                "Nta internet: koresha plan ibitswe amasaha 6, nyuma ukoreshe ibya ngombwa gusa.",
            ],
        },
        "non_reader_workflow": {
            "interface": "colored LED relay board plus voice prompt",
            "green": "appliance stays ON",
            "red": "switch appliance OFF first",
            "amber": "prepare to switch off if outage starts",
            "voice_prompt_example": "Dryer off. Clippers on. Lights on.",
        },
        "offline_policy": {
            "maximum_staleness_hours": 6,
            "risk_budget": "Stop trusting the plan after 6 hours or when risk may have shifted by about 15 percentage points.",
            "fallback": "Critical-only mode: keep lights, clippers, phone charging, and mobile money router ON; switch dryer, straightener, and TV/radio OFF.",
        },
    }


def run_pipeline(business: str = "salon", regenerate_data: bool = False, clean: bool = True) -> dict:
    if clean:
        clean_outputs()
    OUTPUT_DIR.mkdir(exist_ok=True)
    MODEL_DIR.mkdir(exist_ok=True)
    ensure_data(regenerate=regenerate_data)

    history = load_history(DATA_DIR / "grid_history.csv")
    t0 = time.perf_counter()
    model_bundle = train(history)
    train_seconds = time.perf_counter() - t0
    save_model(model_bundle, MODEL_DIR / "outage_forecaster.joblib")

    metrics, worst = evaluate_holdout(history)
    forecast_start = time.perf_counter()
    forecast = forecast_next_24(model_bundle, history)
    forecast_latency_ms = (time.perf_counter() - forecast_start) * 1000.0
    metrics["full_train_seconds"] = round(train_seconds, 3)
    metrics["forecast_response_ms"] = round(forecast_latency_ms, 2)

    appliances = read_json(DATA_DIR / "appliances.json")
    businesses = read_json(DATA_DIR / "businesses.json")
    factor_dictionary = read_json(DATA_DIR / "factor_dictionary.json") if (DATA_DIR / "factor_dictionary.json").exists() else {}
    outage_taxonomy = read_json(DATA_DIR / "outage_taxonomy.json") if (DATA_DIR / "outage_taxonomy.json").exists() else {}
    business_map = {b["name"]: b for b in businesses}
    impact: dict[str, dict] = {}
    summaries: dict[str, dict] = {}
    plan_map: dict[str, pd.DataFrame] = {}
    for business_name, business in business_map.items():
        plan_df = plan(forecast, appliances, business)
        plan_df.insert(0, "business", business_name)
        summaries[business_name] = summarize_plan(plan_df)
        impact[business_name] = estimate_weekly_savings(plan_df)
        plan_map[business_name] = plan_df

    all_plans = pd.concat(plan_map.values(), ignore_index=True)
    all_plans.to_csv(OUTPUT_DIR / "plans_all.csv", index=False)

    report = build_report(metrics, history, forecast, worst, appliances, businesses, factor_dictionary, outage_taxonomy, plan_map, summaries, impact)
    write_json(OUTPUT_DIR / "demo_report.json", report)

    save_forecast_chart(forecast, plan_map["salon"], OUTPUT_DIR / "forecast_plan_salon.png")
    build_lite_ui(forecast, plan_map["salon"], metrics, impact, ROOT / "lite_ui.html")
    write_model_card(ROOT / "MODEL_CARD.md", metrics)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the AIMS T2.3 demo report and dashboard assets.")
    parser.add_argument("--business", default="salon", choices=["salon", "cold_room", "tailor"])
    parser.add_argument("--regenerate-data", action="store_true")
    parser.add_argument("--keep-old-outputs", action="store_true", help="Do not clear old files from outputs/ before writing the new report.")
    args = parser.parse_args()

    report = run_pipeline(args.business, regenerate_data=args.regenerate_data, clean=not args.keep_old_outputs)
    metrics = report["metrics"]
    impact = report["impact"]
    chosen = args.business
    print("AIMS T2.3 demo complete")
    print(f"Brier score: {metrics['brier_score']}")
    print(f"Duration MAE: {metrics['duration_mae_min']} minutes")
    print(f"Median lead time: {metrics['median_lead_time_hours']} hours")
    print(f"Forecast response: {metrics['forecast_response_ms']} ms")
    print(f"{chosen} expected weekly saved revenue: {impact[chosen]['weekly_expected_saved_rwf']:,.0f} RWF")
    print("Open lite_ui.html for the static view, or run python dashboard.py for localhost.")


if __name__ == "__main__":
    main()
