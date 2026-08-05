from __future__ import annotations

from core.valuation import value_investing_summary


def test_valuation_pe_sanity_notes_on_absurd_earnings_yield() -> None:
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
    notes = out.get("pe_sanity_notes") or []
    assert notes, "expected PE sanity warning for EPS/price > 20%"
    assert "P/E" in (out.get("value_trap_warning") or "")
