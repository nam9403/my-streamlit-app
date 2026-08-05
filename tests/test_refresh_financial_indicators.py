from __future__ import annotations

import sys


def test_fetch_financial_indicators_force_refresh_skips_disk_and_mem_cache(monkeypatch) -> None:
    import scrapers.portal as portal

    disk_reads: list[str] = []
    mem_reads: list[str] = []
    live_calls: list[bool] = []
    writes: list[str] = []

    monkeypatch.setattr(
        portal,
        "_cache_get",
        lambda key, ttl: mem_reads.append(key) or {"symbol": "FPT", "source": "mem_cache"},
    )
    monkeypatch.setattr(
        portal,
        "_read_fin_disk_cache",
        lambda sym: disk_reads.append(sym) or {"symbol": sym, "source": "old:disk_cache", "saved_at": "2020-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_from_vnstock",
        lambda sym, force_refresh=False: live_calls.append(force_refresh)
        or {"symbol": sym, "data_quality_score": 5, "pe_ratio": 12.0, "source": "vnstock_finance:vci"},
    )
    monkeypatch.setattr(portal, "_write_fin_disk_cache", lambda sym, payload: writes.append(sym))
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)
    monkeypatch.setenv("II_FINANCIAL_DISK_FIRST", "1")
    monkeypatch.setenv("II_FINANCIAL_STALE_WHILE_REVALIDATE", "1")

    out = portal.fetch_financial_indicators("FPT", fast_mode=False, force_refresh=True)

    assert mem_reads == []
    assert disk_reads == []
    assert live_calls == [True]
    assert writes == ["FPT"]
    assert out["source"] == "vnstock:live"
    assert out["pe_ratio"] == 12.0


def test_fetch_financial_indicators_env_live_refresh_skips_disk_cache(monkeypatch) -> None:
    import scrapers.portal as portal

    disk_reads: list[str] = []

    monkeypatch.setenv("II_FINANCIAL_LIVE_REFRESH", "1")
    monkeypatch.setenv("II_FINANCIAL_DISK_FIRST", "0")
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(
        portal,
        "_read_fin_disk_cache",
        lambda sym: disk_reads.append(sym) or {"symbol": sym, "source": "stale:disk_cache"},
    )
    monkeypatch.setattr(
        portal,
        "_fetch_financial_indicators_from_vnstock",
        lambda sym, force_refresh=False: {"symbol": sym, "data_quality_score": 4, "source": "vnstock_finance:vci"},
    )
    monkeypatch.setattr(portal, "_write_fin_disk_cache", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_cache_set", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_sla_mark", lambda *a, **k: None)

    out = portal.fetch_financial_indicators("HPG", fast_mode=False)

    assert disk_reads == []
    assert out["source"] == "vnstock:live"


def test_refresh_financial_indicators_script_passes_force_flag(monkeypatch) -> None:
    import os

    import scripts.refresh_financial_indicators as mod

    calls: list[dict[str, object]] = []
    prev_live = os.environ.get("II_FINANCIAL_LIVE_REFRESH")
    prev_disk = os.environ.get("II_FINANCIAL_DISK_FIRST")

    def fake_fetch(sym: str, *, fast_mode: bool = False, force_refresh: bool = False) -> dict[str, str]:
        calls.append({"sym": sym, "fast_mode": fast_mode, "force_refresh": force_refresh})
        return {"source": "vnstock:live", "symbol": sym}

    monkeypatch.setattr(
        "scrapers.portal.fetch_financial_indicators",
        fake_fetch,
    )
    monkeypatch.setattr(sys, "argv", ["refresh_financial_indicators.py", "--symbols", "FPT", "--force"])

    try:
        rc = mod.main()
    finally:
        if prev_live is None:
            os.environ.pop("II_FINANCIAL_LIVE_REFRESH", None)
        else:
            os.environ["II_FINANCIAL_LIVE_REFRESH"] = prev_live
        if prev_disk is None:
            os.environ.pop("II_FINANCIAL_DISK_FIRST", None)
        else:
            os.environ["II_FINANCIAL_DISK_FIRST"] = prev_disk

    assert rc == 0
    assert len(calls) == 1
    assert calls[0]["sym"] == "FPT"
    assert calls[0]["force_refresh"] is True


def test_refresh_financial_indicators_live_alias(monkeypatch) -> None:
    import os

    import scripts.refresh_financial_indicators as mod

    calls: list[bool] = []
    prev_live = os.environ.get("II_FINANCIAL_LIVE_REFRESH")
    prev_disk = os.environ.get("II_FINANCIAL_DISK_FIRST")

    monkeypatch.setattr(
        "scrapers.portal.fetch_financial_indicators",
        lambda sym, *, fast_mode=False, force_refresh=False: calls.append(force_refresh) or {"source": "vnstock:live"},
    )
    monkeypatch.setattr(sys, "argv", ["refresh_financial_indicators.py", "--symbols", "VNM", "--live"])

    try:
        assert mod.main() == 0
    finally:
        if prev_live is None:
            os.environ.pop("II_FINANCIAL_LIVE_REFRESH", None)
        else:
            os.environ["II_FINANCIAL_LIVE_REFRESH"] = prev_live
        if prev_disk is None:
            os.environ.pop("II_FINANCIAL_DISK_FIRST", None)
        else:
            os.environ["II_FINANCIAL_DISK_FIRST"] = prev_disk

    assert calls == [True]
