from __future__ import annotations

import pandas as pd


def test_fetch_financial_indicators_prefers_vnstock(monkeypatch) -> None:
    import scrapers.portal as portal

    ratio = pd.DataFrame(
        {
            "item_id": ["pe_ratio", "pb_ratio", "roe", "debt_to_equity"],
            "2024": [10.0, 1.8, 16.0, 0.5],
        }
    )
    vn_out = {
        "symbol": "FPT",
        "pe_ratio": 10.0,
        "pb_ratio": 1.8,
        "roe": 16.0,
        "debt_to_equity": 0.5,
        "data_quality_score": 4,
        "source": "vnstock_finance:vci",
    }

    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_read_fin_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_bool_env", lambda name, default=False: name == "II_FINANCIAL_LIVE_REFRESH")
    monkeypatch.setattr(portal, "_fetch_financial_indicators_from_vnstock", lambda sym, force_refresh=False: dict(vn_out))
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_uncached",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("should_not_call")),
    )
    monkeypatch.setattr(portal, "_write_fin_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)

    out = portal.fetch_financial_indicators("FPT", fast_mode=False)
    assert out["pe_ratio"] == 10.0
    assert out["roe"] == 16.0
    assert "vnstock" in str(out.get("source") or "")
