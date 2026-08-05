"""
P1 market regime — VNINDEX + macro bias → risk_on / neutral / risk_off.

Used by decision playbook to cap size and block hard BUY in risk-off.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def _f(v: Any, default: float = 0.0) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def assess_vnindex_tape(ohlcv: pd.DataFrame | None) -> dict[str, Any]:
    """
    Lightweight tape regime from VNINDEX (or any index) OHLCV.
    """
    if ohlcv is None or getattr(ohlcv, "empty", True) or len(ohlcv) < 20:
        return {
            "ok": False,
            "score": 0.0,
            "ret_5d_pct": None,
            "vs_ma20_pct": None,
            "label_hint": "unknown",
            "notes_vi": ["Thiếu OHLCV chỉ số (≥20 phiên)."],
        }
    d = ohlcv.copy()
    for col in ("close", "high", "low", "volume"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    d = d.dropna(subset=["close"])
    if len(d) < 20:
        return {
            "ok": False,
            "score": 0.0,
            "ret_5d_pct": None,
            "vs_ma20_pct": None,
            "label_hint": "unknown",
            "notes_vi": ["OHLCV chỉ số quá ngắn."],
        }
    close = float(d.iloc[-1]["close"])
    ma20 = float(d["close"].tail(20).mean())
    close_5 = float(d.iloc[-6]["close"]) if len(d) >= 6 else close
    ret_5d = ((close / close_5) - 1.0) * 100.0 if close_5 > 0 else 0.0
    vs_ma20 = ((close / ma20) - 1.0) * 100.0 if ma20 > 0 else 0.0

    score = 0.0
    notes: list[str] = []
    if vs_ma20 >= 1.0:
        score += 0.35
        notes.append(f"VNINDEX trên MA20 (+{vs_ma20:.1f}%).")
    elif vs_ma20 <= -1.5:
        score -= 0.45
        notes.append(f"VNINDEX dưới MA20 ({vs_ma20:.1f}%).")
    else:
        notes.append(f"VNINDEX quanh MA20 ({vs_ma20:.1f}%).")

    if ret_5d >= 1.5:
        score += 0.30
        notes.append(f"Tape 5 phiên mạnh (+{ret_5d:.1f}%).")
    elif ret_5d <= -2.0:
        score -= 0.40
        notes.append(f"Tape 5 phiên yếu ({ret_5d:.1f}%).")
    else:
        notes.append(f"Tape 5 phiên trung tính ({ret_5d:.1f}%).")

    # Soft breadth proxy: volume vs 20d avg on last bar
    if "volume" in d.columns:
        vol = float(d.iloc[-1].get("volume") or 0)
        vol_ma = float(d["volume"].tail(20).mean() or 0)
        if vol_ma > 0:
            vm = vol / vol_ma
            if ret_5d < 0 and vm >= 1.4:
                score -= 0.15
                notes.append("Khối lượng cao khi giảm — phân phối chỉ số.")
            elif ret_5d > 0 and vm >= 1.2:
                score += 0.10
                notes.append("Khối lượng xác nhận tăng.")

    score = _clamp(score)
    if score >= 0.25:
        hint = "risk_on"
    elif score <= -0.25:
        hint = "risk_off"
    else:
        hint = "neutral"
    return {
        "ok": True,
        "score": round(score, 3),
        "ret_5d_pct": round(ret_5d, 3),
        "vs_ma20_pct": round(vs_ma20, 3),
        "close": close,
        "ma20": round(ma20, 2),
        "label_hint": hint,
        "notes_vi": notes[:5],
    }


def assess_market_regime(
    *,
    vnindex_ohlcv: pd.DataFrame | None = None,
    macro: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Combine VNINDEX tape + macro market_bias → regime label and size multiplier.
    """
    tape = assess_vnindex_tape(vnindex_ohlcv)
    macro_d = macro if isinstance(macro, dict) else {}
    market_bias = _clamp(_f(macro_d.get("market_bias"), 0.0))

    # Blend: tape 65% + macro bias 35%
    blended = _clamp(0.65 * float(tape.get("score") or 0.0) + 0.35 * market_bias)
    notes = list(tape.get("notes_vi") or [])
    if macro_d:
        notes.append(f"Macro market_bias={market_bias:+.2f} (src={macro_d.get('source') or '—'}).")

    if blended >= 0.22:
        label = "risk_on"
        size_mult = 1.0
        note_vi = "Chế độ risk-on — được phép size chuẩn khi thesis/setup đủ."
    elif blended <= -0.22:
        label = "risk_off"
        size_mult = 0.35
        note_vi = "Chế độ risk-off — cấm BUY cứng; chỉ CONDITIONAL_BUY size nhỏ hoặc WATCH."
    else:
        label = "neutral"
        size_mult = 0.7
        note_vi = "Chế độ trung tính — giảm size; ưu tiên CONDITIONAL_BUY hơn BUY."

    if not tape.get("ok"):
        # Unknown tape → conservative neutral
        if label == "risk_on":
            label = "neutral"
            size_mult = min(size_mult, 0.7)
        notes.append("Tape chỉ số chưa đủ — giữ thận trọng.")

    return {
        "label": label,
        "score": round(blended, 3),
        "size_mult": size_mult,
        "market_bias": market_bias,
        "tape": tape,
        "allow_hard_buy": label == "risk_on",
        "note_vi": note_vi,
        "notes_vi": notes[:6],
    }


def load_market_regime_safe() -> dict[str, Any]:
    """Best-effort regime from disk/live helpers — never raises."""
    vnindex = None
    macro = None
    try:
        from core.ohlcv_store import load_recent_ohlcv

        vnindex = load_recent_ohlcv("VNINDEX", sessions=45)
        if vnindex is None or getattr(vnindex, "empty", True):
            try:
                from scrapers.portal import fetch_ohlcv_history

                vnindex = fetch_ohlcv_history("VNINDEX", sessions=45)
            except Exception:
                vnindex = None
    except Exception:
        vnindex = None
    try:
        from core.news_macro_service import get_macro_snapshot

        macro = get_macro_snapshot()
    except Exception:
        macro = None
    return assess_market_regime(vnindex_ohlcv=vnindex, macro=macro)
