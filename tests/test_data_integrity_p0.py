"""P0 data integrity gates — OHLCV, price cross-check, MOS clamp, RSI fail, trade plan."""

from __future__ import annotations

import pandas as pd

from core.data_integrity import (
    apply_mos_integrity_clamp,
    assess_ohlcv_integrity,
    assess_price_crosscheck,
    is_extreme_rsi_fail,
    paper_action_allows_long,
    sanitize_ohlcv_frame,
)
from core.decision_action_gate import apply_trade_plan_visibility
from core.engine import detect_market_phase_from_ohlcv
from core.valuation import value_investing_summary


def _clean_ohlcv(n: int = 80) -> pd.DataFrame:
    rows = []
    for i in range(n):
        c = 100.0 + i * 0.2
        rows.append({"open": c - 0.1, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1_000_000})
    return pd.DataFrame(rows)


def test_sanitize_drops_invalid_bars_and_keeps_enough() -> None:
    df = _clean_ohlcv(60)
    # Inject corrupt bars
    df.loc[10, "low"] = 0.0
    df.loc[11, "high"] = 50.0
    df.loc[11, "low"] = 90.0  # high < low
    df.loc[12, "close"] = 200.0  # outside range
    cleaned, report = sanitize_ohlcv_frame(df)
    assert report["dropped"] >= 3
    assert len(cleaned) >= 50
    assert report["ok"] is True


def test_assess_ohlcv_flags_absurd_range() -> None:
    df = _clean_ohlcv(60)
    df.loc[55, "low"] = 0.01
    df.loc[55, "high"] = 500.0
    df.loc[55, "open"] = 100.0
    df.loc[55, "close"] = 100.0
    cleaned, report = sanitize_ohlcv_frame(df)
    # After sanitize, low=0.01 may remain if >0; range still absurd
    rep = assess_ohlcv_integrity(cleaned)
    assert rep["critical"] is True or (rep.get("range_pct_10") or 0) > 80
    assert rep["block_forecast_mc"] is True


def test_price_crosscheck_blocks_at_3pct() -> None:
    soft = assess_price_crosscheck(100.0, 104.0)
    assert soft["note_level"] == "soft"
    assert soft["block_trade_plan"] is True
    hard = assess_price_crosscheck(100.0, 110.0)
    assert hard["note_level"] == "hard"
    assert hard["hard_desync"] is True


def test_extreme_rsi_is_indicator_fail() -> None:
    assert is_extreme_rsi_fail(100.0) is True
    assert is_extreme_rsi_fail(0.0) is True
    assert is_extreme_rsi_fail(50.0) is False


def test_phase_marks_rsi_indicator_fail_on_saturated_rsi() -> None:
    # Pure uptrend → Wilder RSI saturates ~100 at the end
    n = 80
    rows = []
    for i in range(n):
        c = 50.0 + i * 1.5
        rows.append({"open": c - 0.2, "high": c + 0.5, "low": c - 0.5, "close": c, "volume": 1_000_000})
    phase = detect_market_phase_from_ohlcv(pd.DataFrame(rows))
    assert float(phase.metrics.get("rsi14_raw") or 0) >= 99.5
    assert phase.metrics.get("rsi_indicator_fail") is True
    assert float(phase.metrics.get("rsi14") or 0) == 50.0  # display clamped


def test_mos_integrity_clamps_absurd_and_pe_sanity() -> None:
    out = apply_mos_integrity_clamp(
        180.0,
        pe_sanity_notes=["P/E tính lại=3.0 rất thấp"],
        pe=3.0,
        earnings_yield=0.33,
    )
    assert out["mos_integrity_blocked"] is True
    assert abs(float(out["mos_display_pct"])) <= 95.0
    assert abs(float(out["mos_display_pct"])) <= 40.0  # actionable cap when blocked


def test_valuation_blocks_mos_on_absurd_earnings_yield() -> None:
    snap = {
        "symbol": "PNJ",
        "price": 35500.0,
        "eps": 10677.0,
        "pe_ratio": 3.57,
        "book_value_per_share": 10000.0,
        "roe": 25.0,
        "debt_to_equity": 0.2,
        "current_ratio": 1.8,
        "growth_rate_pct": 5.0,
        "industry": "Bán lẻ trang sức — Tiêu dùng",
        "industry_cluster": "consumer_retail_transport",
        "industry_subtype": "consumer_retail",
    }
    out = value_investing_summary(snap, include_extensions=False)
    assert out.get("pe_sanity_notes")
    assert out.get("mos_integrity_blocked") is True
    mos = float(out.get("margin_of_safety_composite_pct") or 0)
    assert abs(mos) <= 95.0
    assert out.get("instant_conclusion") != "Mua mạnh"


def test_trade_plan_hidden_on_integrity_block() -> None:
    rep = {
        "final_action": "BUY",
        "gate_passed": True,
        "output_gate_passed": True,
        "decision_alignment": {"unified_action": "BUY", "note_vi": ""},
        "price_crosscheck_note_vi": "Giá quote lệch 5%",
        "price_crosscheck": {"block_trade_plan": True, "hard_desync": False},
        "risk_plan": {"entry_price": 100.0, "stop_loss_price": 90.0, "take_profit_price": 120.0},
    }
    out = apply_trade_plan_visibility(rep)
    assert out["show_trade_plan"] is False
    assert out["risk_plan"]["trade_plan_active"] is False
    assert out.get("trade_plan_integrity_block") is True


def test_paper_action_allowlist() -> None:
    assert paper_action_allows_long("BUY") is True
    assert paper_action_allows_long("CONDITIONAL_BUY") is True
    assert paper_action_allows_long("WATCH") is False
    assert paper_action_allows_long("HOLD") is False
    assert paper_action_allows_long("AVOID") is False
