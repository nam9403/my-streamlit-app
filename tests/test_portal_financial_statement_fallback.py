from __future__ import annotations


def test_fetch_financial_indicators_falls_back_to_statements(monkeypatch) -> None:
    import scrapers.portal as portal

    monkeypatch.setenv("II_FINANCIAL_LIVE_REFRESH", "1")
    monkeypatch.setenv("II_FINANCIAL_DISK_FIRST", "0")
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_read_fin_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_write_fin_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_from_vnstock",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("vnstock fail")),
    )
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_uncached",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("live fail")),
    )
    monkeypatch.setattr(
        portal,
        "fetch_vndirect_financial_statement_rows",
        lambda *a, **k: ([{"year": 2026, "quarter": 1}, {"year": 2025, "quarter": 1}], "fs_q"),
    )
    monkeypatch.setattr(
        portal,
        "compute_trend_metrics",
        lambda rows: {
            "periods": len(rows),
            "revenue_yoy_pct": 12.3,
            "profit_yoy_pct": 8.4,
            "trend_label": "Doanh thu tăng (YoY)",
            "yoy_compare_label_vi": "Q1/2026 so với Q1/2025",
        },
    )

    out = portal.fetch_financial_indicators("FPT", fast_mode=False)
    assert out["source"].startswith("vndirect_financial_statements:")
    assert out["revenue_growth_yoy"] == 12.3
    assert out["profit_growth_yoy"] == 8.4
