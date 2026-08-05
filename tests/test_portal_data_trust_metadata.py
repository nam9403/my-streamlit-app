from __future__ import annotations

import pandas as pd


def test_ohlcv_store_fastpath_exposes_data_trust(monkeypatch) -> None:
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
    trust = out.attrs.get("data_trust") or {}
    assert str(out.attrs.get("source") or "") == "ohlcv_store_fastpath"
    assert isinstance(trust, dict)
    assert str(trust.get("source") or "") == "ohlcv_store_fastpath"
    assert isinstance(trust.get("fallback_chain"), list)
    assert bool(trust.get("is_stale")) is False


def test_financial_swr_exposes_data_trust(monkeypatch) -> None:
    import scrapers.portal as portal

    launched: dict[str, object] = {}
    monkeypatch.setenv("II_FINANCIAL_STALE_WHILE_REVALIDATE", "1")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_read_fin_disk_cache",
        lambda sym: {
            "symbol": sym,
            "debt_to_equity": 0.9,
            "source": "disk_cache",
            "saved_at": "2026-01-01T00:00:00+00:00",
        },
    )
    monkeypatch.setattr(portal, "_fin_disk_cache_age_seconds", lambda payload: 120.0)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_launch_financial_refresh",
        lambda sym, max_probes: launched.update({"sym": sym, "max_probes": int(max_probes)}),
    )

    out = portal.fetch_financial_indicators("FPT", fast_mode=False)
    trust = out.get("data_trust") or {}
    assert str(out.get("source", "")).endswith(":swr")
    assert isinstance(trust, dict)
    assert "financial_swr" in [str(x) for x in (trust.get("fallback_chain") or [])]
    assert launched.get("sym") == "FPT"

