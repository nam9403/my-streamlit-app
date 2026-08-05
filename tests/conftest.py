"""Pytest defaults: tránh gọi mạng nặng khi không chỉ định."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

# Headless matplotlib trong pytest (tránh Tk/__del__ trên Windows); không ảnh hưởng chạy app Streamlit.
os.environ.setdefault("MPLBACKEND", "Agg")

import pytest

# BCTC nhiều kỳ (VNDirect) — bật tay trong môi trường thật: II_FETCH_FINANCIAL_STATEMENTS=1
os.environ.setdefault("II_FETCH_FINANCIAL_STATEMENTS", "0")
os.environ.setdefault("II_SKIP_PEER_FETCH", "1")
os.environ.setdefault("II_SNAPSHOT_DISK_CACHE", "0")
# Test suite: mock-first snapshot tránh gọi mạng; app Streamlit không load conftest → mặc định live (financial_data).
os.environ.setdefault("II_SNAPSHOT_PREFER_LIVE", "0")
# Forecast settle: chỉ dùng OHLCV store đã có — không backfill live (tránh treo connect trong pytest).
os.environ.setdefault("II_FORECAST_SETTLE_LIVE_BACKFILL", "0")
# Offline-first OHLCV/financial: ưu tiên disk/cache; fail-fast nếu vẫn lọt ra live HTTP.
os.environ.setdefault("II_OHLCV_DISK_FIRST", "1")
os.environ.setdefault("II_SCAN_OHLCV_DISK_FIRST", "1")
os.environ.setdefault("II_OHLCV_ALLOW_STALE_DISK_FALLBACK", "1")
os.environ.setdefault("II_FINANCIAL_DISK_FIRST", "1")
os.environ.setdefault("II_PORTAL_FAIL_FAST", "1")
os.environ.setdefault("II_PORTAL_FAIL_FAST_BUDGET_SEC", "2")
os.environ.setdefault("II_PORTAL_LIVE_BUDGET_SEC", "2")


# Trước đây các file dưới bị gắn `network`, khiến fixture cách ly mạng bỏ qua và
# `is_tradable_vn_symbol` (gọi ngầm trong fetch_financial_snapshot) mở socket thật
# → treo test. Thực tế cả ba đều mock đầy đủ nguồn dữ liệu (pure-logic/unit), nên
# để trống danh sách này và cho fixture cách ly mạng áp dụng cho toàn bộ suite.
_NETWORK_TEST_FILES: frozenset[str] = frozenset()

_SLOW_TEST_FILES = frozenset(
    {
        "test_flow_backtest_service.py",
        "test_valuation_optimizer.py",
        "test_hybrid_forecast_service.py",
        "test_monthly_scheduler_script.py",
        "test_strategy_backtest.py",
        "test_candlestick_hover_compat.py",
        "test_runtime_alert_guard.py",
        "test_scale_gate_check.py",
        "test_slo_gate_check.py",
        "test_export_pilot_kpi_snapshot.py",
        "test_bootstrap_postgres.py",
        "test_backtest_flow_signals_cli.py",
    }
)

_SLOW_NODE_SUBSTRINGS = (
    "test_render_candlestick_modes_smoke",
    "test_scanner_scan_prefilter_and_empty_universe",
    "test_scan_respects_preselect_limit_cap",
)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        nid = getattr(item, "nodeid", "") or ""
        filepart = nid.split("::", 1)[0] if "::" in nid else nid
        base = Path(filepart).name
        if base in _NETWORK_TEST_FILES:
            item.add_marker(pytest.mark.network)
        if base in _SLOW_TEST_FILES:
            item.add_marker(pytest.mark.slow)
            # 10s default (bắt treo ngầm) không đủ cho test nặng hợp lệ → nới timeout.
            item.add_marker(pytest.mark.timeout(120))
            continue
        if any(s in nid for s in _SLOW_NODE_SUBSTRINGS):
            item.add_marker(pytest.mark.slow)
            item.add_marker(pytest.mark.timeout(120))


@pytest.fixture(autouse=True)
def _isolate_vn_listing_network(request: pytest.FixtureRequest):
    """
    Cách ly gọi mạng listing (VNDirect/FireAnt) trong test suite.

    `is_tradable_vn_symbol` → `list_tradable_vn_symbols(use_api=True)` gọi
    `requests.get(...)` thật; khi máy CI/offline không tới được host, socket
    connect treo vô thời hạn (không bị `requests timeout` chặn ở tầng connect
    trên một số nền tảng). Patch hai hàm fetch cấp thấp về "offline" giúp mọi
    test chạy hoàn toàn cục bộ. Test gắn marker `network` vẫn gọi thật.
    """
    if request.node.get_closest_marker("network"):
        yield
        return
    try:
        from scrapers import vn_listing as _vl
        from scrapers import vnstock_provider as _vp
    except Exception:
        yield
        return

    def _offline_vnstock_listing(**_kwargs):
        from scrapers.vnstock_provider import VnstockProviderError

        raise VnstockProviderError("offline_test")

    with (
        patch.object(_vp, "fetch_listing_snapshot", side_effect=_offline_vnstock_listing),
        patch.object(_vl, "fetch_vndirect_stock_codes", return_value=([], "offline_test")),
        patch.object(_vl, "fetch_fireant_stock_codes", return_value=([], "offline_test")),
    ):
        yield


@pytest.fixture(autouse=True)
def _block_outbound_http(request: pytest.FixtureRequest):
    """
    Fail-fast mọi outbound HTTP mặc định — tránh treo socket connect trên Windows.

    Test gắn `@pytest.mark.network` vẫn gọi thật. Test unit mock `requests.get` /
    `urlopen` riêng vẫn ghi đè được nhờ monkeypatch áp sau fixture này.
    """
    if request.node.get_closest_marker("network"):
        yield
        return

    import requests
    import urllib.error
    import urllib.request

    def _blocked_requests(*_a, **_k):
        raise requests.exceptions.ConnectionError("offline_test_blocked")

    def _blocked_urlopen(*_a, **_k):
        raise urllib.error.URLError("offline_test_blocked")

    with (
        patch.object(requests, "get", side_effect=_blocked_requests),
        patch.object(requests, "post", side_effect=_blocked_requests),
        patch.object(requests, "request", side_effect=_blocked_requests),
        patch.object(requests.sessions.Session, "request", side_effect=_blocked_requests),
        patch.object(urllib.request, "urlopen", side_effect=_blocked_urlopen),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_vn_tradable_symbol_cache() -> None:
    try:
        from scrapers.financial_data import clear_stock_metadata_cache
        from scrapers.vn_listing import clear_tradable_vn_symbol_cache

        clear_tradable_vn_symbol_cache()
        clear_stock_metadata_cache()
    except Exception:
        pass
    yield
    try:
        from scrapers.financial_data import clear_stock_metadata_cache
        from scrapers.vn_listing import clear_tradable_vn_symbol_cache

        clear_tradable_vn_symbol_cache()
        clear_stock_metadata_cache()
    except Exception:
        pass
