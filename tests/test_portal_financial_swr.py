from __future__ import annotations


def test_financial_indicators_swr_serves_cache_and_schedules_refresh(monkeypatch) -> None:
    import scrapers.portal as portal

    launched: dict[str, object] = {}
    monkeypatch.setenv("II_FINANCIAL_STALE_WHILE_REVALIDATE", "1")
    monkeypatch.setenv("II_FINANCIAL_LIVE_REFRESH", "0")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_read_fin_disk_cache",
        lambda sym: {"symbol": sym, "debt_to_equity": 0.9, "source": "disk_cache", "saved_at": "2026-01-01T00:00:00+00:00"},
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
    assert str(out.get("source", "")).endswith(":swr")
    assert launched.get("sym") == "FPT"
