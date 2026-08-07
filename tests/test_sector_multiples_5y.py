"""Multi-year sector multiples warehouse."""

from __future__ import annotations

import json
from pathlib import Path

from core.sector_multiples import resolve_sector_multiples
from core.sector_multiples_5y import (
    build_sector_multiples_5y,
    lookup_5y_multiples,
    reconstruct_annual_multiples,
)
from core.valuation import value_investing_summary


def test_reconstruct_bid_has_multi_year_pe() -> None:
    pts = reconstruct_annual_multiples("BID", years=5)
    assert len(pts) >= 3
    assert all(4.0 <= float(p["pe"]) <= 40.0 for p in pts)


def test_build_warehouse_writes_bank_bucket(tmp_path: Path) -> None:
    out = tmp_path / "sector_multiples_5y.json"
    payload = build_sector_multiples_5y(symbols=["BID", "ACB", "VCB", "CTG"], years=5, out_path=out)
    assert out.is_file()
    assert payload.get("symbols_with_points", 0) >= 3
    bank = (payload.get("by_industry_subtype") or {}).get("bank")
    assert bank is not None
    assert bank.get("coverage") in ("5y", "multi_year")
    assert float(bank.get("pe_avg") or 0) > 0


def test_lookup_and_resolve_prefer_warehouse() -> None:
    # Ensure warehouse exists (build from liquid cache if missing).
    path = Path("data/sector_multiples_5y.json")
    if not path.is_file():
        build_sector_multiples_5y(years=5)
    hit = lookup_5y_multiples(symbol="BID", industry_subtype="bank")
    assert hit is not None
    assert hit.get("coverage") in ("5y", "multi_year")
    # Ưu tiên lịch sử chính mã BID hơn median ngành bank.
    assert str(hit.get("match") or "").startswith("symbol:")

    resolved = resolve_sector_multiples(
        symbol="BID",
        industry_subtype="bank",
        industry_cluster="financial",
        icb_sector="8300",
    )
    assert "5y" in str(resolved.get("source_pe") or "") or "multi_year" in str(
        resolved.get("source_pe") or ""
    )
    assert float(resolved.get("sector_pe") or 0) > 0
    assert resolved.get("horizon") in ("5y_reconstruct", "multi_year_reconstruct")
    # BID hist PE ~8–9, không bị kéo về median ngành ~5.6
    assert float(resolved["sector_pe"]) >= 7.0


def test_valuation_notes_show_warehouse_source() -> None:
    if not Path("data/sector_multiples_5y.json").is_file():
        build_sector_multiples_5y(years=5)
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
    out = value_investing_summary(snap, include_extensions=False)
    note = str(out.get("sector_pe_5y_note") or "")
    assert "đa năm" in note or "5y" in note or "multi_year" in note or "blend" in note
    meta = out.get("sector_multiples_meta") or {}
    assert meta.get("coverage") in ("5y", "multi_year") or "5y" in str(meta.get("source_pe") or "")
    fair = float(out.get("best_fair_value") or 0)
    assert fair > 30000
