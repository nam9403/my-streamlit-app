"""
Pure helper utilities for app rendering flows.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from concurrent.futures import as_completed
from typing import Any

from core.streamlit_executor import streamlit_thread_pool_executor

from scrapers.vn_listing import is_tradable_vn_symbol


def _parse_leading_vn_price(s: str) -> float | None:
    m = re.match(r"^\s*([\d.,]+)\s+", s)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        v = float(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def normalize_watch_seed(seed_value: str) -> list[str]:
    raw_parts = [part.strip().upper() for part in str(seed_value or "").replace(";", ",").split(",")]
    cleaned: list[str] = []
    for symbol in raw_parts:
        if not symbol:
            continue
        if 2 <= len(symbol) <= 6 and symbol.isalnum():
            cleaned.append(symbol)
    return cleaned


def _watch_shelf_prefer_live_quote() -> bool:
    """Kệ giá nhanh: mặc định bám II_SNAPSHOT_PREFER_LIVE (app live=1 → gọi quote trước snapshot)."""
    v = str(os.environ.get("II_WATCH_SHELF_PREFER_LIVE", "") or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    pl = str(os.environ.get("II_SNAPSHOT_PREFER_LIVE", "1") or "").strip().lower()
    if pl in ("0", "false", "no", "off"):
        return False
    return True


def _watch_shelf_quote_max_workers(n_symbols: int) -> int:
    try:
        raw = int(os.environ.get("II_WATCH_SHELF_QUOTE_MAX_WORKERS", "8") or "8")
    except ValueError:
        raw = 8
    return max(1, min(max(1, raw), 16, max(1, n_symbols)))


def _fetch_shelf_live_quote(symbol: str) -> tuple[str, float | None, str, str]:
    """(symbol, price|None, source, err_note)."""
    try:
        from scrapers.finance_scraper import ScraperError, get_stock_data

        d = get_stock_data(symbol, use_cache=False)
        p = float(d.get("price") or 0)
        if p > 0:
            return symbol, p, str(d.get("source") or "quote"), ""
    except ScraperError as e:
        return symbol, None, "unknown", str(e)[:120]
    except Exception as e:
        return symbol, None, "unknown", str(e)[:80]
    return symbol, None, "unknown", ""


def build_watch_rows(
    watchlist: list[str],
    watchlist_default: list[str],
    load_snapshot_cached: Callable[[str], dict[str, Any] | None],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    symbols_in_order = list(watchlist or watchlist_default)
    live_pref = _watch_shelf_prefer_live_quote()
    live_ok: dict[str, tuple[float, str]] = {}
    live_err: dict[str, str] = {}
    if live_pref:
        tradable = [s for s in symbols_in_order if is_tradable_vn_symbol(s)]
        if tradable:
            workers = _watch_shelf_quote_max_workers(len(tradable))
            with streamlit_thread_pool_executor(max_workers=workers) as ex:
                futures = {ex.submit(_fetch_shelf_live_quote, s): s for s in tradable}
                for fut in as_completed(futures):
                    sym, px, src, err = fut.result()
                    if px is not None and px > 0:
                        live_ok[sym] = (px, src)
                    elif err:
                        live_err[sym] = err

    for symbol in symbols_in_order:
        if not is_tradable_vn_symbol(symbol):
            rows.append(
                {
                    "Mã": symbol,
                    "Giá hiện tại": None,
                    "Nguồn giá": "—",
                    "Trạng thái": "Không phải mã niêm yết VN",
                }
            )
            continue
        if symbol in live_ok:
            px, src = live_ok[symbol]
            rows.append(
                {
                    "Mã": symbol,
                    "Giá hiện tại": px,
                    "Nguồn giá": src,
                    "Trạng thái": "Sẵn sàng",
                }
            )
            continue

        snapshot = load_snapshot_cached(symbol)
        if snapshot is None:
            err = live_err.get(symbol, "")
            rows.append(
                {
                    "Mã": symbol,
                    "Giá hiện tại": None,
                    "Nguồn giá": "N/A",
                    "Trạng thái": err or "Chưa có dữ liệu",
                }
            )
            continue
        try:
            px = float(snapshot.get("price") or 0)
        except (TypeError, ValueError):
            px = 0.0
        src = str(snapshot.get("price_source") or snapshot.get("source") or "unknown")
        if px <= 0:
            recovered = _parse_leading_vn_price(src)
            if recovered is not None:
                px = float(recovered)
                src = src.split(None, 1)[-1].strip() if src.strip() else src
        status = "Sẵn sàng"
        if px <= 0 and symbol in live_err:
            status = live_err[symbol][:200] if live_err[symbol] else status
        rows.append(
            {
                "Mã": symbol,
                "Giá hiện tại": px if px > 0 else None,
                "Nguồn giá": src,
                "Trạng thái": status,
            }
        )
    return rows

