from __future__ import annotations

import os
from concurrent.futures import as_completed
from typing import Any

import streamlit as st

from core.streamlit_executor import streamlit_thread_pool_executor

from core.ai_logic import generate_strategic_report
from core.background_jobs import run_background_cycle
from scrapers.financial_data import fetch_financial_snapshot
from scrapers.portal import fetch_financial_indicators, fetch_ohlcv_history


def _snapshot_impl(ticker: str):
    """No @st.cache_data so it can run in ThreadPoolExecutor."""
    return fetch_financial_snapshot(ticker)


@st.cache_data(ttl=300)
def load_snapshot_cached(ticker: str):
    return _snapshot_impl(ticker)


def _ohlcv_impl(ticker: str):
    # Keep configurable history depth: lower on low-memory machines, higher for deep chart workflows.
    try:
        sessions = max(260, int(os.environ.get("II_OHLCV_RUNTIME_SESSIONS", "1300")))
    except ValueError:
        sessions = 1300
    return fetch_ohlcv_history(ticker, sessions=sessions)


@st.cache_data(ttl=300)
def load_ohlcv_cached(ticker: str):
    return _ohlcv_impl(ticker)


def _strategic_report_impl(
    ticker: str,
    snapshot: dict[str, Any],
    profile: str,
    total_capital_vnd: float,
    *,
    quick_mode: bool = True,
    llm_live: bool = True,
    task_mode: str | None = None,
):
    sessions = 60 if quick_mode else 80
    news_limit = 5 if quick_mode else 10
    enable_llm = bool(llm_live) and (not quick_mode)
    return generate_strategic_report(
        ticker,
        snapshot,
        profile=profile,
        total_capital_vnd=float(total_capital_vnd),
        sessions=sessions,
        news_limit=news_limit,
        enable_llm=enable_llm,
        fast_mode=quick_mode,
        task_mode=task_mode,
    )


@st.cache_data(ttl=240)
def load_strategic_report_cached(
    ticker: str,
    snapshot: dict[str, Any],
    profile: str,
    total_capital_vnd: float,
    *,
    quick_mode: bool = True,
    llm_live: bool = True,
    task_mode: str | None = None,
):
    return _strategic_report_impl(
        ticker,
        snapshot,
        profile,
        total_capital_vnd,
        quick_mode=quick_mode,
        llm_live=llm_live,
        task_mode=task_mode,
    )


def prewarm_watchlist_cache(symbols: list[str], profile: str, total_capital_vnd: float, quick_mode: bool) -> None:
    syms = [s for s in symbols if s][: min(8, len(symbols))]
    if not syms:
        return

    def _warm(sym: str) -> None:
        snap = _snapshot_impl(sym)
        if snap is None:
            return
        try:
            fetch_financial_indicators(sym, fast_mode=False)
        except Exception:
            pass
        try:
            _strategic_report_impl(sym, snap, profile, total_capital_vnd, quick_mode=quick_mode)
        except Exception:
            return

    max_workers = min(4, max(2, len(syms)))
    with streamlit_thread_pool_executor(max_workers=max_workers) as ex:
        futs = [ex.submit(_warm, s) for s in syms]
        for fut in as_completed(futs):
            try:
                fut.result()
            except Exception:
                pass


def run_bg_warm_job(
    watchlist: list[str],
    universe_limit: int,
    queue_jobs: int = 10,
    warm_financial_live: bool = False,
) -> dict[str, Any]:
    return run_background_cycle(
        universe_limit=max(0, int(universe_limit)),
        watchlist=watchlist[:12],
        queue_jobs=max(1, int(queue_jobs)),
        warm_financial_live=bool(warm_financial_live),
    )
