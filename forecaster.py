"""CPU-only outage forecaster for AIMS T2.3.

This module avoids heavy ML dependencies. It implements:
- weighted logistic regression for P(outage)
- ridge regression on log duration for E[duration | outage]
- a 24-hour forecast API using lagged features and simple weather/load climatology
"""

from __future__ import annotations

import pickle
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FEATURE_COLUMNS = [
    "hour",
    "dayofweek",
    "is_weekend",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "load_mw",
    "load_lag1",
    "load_lag24",
    "load_roll3",
    "load_roll6",
    "load_roll24",
    "rain_mm",
    "rain_lag1",
    "rain_roll3",
    "temp_c",
    "humidity",
    "wind_ms",
    "outage_lag1",
    "outage_roll24",
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

FACTOR_COLUMNS = [
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

FACTOR_LABELS = {
    "load_stress_index": "high local demand",
    "rain_stress_index": "heavy rain",
    "wind_stress_index": "wind stress",
    "feeder_congestion_index": "feeder congestion",
    "voltage_drop_index": "voltage drop",
    "maintenance_flag": "maintenance window",
    "neighbor_outage_reports": "neighbor reports",
    "transformer_age_years": "older transformer risk",
    "payment_day_flag": "payment-day demand",
    "reserve_margin_index": "low reserve margin",
    "fuel_supply_risk_index": "fuel supply risk",
    "hydro_inflow_stress_index": "hydro inflow stress",
    "vegetation_risk_index": "vegetation exposure",
    "protection_miscoordination_index": "protection coordination risk",
    "scada_telecom_risk_index": "SCADA/telecom risk",
    "non_technical_loss_index": "non-technical losses",
    "asset_health_index": "asset health risk",
    "der_backup_risk_index": "DER/backup readiness risk",
}


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40, 40)))


def load_history(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    required = {"timestamp", "load_mw", "temp_c", "humidity", "wind_ms", "rain_mm", "outage", "duration_min"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")
    return df.sort_values("timestamp").reset_index(drop=True)


def make_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Create lagged time-series features and return X, outage target, duration target."""
    frame = df.copy().sort_values("timestamp").reset_index(drop=True)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["hour"] = frame["timestamp"].dt.hour.astype(float)
    frame["dayofweek"] = frame["timestamp"].dt.dayofweek.astype(float)
    frame["is_weekend"] = (frame["dayofweek"] >= 5).astype(float)
    frame["hour_sin"] = np.sin(2 * np.pi * frame["hour"] / 24)
    frame["hour_cos"] = np.cos(2 * np.pi * frame["hour"] / 24)
    frame["dow_sin"] = np.sin(2 * np.pi * frame["dayofweek"] / 7)
    frame["dow_cos"] = np.cos(2 * np.pi * frame["dayofweek"] / 7)

    for lag in (1, 24):
        frame[f"load_lag{lag}"] = frame["load_mw"].shift(lag)
    frame["rain_lag1"] = frame["rain_mm"].shift(1)
    frame["outage_lag1"] = frame["outage"].shift(1)
    frame["outage_roll24"] = frame["outage"].shift(1).rolling(24, min_periods=1).mean()
    frame["load_roll3"] = frame["load_mw"].shift(1).rolling(3, min_periods=1).mean()
    frame["load_roll6"] = frame["load_mw"].shift(1).rolling(6, min_periods=1).mean()
    frame["load_roll24"] = frame["load_mw"].shift(1).rolling(24, min_periods=1).mean()
    frame["rain_roll3"] = frame["rain_mm"].shift(1).rolling(3, min_periods=1).sum()

    defaults = {
        "load_stress_index": np.clip((frame["load_mw"] - 48.0) / 18.0, 0, 1),
        "rain_stress_index": np.clip(frame["rain_mm"] / 18.0, 0, 1),
        "wind_stress_index": np.clip((frame["wind_ms"] - 3.0) / 3.5, 0, 1),
        "feeder_congestion_index": np.clip(0.45 * np.clip((frame["load_mw"] - 48.0) / 18.0, 0, 1) + 0.20 * (frame["hour"].between(17, 21)), 0, 1),
        "voltage_drop_index": np.clip(0.35 * np.clip((frame["load_mw"] - 48.0) / 18.0, 0, 1) + 0.25 * np.clip(frame["rain_mm"] / 18.0, 0, 1), 0, 1),
        "maintenance_flag": 0,
        "neighbor_outage_reports": 0,
        "transformer_age_years": 9.0,
        "payment_day_flag": frame["timestamp"].dt.day.isin([15, 30, 31]).astype(int),
        "reserve_margin_index": np.clip(0.5 * np.clip((frame["load_mw"] - 48.0) / 18.0, 0, 1) + 0.2 * frame["timestamp"].dt.hour.between(17, 21), 0, 1),
        "fuel_supply_risk_index": 0.12,
        "hydro_inflow_stress_index": np.clip(0.25 - 0.2 * np.clip(frame["rain_mm"] / 18.0, 0, 1), 0, 1),
        "vegetation_risk_index": np.clip(0.2 + 0.35 * np.clip(frame["rain_mm"] / 18.0, 0, 1) + 0.2 * np.clip((frame["wind_ms"] - 3.0) / 3.5, 0, 1), 0, 1),
        "protection_miscoordination_index": 0.15,
        "scada_telecom_risk_index": np.clip(0.06 + 0.1 * np.clip(frame["rain_mm"] / 18.0, 0, 1), 0, 1),
        "non_technical_loss_index": 0.20,
        "asset_health_index": 0.55,
        "der_backup_risk_index": 0.18,
    }
    for column, default in defaults.items():
        if column not in frame.columns:
            frame[column] = default

    X = frame[FEATURE_COLUMNS].copy()
    X = X.ffill().bfill().fillna(0.0)
    y_outage = frame["outage"].astype(float)
    y_duration = frame["duration_min"].astype(float)
    return X, y_outage, y_duration


def _standardize(X: pd.DataFrame, mean: np.ndarray | None = None, scale: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values = X.to_numpy(dtype=float)
    if mean is None:
        mean = values.mean(axis=0)
    if scale is None:
        scale = values.std(axis=0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    return (values - mean) / scale, mean, scale


def _add_intercept(X: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(X)), X])


def _fit_logistic(X: np.ndarray, y: np.ndarray, positive_weight: float, l2: float = 0.02, epochs: int = 1800, lr: float = 0.055) -> np.ndarray:
    Xb = _add_intercept(X)
    weights = np.where(y > 0.5, positive_weight, 1.0)
    beta = np.zeros(Xb.shape[1])
    denom = weights.sum()
    for _ in range(epochs):
        p = sigmoid(Xb @ beta)
        grad = (Xb.T @ ((p - y) * weights)) / denom
        grad[1:] += l2 * beta[1:]
        beta -= lr * grad
    return beta


def _fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float = 2.0) -> np.ndarray:
    Xb = _add_intercept(X)
    penalty = np.eye(Xb.shape[1]) * alpha
    penalty[0, 0] = 0.0
    return np.linalg.solve(Xb.T @ Xb + penalty, Xb.T @ y)


def _predict_logistic(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return sigmoid(_add_intercept(X) @ beta)


def _predict_ridge(beta: np.ndarray, X: np.ndarray) -> np.ndarray:
    return _add_intercept(X) @ beta


def train(history: pd.DataFrame) -> dict[str, Any]:
    start = time.perf_counter()
    X, y_outage, y_duration = make_features(history)
    Xs, mean, scale = _standardize(X)
    y = y_outage.to_numpy(dtype=float)
    positive_count = max(float(y.sum()), 1.0)
    negative_count = max(float(len(y) - y.sum()), 1.0)
    positive_weight = min(18.0, negative_count / positive_count)
    outage_beta = _fit_logistic(Xs, y, positive_weight=positive_weight)

    outage_rows = y_duration.to_numpy() > 0
    if int(outage_rows.sum()) >= 8:
        duration_beta = _fit_ridge(Xs[outage_rows], np.log1p(y_duration.to_numpy()[outage_rows]))
        duration_mean = float(y_duration.to_numpy()[outage_rows].mean())
    else:
        duration_beta = np.zeros(Xs.shape[1] + 1)
        duration_beta[0] = np.log1p(90.0)
        duration_mean = 90.0

    fitted_p = _predict_logistic(outage_beta, Xs)
    residual_std = float(np.std(y - fitted_p))
    hour_residual = pd.DataFrame(
        {
            "hour": pd.to_datetime(history["timestamp"]).dt.hour,
            "resid": np.abs(y - fitted_p),
        }
    )
    hour_band = hour_residual.groupby("hour")["resid"].quantile(0.75).to_dict()
    forecast_history = history.copy().sort_values("timestamp").reset_index(drop=True)
    forecast_history["timestamp"] = pd.to_datetime(forecast_history["timestamp"])
    forecast_history_end = forecast_history["timestamp"].max()

    return {
        "feature_columns": FEATURE_COLUMNS,
        "mean": mean,
        "scale": scale,
        "outage_beta": outage_beta,
        "duration_beta": duration_beta,
        "duration_mean": duration_mean,
        "factor_labels": FACTOR_LABELS,
        "positive_weight": positive_weight,
        "residual_std": residual_std,
        "hour_band": hour_band,
        "forecast_climatology": _build_climatology(forecast_history),
        "forecast_seed_records": forecast_history.tail(48).to_dict(orient="records"),
        "forecast_history_end": forecast_history_end.isoformat(),
        "trained_at": pd.Timestamp.now(tz="UTC").isoformat(),
        "train_seconds": time.perf_counter() - start,
    }


def predict_from_features(model_bundle: dict[str, Any], X: pd.DataFrame) -> pd.DataFrame:
    Xs, _, _ = _standardize(X[model_bundle["feature_columns"]], model_bundle["mean"], model_bundle["scale"])
    p = _predict_logistic(model_bundle["outage_beta"], Xs)
    duration_log = _predict_ridge(model_bundle["duration_beta"], Xs)
    duration = np.clip(np.expm1(duration_log), 10.0, 360.0)
    return pd.DataFrame({"p_outage": np.clip(p, 0.0, 1.0), "expected_duration_min": duration})


def _future_row(history: pd.DataFrame, ts: pd.Timestamp) -> dict[str, Any]:
    hour = ts.hour
    dow = ts.dayofweek
    recent = history.tail(24 * 21).copy()
    by_hour = recent[recent["timestamp"].dt.hour == hour]
    by_hour_dow = by_hour[by_hour["timestamp"].dt.dayofweek == dow]
    source = by_hour_dow if len(by_hour_dow) >= 2 else by_hour
    if source.empty:
        source = recent
    return {
        "timestamp": ts,
        "load_mw": float(source["load_mw"].mean()),
        "temp_c": float(source["temp_c"].mean()),
        "humidity": float(source["humidity"].mean()),
        "wind_ms": float(source["wind_ms"].mean()),
        "rain_mm": float(source["rain_mm"].median()),
        "load_stress_index": float(source.get("load_stress_index", pd.Series([0])).mean()),
        "rain_stress_index": float(source.get("rain_stress_index", pd.Series([0])).mean()),
        "wind_stress_index": float(source.get("wind_stress_index", pd.Series([0])).mean()),
        "feeder_congestion_index": float(source.get("feeder_congestion_index", pd.Series([0])).mean()),
        "voltage_drop_index": float(source.get("voltage_drop_index", pd.Series([0])).mean()),
        "maintenance_flag": float(source.get("maintenance_flag", pd.Series([0])).max()),
        "neighbor_outage_reports": float(source.get("neighbor_outage_reports", pd.Series([0])).mean()),
        "transformer_age_years": float(source.get("transformer_age_years", pd.Series([9])).mean()),
        "payment_day_flag": float(ts.day in [15, 30, 31]),
        "reserve_margin_index": float(source.get("reserve_margin_index", pd.Series([0])).mean()),
        "fuel_supply_risk_index": float(source.get("fuel_supply_risk_index", pd.Series([0.12])).mean()),
        "hydro_inflow_stress_index": float(source.get("hydro_inflow_stress_index", pd.Series([0.2])).mean()),
        "vegetation_risk_index": float(source.get("vegetation_risk_index", pd.Series([0.2])).mean()),
        "protection_miscoordination_index": float(source.get("protection_miscoordination_index", pd.Series([0.15])).mean()),
        "scada_telecom_risk_index": float(source.get("scada_telecom_risk_index", pd.Series([0.06])).mean()),
        "non_technical_loss_index": float(source.get("non_technical_loss_index", pd.Series([0.2])).mean()),
        "asset_health_index": float(source.get("asset_health_index", pd.Series([0.55])).mean()),
        "der_backup_risk_index": float(source.get("der_backup_risk_index", pd.Series([0.18])).mean()),
        "outage": 0.0,
        "duration_min": 0.0,
    }


def _latest_feature_row(frame: pd.DataFrame) -> pd.DataFrame:
    """Build features for the final row without recomputing the full matrix."""
    current = frame.iloc[-1]
    previous = frame.iloc[:-1]
    ts = pd.Timestamp(current["timestamp"])
    if previous.empty:
        previous = frame.tail(1)

    def prev_value(column: str, fallback: float = 0.0) -> float:
        if previous.empty:
            return fallback
        return float(previous[column].iloc[-1])

    def lag_value(column: str, lag: int, fallback: float) -> float:
        if len(frame) > lag:
            return float(frame[column].iloc[-lag - 1])
        return fallback

    def rolling_mean(column: str, window: int, fallback: float) -> float:
        values = previous[column].tail(window)
        if values.empty:
            return fallback
        return float(values.mean())

    def rolling_sum(column: str, window: int) -> float:
        values = previous[column].tail(window)
        if values.empty:
            return 0.0
        return float(values.sum())

    row = {
        "hour": float(ts.hour),
        "dayofweek": float(ts.dayofweek),
        "is_weekend": float(ts.dayofweek >= 5),
        "hour_sin": float(np.sin(2 * np.pi * ts.hour / 24)),
        "hour_cos": float(np.cos(2 * np.pi * ts.hour / 24)),
        "dow_sin": float(np.sin(2 * np.pi * ts.dayofweek / 7)),
        "dow_cos": float(np.cos(2 * np.pi * ts.dayofweek / 7)),
        "load_mw": float(current["load_mw"]),
        "load_lag1": prev_value("load_mw", float(current["load_mw"])),
        "load_lag24": lag_value("load_mw", 24, prev_value("load_mw", float(current["load_mw"]))),
        "load_roll3": rolling_mean("load_mw", 3, float(current["load_mw"])),
        "load_roll6": rolling_mean("load_mw", 6, float(current["load_mw"])),
        "load_roll24": rolling_mean("load_mw", 24, float(current["load_mw"])),
        "rain_mm": float(current["rain_mm"]),
        "rain_lag1": prev_value("rain_mm", 0.0),
        "rain_roll3": rolling_sum("rain_mm", 3),
        "temp_c": float(current["temp_c"]),
        "humidity": float(current["humidity"]),
        "wind_ms": float(current["wind_ms"]),
        "outage_lag1": prev_value("outage", 0.0),
        "outage_roll24": rolling_mean("outage", 24, 0.0),
        "load_stress_index": float(current.get("load_stress_index", max(0.0, min(1.0, (float(current["load_mw"]) - 48.0) / 18.0)))),
        "rain_stress_index": float(current.get("rain_stress_index", max(0.0, min(1.0, float(current["rain_mm"]) / 18.0)))),
        "wind_stress_index": float(current.get("wind_stress_index", max(0.0, min(1.0, (float(current["wind_ms"]) - 3.0) / 3.5)))),
        "feeder_congestion_index": float(current.get("feeder_congestion_index", 0.0)),
        "voltage_drop_index": float(current.get("voltage_drop_index", 0.0)),
        "maintenance_flag": float(current.get("maintenance_flag", 0.0)),
        "neighbor_outage_reports": float(current.get("neighbor_outage_reports", 0.0)),
        "transformer_age_years": float(current.get("transformer_age_years", 9.0)),
        "payment_day_flag": float(current.get("payment_day_flag", ts.day in [15, 30, 31])),
        "reserve_margin_index": float(current.get("reserve_margin_index", 0.0)),
        "fuel_supply_risk_index": float(current.get("fuel_supply_risk_index", 0.12)),
        "hydro_inflow_stress_index": float(current.get("hydro_inflow_stress_index", 0.2)),
        "vegetation_risk_index": float(current.get("vegetation_risk_index", 0.2)),
        "protection_miscoordination_index": float(current.get("protection_miscoordination_index", 0.15)),
        "scada_telecom_risk_index": float(current.get("scada_telecom_risk_index", 0.06)),
        "non_technical_loss_index": float(current.get("non_technical_loss_index", 0.2)),
        "asset_health_index": float(current.get("asset_health_index", 0.55)),
        "der_backup_risk_index": float(current.get("der_backup_risk_index", 0.18)),
    }
    return pd.DataFrame([row], columns=FEATURE_COLUMNS)


def _build_climatology(history: pd.DataFrame) -> dict[str, Any]:
    recent = history.tail(24 * 21).copy()
    recent["hour"] = recent["timestamp"].dt.hour
    recent["dayofweek"] = recent["timestamp"].dt.dayofweek
    for column in FACTOR_COLUMNS:
        if column not in recent.columns:
            recent[column] = 0.0
    numeric = ["load_mw", "temp_c", "humidity", "wind_ms", "rain_mm"] + FACTOR_COLUMNS
    by_hour_dow = recent.groupby(["dayofweek", "hour"])[numeric].mean().to_dict("index")
    by_hour = recent.groupby("hour").agg(
        load_mw=("load_mw", "mean"),
        temp_c=("temp_c", "mean"),
        humidity=("humidity", "mean"),
        wind_ms=("wind_ms", "mean"),
        rain_mm=("rain_mm", "median"),
    ).to_dict("index")
    global_mean = recent[numeric].mean().to_dict()
    return {"by_hour_dow": by_hour_dow, "by_hour": by_hour, "global": global_mean}


def _future_row_fast(climatology: dict[str, Any], ts: pd.Timestamp) -> dict[str, Any]:
    values = climatology["by_hour_dow"].get((ts.dayofweek, ts.hour))
    if values is None:
        values = climatology["by_hour"].get(ts.hour, climatology["global"])
    return {
        "timestamp": ts,
        "load_mw": float(values["load_mw"]),
        "temp_c": float(values["temp_c"]),
        "humidity": float(values["humidity"]),
        "wind_ms": float(values["wind_ms"]),
        "rain_mm": float(values["rain_mm"]),
        "load_stress_index": float(values.get("load_stress_index", 0.0)),
        "rain_stress_index": float(values.get("rain_stress_index", 0.0)),
        "wind_stress_index": float(values.get("wind_stress_index", 0.0)),
        "feeder_congestion_index": float(values.get("feeder_congestion_index", 0.0)),
        "voltage_drop_index": float(values.get("voltage_drop_index", 0.0)),
        "maintenance_flag": float(values.get("maintenance_flag", 0.0)),
        "neighbor_outage_reports": float(values.get("neighbor_outage_reports", 0.0)),
        "transformer_age_years": float(values.get("transformer_age_years", 9.0)),
        "payment_day_flag": float(ts.day in [15, 30, 31]),
        "reserve_margin_index": float(values.get("reserve_margin_index", 0.0)),
        "fuel_supply_risk_index": float(values.get("fuel_supply_risk_index", 0.12)),
        "hydro_inflow_stress_index": float(values.get("hydro_inflow_stress_index", 0.2)),
        "vegetation_risk_index": float(values.get("vegetation_risk_index", 0.2)),
        "protection_miscoordination_index": float(values.get("protection_miscoordination_index", 0.15)),
        "scada_telecom_risk_index": float(values.get("scada_telecom_risk_index", 0.06)),
        "non_technical_loss_index": float(values.get("non_technical_loss_index", 0.2)),
        "asset_health_index": float(values.get("asset_health_index", 0.55)),
        "der_backup_risk_index": float(values.get("der_backup_risk_index", 0.18)),
        "outage": 0.0,
        "duration_min": 0.0,
    }


def _latest_feature_dict_from_records(records: list[dict[str, Any]]) -> dict[str, float]:
    current = records[-1]
    previous = records[:-1]
    ts = pd.Timestamp(current["timestamp"])

    def prev_value(column: str, fallback: float = 0.0) -> float:
        if not previous:
            return fallback
        return float(previous[-1][column])

    def lag_value(column: str, lag: int, fallback: float) -> float:
        if len(records) > lag:
            return float(records[-lag - 1][column])
        return fallback

    def rolling_mean(column: str, window: int, fallback: float) -> float:
        values = [float(r[column]) for r in previous[-window:]]
        if not values:
            return fallback
        return float(np.mean(values))

    def rolling_sum(column: str, window: int) -> float:
        values = [float(r[column]) for r in previous[-window:]]
        if not values:
            return 0.0
        return float(np.sum(values))

    row = {
        "hour": float(ts.hour),
        "dayofweek": float(ts.dayofweek),
        "is_weekend": float(ts.dayofweek >= 5),
        "hour_sin": float(np.sin(2 * np.pi * ts.hour / 24)),
        "hour_cos": float(np.cos(2 * np.pi * ts.hour / 24)),
        "dow_sin": float(np.sin(2 * np.pi * ts.dayofweek / 7)),
        "dow_cos": float(np.cos(2 * np.pi * ts.dayofweek / 7)),
        "load_mw": float(current["load_mw"]),
        "load_lag1": prev_value("load_mw", float(current["load_mw"])),
        "load_lag24": lag_value("load_mw", 24, prev_value("load_mw", float(current["load_mw"]))),
        "load_roll3": rolling_mean("load_mw", 3, float(current["load_mw"])),
        "load_roll6": rolling_mean("load_mw", 6, float(current["load_mw"])),
        "load_roll24": rolling_mean("load_mw", 24, float(current["load_mw"])),
        "rain_mm": float(current["rain_mm"]),
        "rain_lag1": prev_value("rain_mm", 0.0),
        "rain_roll3": rolling_sum("rain_mm", 3),
        "temp_c": float(current["temp_c"]),
        "humidity": float(current["humidity"]),
        "wind_ms": float(current["wind_ms"]),
        "outage_lag1": prev_value("outage", 0.0),
        "outage_roll24": rolling_mean("outage", 24, 0.0),
        "load_stress_index": float(current.get("load_stress_index", max(0.0, min(1.0, (float(current["load_mw"]) - 48.0) / 18.0)))),
        "rain_stress_index": float(current.get("rain_stress_index", max(0.0, min(1.0, float(current["rain_mm"]) / 18.0)))),
        "wind_stress_index": float(current.get("wind_stress_index", max(0.0, min(1.0, (float(current["wind_ms"]) - 3.0) / 3.5)))),
        "feeder_congestion_index": float(current.get("feeder_congestion_index", 0.0)),
        "voltage_drop_index": float(current.get("voltage_drop_index", 0.0)),
        "maintenance_flag": float(current.get("maintenance_flag", 0.0)),
        "neighbor_outage_reports": float(current.get("neighbor_outage_reports", 0.0)),
        "transformer_age_years": float(current.get("transformer_age_years", 9.0)),
        "payment_day_flag": float(current.get("payment_day_flag", ts.day in [15, 30, 31])),
        "reserve_margin_index": float(current.get("reserve_margin_index", 0.0)),
        "fuel_supply_risk_index": float(current.get("fuel_supply_risk_index", 0.12)),
        "hydro_inflow_stress_index": float(current.get("hydro_inflow_stress_index", 0.2)),
        "vegetation_risk_index": float(current.get("vegetation_risk_index", 0.2)),
        "protection_miscoordination_index": float(current.get("protection_miscoordination_index", 0.15)),
        "scada_telecom_risk_index": float(current.get("scada_telecom_risk_index", 0.06)),
        "non_technical_loss_index": float(current.get("non_technical_loss_index", 0.2)),
        "asset_health_index": float(current.get("asset_health_index", 0.55)),
        "der_backup_risk_index": float(current.get("der_backup_risk_index", 0.18)),
    }
    return row


def explain_risk_factors(feature_row: dict[str, float]) -> tuple[str, str]:
    factor_scores = {
        "voltage_drop_index": float(feature_row.get("voltage_drop_index", 0.0)),
        "feeder_congestion_index": float(feature_row.get("feeder_congestion_index", 0.0)),
        "load_stress_index": float(feature_row.get("load_stress_index", 0.0)),
        "rain_stress_index": float(feature_row.get("rain_stress_index", 0.0)),
        "wind_stress_index": float(feature_row.get("wind_stress_index", 0.0)),
        "maintenance_flag": float(feature_row.get("maintenance_flag", 0.0)),
        "neighbor_outage_reports": min(float(feature_row.get("neighbor_outage_reports", 0.0)) / 3.0, 1.0),
        "payment_day_flag": float(feature_row.get("payment_day_flag", 0.0)) * 0.45,
        "reserve_margin_index": float(feature_row.get("reserve_margin_index", 0.0)),
        "fuel_supply_risk_index": float(feature_row.get("fuel_supply_risk_index", 0.0)),
        "hydro_inflow_stress_index": float(feature_row.get("hydro_inflow_stress_index", 0.0)),
        "vegetation_risk_index": float(feature_row.get("vegetation_risk_index", 0.0)),
        "protection_miscoordination_index": float(feature_row.get("protection_miscoordination_index", 0.0)),
        "scada_telecom_risk_index": float(feature_row.get("scada_telecom_risk_index", 0.0)),
        "non_technical_loss_index": float(feature_row.get("non_technical_loss_index", 0.0)),
        "asset_health_index": float(feature_row.get("asset_health_index", 0.0)),
        "der_backup_risk_index": float(feature_row.get("der_backup_risk_index", 0.0)),
    }
    top_key, top_score = max(factor_scores.items(), key=lambda item: item[1])
    if top_score < 0.12:
        return "routine_load", "No single stress factor dominates; risk is mainly routine load and time-of-day pattern."
    top_three = sorted(factor_scores.items(), key=lambda item: item[1], reverse=True)[:3]
    labels = [f"{FACTOR_LABELS[key]} ({score:.2f})" for key, score in top_three if score > 0.05]
    return top_key, "Main drivers: " + ", ".join(labels)


def _latest_feature_row_from_records(records: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([_latest_feature_dict_from_records(records)], columns=FEATURE_COLUMNS)


def _predict_one_from_feature_dict(model_bundle: dict[str, Any], feature_row: dict[str, float]) -> tuple[float, float]:
    values = np.array([[feature_row[column] for column in model_bundle["feature_columns"]]], dtype=float)
    Xs = (values - model_bundle["mean"]) / model_bundle["scale"]
    p = float(_predict_logistic(model_bundle["outage_beta"], Xs)[0])
    duration_log = float(_predict_ridge(model_bundle["duration_beta"], Xs)[0])
    duration = float(np.clip(np.expm1(duration_log), 10.0, 360.0))
    return p, duration


def forecast_next_24(model_bundle: dict[str, Any], history: pd.DataFrame, start_ts: str | pd.Timestamp | None = None) -> pd.DataFrame:
    """Forecast the next 24 hourly outage probabilities and expected durations."""
    cached_end = pd.Timestamp(model_bundle.get("forecast_history_end")) if model_bundle.get("forecast_history_end") else None
    use_cached_seed = (
        start_ts is None
        and cached_end is not None
        and "forecast_climatology" in model_bundle
        and "forecast_seed_records" in model_bundle
        and not history.empty
        and pd.Timestamp(history["timestamp"].iloc[-1]) == cached_end
    )
    if use_cached_seed:
        next_ts = cached_end + pd.Timedelta(hours=1)
        climatology = model_bundle["forecast_climatology"]
        records = [dict(row) for row in model_bundle["forecast_seed_records"]]
    else:
        hist = history.copy().sort_values("timestamp").reset_index(drop=True)
        hist["timestamp"] = pd.to_datetime(hist["timestamp"])
        if start_ts is None:
            next_ts = hist["timestamp"].max() + pd.Timedelta(hours=1)
        else:
            next_ts = pd.Timestamp(start_ts)
        climatology = _build_climatology(hist)
        records = hist.tail(48).to_dict(orient="records")
    rows = []
    for step in range(24):
        ts = next_ts + pd.Timedelta(hours=step)
        new_row = _future_row_fast(climatology, ts)
        records.append(new_row)
        feature_row = _latest_feature_dict_from_records(records)
        p, duration = _predict_one_from_feature_dict(model_bundle, feature_row)
        top_factor, explanation = explain_risk_factors(feature_row)
        records[-1]["outage"] = p
        records[-1]["duration_min"] = p * duration
        band = float(model_bundle.get("hour_band", {}).get(ts.hour, model_bundle.get("residual_std", 0.08)))
        band = max(0.04, min(0.18, band))
        rows.append(
            {
                "timestamp": ts,
                "p_outage": round(p, 4),
                "p_low": round(max(0.0, p - band), 4),
                "p_high": round(min(1.0, p + band), 4),
                "expected_duration_min": round(duration, 1),
                "risk_minutes": round(p * duration, 2),
                "top_risk_factor": top_factor,
                "risk_explanation": explanation,
            }
        )
    return pd.DataFrame(rows)


def save_model(model_bundle: dict[str, Any], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        pickle.dump(model_bundle, f)


def load_model(path: str | Path) -> dict[str, Any]:
    with Path(path).open("rb") as f:
        return pickle.load(f)


def evaluate_holdout(history: pd.DataFrame, threshold: float = 0.10) -> tuple[dict[str, Any], pd.DataFrame]:
    """Evaluate on the final 30 days using a time split."""
    df = history.copy().sort_values("timestamp").reset_index(drop=True)
    cutoff = df["timestamp"].max() - pd.Timedelta(days=30)
    train_df = df[df["timestamp"] < cutoff].copy()
    test_df = df[df["timestamp"] >= cutoff].copy()
    model = train(train_df)

    all_features, _, _ = make_features(df)
    test_features = all_features.loc[test_df.index]
    predictions = predict_from_features(model, test_features)
    actual_outage = test_df["outage"].to_numpy(dtype=float)
    actual_duration = test_df["duration_min"].to_numpy(dtype=float)
    p = predictions["p_outage"].to_numpy()
    pred_duration = predictions["expected_duration_min"].to_numpy()

    brier = float(np.mean((p - actual_outage) ** 2))
    outage_mask = actual_outage > 0.5
    if outage_mask.any():
        duration_mae = float(np.mean(np.abs(pred_duration[outage_mask] - actual_duration[outage_mask])))
    else:
        duration_mae = float("nan")

    alerts = p >= threshold
    lead_times = []
    for idx, is_outage in enumerate(actual_outage.astype(bool)):
        if not is_outage:
            continue
        window_start = max(0, idx - 24)
        prior_alerts = np.where(alerts[window_start : idx + 1])[0]
        if len(prior_alerts):
            first_alert = window_start + int(prior_alerts[0])
            lead_times.append(idx - first_alert)
    median_lead = float(np.median(lead_times)) if lead_times else 0.0
    lead_coverage = float(len(lead_times) / max(int(outage_mask.sum()), 1))

    optional_cols = [col for col in ["timestamp", "load_mw", "rain_mm", "voltage_drop_index", "feeder_congestion_index", "maintenance_flag", "neighbor_outage_reports", "primary_outage_driver", "outage", "duration_min"] if col in test_df.columns]
    scored = test_df[optional_cols].copy()
    scored["p_outage"] = p
    scored["expected_duration_min"] = pred_duration
    scored["probability_error"] = np.abs(scored["outage"] - scored["p_outage"])
    scored["duration_abs_error"] = np.where(
        scored["outage"] == 1,
        np.abs(scored["duration_min"] - scored["expected_duration_min"]),
        0.0,
    )
    worst = scored.sort_values(["probability_error", "duration_abs_error"], ascending=False).head(5)

    metrics = {
        "brier_score": round(brier, 4),
        "duration_mae_min": round(duration_mae, 2),
        "lead_time_threshold": threshold,
        "median_lead_time_hours": round(median_lead, 2),
        "lead_time_coverage": round(lead_coverage, 3),
        "holdout_hours": int(len(test_df)),
        "holdout_outage_hours": int(outage_mask.sum()),
        "train_seconds": round(float(model["train_seconds"]), 3),
    }
    return metrics, worst.reset_index(drop=True)


if __name__ == "__main__":
    history_df = load_history("data/grid_history.csv")
    bundle = train(history_df)
    forecast = forecast_next_24(bundle, history_df)
    print(forecast.head().to_string(index=False))
