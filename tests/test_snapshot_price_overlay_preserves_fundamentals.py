from __future__ import annotations


def test_merge_live_price_preserves_eps_bv(monkeypatch) -> None:
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")
    monkeypatch.setenv("II_SNAPSHOT_STALE_WHILE_REVALIDATE", "0")
    monkeypatch.setattr(fd, "get_cached_snapshot", lambda sym: None)
    monkeypatch.setattr(
        fd,
        "get_disk_snapshot_any_age",
        lambda sym: {
            "symbol": sym,
            "price": 10_000.0,
            "eps": 800.0,
            "book_value_per_share": 12_000.0,
            "roe": 12.0,
            "source": "vietstock",
        },
    )
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {})
    monkeypatch.setattr(
        fs,
        "get_stock_data",
        lambda *a, **k: (_ for _ in ()).throw(fs.ScraperError("offline")),
    )
    monkeypatch.setattr(fd, "_market_price_fallback", lambda sym: (11_300.0, "vnstock:vci"))
    put: dict = {}
    monkeypatch.setattr(fd, "put_snapshot", lambda sym, row: put.__setitem__("row", dict(row)))

    out = fd.fetch_financial_snapshot("QTP")
    assert out is not None
    assert float(out.get("price") or 0) == 11_300.0
    assert float(out.get("eps") or 0) == 800.0
    assert float(out.get("book_value_per_share") or 0) == 12_000.0
    assert float((put.get("row") or {}).get("eps") or 0) == 800.0
    assert float((put.get("row") or {}).get("price") or 0) == 11_300.0


def test_indicator_merge_derives_eps_bvps_from_pe_pb() -> None:
    from core.financial_enrichment import merge_indicator_fundamentals_into_snapshot

    snap = {"symbol": "QTP", "price": 11_300.0}
    fin = {"pe_ratio": 15.0, "pb_ratio": 1.0, "roe": 0.07, "source": "test_fin"}
    notes = merge_indicator_fundamentals_into_snapshot(snap, financials=fin)
    assert float(snap.get("eps") or 0) == round(11300 / 15.0, 4)
    assert float(snap.get("book_value_per_share") or 0) == 11300.0
    assert any("EPS" in n for n in notes)
    assert any("BVPS" in n for n in notes)


def test_price_anchor_not_labeled_as_graham_capped() -> None:
    from core.valuation import select_best_fair_value

    out = select_best_fair_value(
        graham_raw=0.0,
        graham_capped=0.0,
        pe_fair=0.0,
        pb_fair=0.0,
        price=11_100.0,
        eps_trusted=False,
        mos_integrity_blocked=False,
    )
    assert out["best_fair_method"] == "price_anchor"
    assert "Graham" not in str(out.get("best_fair_label_vi") or "")
    assert float(out.get("best_fair_value") or 0) == 11_100.0
    assert out.get("fair_is_price_anchor") is True
