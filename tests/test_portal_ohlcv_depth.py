from __future__ import annotations

import pandas as pd


def test_fetch_ohlcv_history_does_not_fastpath_when_disk_depth_insufficient(monkeypatch) -> None:
    import scrapers.portal as portal

    short_disk = pd.DataFrame(
        {
            "date": pd.date_range("2025-12-01", periods=80, freq="B"),
            "open": [10.0] * 80,
            "high": [11.0] * 80,
            "low": [9.0] * 80,
            "close": [10.5] * 80,
            "volume": [1000.0] * 80,
        }
    )
    short_disk.attrs["saved_at"] = "2026-04-28T00:00:00+00:00"
    long_live = pd.DataFrame(
        {
            "date": pd.date_range("2021-01-01", periods=1000, freq="B"),
            "open": [10.0] * 1000,
            "high": [11.0] * 1000,
            "low": [9.0] * 1000,
            "close": [10.5] * 1000,
            "volume": [1000.0] * 1000,
        }
    )

    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_bool_env", lambda name, default=False: True if name in ("II_OHLCV_DISK_FIRST", "II_READ_STALE_DISK") else default)
    monkeypatch.setattr(portal, "_float_env", lambda *a, **k: 7200.0)
    monkeypatch.setattr(portal, "_read_ohlcv_disk_cache", lambda sym: short_disk.copy())
    monkeypatch.setattr(portal, "_ohlcv_disk_cache_age_seconds", lambda df: 10.0)

    def _vnstock(sym, sessions=80):
        out = long_live.tail(max(50, sessions)).copy()
        out.attrs["source"] = "vnstock"
        return out

    monkeypatch.setattr(portal, "_fetch_ohlcv_vnstock", _vnstock)
    monkeypatch.setattr(portal, "_fetch_ohlcv_history_uncached", lambda sym, sessions=80: long_live.tail(max(50, sessions)).copy())
    monkeypatch.setattr(portal, "_write_ohlcv_disk_cache", lambda *a, **k: None)

    out = portal.fetch_ohlcv_history("FPT", sessions=800)
    assert len(out) >= 800
    assert str(out.attrs.get("source") or "") != "disk_cache_fastpath"
