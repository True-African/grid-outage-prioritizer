"""Appliance prioritizer for the grid outage challenge."""

from __future__ import annotations

from typing import Any

import pandas as pd


CATEGORY_PRIORITY = {"critical": 0, "comfort": 1, "luxury": 2}


def _as_frame(forecast: Any) -> pd.DataFrame:
    if isinstance(forecast, pd.DataFrame):
        return forecast.copy()
    return pd.DataFrame(forecast)


def _business_appliances(appliances: list[dict[str, Any]], business: dict[str, Any] | None) -> list[dict[str, Any]]:
    if business is None:
        return list(appliances)
    names = set(business.get("appliances", []))
    return [item for item in appliances if item["name"] in names]


def _sort_for_keep(appliance: dict[str, Any]) -> tuple:
    revenue_per_watt = appliance["revenue_if_running_rwf_per_h"] / max(appliance["watts_avg"], 1)
    return (
        CATEGORY_PRIORITY.get(appliance["category"], 99),
        -revenue_per_watt,
        appliance["start_up_spike_w"],
        appliance["name"],
    )


def _choose_on(appliances: list[dict[str, Any]], capacity_w: float) -> set[str]:
    selected: set[str] = set()
    used_watts = 0.0
    for appliance in sorted(appliances, key=_sort_for_keep):
        watts = float(appliance["watts_avg"])
        if used_watts + watts <= capacity_w:
            selected.add(appliance["name"])
            used_watts += watts
    return selected


def plan(forecast, appliances, business=None):
    """Return a 24-hour appliance ON/OFF plan.

    The category rule is enforced by sorting appliances in keep order:
    critical first, then comfort, then luxury. That means a luxury appliance
    cannot be kept ahead of a critical appliance just because it is smaller.
    Ties inside a category use revenue-per-watt, lower startup spike, then name.
    """
    forecast_df = _as_frame(forecast).head(24).copy()
    selected_appliances = _business_appliances(list(appliances), business)
    if not selected_appliances:
        raise ValueError("No appliances available for this business.")

    risk_threshold = float((business or {}).get("risk_threshold", 0.10))
    backup_limit_w = float((business or {}).get("backup_limit_w", sum(a["watts_avg"] for a in selected_appliances)))
    rows = []
    for _, hour in forecast_df.iterrows():
        p_outage = float(hour["p_outage"])
        risk_minutes = float(hour.get("risk_minutes", p_outage * hour.get("expected_duration_min", 90)))
        high_risk = p_outage >= risk_threshold or risk_minutes >= 8.0
        if high_risk:
            on_names = _choose_on(selected_appliances, backup_limit_w)
            mode = f"backup limit {int(backup_limit_w)}W"
        else:
            on_names = {a["name"] for a in selected_appliances}
            mode = "normal grid hour"

        for appliance in selected_appliances:
            status = "ON" if appliance["name"] in on_names else "OFF"
            revenue = float(appliance["revenue_if_running_rwf_per_h"])
            expected_revenue = revenue * (1.0 - p_outage) if status == "ON" else 0.0
            if status == "ON" and high_risk:
                reason = (
                    f"ON: {appliance['category']} appliance kept within {mode}; "
                    "tie-break is revenue/W, startup spike, then name."
                )
            elif status == "OFF":
                reason = (
                    f"OFF: high outage risk, {mode}; luxury/comfort load is shed before critical load."
                )
            else:
                reason = "ON: outage risk below threshold, keep appliance running."
            rows.append(
                {
                    "timestamp": hour["timestamp"],
                    "appliance": appliance["name"],
                    "category": appliance["category"],
                    "status": status,
                    "p_outage": round(p_outage, 4),
                    "expected_duration_min": float(hour["expected_duration_min"]),
                    "expected_revenue_rwf": round(expected_revenue, 2),
                    "watts_avg": int(appliance["watts_avg"]),
                    "reason": reason,
                }
            )
    return pd.DataFrame(rows)


def summarize_plan(plan_df: pd.DataFrame) -> dict[str, Any]:
    hours = plan_df.groupby("timestamp")
    high_off = plan_df[plan_df["status"] == "OFF"]
    return {
        "hours": int(hours.ngroups),
        "appliance_hours": int(len(plan_df)),
        "off_appliance_hours": int(len(high_off)),
        "expected_revenue_rwf": round(float(plan_df["expected_revenue_rwf"].sum()), 2),
    }


def estimate_weekly_savings(plan_df: pd.DataFrame) -> dict[str, Any]:
    """Estimate avoided lost revenue over a typical outage week.

    We scale the 24-hour forecast to a week. The baseline assumes an unplanned
    business loses all appliance revenue during outage hours because it did not
    pre-select what the backup can protect. The planned case preserves expected
    revenue from appliances marked ON during risk hours.
    """
    per_hour = plan_df.groupby("timestamp").agg(
        p_outage=("p_outage", "first"),
        plan_expected=("expected_revenue_rwf", "sum"),
    )
    per_hour["plan_saved"] = per_hour["p_outage"] * per_hour["plan_expected"]
    daily_saved = float(per_hour["plan_saved"].sum())
    weekly_saved = daily_saved * 7.0
    return {
        "daily_expected_saved_rwf": round(daily_saved, 0),
        "weekly_expected_saved_rwf": round(weekly_saved, 0),
        "method": "24-hour expected preserved revenue scaled to a typical week",
    }
