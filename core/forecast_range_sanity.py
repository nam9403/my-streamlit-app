"""
P1 forecast range sanity — reject absurd Monte Carlo bands vs ATR / price.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _f(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def estimate_atr_pct(ohlcv: pd.DataFrame | None, *, period: int = 14) -> float | None:
    """Average True Range as % of last close."""
    if ohlcv is None or getattr(ohlcv, "empty", True) or len(ohlcv) < period + 1:
        return None
    d = ohlcv.copy()
    for col in ("high", "low", "close"):
        if col not in d.columns:
            return None
        d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["high", "low", "close"])
    if len(d) < period + 1:
        return None
    prev_close = d["close"].shift(1)
    tr = pd.concat(
        [
            (d["high"] - d["low"]).abs(),
            (d["high"] - prev_close).abs(),
            (d["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.tail(period).mean())
    close = float(d.iloc[-1]["close"])
    if close <= 0 or atr <= 0:
        return None
    return atr / close * 100.0


def assess_forecast_range_sanity(
    *,
    price: float,
    p10: float | None,
    p50: float | None,
    p90: float | None,
    atr_pct: float | None = None,
    horizon_days: int = 90,
) -> dict[str, Any]:
    """
    True when MC band is plausible vs price and ATR.

    Rejects classic bugs: P10 << price (e.g. 6k vs 22k) or inverted bands.
    """
    px = float(price or 0.0)
    issues: list[str] = []
    if px <= 0:
        return {"ok": False, "issues": ["price_missing"], "note_vi": "Thiếu giá để kiểm tra MC."}

    a10, a50, a90 = _f(p10), _f(p50), _f(p90)
    if a10 is None or a90 is None:
        return {"ok": False, "issues": ["range_missing"], "note_vi": "Thiếu P10/P90."}
    if a10 > a90:
        issues.append("inverted_band")
    if a50 is not None and not (a10 <= a50 <= a90):
        issues.append("p50_outside_band")

    # Relative width / distance
    width = (a90 - a10) / px
    p10_gap = (px - a10) / px if a10 < px else 0.0
    p90_gap = (a90 - px) / px if a90 > px else 0.0

    # ATR-scaled envelope: allow ~sqrt(horizon/14) * k * ATR
    atr = float(atr_pct) if atr_pct and atr_pct > 0 else 2.5  # fallback ~2.5% daily-ish proxy as %
    # Convert atr_pct (per bar %) to horizon move allowance
    import math

    horizon_factor = math.sqrt(max(horizon_days, 1) / 14.0)
    max_down = min(0.85, max(0.25, (atr / 100.0) * 6.0 * horizon_factor))  # fraction of price
    max_up = min(1.50, max(0.30, (atr / 100.0) * 8.0 * horizon_factor))
    max_width = min(2.0, max_down + max_up)

    if p10_gap > max_down:
        issues.append(f"p10_too_far:{p10_gap:.2f}>{max_down:.2f}")
    if p90_gap > max_up:
        issues.append(f"p90_too_far:{p90_gap:.2f}>{max_up:.2f}")
    if width > max_width:
        issues.append(f"width_absurd:{width:.2f}>{max_width:.2f}")
    if a10 <= 0 or a10 < px * 0.15:
        issues.append("p10_near_zero")

    ok = not issues
    note = (
        "Khoảng Monte Carlo hợp lệ so với ATR/giá."
        if ok
        else "Monte Carlo range bất thường so với ATR/giá — đã ẩn band MC (P1 sanity)."
    )
    return {
        "ok": ok,
        "issues": issues,
        "note_vi": note,
        "atr_pct": atr_pct,
        "p10_gap_pct": round(p10_gap * 100.0, 2),
        "p90_gap_pct": round(p90_gap * 100.0, 2),
        "width_pct": round(width * 100.0, 2),
        "max_down_pct": round(max_down * 100.0, 2),
        "max_up_pct": round(max_up * 100.0, 2),
    }
