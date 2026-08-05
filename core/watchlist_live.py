"""
Bảng giá watchlist: làm mới định kỳ (không dùng cache scrape dài) + fallback snapshot.
"""

from __future__ import annotations

import os
from concurrent.futures import as_completed
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from core.streamlit_executor import streamlit_thread_pool_executor

from scrapers.finance_scraper import ScraperError, get_stock_data
from scrapers.financial_data import fetch_financial_snapshot

_MAX = max(5, min(40, int(os.environ.get("WATCHLIST_LIVE_MAX_SYMBOLS", "25"))))


def _trim(symbols: list[str]) -> list[str]:
    out: list[str] = []
    for s in symbols:
        u = (s or "").strip().upper()
        if u and u not in out:
            out.append(u)
    return out[:_MAX]


def watchlist_signature(symbols: list[str]) -> str:
    """Khóa ổn định để reset session khi đổi watchlist."""
    return "|".join(_trim(symbols))


def normalize_watchlist_symbols(symbols: list[str]) -> list[str]:
    return _trim(symbols)


@st.cache_data(ttl=45, show_spinner=False)
def watchlist_live_prices_cached(symbols: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    """Giá live — cache ngắn để rerun Streamlit không gọi mạng lặp lại liên tục."""
    return build_watchlist_price_dataframe(list(symbols), live=True)


def _watchlist_quote_max_workers(n_symbols: int) -> int:
    try:
        raw = int(os.environ.get("II_WATCHLIST_QUOTE_MAX_WORKERS", "8") or "8")
    except ValueError:
        raw = 8
    return max(1, min(max(1, raw), 16, max(1, n_symbols)))


def build_watchlist_price_dataframe(symbols: list[str], *, live: bool) -> tuple[pd.DataFrame, str]:
    """
    live=True: ưu tiên quote mới (get_stock_data use_cache=False), fallback snapshot.
    live=False: chỉ snapshot/mock + giá portal (nhẹ hơn, phù hợp khi tắt auto-refresh).

    Gợi ý UX (stale-while-revalidate): gọi live=False để hiển thị ngay từ cache đĩa,
    sau đó (fragment / lượt sau) gọi live=True để đồng bộ giá sàn.
    """
    syms = _trim(symbols)
    rows: list[dict] = []
    live_prices: dict[str, tuple[float, str]] = {}
    live_err: dict[str, str] = {}
    if live and syms:

        def _one(sym: str) -> tuple[str, float | None, str, str]:
            try:
                d = get_stock_data(sym, use_cache=False)
                p = float(d.get("price") or 0)
                if p > 0:
                    return sym, p, str(d.get("source") or ""), ""
            except ScraperError as e:
                return sym, None, "", str(e)[:100]
            return sym, None, "", ""

        workers = _watchlist_quote_max_workers(len(syms))
        with streamlit_thread_pool_executor(max_workers=workers) as ex:
            futs = [ex.submit(_one, s) for s in syms]
            for fut in as_completed(futs):
                sym, p, src, err = fut.result()
                if p is not None and p > 0:
                    live_prices[sym] = (p, src)
                elif err:
                    live_err[sym] = err

    for sym in syms:
        price: float | None = None
        src = "unknown"
        note = ""

        if live:
            hit = live_prices.get(sym)
            if hit is not None:
                price, src = hit[0], hit[1]
                note = "Live"
            elif sym in live_err:
                note = live_err[sym]

        if price is None or price <= 0:
            snap = fetch_financial_snapshot(sym)
            if snap is None:
                rows.append(
                    {
                        "Mã": sym,
                        "Giá hiện tại": None,
                        "Nguồn giá": src,
                        "Trạng thái": "Chưa có dữ liệu" if not note else note,
                    }
                )
                continue
            price = float(snap.get("price") or 0)
            src = str(snap.get("price_source") or snap.get("source") or "snapshot")
            if price > 0:
                note = note or "Snapshot"
            elif not note:
                note = "Chưa có giá"

        if price is None or price <= 0:
            rows.append(
                {
                    "Mã": sym,
                    "Giá hiện tại": None,
                    "Nguồn giá": src,
                    "Trạng thái": note or "Chưa có giá",
                }
            )
        else:
            rows.append(
                {
                    "Mã": sym,
                    "Giá hiện tại": round(float(price), 2),
                    "Nguồn giá": src,
                    "Trạng thái": note or "Sẵn sàng",
                }
            )

    df = pd.DataFrame(rows)
    if not df.empty:
        ok = df["Giá hiện tại"].notna() & (df["Giá hiện tại"] > 0)
        df = df.assign(__ready=ok.astype(int)).sort_values(["__ready", "Mã"], ascending=[False, True]).drop(columns=["__ready"])
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return df, ts
