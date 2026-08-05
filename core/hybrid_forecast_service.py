from __future__ import annotations

import importlib
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


def ensure_python_dependencies(packages: list[str]) -> dict[str, Any]:
    """
    Tự động kiểm tra/cài các thư viện còn thiếu.
    Trả về danh sách đã có, đã cài mới, và lỗi cài đặt (nếu có).
    """
    installed: list[str] = []
    newly_installed: list[str] = []
    failed: list[str] = []
    for pkg in packages:
        name = str(pkg or "").strip()
        if not name:
            continue
        import_name = name.split("[", 1)[0].split("==", 1)[0].split(">=", 1)[0].replace("-", "_")
        try:
            importlib.import_module(import_name)
            installed.append(name)
            continue
        except Exception:
            pass
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", name])
            newly_installed.append(name)
        except Exception:
            failed.append(name)
    return {"installed": installed, "newly_installed": newly_installed, "failed": failed}


@dataclass(frozen=True)
class HybridForecastOutput:
    model_name: str
    horizon_days: int
    expected_return_pct: float
    expected_price: float
    train_rows: int


def _prepare_features(ohlcv: pd.DataFrame) -> pd.DataFrame:
    d = ohlcv.copy()
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
    d = d.dropna(subset=["close", "volume"]).reset_index(drop=True)
    if len(d) < 120:
        return pd.DataFrame()
    d["ret_1"] = d["close"].pct_change(1)
    d["ret_5"] = d["close"].pct_change(5)
    d["ret_20"] = d["close"].pct_change(20)
    d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
    d["ma50"] = d["close"].rolling(50, min_periods=50).mean()
    d["price_to_ma20"] = d["close"] / d["ma20"]
    d["price_to_ma50"] = d["close"] / d["ma50"]
    d["vol_ratio_20"] = d["volume"] / d["volume"].rolling(20, min_periods=20).mean()
    return d.dropna().reset_index(drop=True)


def _fit_linear_fallback(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    if len(x) == 0:
        return np.zeros(0, dtype=float), 0.0
    x_aug = np.hstack([np.ones((x.shape[0], 1)), x])
    coef, *_ = np.linalg.lstsq(x_aug, y, rcond=None)
    return coef[1:], float(coef[0])


def _predict_linear(x: np.ndarray, coef: np.ndarray, bias: float) -> np.ndarray:
    if x.size == 0 or coef.size == 0:
        return np.zeros((x.shape[0],), dtype=float)
    return x @ coef + bias


def build_hybrid_3m_forecast(ohlcv: pd.DataFrame, current_price: float, horizon_days: int = 63) -> HybridForecastOutput | None:
    d = _prepare_features(ohlcv)
    if d.empty or current_price <= 0:
        return None

    d["target_ret"] = d["close"].shift(-horizon_days) / d["close"] - 1.0
    d = d.dropna(subset=["target_ret"]).reset_index(drop=True)
    if len(d) < 80:
        return None

    feature_cols = ["ret_1", "ret_5", "ret_20", "price_to_ma20", "price_to_ma50", "vol_ratio_20"]
    x = d[feature_cols].to_numpy(dtype=float)
    y = d["target_ret"].to_numpy(dtype=float)
    x_last = _prepare_features(ohlcv).tail(1)[feature_cols].to_numpy(dtype=float)
    if x_last.size == 0:
        return None

    model_name = "linear_fallback"
    pred = 0.0
    try:
        from xgboost import XGBRegressor  # type: ignore

        model = XGBRegressor(
            n_estimators=120,
            max_depth=3,
            learning_rate=0.06,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=42,
        )
        model.fit(x, y)
        pred = float(model.predict(x_last)[0])
        model_name = "xgboost"
    except Exception:
        try:
            from sklearn.ensemble import RandomForestRegressor  # type: ignore

            rf = RandomForestRegressor(n_estimators=160, max_depth=6, random_state=42, n_jobs=1)
            rf.fit(x, y)
            pred = float(rf.predict(x_last)[0])
            model_name = "random_forest"
        except Exception:
            coef, bias = _fit_linear_fallback(x, y)
            pred = float(_predict_linear(x_last, coef, bias)[0])

    expected_return_pct = max(-35.0, min(60.0, pred * 100.0))
    expected_price = float(current_price * (1.0 + expected_return_pct / 100.0))
    return HybridForecastOutput(
        model_name=model_name,
        horizon_days=int(horizon_days),
        expected_return_pct=round(expected_return_pct, 2),
        expected_price=round(expected_price, 2),
        train_rows=int(len(d)),
    )


def backtest_hybrid_forecast_1y(ohlcv: pd.DataFrame, horizon_days: int = 63, test_window_days: int = 252) -> dict[str, Any]:
    """
    Backtest rolling cho 1 năm giao dịch gần nhất.
    Báo cáo tỷ lệ dự báo đúng theo hướng và sai số tuyệt đối.
    """
    d = _prepare_features(ohlcv)
    if d.empty or len(d) < max(220, horizon_days + 120):
        return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "model_mix": {}}

    idx_start = max(120, len(d) - test_window_days)
    hits = 0
    abs_errs: list[float] = []
    model_mix: dict[str, int] = {}
    samples = 0
    for i in range(idx_start, len(d) - horizon_days):
        hist = d.iloc[: i + 1].copy()
        if len(hist) < 100:
            continue
        current_price = float(hist["close"].iloc[-1])
        out = build_hybrid_3m_forecast(hist, current_price=current_price, horizon_days=horizon_days)
        if out is None:
            continue
        future_price = float(d["close"].iloc[i + horizon_days])
        realized_ret = (future_price / current_price - 1.0) * 100.0 if current_price > 0 else 0.0
        predicted_ret = float(out.expected_return_pct)
        if (predicted_ret >= 0 and realized_ret >= 0) or (predicted_ret < 0 and realized_ret < 0):
            hits += 1
        # MAPE chuẩn trên giá: |Actual - Forecast| / |Actual| * 100
        forecast_price = float(out.expected_price) if getattr(out, "expected_price", None) else current_price * (1.0 + predicted_ret / 100.0)
        if future_price > 0:
            abs_errs.append(abs(future_price - forecast_price) / future_price * 100.0)
        model_mix[out.model_name] = int(model_mix.get(out.model_name, 0) + 1)
        samples += 1

    if samples <= 0:
        return {"samples": 0, "hit_rate_pct": None, "mape_pct": None, "model_mix": {}}
    hit_rate = round(hits / samples * 100.0, 2)
    mape = round(sum(abs_errs) / len(abs_errs), 2) if abs_errs else None
    return {
        "samples": int(samples),
        "hit_rate_pct": hit_rate,
        "mape_pct": mape,
        "model_mix": model_mix,
    }
