from __future__ import annotations

from core.valuation import value_investing_summary


def test_valuation_pe_sanity_notes_on_absurd_earnings_yield() -> None:
    """Khi không đủ tín hiệu để sửa đơn vị (thiếu BVPS), vẫn cảnh báo EY/P/E absurb."""
    raw_eps = 10677.0
    price = 35500.0
    snap = {
        "symbol": "PNJ",
        "price": price,
        "eps": raw_eps,
        "pe_ratio": 3.57,
        # Không BVPS → khó chứng minh ROE absurb; vẫn có thể scale theo EY+cheap PE
        "roe": 25.0,
        "debt_to_equity": 0.2,
        "current_ratio": 1.8,
        "growth_rate_pct": 5.0,
        "industry": "Bán lẻ trang sức — Tiêu dùng",
        "industry_cluster": "consumer_retail_transport",
        "industry_subtype": "consumer_retail",
    }
    out = value_investing_summary(snap, include_extensions=False)
    eps_g = float(out.get("eps_for_graham") or 0)
    # Có thể đã scale theo EY; nếu còn absurb thì phải có note.
    if eps_g / price > 0.20:
        notes = out.get("pe_sanity_notes") or []
        assert notes, "expected PE sanity warning for EPS/price > 20%"
        assert "P/E" in (out.get("value_trap_warning") or "")
    else:
        assert out.get("eps_unit_corrected") is True
        assert eps_g <= raw_eps
        assert eps_g / price <= 0.20


def test_valuation_unit_fix_with_bvps_clears_absurd_yield() -> None:
    raw_eps = 10677.0
    price = 35500.0
    snap = {
        "symbol": "PNJ",
        "price": price,
        "eps": raw_eps,
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
    eps_g = float(out.get("eps_for_graham") or 0)
    assert eps_g <= raw_eps
    assert eps_g / price <= 0.20
    assert out.get("mos_integrity_blocked") is False
