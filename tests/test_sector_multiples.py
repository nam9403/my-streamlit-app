"""Sector / peer multiples for fair-value PE & PB."""

from __future__ import annotations

from core.sector_multiples import inject_sector_multiples_into_snapshot, resolve_sector_multiples
from core.valuation import value_investing_summary


def test_resolve_bank_multiples_not_hardcoded_10_125() -> None:
    out = resolve_sector_multiples(
        symbol="BID",
        industry_subtype="bank",
        industry_cluster="financial",
        icb_sector="8300",
    )
    assert out.get("sector_pe") is not None
    assert out.get("sector_pb") is not None
    # Warehouse/peer — không còn cặp default cứng (10 / 1.25).
    assert not (float(out["sector_pe"]) == 10.0 and float(out["sector_pb"]) == 1.25)
    assert float(out["sector_pe"]) > 0
    assert float(out["sector_pb"]) >= 1.0
    assert "5y" in str(out.get("source_pe") or "") or "peer" in str(out.get("source_pe") or "") or "prior" in str(
        out.get("source_pe") or ""
    )

def test_inject_does_not_override_explicit_5y() -> None:
    snap = {
        "symbol": "BID",
        "industry_subtype": "bank",
        "sector_pe_5y_avg": 11.0,
        "sector_pb_5y_avg": 1.4,
    }
    notes = inject_sector_multiples_into_snapshot(snap)
    assert float(snap["sector_pe_5y_avg"]) == 11.0
    assert float(snap["sector_pb_5y_avg"]) == 1.4
    assert notes == []


def test_inject_fills_missing_and_valuation_uses_them() -> None:
    snap = {
        "symbol": "BID",
        "price": 38250.0,
        "eps": 4572.0,
        "pe_ratio": 8.37,
        "book_value_per_share": 27304.0,
        "roe": 20.0,
        "debt_to_equity": 8.0,
        "current_ratio": 1.0,
        "growth_rate_pct": 8.0,
        "is_bank": True,
        "industry": "Ngân hàng",
        "industry_cluster": "financial",
        "industry_subtype": "bank",
        "icb_sector": "8300",
    }
    notes = inject_sector_multiples_into_snapshot(snap)
    assert notes
    assert float(snap.get("sector_pe_5y_avg") or 0) > 0
    assert float(snap.get("sector_pb_5y_avg") or 0) > 0

    out = value_investing_summary(dict(snap), include_extensions=False)
    assert "mặc định NH" not in str(out.get("sector_pe_5y_note") or "")
    assert float(out.get("sector_pe_5y_used") or 0) > 0
    assert float(out.get("fair_pb_multiple_used") or 0) >= 1.35
    fair = float(out.get("best_fair_value") or out.get("composite_target_price") or 0)
    assert fair > 0
    # Peer/prior NH không nên kẹp sát sổ sách như P/B 1.25 thuần.
    assert fair > 27304.0 * 1.25


def test_retail_prior_when_peers_thin() -> None:
    out = resolve_sector_multiples(
        symbol="XYZRETAIL",
        industry_subtype="consumer_retail",
        industry_cluster="consumer_retail_transport",
    )
    assert float(out["sector_pe"]) >= 15.0
    assert float(out["sector_pb"]) >= 2.0


def test_graham_filter_criteria_by_sector_group() -> None:
    from core.sector_multiples import graham_filter_criteria_for_sector, is_graham_asset_light_sector

    mfg = graham_filter_criteria_for_sector(industry_cluster="energy_manufacturing")
    assert mfg["group_id"] == "manufacturing_trade"
    assert float(mfg["max_debt_to_equity"]) == 0.5
    assert float(mfg["min_current_ratio"]) == 1.5

    tech = graham_filter_criteria_for_sector(
        industry_cluster="tech_telecom",
        industry_subtype="technology_services",
    )
    assert tech["group_id"] == "asset_light"
    assert float(tech["max_debt_to_equity"]) == 0.8
    assert float(tech["min_current_ratio"]) == 1.1
    assert is_graham_asset_light_sector(industry_text="Viễn thông di động")

    bank = graham_filter_criteria_for_sector(is_bank=True, bank_max_pe=12)
    assert bank["group_id"] == "bank"
    assert bank["mode"] == "bank_pe_roe"
    assert float(bank["bank_max_pe"]) == 12.0
    assert bank["max_debt_to_equity"] is None
    assert bank["min_current_ratio"] is None