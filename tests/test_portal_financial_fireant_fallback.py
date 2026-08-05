from __future__ import annotations


def test_fetch_financial_indicators_falls_back_to_fireant(monkeypatch) -> None:
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
        "_fetch_financial_indicators_from_statements",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("statement fail")),
    )
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_from_fireant",
        lambda *a, **k: {
            "symbol": "FPT",
            "source": "fireant_finance_api",
            "debt_to_equity": 0.7,
            "gross_margin": 41.2,
            "revenue_growth_yoy": 12.0,
            "profit_growth_yoy": 9.0,
            "data_quality_score": 4,
        },
    )

    out = portal.fetch_financial_indicators("FPT", fast_mode=False)
    assert out["source"] == "fireant_finance_api"
    assert out["data_quality_score"] == 4
