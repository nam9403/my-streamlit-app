"""
Unified technical indicators — Wilder RSI, MACD, moving averages.

Single source of truth for engine, chart panel, and downstream analytics.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI using Wilder's smoothing (EWM alpha=1/period)."""
    c = pd.to_numeric(close, errors="coerce")
    delta = c.diff()
    gain = delta.clip(lower=0.0)
    # Loss must be non-negative: down-move magnitude. (Bugfix: clip(upper=0) zeroed all losses.)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = 100.0 - (100.0 / (1.0 + rs))
    no_loss = avg_loss.fillna(0.0) <= 1e-12
    rsi = rsi.mask(no_loss & (avg_gain > 1e-12), 100.0)
    rsi = rsi.mask(no_loss & (avg_gain <= 1e-12), 50.0)
    return pd.to_numeric(rsi, errors="coerce").astype(float)


def compute_macd(
    close: pd.Series,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, histogram."""
    c = pd.to_numeric(close, errors="coerce")
    ema_fast = c.ewm(span=fast, adjust=False).mean()
    ema_slow = c.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    macd_signal = macd_line.ewm(span=signal, adjust=False).mean()
    macd_hist = macd_line - macd_signal
    return macd_line.astype(float), macd_signal.astype(float), macd_hist.astype(float)


def compute_bollinger_bands(
    close: pd.Series,
    *,
    window: int = 20,
    min_periods: int = 10,
    num_std: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Middle band (SMA), upper, lower."""
    c = pd.to_numeric(close, errors="coerce")
    mid = c.rolling(window, min_periods=min_periods).mean()
    std = c.rolling(window, min_periods=min_periods).std()
    upper = mid + (num_std * std)
    lower = mid - (num_std * std)
    return mid.astype(float), upper.astype(float), lower.astype(float)


def add_engine_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Engine-grade indicators with strict warm-up (min_periods = window).
    Columns: ma20, ma50, rsi14, vol_ma20, vol_std20, macd, macd_signal, macd_hist.
    """
    out = df.copy()
    close = out["close"]
    out["ma20"] = close.rolling(20, min_periods=20).mean()
    out["ma50"] = close.rolling(50, min_periods=50).mean()
    out["rsi14"] = wilder_rsi(close, period=14)
    out["vol_ma20"] = out["volume"].rolling(20, min_periods=20).mean()
    out["vol_std20"] = out["volume"].rolling(20, min_periods=20).std()
    macd, sig, hist = compute_macd(close)
    out["macd"] = macd
    out["macd_signal"] = sig
    out["macd_hist"] = hist
    return out


def add_chart_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Chart panel indicators with relaxed MA warm-up for shorter histories.
    """
    out = df.copy()
    close = out["close"]
    out["ma20"] = close.rolling(20, min_periods=5).mean()
    out["ma50"] = close.rolling(50, min_periods=10).mean()
    out["rsi14"] = wilder_rsi(close, period=14)
    bb_mid, bb_upper, bb_lower = compute_bollinger_bands(close, window=20, min_periods=10)
    out["bb_mid"] = bb_mid
    out["bb_upper"] = bb_upper
    out["bb_lower"] = bb_lower
    macd, sig, hist = compute_macd(close)
    out["macd"] = macd
    out["macd_signal"] = sig
    out["macd_hist"] = hist
    return out
