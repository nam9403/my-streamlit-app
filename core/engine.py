"""Data engine (technical) + Trend & Flow phase detection."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Callable

import pandas as pd

from core.indicators import add_engine_technical_indicators

from core.valuation import value_investing_summary
from scrapers.portal import fetch_financial_indicators, fetch_latest_news, fetch_ohlcv_history


class EngineError(Exception):
    """Base error for technical data engine."""


class OhlcvDataError(EngineError):
    """Raised when OHLCV data is missing or invalid."""


@dataclass(frozen=True)
class MarketPhaseResult:
    """Structured output for market phase detection."""

    phase: str
    reason: str
    metrics: dict[str, Any]


def _phase_rsi_coherence(
    *,
    close: float,
    ma20: float,
    day_change_pct: float,
    rsi14: float,
) -> tuple[float, float, str, bool]:
    """
    Phát hiện RSI lệch pha với xu hướng (vd. giá dưới MA20 + ngày giảm nhưng RSI≈100).
    Trả (rsi_display, anomaly_flag 0/1, note_vi, indicator_fail).

    P0: RSI≈100 hoặc ≈0 luôn là indicator_fail (không chỉ clamp hiển thị).
    """
    from core.data_integrity import is_extreme_rsi_fail

    note = ""
    anomaly = 0.0
    indicator_fail = False
    rsi_out = float(rsi14)
    if is_extreme_rsi_fail(rsi14):
        anomaly = 1.0
        indicator_fail = True
        rsi_out = 50.0
        note = (
            f"RSI14={rsi14:.1f} cực trị (≈0/100) — coi là indicator fail (P0); "
            "đã đặt RSI hiển thị trung tính, chặn tín hiệu dựa trên RSI."
        )
    # Giá dưới MA20 và phiên giảm nhưng RSI cực cao → nhiễu chuỗi / scale OHLCV.
    elif ma20 > 0 and close < ma20 * 0.98 and day_change_pct < 0 and rsi14 >= 80.0:
        anomaly = 1.0
        rsi_out = 50.0  # trung tính để tránh tín hiệu giả trong UI/rules
        note = (
            f"RSI14={rsi14:.1f} không khớp xu hướng giảm (close < MA20); "
            "đã đặt RSI hiển thị trung tính và gắn cờ rsi_anomaly."
        )
    elif ma20 > 0 and close > ma20 * 1.02 and day_change_pct > 0 and rsi14 <= 20.0:
        anomaly = 1.0
        rsi_out = 50.0
        note = (
            f"RSI14={rsi14:.1f} không khớp xu hướng tăng (close > MA20); "
            "đã đặt RSI hiển thị trung tính và gắn cờ rsi_anomaly."
        )
    return rsi_out, anomaly, note, indicator_fail


def _validate_ohlcv(df: pd.DataFrame, min_rows: int = 50) -> pd.DataFrame:
    """Validate and normalize OHLCV data (P0: drop invalid bars + integrity attrs)."""
    if df is None or df.empty:
        raise OhlcvDataError("OHLCV trống.")

    required = {"open", "high", "low", "close", "volume"}
    miss = [c for c in required if c not in df.columns]
    if miss:
        raise OhlcvDataError(f"Thiếu cột OHLCV bắt buộc: {', '.join(miss)}")

    from core.data_integrity import sanitize_ohlcv_frame

    out, integrity = sanitize_ohlcv_frame(df)
    if out is None or out.empty:
        raise OhlcvDataError("OHLCV trống sau khi lọc bar không hợp lệ.")

    if len(out) < min_rows:
        raise OhlcvDataError(f"Không đủ dữ liệu: cần >= {min_rows} phiên, hiện có {len(out)}.")

    # Critical integrity (absurd range/gaps) keeps rows for audit but marks attrs;
    # callers (phase/forecast) must respect block flags.
    try:
        out.attrs["ohlcv_integrity"] = integrity
    except Exception:
        pass
    return out


def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add technical indicators from OHLCV:
    - MA20, MA50
    - RSI14 (Wilder EWM)
    - vol_ma20, vol_std20
    - MACD line/signal/hist
    """
    out = _validate_ohlcv(df, min_rows=50)
    return add_engine_technical_indicators(out)


def detect_market_phase_from_ohlcv(df: pd.DataFrame) -> MarketPhaseResult:
    """
    Detect market phase:
    - Accumulation: 10-session range < 5% and volume < average 20 sessions.
    - Breakout: daily close change > 3% and volume > 1.5x average 20 sessions.
    - Distribution/Weakness: daily close change < 0 and volume > 1.5x average 20 sessions.
    """
    indicator_cols = ("ma20", "ma50", "rsi14", "vol_ma20", "vol_std20")
    if all(c in df.columns for c in indicator_cols):
        out = _validate_ohlcv(df, min_rows=50)
    else:
        out = compute_technical_indicators(df)
    last = out.iloc[-1]
    last10 = out.iloc[-10:]

    high_10 = float(last10["high"].max())
    low_10 = float(last10["low"].min())
    range_pct_10 = ((high_10 - low_10) / low_10 * 100.0) if low_10 > 0 else 0.0

    prev_close = float(out.iloc[-2]["close"])
    close = float(last["close"])
    day_change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

    vol = float(last["volume"])
    vol_ma20 = float(last["vol_ma20"]) if pd.notna(last["vol_ma20"]) else 0.0
    vol_multiple = (vol / vol_ma20) if vol_ma20 > 0 else 0.0

    accumulation = (range_pct_10 < 5.0) and (vol < vol_ma20 if vol_ma20 > 0 else False)
    breakout = (day_change_pct > 3.0) and (vol_multiple > 1.5)
    distribution = (day_change_pct < 0.0) and (vol_multiple > 1.5)

    if breakout:
        phase = "breakout"
        reason = "Giá tăng >3% và khối lượng >1.5 lần trung bình 20 phiên."
    elif distribution:
        phase = "distribution"
        reason = "Giá giảm kèm khối lượng lớn, tín hiệu suy yếu/phân phối."
    elif accumulation:
        phase = "accumulation"
        reason = "Giá đi ngang biên hẹp (<5%) và thanh khoản thấp hơn trung bình."
    else:
        phase = "neutral"
        reason = "Chưa xuất hiện tín hiệu tích lũy/bùng nổ/phân phối rõ."

    ma20 = float(last["ma20"]) if pd.notna(last["ma20"]) else 0.0
    ma50 = float(last["ma50"]) if pd.notna(last["ma50"]) else 0.0
    rsi_raw = float(last["rsi14"]) if pd.notna(last["rsi14"]) else 50.0
    rsi14, rsi_anomaly, rsi_note, rsi_fail = _phase_rsi_coherence(
        close=close, ma20=ma20, day_change_pct=day_change_pct, rsi14=rsi_raw
    )
    integrity = {}
    try:
        raw_i = out.attrs.get("ohlcv_integrity")
        if isinstance(raw_i, dict):
            integrity = raw_i
    except Exception:
        integrity = {}
    # P0: corrupt range / integrity → force neutral + unreliable flag
    if integrity.get("block_phase") or (range_pct_10 > 80.0):
        phase = "neutral"
        reason = (
            "OHLCV integrity fail — không xác định pha (range/gap bất thường). "
            + str(integrity.get("note_vi") or "")
        ).strip()
    metrics: dict[str, Any] = {
        "close": close,
        "day_change_pct": day_change_pct,
        "range_pct_10": range_pct_10,
        "volume": vol,
        "vol_ma20": vol_ma20,
        "vol_multiple": vol_multiple,
        "ma20": ma20,
        "ma50": ma50,
        "rsi14": rsi14,
        "rsi14_raw": rsi_raw,
        "rsi_anomaly": rsi_anomaly,
        "rsi_indicator_fail": bool(rsi_fail),
        "ohlcv_integrity_ok": bool(integrity.get("ok", True)) if integrity else (range_pct_10 <= 80.0),
        "vol_std20": float(last["vol_std20"]) if pd.notna(last["vol_std20"]) else 0.0,
    }
    if integrity:
        metrics["ohlcv_integrity"] = integrity
    if rsi_note:
        metrics["rsi_anomaly_note_vi"] = rsi_note

    return MarketPhaseResult(
        phase=phase,
        reason=reason,
        metrics=metrics,
    )


def detect_market_phase_at_index(
    ohlcv: pd.DataFrame,
    indicators: pd.DataFrame,
    index: int,
) -> MarketPhaseResult:
    """
    O(1) phase detection at bar ``index`` using precomputed indicators (incremental backtest).
    """
    i = int(index)
    if i < 1 or i >= len(ohlcv) or i >= len(indicators):
        raise OhlcvDataError(f"index_out_of_range:{i}")
    last = indicators.iloc[i]
    last10 = ohlcv.iloc[max(0, i - 9) : i + 1]

    high_10 = float(last10["high"].max())
    low_10 = float(last10["low"].min())
    range_pct_10 = ((high_10 - low_10) / low_10 * 100.0) if low_10 > 0 else 0.0

    prev_close = float(ohlcv.iloc[i - 1]["close"])
    close = float(last["close"])
    day_change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0

    vol = float(last["volume"])
    vol_ma20 = float(last["vol_ma20"]) if pd.notna(last["vol_ma20"]) else 0.0
    vol_multiple = (vol / vol_ma20) if vol_ma20 > 0 else 0.0

    accumulation = (range_pct_10 < 5.0) and (vol < vol_ma20 if vol_ma20 > 0 else False)
    breakout = (day_change_pct > 3.0) and (vol_multiple > 1.5)
    distribution = (day_change_pct < 0.0) and (vol_multiple > 1.5)

    if breakout:
        phase = "breakout"
        reason = "Giá tăng >3% và khối lượng >1.5 lần trung bình 20 phiên."
    elif distribution:
        phase = "distribution"
        reason = "Giá giảm kèm khối lượng lớn, tín hiệu suy yếu/phân phối."
    elif accumulation:
        phase = "accumulation"
        reason = "Giá đi ngang biên hẹp (<5%) và thanh khoản thấp hơn trung bình."
    else:
        phase = "neutral"
        reason = "Chưa xuất hiện tín hiệu tích lũy/bùng nổ/phân phối rõ."

    ma20 = float(last["ma20"]) if pd.notna(last["ma20"]) else 0.0
    ma50 = float(last["ma50"]) if pd.notna(last["ma50"]) else 0.0
    rsi_raw = float(last["rsi14"]) if pd.notna(last["rsi14"]) else 50.0
    # Incremental path: giữ RSI raw (backtest O(1)); chỉ gắn cờ, không clamp.
    _, rsi_anomaly, rsi_note, rsi_fail = _phase_rsi_coherence(
        close=close, ma20=ma20, day_change_pct=day_change_pct, rsi14=rsi_raw
    )
    metrics: dict[str, Any] = {
        "close": close,
        "day_change_pct": day_change_pct,
        "range_pct_10": range_pct_10,
        "volume": vol,
        "vol_ma20": vol_ma20,
        "vol_multiple": vol_multiple,
        "ma20": ma20,
        "ma50": ma50,
        "rsi14": rsi_raw,
        "rsi14_raw": rsi_raw,
        "rsi_anomaly": rsi_anomaly,
        "rsi_indicator_fail": bool(rsi_fail),
        "vol_std20": float(last["vol_std20"]) if pd.notna(last["vol_std20"]) else 0.0,
    }
    if rsi_note:
        metrics["rsi_anomaly_note_vi"] = rsi_note

    return MarketPhaseResult(
        phase=phase,
        reason=reason,
        metrics=metrics,
    )


def detect_market_phase(
    ticker: str,
    ohlcv_provider: Callable[[str], pd.DataFrame],
) -> MarketPhaseResult:
    """
    Wrapper using a provider function to fetch OHLCV then detect phase.

    `ohlcv_provider` should return a DataFrame with columns:
    open, high, low, close, volume (>= 50 rows).
    """
    if not ticker or not ticker.strip():
        raise OhlcvDataError("Ticker rỗng.")
    try:
        raw = ohlcv_provider(ticker.strip().upper())
    except Exception as e:  # pragma: no cover - provider-specific failures
        raise OhlcvDataError(f"Lỗi lấy OHLCV cho {ticker}: {e}") from e
    return detect_market_phase_from_ohlcv(raw)


def _safe_num(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _derive_financials_from_snapshot(symbol: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    sym = str(symbol or "").strip().upper()
    rev = _safe_num(snapshot.get("revenue"))
    rev_p = _safe_num(snapshot.get("revenue_prev"))
    ni = _safe_num(snapshot.get("net_income"))
    ni_p = _safe_num(snapshot.get("net_income_prev"))
    cogs = _safe_num(snapshot.get("cost_of_goods_sold"))
    debt = _safe_num(snapshot.get("debt"))
    equity = _safe_num(snapshot.get("shareholders_equity"))
    if equity <= 0:
        bvps = _safe_num(snapshot.get("book_value_per_share"))
        shares = _safe_num((snapshot.get("piotroski") or {}).get("shares_outstanding"))
        if bvps > 0 and shares > 0:
            equity = bvps * shares
    gross_margin = ((rev - cogs) / rev * 100.0) if rev > 0 else None
    rev_yoy = ((rev - rev_p) / rev_p * 100.0) if rev > 0 and rev_p > 0 else None
    profit_yoy = ((ni - ni_p) / ni_p * 100.0) if ni > 0 and ni_p > 0 else None
    debt_to_equity = (debt / equity) if debt > 0 and equity > 0 else None
    quality = sum(
        x is not None
        for x in (
            debt_to_equity,
            gross_margin,
            rev_yoy,
            profit_yoy,
        )
    )
    return {
        "symbol": sym,
        "debt_to_equity": debt_to_equity,
        "gross_margin": gross_margin,
        "revenue_growth_yoy": rev_yoy,
        "revenue_growth_qoq": None,
        "profit_growth_yoy": profit_yoy,
        "profit_growth_qoq": None,
        "data_quality_score": quality,
        "source": "snapshot_derived",
    }


def _strict_real_financial_data() -> bool:
    v = str(os.environ.get("II_STRICT_REAL_FINANCIAL_DATA", "1") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def build_investment_context(
    ticker: str,
    snapshot: dict,
    *,
    sessions: int = 80,
    news_limit: int = 10,
    fast_mode: bool = False,
) -> dict:
    """
    Aggregate 3-layer data for UI/AI:
    - technical: OHLCV + indicators + market phase
    - financial: ratio indicators
    - valuation: dynamic industry valuation summary
    - news: latest headlines
    """
    sym = (ticker or "").strip().upper()
    if not sym:
        raise OhlcvDataError("Ticker rỗng.")

    with ThreadPoolExecutor(max_workers=3) as ex:
        fut_ohlcv = ex.submit(fetch_ohlcv_history, sym, sessions)
        fut_fin = ex.submit(fetch_financial_indicators, sym, fast_mode=fast_mode)
        fut_news = ex.submit(fetch_latest_news, sym, news_limit)
        ohlcv = fut_ohlcv.result()
        try:
            financials = fut_fin.result()
        except Exception:
            financials = {}
        if _strict_real_financial_data():
            if not isinstance(financials, dict) or not financials:
                financials = {"symbol": sym, "source": "unavailable_live"}
        else:
            fin_src = str((financials or {}).get("source") or "").lower() if isinstance(financials, dict) else ""
            weak_fin = (
                not isinstance(financials, dict)
                or not financials
                or fin_src.startswith("unavailable")
                or not any(
                    financials.get(k) is not None
                    for k in ("debt_to_equity", "gross_margin", "revenue_growth_yoy", "operating_cash_flow")
                )
            )
            if weak_fin:
                financials = _derive_financials_from_snapshot(sym, snapshot)
        try:
            news = fut_news.result()
        except Exception:
            news = []

    # Gộp indicators (đã tải) vào snapshot trước khi chấm Legend — tránh hai đường song song.
    try:
        from core.financial_enrichment import merge_indicator_fundamentals_into_snapshot

        if isinstance(financials, dict) and financials:
            merge_indicator_fundamentals_into_snapshot(snapshot, financials)
    except Exception:
        pass

    # Đồng bộ hiển thị: quote vs OHLCV close (không ghi đè giá định giá). P0 ≥3%.
    try:
        from core.data_integrity import assess_price_crosscheck

        if ohlcv is not None and not ohlcv.empty:
            close = float(ohlcv.iloc[-1].get("close") or 0)
            if close > 0:
                snapshot["ohlcv_close"] = close
                snapshot.setdefault("ohlcv_close_source", str(ohlcv.attrs.get("source") or "ohlcv"))
                try:
                    quote_px = float(snapshot.get("price") or 0)
                except (TypeError, ValueError):
                    quote_px = 0.0
                xchk = assess_price_crosscheck(quote_px, close)
                snapshot["price_crosscheck"] = xchk
                if xchk.get("note_vi"):
                    snapshot["price_crosscheck_note_vi"] = xchk["note_vi"]
                integrity = ohlcv.attrs.get("ohlcv_integrity") if hasattr(ohlcv, "attrs") else None
                if isinstance(integrity, dict):
                    snapshot["ohlcv_integrity"] = integrity
    except Exception:
        pass

    valuation = value_investing_summary(snapshot)

    technical = compute_technical_indicators(ohlcv)
    phase = detect_market_phase_from_ohlcv(technical)
    # Propagate RSI / integrity flags onto snapshot for trust + trade-plan gates
    try:
        metrics = phase.metrics if isinstance(phase.metrics, dict) else {}
        if metrics.get("rsi_anomaly") in (1, 1.0, True):
            snapshot["rsi_anomaly"] = 1
        if metrics.get("rsi_indicator_fail"):
            snapshot["rsi_indicator_fail"] = True
        if isinstance(metrics.get("ohlcv_integrity"), dict):
            snapshot["ohlcv_integrity"] = metrics["ohlcv_integrity"]
        elif hasattr(technical, "attrs") and isinstance(technical.attrs.get("ohlcv_integrity"), dict):
            snapshot["ohlcv_integrity"] = technical.attrs["ohlcv_integrity"]
    except Exception:
        pass

    return {
        "ticker": sym,
        "technical": {
            "ohlcv": technical,
            "latest": technical.iloc[-1].to_dict() if not technical.empty else {},
            "market_phase": asdict(phase),
        },
        "financials": financials,
        "valuation": valuation,
        "news": news,
    }


def backtest_action_strategy(ohlcv: pd.DataFrame, horizon_days: int = 10) -> dict:
    """
    Backtest BUY/HOLD/AVOID action rules on historical OHLCV.
    Rule proxy:
    - BUY when close > ma20 and ma20 > ma50 and RSI in [45,70]
    - AVOID when close < ma20 and RSI < 45
    - HOLD otherwise
    Metric:
    - forward return after `horizon_days`
    - win rate for BUY signals
    """
    d = compute_technical_indicators(ohlcv).copy()
    if len(d) < max(60, horizon_days + 25):
        return {"samples": 0, "buy_signals": 0, "buy_win_rate_pct": 0.0, "buy_avg_return_pct": 0.0}

    d["fwd_ret_pct"] = d["close"].shift(-horizon_days) / d["close"] - 1.0

    def _signal(row: pd.Series) -> str:
        ma20_raw = row.get("ma20")
        ma50_raw = row.get("ma50")
        rsi_raw = row.get("rsi14")
        if pd.isna(ma20_raw) or pd.isna(ma50_raw) or pd.isna(rsi_raw):
            return "HOLD"
        c = float(row.get("close") or 0)
        ma20 = float(ma20_raw)
        ma50 = float(ma50_raw)
        rsi = float(rsi_raw)
        if c > ma20 > ma50 and 45 <= rsi <= 70:
            return "BUY"
        if c < ma20 and rsi < 45:
            return "AVOID"
        return "HOLD"

    d["signal"] = d.apply(_signal, axis=1)
    valid = d.dropna(subset=["fwd_ret_pct"])
    if valid.empty:
        return {"samples": 0, "buy_signals": 0, "buy_win_rate_pct": 0.0, "buy_avg_return_pct": 0.0}

    buy = valid[valid["signal"] == "BUY"]
    if buy.empty:
        return {
            "samples": int(len(valid)),
            "buy_signals": 0,
            "buy_win_rate_pct": 0.0,
            "buy_avg_return_pct": 0.0,
            "horizon_days": int(horizon_days),
        }
    win_rate = (buy["fwd_ret_pct"] > 0).mean() * 100.0
    avg_ret = buy["fwd_ret_pct"].mean() * 100.0
    return {
        "samples": int(len(valid)),
        "buy_signals": int(len(buy)),
        "buy_win_rate_pct": float(round(win_rate, 2)),
        "buy_avg_return_pct": float(round(avg_ret, 2)),
        "horizon_days": int(horizon_days),
    }
