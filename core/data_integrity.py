"""
P0 data integrity gates — OHLCV hygiene, price cross-check, MOS/PE clamp, RSI fail, paper action allowlist.

Hard rules for trustworthy DSS decisions. Not a profit guarantee.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

# --- Thresholds (tunable via env later if needed) ---
PRICE_CROSSCHECK_NOTE_PCT = 0.03  # ≥3% → note + trust penalty
PRICE_CROSSCHECK_HARD_PCT = 0.08  # ≥8% → block trade plan / MC trust
MAX_RANGE_PCT_10 = 80.0  # 10-session high-low range above this → corrupt / split mess
MAX_SINGLE_DAY_GAP_PCT = 45.0  # overnight gap without continuity → integrity fail
EXTREME_RSI_HIGH = 99.5
EXTREME_RSI_LOW = 0.5
MOS_ABS_HARD_CAP = 100.0  # |MOS| above this is not publishable as actionable
MOS_DISPLAY_CAP = 95.0  # clamp display when integrity soft-fails
EARNINGS_YIELD_ABSURD = 0.20  # EPS/price > 20% → PE sanity / MOS block
MIN_PE_ABSURD = 5.0

PAPER_LONG_ACTIONS = frozenset({"BUY", "CONDITIONAL_BUY"})


def _f(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sanitize_ohlcv_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """
    Drop structurally invalid bars; return cleaned frame + integrity report.

    Never invents prices — only removes impossible OHLC rows.
    """
    issues: list[str] = []
    if df is None or getattr(df, "empty", True):
        return df if df is not None else pd.DataFrame(), {
            "ok": False,
            "critical": True,
            "issues": ["ohlcv_empty"],
            "rows_in": 0,
            "rows_out": 0,
            "dropped": 0,
        }

    required = {"open", "high", "low", "close", "volume"}
    miss = [c for c in required if c not in df.columns]
    if miss:
        return df, {
            "ok": False,
            "critical": True,
            "issues": [f"missing_cols:{','.join(miss)}"],
            "rows_in": int(len(df)),
            "rows_out": int(len(df)),
            "dropped": 0,
        }

    out = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    rows_in = int(len(out))
    out = out.dropna(subset=["open", "high", "low", "close", "volume"])

    # Structural invariants
    bad_low = out["low"] <= 0
    bad_hl = out["high"] < out["low"]
    bad_close = (out["close"] < out["low"]) | (out["close"] > out["high"])
    bad_open = (out["open"] < out["low"] * 0.5) | (out["open"] > out["high"] * 1.5)
    bad_vol = out["volume"] < 0
    mask_bad = bad_low | bad_hl | bad_close | bad_open | bad_vol
    dropped = int(mask_bad.sum())
    if dropped:
        issues.append(f"dropped_invalid_bars:{dropped}")
        out = out.loc[~mask_bad].copy()

    report = assess_ohlcv_integrity(out, prior_issues=issues, rows_in=rows_in, dropped=dropped)
    try:
        out.attrs["ohlcv_integrity"] = report
    except Exception:
        pass
    return out, report


def assess_ohlcv_integrity(
    df: pd.DataFrame | None,
    *,
    prior_issues: list[str] | None = None,
    rows_in: int | None = None,
    dropped: int = 0,
) -> dict[str, Any]:
    """Score OHLCV series for phase / MC / WF eligibility."""
    issues = list(prior_issues or [])
    critical = False
    ok = True
    range_pct_10 = None
    max_gap_pct = None
    n = 0 if df is None or getattr(df, "empty", True) else int(len(df))

    if n < 2:
        return {
            "ok": False,
            "critical": True,
            "issues": issues + ["insufficient_rows"],
            "rows_in": rows_in if rows_in is not None else n,
            "rows_out": n,
            "dropped": int(dropped),
            "range_pct_10": None,
            "max_gap_pct": None,
            "block_phase": True,
            "block_forecast_mc": True,
        }

    try:
        last10 = df.iloc[-10:] if n >= 10 else df
        high_10 = float(last10["high"].max())
        low_10 = float(last10["low"].min())
        if low_10 <= 0:
            critical = True
            ok = False
            issues.append("low_non_positive_in_window")
            range_pct_10 = None
        else:
            range_pct_10 = (high_10 - low_10) / low_10 * 100.0
            if range_pct_10 > MAX_RANGE_PCT_10:
                critical = True
                ok = False
                issues.append(f"range_pct_10_absurd:{range_pct_10:.1f}")
    except Exception:
        issues.append("range_pct_10_calc_failed")
        ok = False
        critical = True

    try:
        closes = pd.to_numeric(df["close"], errors="coerce")
        prev = closes.shift(1)
        gap = ((closes - prev).abs() / prev.replace(0, pd.NA) * 100.0).dropna()
        if not gap.empty:
            max_gap_pct = float(gap.max())
            # Allow one large gap (split/dividend) but flag if multiple or extreme with low volume continuity
            extreme_gaps = gap[gap > MAX_SINGLE_DAY_GAP_PCT]
            if len(extreme_gaps) >= 2 or (len(extreme_gaps) == 1 and float(extreme_gaps.iloc[-1]) > 120.0):
                ok = False
                critical = True
                issues.append(f"gap_absurd:max={max_gap_pct:.1f}")
            elif len(extreme_gaps) == 1:
                issues.append(f"gap_warning:max={max_gap_pct:.1f}")
    except Exception:
        issues.append("gap_calc_failed")

    block_phase = critical or (not ok)
    block_mc = critical or (not ok)
    return {
        "ok": bool(ok and not critical),
        "critical": bool(critical),
        "issues": issues,
        "rows_in": rows_in if rows_in is not None else n,
        "rows_out": n,
        "dropped": int(dropped),
        "range_pct_10": None if range_pct_10 is None else round(float(range_pct_10), 4),
        "max_gap_pct": None if max_gap_pct is None else round(float(max_gap_pct), 4),
        "block_phase": bool(block_phase),
        "block_forecast_mc": bool(block_mc),
        "note_vi": (
            "OHLCV không đủ tin cậy — đã chặn phase/MC cho đến khi chuỗi giá sạch."
            if (critical or not ok)
            else ""
        ),
    }


def is_extreme_rsi_fail(rsi: float | None) -> bool:
    if rsi is None:
        return False
    try:
        r = float(rsi)
    except (TypeError, ValueError):
        return False
    return r >= EXTREME_RSI_HIGH or r <= EXTREME_RSI_LOW


def assess_price_crosscheck(quote: float | None, ohlcv_close: float | None) -> dict[str, Any]:
    """Compare snapshot quote vs last OHLCV close."""
    q = _f(quote) or 0.0
    c = _f(ohlcv_close) or 0.0
    if q <= 0 or c <= 0:
        return {
            "ok": True,
            "rel_pct": None,
            "note_level": "none",
            "note_vi": "",
            "block_trade_plan": False,
            "hard_desync": False,
        }
    rel = abs(c - q) / max(q, c, 1e-6)
    note_vi = ""
    note_level = "none"
    hard = rel >= PRICE_CROSSCHECK_HARD_PCT
    soft = rel >= PRICE_CROSSCHECK_NOTE_PCT
    if hard:
        note_level = "hard"
        note_vi = (
            f"Giá quote ({q:,.0f}) lệch {rel * 100:.1f}% so với đóng cửa OHLCV ({c:,.0f}); "
            "định giá dùng quote; phase/chart dùng OHLCV — chặn kế hoạch giao dịch đến khi đồng bộ nguồn."
        )
    elif soft:
        note_level = "soft"
        note_vi = (
            f"Giá quote ({q:,.0f}) lệch {rel * 100:.1f}% so với đóng cửa OHLCV ({c:,.0f}); "
            "kiểm tra scale/nguồn trước khi giải ngân."
        )
    return {
        "ok": not hard,
        "rel_pct": round(rel * 100.0, 3),
        "note_level": note_level,
        "note_vi": note_vi,
        "block_trade_plan": bool(hard or soft),  # P0: ≥3% already blocks actionable plan
        "hard_desync": bool(hard),
    }


def apply_mos_integrity_clamp(
    mos_pct: float | None,
    *,
    pe_sanity_notes: list[str] | None = None,
    pe_anomaly_flag: bool = False,
    eps_anomaly_flag: bool = False,
    pe: float | None = None,
    earnings_yield: float | None = None,
    price: float | None = None,
    eps: float | None = None,
) -> dict[str, Any]:
    """
    Clamp / block publishable MOS when unit/PE sanity fails or |MOS| is absurd.
    """
    notes = [str(x) for x in (pe_sanity_notes or []) if str(x).strip()]
    blocked = False
    reasons: list[str] = []

    ey = earnings_yield
    if ey is None and price and eps and float(price) > 0 and float(eps) > 0:
        ey = float(eps) / float(price)
    pe_v = _f(pe)

    if pe_anomaly_flag or eps_anomaly_flag:
        blocked = True
        reasons.append("pe_eps_anomaly")
    if notes:
        blocked = True
        reasons.append("pe_sanity_notes")
    if pe_v is not None and pe_v > 0 and pe_v < MIN_PE_ABSURD and ey is not None and ey > EARNINGS_YIELD_ABSURD:
        blocked = True
        reasons.append("absurd_earnings_yield")
    if mos_pct is not None and abs(float(mos_pct)) > MOS_ABS_HARD_CAP:
        blocked = True
        reasons.append("mos_abs_over_cap")

    raw = None if mos_pct is None else float(mos_pct)
    display = raw
    if raw is not None and abs(raw) > MOS_DISPLAY_CAP:
        display = MOS_DISPLAY_CAP if raw > 0 else -MOS_DISPLAY_CAP
        reasons.append("mos_display_clamped")
    if blocked and raw is not None:
        # Do not advertise extreme MOS as actionable edge
        if abs(raw) > 40.0:
            display = max(-40.0, min(40.0, display if display is not None else 0.0))
            reasons.append("mos_actionable_capped_on_integrity_fail")

    note_vi = ""
    if blocked:
        note_vi = (
            "MOS bị siết/không dùng để giải ngân do nghi ngờ đơn vị EPS/P/E hoặc biên an toàn phi thực tế. "
            + (" ".join(notes[:2]) if notes else "")
        ).strip()

    return {
        "mos_raw_pct": raw,
        "mos_display_pct": display,
        "mos_integrity_blocked": bool(blocked),
        "reasons": reasons,
        "note_vi": note_vi,
    }


def paper_action_allows_long(action: str | None) -> bool:
    """P0: only BUY / CONDITIONAL_BUY may open paper LONG."""
    raw = str(action or "").strip().upper()
    aliases = {
        "MUA": "BUY",
        "CONDITIONAL BUY": "CONDITIONAL_BUY",
        "MUA CÓ ĐIỀU KIỆN": "CONDITIONAL_BUY",
    }
    norm = aliases.get(raw, raw)
    return norm in PAPER_LONG_ACTIONS


def integrity_blocks_trade_plan(report: dict[str, Any] | None) -> tuple[bool, list[str]]:
    """Aggregate P0 blockers for Entry/SL/TP visibility."""
    rep = report if isinstance(report, dict) else {}
    reasons: list[str] = []

    trust = rep.get("data_trust_score") if isinstance(rep.get("data_trust_score"), dict) else {}
    if str(trust.get("band") or "").upper() == "LOW":
        reasons.append("data_trust_low")

    cross = str(rep.get("price_crosscheck_note_vi") or "").strip()
    if cross:
        reasons.append("price_ohlcv_desync")
    cross_meta = rep.get("price_crosscheck") if isinstance(rep.get("price_crosscheck"), dict) else {}
    if cross_meta.get("block_trade_plan"):
        if "price_ohlcv_desync" not in reasons:
            reasons.append("price_ohlcv_desync")

    ohlcv_i = rep.get("ohlcv_integrity") if isinstance(rep.get("ohlcv_integrity"), dict) else {}
    if ohlcv_i.get("critical") or ohlcv_i.get("block_forecast_mc"):
        reasons.append("ohlcv_integrity_fail")

    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    metrics = phase.get("metrics") if isinstance(phase.get("metrics"), dict) else {}
    if metrics.get("rsi_indicator_fail") or metrics.get("rsi_anomaly") in (1, 1.0, True):
        # Extreme RSI fail always blocks; soft anomaly alone is trust penalty only unless flag set
        if metrics.get("rsi_indicator_fail"):
            reasons.append("rsi_indicator_fail")

    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    if val.get("mos_integrity_blocked"):
        reasons.append("mos_integrity_blocked")

    snap_rsi = rep.get("rsi_indicator_fail") or rep.get("rsi_anomaly")
    if snap_rsi in (1, 1.0, True) and "rsi_indicator_fail" not in reasons:
        if rep.get("rsi_indicator_fail"):
            reasons.append("rsi_indicator_fail")

    return bool(reasons), reasons


def degraded_forecast_payload(*, horizon_days: int, reason_vi: str) -> dict[str, Any]:
    return {
        "horizon_days": horizon_days,
        "expected_price": None,
        "expected_return_pct": None,
        "scenarios": [],
        "forecast_range": {},
        "integrity_blocked": True,
        "summary": reason_vi
        or "Dự phóng xác suất bị chặn vì OHLCV/RSI không đủ tin cậy (P0 integrity).",
    }
