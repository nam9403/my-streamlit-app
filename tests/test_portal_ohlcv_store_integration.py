from __future__ import annotations

import pandas as pd


def test_fetch_ohlcv_history_uses_store_fastpath(monkeypatch) -> None:
    import scrapers.portal as portal

    store_df = pd.DataFrame(
        {
            "date": pd.date_range(end=pd.Timestamp.today().normalize(), periods=900, freq="B"),
            "open": [25_000.0] * 900,
            "high": [25_500.0] * 900,
            "low": [24_500.0] * 900,
            "close": [25_200.0] * 900,
            "volume": [1000.0] * 900,
        }
    )
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_bool_env", lambda name, default=False: True if name == "II_OHLCV_STORE_ENABLED" else default)
    monkeypatch.setattr(portal, "_is_suspicious_vn_price_scale", lambda sym, df: False)
    monkeypatch.setattr(portal, "load_recent_ohlcv", lambda symbol, sessions=80: store_df.tail(sessions).copy())

    out = portal.fetch_ohlcv_history("FPT", sessions=800)
    assert len(out) == 800
    assert str(out.attrs.get("source") or "") == "ohlcv_store_fastpath"

