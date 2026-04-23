"""End-to-end demo runner for Grid Outage Planner.

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


def build_lite_ui(report: dict, path: Path) -> None:
    forecast = report["forecast"]
    businesses = report["businesses"]
    appliance_lookup = {
        item["name"]: {
            "category": item["category"],
            "watts_avg": item["watts_avg"],
            "start_up_spike_w": item["start_up_spike_w"],
            "revenue_if_running_rwf_per_h": item["revenue_if_running_rwf_per_h"],
        }
        for item in report["appliances"]
    }
    hours = [row["timestamp"][-5:] for row in forecast]
    compact_plans: dict[str, dict[str, list[str]]] = {}
    for business_name, business in businesses.items():
        rows = report["plans"][business_name]
        compact_plans[business_name] = {}
        for appliance in business["appliances"]:
            appliance_rows = [row for row in rows if row["appliance"] == appliance]
            appliance_rows.sort(key=lambda row: row["timestamp"])
            compact_plans[business_name][appliance] = [row["status"] for row in appliance_rows]

    top_windows = sorted(forecast, key=lambda row: float(row["risk_minutes"]), reverse=True)[:6]
    factor_counts = sorted(
        report["factor_summary"]["driver_counts_on_outage_hours"].items(),
        key=lambda item: item[1],
        reverse=True,
    )
    taxonomy_groups = [
        {
            "group": item["group"],
            "prototype_fields": item.get("prototype_fields", []),
        }
        for item in report.get("outage_taxonomy", {}).get("driver_groups", [])[:8]
    ]
    ui_data = {
        "generated_at": report["generated_at"],
        "plain_language": report["plain_language"],
        "metrics": report["metrics"],
        "forecast": forecast,
        "hours": hours,
        "businesses": businesses,
        "plans": compact_plans,
        "impact": report["impact"],
        "summaries": report["summaries"],
        "decision_summary": report["decision_summary"],
        "sms_digest": report["sms_digest"],
        "localized_messages": report["localized_messages"],
        "offline_policy": report["offline_policy"],
        "non_reader_workflow": report["non_reader_workflow"],
        "worst_forecast_window": report["worst_forecast_window"],
        "factor_counts": [{"name": key.replace("_", " "), "count": value} for key, value in factor_counts[:8]],
        "top_windows": top_windows,
        "taxonomy_groups": taxonomy_groups,
        "factor_summary": report["factor_summary"],
        "appliance_lookup": appliance_lookup,
        "hosted_notice": {
            "title": "Hosted static snapshot",
            "message": "This Hugging Face page shows the latest generated report. The full live dashboard, rebuild action, incoming-data API, SMS delivery, and saved voice notes run from dashboard.py on localhost.",
        },
    }

    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Grid Outage Planner</title>
<style>
:root{--ink:#17212b;--muted:#60707d;--line:#d9e2e8;--panel:#fff;--bg:#f4f7f8;--rail:#11191f;--teal:#006d77;--green:#2a9d8f;--red:#d95f5f;--amber:#f4a261;--blue:#457b9d}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;font-family:Arial,Helvetica,sans-serif;color:var(--ink);background:var(--bg)}header{background:#fff;border-bottom:1px solid var(--line);padding:14px 18px;position:sticky;top:0;z-index:5}h1{font-size:23px;margin:0 0 4px;letter-spacing:0}h2{font-size:17px;margin:0}h3{font-size:14px;margin:12px 0 7px}p{line-height:1.42}.top{display:flex;gap:12px;align-items:center;justify-content:space-between;flex-wrap:wrap}.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap}select,button{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:#fff}button{background:var(--teal);color:#fff;border-color:var(--teal);cursor:pointer}.ghost{background:#fff;color:var(--teal)}main{max-width:1440px;margin:0 auto;padding:14px}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.layout{display:grid;grid-template-columns:270px minmax(0,1fr);gap:12px}.side{background:var(--rail);color:#dce7eb;border-radius:8px;padding:12px;position:sticky;top:92px;align-self:start;max-height:calc(100vh - 108px);overflow:auto}.side h2,.side h3{color:#fff}.muted{color:var(--muted);font-size:13px}.side .muted{color:#9eb1bb}.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:0;margin-bottom:10px;overflow:hidden}.panel>summary{list-style:none;cursor:pointer;padding:12px 14px;font-weight:bold;display:flex;justify-content:space-between;gap:12px;align-items:center;background:#fbfdfe;border-bottom:1px solid var(--line)}.panel>summary::-webkit-details-marker{display:none}.panel>summary:after{content:"+";font-size:18px;color:var(--teal)}.panel[open]>summary:after{content:"-"}details.panel>*:not(summary){margin-left:14px;margin-right:14px}.panel-pad{padding:12px 14px}.two{display:grid;grid-template-columns:1.35fr .65fr;gap:12px}.kpi{background:#fff;border:1px solid var(--line);border-left:5px solid var(--teal);padding:9px;border-radius:7px}.kpi b{display:block;font-size:19px;margin-top:3px}.caption{color:var(--muted);font-size:13px;margin:8px 0 12px}.pill{display:inline-block;padding:3px 8px;border-radius:999px;background:#edf5f6;color:#124f57;font-size:12px;margin:2px}.risk-high{background:#ffe9e4;color:#8a231a}.risk-ok{background:#e7f6f2;color:#1d6a60}.risk-mid{background:#fff3e8;color:#9b5400}.hosted{background:#ecf4ff;color:#1d5275}canvas{width:100%;height:280px;border:1px solid var(--line);border-radius:6px;background:#fff}.table-wrap{overflow:auto}table{border-collapse:collapse;width:100%;font-size:12px}th,td{border:1px solid var(--line);padding:6px;text-align:left;vertical-align:top}th{background:#f2f6f8}.heat th,.heat td{text-align:center;white-space:nowrap}.heat th:first-child,.heat td:first-child{position:sticky;left:0;background:#fff;text-align:left;z-index:1}.on{background:var(--green);color:#fff;font-weight:bold}.off{background:var(--red);color:#fff;font-weight:bold}.sms{font-family:Consolas,monospace;background:#f3f6f7;padding:9px;border-radius:6px;margin:8px 0}.decision,.signal{border-left:4px solid var(--amber);padding:8px 10px;background:#fffaf3;margin:8px 0}.signal{background:#152229;border-color:#2a9d8f;color:#dce7eb}.signal b{color:#fff}.small-list{max-height:320px;overflow:auto}.status-strip{display:grid;grid-template-columns:repeat(12,1fr);gap:5px;margin:8px 0 12px}.dot{width:12px;height:12px;border-radius:50%;display:inline-block;background:#2a9d8f}.dot.amber{background:#f4a261}.dot.red{background:#d95f5f}.side-note{font-size:12px;border-top:1px solid #2d3b44;border-bottom:1px solid #2d3b44;padding:9px 0;margin:8px 0 12px}.summary-note{font-weight:normal;color:var(--muted);font-size:12px}.notice{background:#eef6f8;border:1px solid #d4e6ea;border-radius:8px;padding:10px 12px;margin-bottom:10px}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}.tabs a{font-size:13px;text-decoration:none;color:#15323a;background:#e9f2f3;border:1px solid #d0e2e5;padding:6px 10px;border-radius:6px}.list-table td:last-child{font-family:Consolas,monospace;font-size:11px}.tag{display:inline-block;padding:2px 6px;border-radius:999px;background:#f1f5f8;color:#30424f;font-size:11px;margin:2px 4px 2px 0}.voice-box{background:#f7fafb;border:1px solid var(--line);border-radius:8px;padding:10px 12px}.mini{font-size:12px}.tight p{margin:8px 0}@media(max-width:1080px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.two,.layout{grid-template-columns:1fr}.side{position:static;max-height:none}}@media(max-width:720px){header{position:static}.grid{grid-template-columns:1fr}canvas{height:235px}}
</style>
</head>
<body>
<header>
  <div class="top">
    <div>
      <h1>Grid Outage Planner</h1>
      <div class="muted" id="subTitle">Hosted static dashboard for outage risk, appliance decisions, and small-business action planning.</div>
    </div>
    <div class="controls">
      <label for="business">Business</label>
      <select id="business"></select>
      <button id="playVoice">Play browser voice</button>
      <span class="pill hosted">Hugging Face static view</span>
    </div>
  </div>
</header>
<main>
  <div class="notice"><b id="noticeTitle"></b><br><span id="noticeText"></span></div>
  <section class="grid" id="kpis"></section>
  <nav class="tabs" aria-label="Dashboard sections">
    <a href="#overview">Overview</a>
    <a href="#plan">Appliance plan</a>
    <a href="#channels">SMS and voice</a>
    <a href="#evidence">Evidence</a>
    <a href="#technical">Technical checks</a>
  </nav>
  <div class="layout">
    <aside class="side">
      <h2>Risk monitor</h2>
      <div class="muted">24 hourly risk dots</div>
      <div id="statusStrip" class="status-strip"></div>
      <div class="side-note">Green is low risk, amber is prepare, red is high risk. Run the localhost dashboard for live updates from new alerts and incoming measurements.</div>
      <h3>Top future drivers</h3>
      <div id="driverList"></div>
      <h3>Snapshot details</h3>
      <div class="muted" id="snapshotMeta"></div>
    </aside>
    <section>
      <details class="panel" id="overview" open>
        <summary>Overview <span class="summary-note">Forecast, business impact, and highest-risk window</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>24-hour risk forecast</h2>
            <canvas id="forecast" width="1000" height="300"></canvas>
            <p class="caption">The line shows outage risk. The shaded band shows uncertainty. Orange bars show expected minutes at risk for that hour.</p>
          </div>
          <div class="tight">
            <h2>Main insight</h2>
            <div id="insight"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="plan" open>
        <summary>Appliance ON/OFF plan <span class="summary-note">Actionable decisions by hour</span></summary>
        <div class="panel-pad">
          <div class="table-wrap heat" id="heat"></div>
          <p class="caption">Green means keep ON. Red means switch OFF first. The decision rule always sheds luxury before comfort, and comfort before critical.</p>
          <h3>Hourly decisions</h3>
          <div class="small-list" id="decisions"></div>
        </div>
      </details>
      <details class="panel" id="channels">
        <summary>SMS and voice workflow <span class="summary-note">Low-bandwidth and non-reader adaptation</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>Morning SMS digest</h2>
            <div id="sms"></div>
            <h3>Simple local-language support</h3>
            <div id="localized"></div>
          </div>
          <div>
            <h2>Voice workflow</h2>
            <div class="voice-box" id="voiceStatus"></div>
            <h3>Offline rule</h3>
            <div id="offline"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="evidence">
        <summary>Evidence and ground realities <span class="summary-note">Why risk rises and how the design fits the local setting</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>Why outage risk rises</h2>
            <div id="factors"></div>
          </div>
          <div>
            <h2>Ground realities implemented</h2>
            <div id="realities"></div>
          </div>
        </div>
      </details>
      <details class="panel" id="technical">
        <summary>Technical checks and parameters <span class="summary-note">For evaluators who want detail</span></summary>
        <div class="two panel-pad">
          <div>
            <h2>Forecast quality checks</h2>
            <div id="quality"></div>
            <p class="caption">These numbers are included for technical judges. A business owner mainly needs the risk window and the appliance actions.</p>
          </div>
          <div>
            <h2>Business parameters</h2>
            <div id="businessParams"></div>
            <h3>Appliance parameters</h3>
            <div class="table-wrap" id="applianceParams"></div>
          </div>
        </div>
      </details>
    </section>
  </div>
</main>
<script>
const ui=__UI_DATA__;
function byId(id){return document.getElementById(id)}
function fmt(n,d=0){return Number(n).toLocaleString(undefined,{maximumFractionDigits:d,minimumFractionDigits:d})}
function money(n){return fmt(n,0)+" RWF"}
function riskClass(p){if(p>=0.35)return "risk-high"; if(p>=0.10)return "risk-mid"; return "risk-ok"}
function setupBusiness(){
  const sel=byId("business");
  const current=sel.value||"salon";
  sel.innerHTML=Object.keys(ui.businesses).map(function(key){return "<option value='"+key+"'>"+(ui.businesses[key].display_name||key)+"</option>"}).join("");
  sel.value=ui.businesses[current]?current:"salon";
}
function activeDecision(business){
  const rows=ui.decision_summary[business]||[];
  for(const row of rows){if(row.off && row.off.length){return row;}}
  return rows[0]||{off:[],on:[]};
}
function voiceTranscript(business){
  const biz=ui.businesses[business];
  const row=activeDecision(business);
  const off=(row.off||[]).length?(row.off||[]).join(", "):"no appliance";
  const on=(row.on||[]).length?(row.on||[]).slice(0,4).join(", "):"critical appliances";
  return "Power Plan voice note for "+(biz.display_name||business)+". Highest outage risk is "+ui.worst_forecast_window.label+". Switch off "+off+" first. Keep "+on+" on. If internet is not available, use the cached plan for "+ui.offline_policy.maximum_staleness_hours+" hours. After that, use critical-only mode.";
}
function render(){
  const business=byId("business").value;
  const biz=ui.businesses[business];
  const impact=ui.impact[business];
  const summary=ui.summaries[business];
  byId("noticeTitle").textContent=ui.hosted_notice.title;
  byId("noticeText").textContent=ui.hosted_notice.message;
  byId("subTitle").textContent=ui.plain_language.what_it_does;
  byId("snapshotMeta").innerHTML="Generated: <b>"+ui.generated_at.slice(0,16).replace("T"," ")+"</b><br>History: <b>"+ui.factor_summary.history_days+" days</b><br>Outage rate: <b>"+Math.round(ui.factor_summary.outage_rate*1000)/10+"%</b>";
  byId("kpis").innerHTML=[
    ["Worst risk window",ui.worst_forecast_window.label,Math.round(ui.worst_forecast_window.p_outage*100)+"% outage risk"],
    ["Weekly value protected",money(impact.weekly_expected_saved_rwf),"Expected preserved revenue"],
    ["Actions produced",summary.off_appliance_hours+" OFF blocks",summary.appliance_hours+" appliance-hours checked"],
    ["Model check","Brier "+ui.metrics.brier_score+", MAE "+ui.metrics.duration_mae_min+" min","Lead time "+ui.metrics.median_lead_time_hours+" h"]
  ].map(function(row){return "<div class='kpi'><span>"+row[0]+"</span><b>"+row[1]+"</b><div class='muted'>"+row[2]+"</div></div>"}).join("");
  renderStatusStrip();
  renderDrivers();
  renderForecast();
  renderInsight(business);
  renderHeat(business);
  renderDecisions(business);
  renderSms(business);
  renderOffline();
  renderFactors();
  renderRealities();
  renderQuality();
  renderParams(business);
}
function renderStatusStrip(){
  byId("statusStrip").innerHTML=ui.forecast.map(function(row){
    const p=Number(row.p_outage||0);
    const cls=p>=0.35?"red":(p>=0.10?"amber":"");
    return "<span class='dot "+cls+"' title='"+row.timestamp.slice(11)+" risk "+Math.round(p*100)+"%'></span>";
  }).join("");
}
function renderDrivers(){
  byId("driverList").innerHTML=ui.top_windows.slice(0,5).map(function(row){
    return "<div class='signal'><b>"+row.timestamp.slice(11)+"</b><br>"+String(row.top_risk_factor||"routine").replaceAll("_"," ")+"<br><span class='muted'>"+(row.risk_explanation||"")+"</span></div>";
  }).join("");
}
function renderInsight(business){
  const biz=ui.businesses[business];
  const impact=ui.impact[business];
  byId("insight").innerHTML="<p><span class='pill "+riskClass(ui.worst_forecast_window.p_outage)+"'>Highest risk "+ui.worst_forecast_window.label+"</span></p>"+
    "<p><b>"+(biz.display_name||business)+"</b>: "+ui.plain_language.decision_rule+"</p>"+
    "<p><b>Expected weekly value protected:</b> "+money(impact.weekly_expected_saved_rwf)+".</p>"+
    "<p class='muted'>No ML background needed: "+ui.plain_language.no_ml_background_needed+"</p>";
}
function renderForecast(){
  const c=byId("forecast"),ctx=c.getContext("2d"),w=c.width,h=c.height,pad=44,f=ui.forecast;
  ctx.clearRect(0,0,w,h); ctx.font="12px Arial"; ctx.strokeStyle="#d9e1e7"; ctx.lineWidth=1;
  for(let i=0;i<=4;i++){let y=pad+(h-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-pad,y);ctx.stroke();ctx.fillStyle="#5a6772";ctx.fillText(((4-i)*25)+"%",8,y+4)}
  const maxRisk=Math.max.apply(null,f.map(function(x){return x.risk_minutes;}),1);
  const sx=function(i){return pad+i*(w-2*pad)/(f.length-1)};
  const sy=function(p){return h-pad-p*(h-2*pad)};
  f.forEach(function(row,i){let bh=(row.risk_minutes/maxRisk)*(h-2*pad)*0.45;ctx.fillStyle="rgba(244,162,97,.45)";ctx.fillRect(sx(i)-8,h-pad-bh,16,bh)});
  ctx.beginPath();f.forEach(function(row,i){let y=sy(row.p_high);if(i===0)ctx.moveTo(sx(i),y);else ctx.lineTo(sx(i),y)});
  f.slice().reverse().forEach(function(row,j){let i=f.length-1-j;ctx.lineTo(sx(i),sy(row.p_low))});ctx.closePath();ctx.fillStyle="rgba(168,218,220,.6)";ctx.fill();
  ctx.beginPath();f.forEach(function(row,i){let y=sy(row.p_outage);if(i===0)ctx.moveTo(sx(i),y);else ctx.lineTo(sx(i),y)});ctx.strokeStyle="#006d77";ctx.lineWidth=3;ctx.stroke();
  ctx.fillStyle="#16202a";ui.hours.forEach(function(hour,i){if(i%3===0){ctx.fillText(hour,sx(i)-14,h-15)}});
}
function renderHeat(business){
  const plan=ui.plans[business];
  const appliances=ui.businesses[business].appliances;
  let html="<table><thead><tr><th>Appliance</th>"+ui.hours.map(function(hour){return "<th>"+hour+"</th>"}).join("")+"</tr></thead><tbody>";
  appliances.forEach(function(appliance){
    html+="<tr><td>"+appliance+"</td>";
    (plan[appliance]||[]).forEach(function(status){html+="<td class='"+(status==="ON"?"on":"off")+"'>"+status+"</td>"});
    html+="</tr>";
  });
  byId("heat").innerHTML=html+"</tbody></table>";
}
function renderDecisions(business){
  const rows=(ui.decision_summary[business]||[]).filter(function(row){return row.off && row.off.length>0});
  const displayRows=rows.length?rows.slice(0,10):(ui.decision_summary[business]||[]).slice(0,6);
  byId("decisions").innerHTML=displayRows.map(function(row){
    return "<div class='decision'><b>"+row.timestamp.slice(11)+"</b>: "+row.action+"<br><span class='muted'>Kept ON: "+(row.on||[]).join(", ")+"</span></div>";
  }).join("");
}
function renderSms(business){
  byId("sms").innerHTML=ui.sms_digest.map(function(item,index){
    return "<div class='sms'>"+(index+1)+". "+item.message+"<br><span class='muted'>"+item.characters+"/160 characters</span></div>";
  }).join("");
  byId("localized").innerHTML="<div class='sms mini'>EN: "+ui.localized_messages.en.join(" ")+"</div><div class='sms mini'>RW simple: "+ui.localized_messages.rw_simple.join(" ")+"</div>";
  byId("voiceStatus").innerHTML="<b>Voice transcript</b><p>"+voiceTranscript(business)+"</p><p class='muted'>Browser speech works here. Saved WAV files and live voice-note generation stay in the localhost dashboard.</p>";
}
function renderOffline(){
  const workflow=ui.non_reader_workflow;
  byId("offline").innerHTML="<p><b>Maximum stale plan:</b> "+ui.offline_policy.maximum_staleness_hours+" hours</p>"+
    "<p><b>Fallback:</b> "+ui.offline_policy.fallback+"</p>"+
    "<p><b>Non-reader path:</b> "+workflow.interface+". Green = "+workflow.green+", red = "+workflow.red+", amber = "+workflow.amber+".</p>"+
    "<p class='muted'>"+ui.offline_policy.risk_budget+"</p>";
}
function renderFactors(){
  const factorRows=ui.factor_counts.map(function(item){return "<tr><td>"+item.name+"</td><td>"+item.count+"</td></tr>"}).join("") || "<tr><td>No outage drivers recorded</td><td>0</td></tr>";
  const groupRows=ui.taxonomy_groups.map(function(item){
    return "<tr><td>"+item.group+"</td><td>"+item.prototype_fields.join(", ")+"</td></tr>";
  }).join("");
  byId("factors").innerHTML="<p>Outage risk is not based on appliances. It uses grid and weather signals such as load, rain, wind, voltage drops, feeder congestion, maintenance, reserve margin, asset health, and backup readiness.</p>"+
    "<h3>Drivers seen in outage history</h3><table class='list-table'><tbody>"+factorRows+"</tbody></table>"+
    "<h3>Broader outage groups represented</h3><table class='list-table'><tbody>"+groupRows+"</tbody></table>";
}
function renderRealities(){
  byId("realities").innerHTML="<table><tbody>"+
    "<tr><th>Low bandwidth</th><td>Single static page with compact charts, SMS wording, and no backend dependency on the hosted view.</td></tr>"+
    "<tr><th>Intermittent power/internet</th><td>Plan is trusted for "+ui.offline_policy.maximum_staleness_hours+" hours, then moves to critical-only mode.</td></tr>"+
    "<tr><th>Non-smartphone user</th><td>Morning digest stays within 3 SMS messages and each message is under 160 characters.</td></tr>"+
    "<tr><th>Multiple languages</th><td>Messages are kept in simple English and simple Kinyarwanda wording.</td></tr>"+
    "<tr><th>Illiteracy</th><td>Browser voice playback mirrors the LED workflow: green ON, red OFF, amber prepare.</td></tr>"+
    "</tbody></table>";
}
function renderQuality(){
  const worst=ui.top_windows[0];
  byId("quality").innerHTML="<table><tbody>"+
    "<tr><th>Probability accuracy score</th><td>"+ui.metrics.brier_score+"</td></tr>"+
    "<tr><th>Duration error</th><td>"+ui.metrics.duration_mae_min+" minutes</td></tr>"+
    "<tr><th>Warning lead time</th><td>"+ui.metrics.median_lead_time_hours+" hours</td></tr>"+
    "<tr><th>Forecast response</th><td>"+ui.metrics.forecast_response_ms+" ms</td></tr>"+
    "<tr><th>Training time</th><td>"+ui.metrics.full_train_seconds+" seconds</td></tr>"+
    "<tr><th>Worst future risk window</th><td>"+worst.timestamp+" with "+Math.round(worst.p_outage*100)+"% probability</td></tr>"+
    "</tbody></table>";
}
function renderParams(business){
  const biz=ui.businesses[business];
  byId("businessParams").innerHTML="<p><b>"+(biz.display_name||business)+"</b></p><p>Backup limit: <b>"+biz.backup_limit_w+" W</b><br>Risk threshold: <b>"+Math.round(biz.risk_threshold*100)+"%</b></p><p class='muted'>"+(biz.notes||"")+"</p>";
  const rows=biz.appliances.map(function(name){
    const item=ui.appliance_lookup[name];
    return "<tr><td>"+name+"</td><td>"+item.category+"</td><td>"+item.watts_avg+"</td><td>"+money(item.revenue_if_running_rwf_per_h)+"</td></tr>";
  }).join("");
  byId("applianceParams").innerHTML="<table><thead><tr><th>Appliance</th><th>Type</th><th>Watts</th><th>Revenue/h</th></tr></thead><tbody>"+rows+"</tbody></table>";
}
function playVoice(){
  const transcript=voiceTranscript(byId("business").value);
  byId("voiceStatus").innerHTML="<b>Voice transcript</b><p>"+transcript+"</p><p class='muted'>Playing from the browser.</p>";
  if("speechSynthesis" in window){
    window.speechSynthesis.cancel();
    const utterance=new SpeechSynthesisUtterance(transcript);
    utterance.rate=0.92;
    utterance.lang="en-US";
    window.speechSynthesis.speak(utterance);
  }
}
byId("business").addEventListener("change",render);
byId("playVoice").addEventListener("click",playVoice);
setupBusiness();
render();
</script>
</body>
</html>
"""
    html = html.replace("__UI_DATA__", json.dumps(ui_data, separators=(",", ":")))
    path.write_text(html, encoding="utf-8")


def write_model_card(path: Path, metrics: dict) -> None:
    text = f"""# Grid Outage Forecaster Model Card

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
The data is synthetic. This is a decision-support prototype, not a guarantee of grid behavior. Deployment requires calibration with utility outage logs, transformer-level events, and verified crowd reports.

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
        f"Power Plan: Salon today. Highest risk {worst['label']}. Keep lights, clippers and payments ready; delay dryer when alert is red.",
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
        "challenge": "Grid Outage Forecaster + Appliance Prioritizer",
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
    build_lite_ui(report, ROOT / "lite_ui.html")
    write_model_card(ROOT / "MODEL_CARD.md", metrics)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Grid Outage Planner demo report and dashboard assets.")
    parser.add_argument("--business", default="salon", choices=["salon", "cold_room", "tailor"])
    parser.add_argument("--regenerate-data", action="store_true")
    parser.add_argument("--keep-old-outputs", action="store_true", help="Do not clear old files from outputs/ before writing the new report.")
    args = parser.parse_args()

    report = run_pipeline(args.business, regenerate_data=args.regenerate_data, clean=not args.keep_old_outputs)
    metrics = report["metrics"]
    impact = report["impact"]
    chosen = args.business
    print("Grid Outage Planner demo complete")
    print(f"Brier score: {metrics['brier_score']}")
    print(f"Duration MAE: {metrics['duration_mae_min']} minutes")
    print(f"Median lead time: {metrics['median_lead_time_hours']} hours")
    print(f"Forecast response: {metrics['forecast_response_ms']} ms")
    print(f"{chosen} expected weekly saved revenue: {impact[chosen]['weekly_expected_saved_rwf']:,.0f} RWF")
    print("Open lite_ui.html for the static view, or run python dashboard.py for localhost.")


if __name__ == "__main__":
    main()
