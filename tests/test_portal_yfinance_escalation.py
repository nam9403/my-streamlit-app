from __future__ import annotations

import pandas as pd


def test_fetch_ohlcv_history_escalates_to_yfinance_when_yahoo_short(monkeypatch) -> None:
    import scrapers.portal as portal

    short_df = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=680, freq="B"),
            "open": [10.0] * 680,
            "high": [11.0] * 680,
            "low": [9.0] * 680,
            "close": [10.5] * 680,
            "volume": [1000.0] * 680,
        }
    )
    long_df = pd.DataFrame(
        {
            "date": pd.date_range("2021-01-01", periods=1100, freq="B"),
            "open": [10.0] * 1100,
            "high": [11.0] * 1100,
            "low": [9.0] * 1100,
            "close": [10.5] * 1100,
            "volume": [1000.0] * 1100,
        }
    )

    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_bool_env",
        lambda name, default=False: (
            False if name in ("II_OHLCV_DISK_FIRST", "II_OHLCV_STORE_ENABLED") else True
        ),
    )
    monkeypatch.setattr(portal, "_float_env", lambda *a, **k: 7200.0)
    monkeypatch.setattr(portal, "_read_ohlcv_disk_cache", lambda sym: None)
    monkeypatch.setattr(
        portal,
        "_fetch_ohlcv_vnstock",
        lambda *a, **k: (_ for _ in ()).throw(portal.VnstockProviderError("vnstock fail")),
    )
    monkeypatch.setattr(portal, "_fetch_ohlcv_history_uncached", lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("live fail")))
    monkeypatch.setattr(
        portal,
        "_fetch_ohlcv_fireant_uncached",
        lambda *a, **k: (_ for _ in ()).throw(portal.PortalDataError("fireant fail")),
    )
    monkeypatch.setattr(portal, "_fetch_ohlcv_yahoo_uncached", lambda *a, **k: short_df.copy())
    monkeypatch.setattr(portal, "_fetch_ohlcv_yfinance_uncached", lambda *a, **k: long_df.copy())
    monkeypatch.setattr(portal, "_write_ohlcv_disk_cache", lambda *a, **k: None)

    out = portal.fetch_ohlcv_history("FPT", sessions=1000)
    assert len(out) >= 1000
    assert str(out.attrs.get("source") or "") == "yfinance_fallback"
