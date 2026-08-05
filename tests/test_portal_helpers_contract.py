from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import pandas as pd


def test_portal_env_and_timeout_helpers(monkeypatch) -> None:
    import scrapers.portal as portal

    monkeypatch.delenv("II_PORTAL_FAIL_FAST", raising=False)
    monkeypatch.delenv("II_PORTAL_TIMEOUT_LADDER_SEC", raising=False)
    monkeypatch.setenv("II_PORTAL_FAIL_FAST", "true")
    monkeypatch.setenv("II_PORTAL_FAIL_FAST_BUDGET_SEC", "4")
    ladder = portal._timeout_ladder()
    assert len(ladder) >= 1
    assert portal._live_budget_seconds(12.0) <= 12.0

    monkeypatch.setenv("II_PORTAL_TIMEOUT_LADDER_SEC", "1.5,2.0,x,bad")
    assert portal._timeout_ladder()[:2] == [1.5, 2.0]

    monkeypatch.setenv("TEST_BOOL", "yes")
    assert portal._bool_env("TEST_BOOL") is True
    monkeypatch.setenv("TEST_FLOAT", "not-num")
    assert portal._float_env("TEST_FLOAT", 3.5) == 3.5


def test_financial_source_and_ticker_norm() -> None:
    import scrapers.portal as portal

    assert portal._is_real_financial_source({"source": "vndirect"}) is True
    assert portal._is_real_financial_source({"source": "snapshot_derived"}) is False
    assert portal._is_real_financial_source({"source": "mock_provider"}) is False

    assert portal._norm_ticker(" fpt ") == "FPT"
    try:
        portal._norm_ticker("  ")
    except portal.PortalDataError as e:
        assert "rỗng" in str(e).lower() or "Ticker" in str(e)


def test_age_and_data_trust_attach() -> None:
    import scrapers.portal as portal

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    assert portal._age_seconds_from_iso(past) is not None
    assert portal._age_seconds_from_iso("") is None
    assert portal._age_seconds_from_iso("not-a-date") is None

    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "open": [1.0, 1.0, 1.0],
            "high": [1.0, 1.0, 1.0],
            "low": [1.0, 1.0, 1.0],
            "close": [1.0, 1.0, 1.0],
            "volume": [100.0, 100.0, 100.0],
        }
    )
    out = portal._attach_ohlcv_data_trust(df, source="test", saved_at=past, stale_max_age_s=3600.0, fallback_chain=["a"])
    assert out.attrs.get("data_trust", {}).get("source") == "test"
    assert isinstance(out.attrs.get("fallback_chain"), list)

    fin = portal._attach_financial_data_trust({"eps": 1.0}, source="portal", saved_at=past, stale_max_age_s=1e9)
    assert fin.get("data_trust", {}).get("is_stale") is False


def test_tag_normalize_news_and_sla_roundtrip(monkeypatch, tmp_path: Path) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(portal, "_SLA_PATH", tmp_path / "sla.json")

    assert portal._tag_attr_text(["  a ", " b"]) == "a b"
    item = portal._normalize_news_item("  Tiêu đề tin FPT dài đủ hai mươi ký tự  ", "https://cafef.vn/x", "cafef")
    assert item["url"].startswith("https://")

    portal._sla_mark("unit_test_source", True)
    portal._sla_mark("unit_test_source", False)
    rows = portal.get_source_sla_report()
    assert any(r.get("source") == "unit_test_source" for r in rows)


def test_fetch_latest_news_uncached_merges_and_dedup(monkeypatch) -> None:
    import scrapers.portal as portal

    long_title = "Thông tin cổ phiếu FPT có nội dung đủ dài để vượt ngưỡng hai mươi"

    def fake_cafef(_sym: str, limit: int):
        return [{"title": long_title, "url": "https://cafef.vn/a", "source": "cafef"}][:limit]

    def fake_vs(_sym: str, limit: int):
        return [{"title": long_title + " Vietstock", "url": "https://vietstock.vn/b", "source": "vietstock"}][:limit]

    monkeypatch.setattr(portal, "_fetch_cafef_news", fake_cafef)
    monkeypatch.setattr(portal, "_fetch_vietstock_news", fake_vs)
    out = portal._fetch_latest_news_uncached("FPT", limit=5)
    assert len(out) >= 1
    urls = {x["url"] for x in out}
    assert "https://cafef.vn/a" in urls or "https://vietstock.vn/b" in urls


def test_fetch_latest_news_uncached_parallel_reduces_wait(monkeypatch) -> None:
    import scrapers.portal as portal

    long_title = "Thông tin cổ phiếu FPT có nội dung đủ dài để vượt ngưỡng hai mươi"

    def fake_cafef(_sym: str, limit: int):
        import time

        time.sleep(0.12)
        return [{"title": long_title, "url": "https://cafef.vn/a", "source": "cafef"}][:limit]

    def fake_vs(_sym: str, limit: int):
        import time

        time.sleep(0.12)
        return [{"title": long_title + " 2", "url": "https://vietstock.vn/b", "source": "vietstock"}][:limit]

    monkeypatch.setattr(portal, "_fetch_cafef_news", fake_cafef)
    monkeypatch.setattr(portal, "_fetch_vietstock_news", fake_vs)
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda default_budget=6.0: default_budget)

    t0 = perf_counter()
    out = portal._fetch_latest_news_uncached("FPT", limit=5)
    elapsed = perf_counter() - t0

    # Sequential baseline ~0.24s; parallel should stay near a single provider call.
    assert elapsed < 0.22
    assert len(out) >= 2


def test_fetch_latest_news_uses_disk_cache_fastpath(monkeypatch, tmp_path: Path) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(portal, "_NEWS_DISK_CACHE_PATH", tmp_path / "news_cache.json")
    portal._write_news_disk_cache(
        "FPT",
        [
            {"title": "Tin FPT 1 đủ dài để hợp lệ", "url": "https://cafef.vn/a", "source": "cafef"},
            {"title": "Tin FPT 2 đủ dài để hợp lệ", "url": "https://vietstock.vn/b", "source": "vietstock"},
        ],
    )
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_news_disk_cache_ttl_seconds", lambda: 600.0)

    called = {"n": 0}

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("should not call live news when disk fastpath is fresh")

    monkeypatch.setattr(portal, "_fetch_latest_news_uncached", _boom)
    out = portal.fetch_latest_news("FPT", limit=2)
    assert len(out) == 2
    assert called["n"] == 0


def test_fetch_latest_news_fallback_to_stale_disk_on_live_error(monkeypatch, tmp_path: Path) -> None:
    import scrapers.portal as portal

    monkeypatch.setattr(portal, "_NEWS_DISK_CACHE_PATH", tmp_path / "news_cache.json")
    portal._write_news_disk_cache(
        "FPT",
        [{"title": "Tin FPT đủ dài để fallback", "url": "https://cafef.vn/c", "source": "cafef"}],
    )
    monkeypatch.setattr(portal, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(portal, "_news_disk_cache_ttl_seconds", lambda: 0.0)
    monkeypatch.setattr(portal, "_news_disk_stale_fallback_seconds", lambda: 999999.0)

    def _raise(*_a, **_k):
        raise portal.PortalDataError("live down")

    monkeypatch.setattr(portal, "_fetch_latest_news_uncached", _raise)
    out = portal.fetch_latest_news("FPT", limit=1)
    assert len(out) == 1
    assert out[0]["url"] == "https://cafef.vn/c"


def _vndirect_rows(count: int, *, bad_prefix: int = 0, alt_fields: bool = False) -> list[dict]:
    rows_out: list[dict] = []
    base = datetime(2024, 1, 1, tzinfo=timezone.utc).date()
    for i in range(count):
        d = (base + timedelta(days=i)).isoformat()
        if i < bad_prefix:
            rows_out.append({"date": d, "open": None, "high": None, "low": None, "close": None, "nmVolume": None})
            continue
        if alt_fields and i % 3 == 0:
            rows_out.append(
                {
                    "tradingDate": d,
                    "open": 10.0 + i * 0.01,
                    "high": 11.0 + i * 0.01,
                    "low": 9.0 + i * 0.01,
                    "lastPrice": 10.5 + i * 0.01,
                    "volume": 1000000.0,
                }
            )
        else:
            rows_out.append(
                {
                    "date": d,
                    "open": 10.0 + i * 0.01,
                    "high": 11.0 + i * 0.01,
                    "low": 9.0 + i * 0.01,
                    "close": 10.5 + i * 0.01,
                    "nmVolume": 1000000.0,
                }
            )
    return rows_out


def test_fetch_ohlcv_history_uncached_vndirect_json(monkeypatch) -> None:
    import scrapers.portal as portal

    rows = _vndirect_rows(55)

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": rows}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 5.0)

    df = portal._fetch_ohlcv_history_uncached("FPT", sessions=80)
    assert len(df) >= 50
    assert list(df.columns)[:6] == ["date", "open", "high", "low", "close", "volume"]


def test_fetch_ohlcv_history_uncached_empty_data_raises(monkeypatch) -> None:
    import scrapers.portal as portal

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": []}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 5.0)

    try:
        portal._fetch_ohlcv_history_uncached("FPT", sessions=80)
    except portal.PortalDataError as e:
        assert "Không có dữ liệu OHLCV" in str(e)
    else:
        raise AssertionError("expected PortalDataError")


def test_fetch_ohlcv_history_uncached_insufficient_valid_rows_raises(monkeypatch) -> None:
    import scrapers.portal as portal

    rows = _vndirect_rows(45)

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": rows}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 5.0)

    try:
        portal._fetch_ohlcv_history_uncached("FPT", sessions=80)
    except portal.PortalDataError as e:
        assert "chưa đủ 50 phiên" in str(e)
    else:
        raise AssertionError("expected PortalDataError")


def test_fetch_ohlcv_history_uncached_skips_bad_rows_and_alt_fields(monkeypatch) -> None:
    import scrapers.portal as portal

    rows = _vndirect_rows(75, bad_prefix=20, alt_fields=True)

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": rows}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 5.0)

    df = portal._fetch_ohlcv_history_uncached("FPT", sessions=80)
    assert len(df) >= 50


def test_fetch_ohlcv_history_uncached_second_url_after_request_error(monkeypatch) -> None:
    import scrapers.portal as portal

    rows = _vndirect_rows(55)
    calls = {"n": 0}

    class _RespOk:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"data": rows}

    def fake_get(url: str, headers=None, timeout=None):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            raise portal.requests.RequestException("timeout")
        return _RespOk()

    monkeypatch.setattr(portal.requests, "get", fake_get)
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "FPT")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 5.0)

    df = portal._fetch_ohlcv_history_uncached("FPT", sessions=80)
    assert len(df) >= 50
    assert calls["n"] == 2


def test_fetch_ohlcv_yahoo_uncached_raises_when_all_invalid(monkeypatch) -> None:
    import scrapers.portal as portal

    class _Resp:
        status_code = 404

        def json(self) -> dict:
            return {}

    monkeypatch.setattr(portal.requests, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(portal, "_norm_ticker", lambda t: "ZZZ")
    monkeypatch.setattr(portal, "_live_budget_seconds", lambda *_: 30.0)
    monkeypatch.setattr(portal, "_pick_timeout_for_probe", lambda *a, **k: 2.0)

    try:
        portal._fetch_ohlcv_yahoo_uncached("ZZZ", sessions=80)
    except portal.PortalDataError as e:
        assert "Yahoo" in str(e) or "ZZZ" in str(e)
    else:
        raise AssertionError("expected PortalDataError")
