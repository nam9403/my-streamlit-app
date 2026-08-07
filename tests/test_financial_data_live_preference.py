from __future__ import annotations


def test_prod_prefers_live_over_mock(monkeypatch) -> None:
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_ENV", "prod")
    monkeypatch.delenv("II_SNAPSHOT_PREFER_LIVE", raising=False)
    monkeypatch.setattr(fd, "get_cached_snapshot", lambda sym: None)
    monkeypatch.setattr(fd, "get_disk_snapshot_any_age", lambda sym: None)
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {"FPT": {"price": 1.0}})

    monkeypatch.setattr(fs, "get_stock_data", lambda sym, use_cache=True: {"symbol": sym, "price": 123.0, "source": "vndirect_finfo"})
    monkeypatch.setattr(fd, "_resolve_snapshot_market_price", lambda row, sym, **kwargs: None)
    monkeypatch.setattr(fd, "_merge_stock_metadata", lambda row, sym: None)
    monkeypatch.setattr(fd, "put_snapshot", lambda sym, row: None)

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert str(out.get("source")) == "vndirect_finfo"
    assert float(out.get("price") or 0) == 123.0


def test_dev_mock_first_when_live_disabled(monkeypatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_ENV", "dev")
    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "0")
    monkeypatch.setattr(fd, "get_cached_snapshot", lambda sym: None)
    monkeypatch.setattr(fd, "get_disk_snapshot_any_age", lambda sym: None)
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {"FPT": {"price": 98_000}})
    monkeypatch.setattr(fd, "_resolve_snapshot_market_price", lambda row, sym, **kwargs: None)
    monkeypatch.setattr(fd, "_merge_stock_metadata", lambda row, sym: None)
    monkeypatch.setattr(fd, "put_snapshot", lambda sym, row: None)

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert str(out.get("source")) == "mock_json"
    assert float(out.get("price") or 0) == 98_000


def test_prod_snapshot_swr_returns_stale_and_launches_refresh(monkeypatch) -> None:
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    launched: dict[str, str] = {}
    monkeypatch.setenv("II_ENV", "prod")
    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")
    monkeypatch.setenv("II_SNAPSHOT_STALE_WHILE_REVALIDATE", "1")
    monkeypatch.setenv("II_SNAPSHOT_SWR_PRICE_OVERLAY", "0")
    monkeypatch.setenv("II_READ_STALE_DISK", "1")
    monkeypatch.setattr(fd, "get_cached_snapshot", lambda sym: None)
    monkeypatch.setattr(fd, "get_disk_snapshot_any_age", lambda sym: {"symbol": sym, "price": 101.0, "source": "disk_cache"})
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {})
    monkeypatch.setattr(fd, "_launch_snapshot_refresh", lambda sym: launched.setdefault("sym", sym))
    monkeypatch.setattr(fs, "get_stock_data", lambda *a, **k: (_ for _ in ()).throw(fs.ScraperError("boom")))

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert str(out.get("source", "")).endswith(":swr")
    assert launched.get("sym") == "FPT"


def test_swr_price_overlay_updates_price_from_fast_quote(monkeypatch) -> None:
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    launched: dict[str, str] = {}
    monkeypatch.setenv("II_ENV", "dev")
    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")
    monkeypatch.setenv("II_SNAPSHOT_STALE_WHILE_REVALIDATE", "1")
    monkeypatch.setenv("II_SNAPSHOT_SWR_PRICE_OVERLAY", "1")
    monkeypatch.setenv("II_READ_STALE_DISK", "1")
    monkeypatch.setattr(fd, "get_cached_snapshot", lambda sym: None)
    monkeypatch.setattr(
        fd,
        "get_disk_snapshot_any_age",
        lambda sym: {"symbol": sym, "price": 100.0, "eps": 5.0, "source": "disk_cache"},
    )
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {})
    monkeypatch.setattr(fd, "_launch_snapshot_refresh", lambda sym: launched.setdefault("sym", sym))
    monkeypatch.setattr(
        fs,
        "get_quote_price_fast",
        lambda sym, budget_sec=None, max_providers=None: {"symbol": sym, "price": 120.0, "source": "vndirect_finfo"},
    )

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert float(out.get("price") or 0) == 120.0
    assert float(out.get("eps") or 0) == 5.0
    assert str(out.get("price_source", "")).startswith("quote_fast:")
    assert str(out.get("source", "")).endswith(":swr")
    assert launched.get("sym") == "FPT"


def test_hot_cache_prefer_live_refreshes_price(monkeypatch) -> None:
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")
    monkeypatch.setenv("II_SNAPSHOT_SWR_PRICE_OVERLAY", "1")
    monkeypatch.setattr(
        fd,
        "get_cached_snapshot",
        lambda sym: {"symbol": sym, "price": 98_000.0, "eps": 6.0, "source": "vietstock"},
    )
    monkeypatch.setattr(fd, "get_disk_snapshot_any_age", lambda sym: None)
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {})
    monkeypatch.setattr(
        fs,
        "get_quote_price_fast",
        lambda sym, budget_sec=None, max_providers=None: {"symbol": sym, "price": 70_500.0, "source": "vndirect"},
    )

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert float(out.get("price") or 0) == 70_500.0
    assert float(out.get("eps") or 0) == 6.0
    assert str(out.get("price_source", "")).startswith("quote_fast:")


def test_market_fallback_cache_is_not_treated_as_pure_mock(monkeypatch) -> None:
    """Bug: 'mock_json' in 'mock_json+market_fallback' từng khiến bỏ cache giá đúng → rơi về mock 98k."""
    import scrapers.finance_scraper as fs
    import scrapers.financial_data as fd

    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")
    monkeypatch.setenv("II_SNAPSHOT_SWR_PRICE_OVERLAY", "1")
    monkeypatch.setattr(
        fd,
        "get_cached_snapshot",
        lambda sym: {
            "symbol": sym,
            "price": 70_800.0,
            "eps": 6200.0,
            "source": "mock_json+market_fallback",
            "price_source": "vnstock:vci",
        },
    )
    monkeypatch.setattr(fd, "get_disk_snapshot_any_age", lambda sym: None)
    monkeypatch.setattr(fd, "_load_mock_json", lambda: {"FPT": {"price": 98_000}})
    monkeypatch.setattr(
        fs,
        "get_quote_price_fast",
        lambda sym, budget_sec=None, max_providers=None: {"symbol": sym, "price": 70_900.0, "source": "vndirect"},
    )
    # Nếu nhầm skip cache → sẽ scrape; chặn scrape để chắc đi path cache.
    monkeypatch.setattr(
        fs,
        "get_stock_data",
        lambda *a, **k: (_ for _ in ()).throw(fs.ScraperError("should_not_scrape")),
    )

    out = fd.fetch_financial_snapshot("FPT")
    assert out is not None
    assert float(out.get("price") or 0) == 70_900.0
    assert "98" not in str(int(out.get("price") or 0))


def test_list_universe_symbols_offset_and_limit(monkeypatch) -> None:
    import scrapers.financial_data as fd

    monkeypatch.setattr(
        fd,
        "list_tradable_vn_symbols",
        lambda use_api=True: ["A", "B", "C", "D", "E"],
    )
    assert fd.list_universe_symbols(limit=2, offset=1) == ["B", "C"]
    assert fd.list_universe_symbols(limit=None, offset=3) == ["D", "E"]
