from __future__ import annotations

from unittest.mock import patch

import pytest

from core.app_view_helpers import build_watch_rows, normalize_watch_seed


def test_normalize_watch_seed_filters_invalid_symbols() -> None:
    values = normalize_watch_seed("fpt, hpg; vnm, @@, abcdefg, aa")
    assert values == ["FPT", "HPG", "VNM", "AA"]


def test_build_watch_rows_marks_missing_snapshot() -> None:
    def _fake_loader(symbol: str):
        if symbol == "FPT":
            return {"price": 123.4, "price_source": "vndirect"}
        return None

    rows = build_watch_rows(["FPT", "HPG"], ["VNM"], _fake_loader)
    assert rows[0]["Mã"] == "FPT"
    assert rows[0]["Trạng thái"] == "Sẵn sàng"
    assert rows[1]["Mã"] == "HPG"
    assert rows[1]["Trạng thái"] == "Chưa có dữ liệu"


def test_build_watch_rows_recover_price_from_malformed_source_string() -> None:
    def _fake_loader(symbol: str) -> dict:
        return {"price": 0, "price_source": "70000 ohlcv_session_close:ohlcv_store_fastpath"}

    rows = build_watch_rows(["FPT"], ["FPT"], _fake_loader)
    assert rows[0]["Giá hiện tại"] == 70000.0
    assert rows[0]["Nguồn giá"] == "ohlcv_session_close:ohlcv_store_fastpath"


def test_build_watch_rows_prefers_live_quote_when_live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SNAPSHOT_PREFER_LIVE", "1")

    def _fake_loader(symbol: str):
        return {"price": 1.0, "price_source": "ohlcv_session_close:ohlcv_store_fastpath"}

    def _fake_quote(sym: str, *, use_cache: bool = True):
        assert use_cache is False
        return {"price": 99_000.0, "source": "cafef_hose"}

    with patch("scrapers.finance_scraper.get_stock_data", side_effect=_fake_quote):
        rows = build_watch_rows(["FPT"], ["FPT"], _fake_loader)
    assert rows[0]["Giá hiện tại"] == 99_000.0
    assert rows[0]["Nguồn giá"] == "cafef_hose"

