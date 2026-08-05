from __future__ import annotations

import pandas as pd


def test_fetch_ohlcv_history_uses_fireant_fallback(monkeypatch) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "VHM")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_read_ohlcv_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_write_ohlcv_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_bool_env", lambda *a, **k: False)
    monkeypatch.setattr(
        portal,
        "_fetch_ohlcv_vnstock",
        lambda *a, **k: (_ for _ in ()).throw(portal.VnstockProviderError("vnstock fail")),
    )
    monkeypatch.setattr(
        portal,
        "_fetch_ohlcv_history_uncached",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("live fail")),
    )
    fireant_df = pd.DataFrame(
        [
            {"date": "2024-01-01", "open": 1.0, "high": 1.2, "low": 0.9, "close": 1.1, "volume": 1000.0},
            {"date": "2024-01-02", "open": 1.1, "high": 1.3, "low": 1.0, "close": 1.2, "volume": 1100.0},
        ]
        * 60
    )
    monkeypatch.setattr(portal, "_fetch_ohlcv_fireant_uncached", lambda *a, **k: fireant_df.copy())

    out = portal.fetch_ohlcv_history("VHM", sessions=80)
    assert str(out.attrs.get("source")) == "fireant_fallback"
    assert len(out) >= 50
