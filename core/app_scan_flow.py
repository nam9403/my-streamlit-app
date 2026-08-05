"""
Scan flow orchestration utilities.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import date
from time import time
from typing import Any

import pandas as pd
import streamlit as st

from core.liquid_universe import resolve_scan_universe
from core.universe_rotation import universe_auto_rotate_enabled


def _format_cache_age(age_sec: float) -> str:
    sec = max(0, int(age_sec))
    if sec < 60:
        return f"{sec}s"
    minutes, seconds = divmod(sec, 60)
    return f"{minutes}m {seconds}s"


def run_scan_flow(
    *,
    run_scan: bool,
    universe_limit: int,
    plan: dict[str, Any],
    plan_label: str,
    subtype_labels: list[str],
    subtype_label_to_id: dict[str, str],
    user_id: str,
    plan_id: str,
    profile: str,
    total_capital_vnd: float,
    min_avg_volume_20: float,
    list_universe_symbols: Callable[..., list[str]],
    universe_subtype_map: Callable[[], dict[str, str]],
    can_use_feature: Callable[..., tuple[bool, str]],
    log_event: Callable[..., Any],
    scan_potential_stocks: Callable[..., pd.DataFrame],
    build_portfolio_options: Callable[..., dict[str, Any]],
) -> None:
    if not run_scan:
        return

    capped_limit = min(universe_limit, int(plan["scan_limit"]))
    try:
        from scrapers.vn_listing import list_tradable_vn_symbols

        full = list(list_tradable_vn_symbols(use_api=False) or [])
    except Exception:
        full = []
    if not full:
        full = list_universe_symbols(limit=None)
    rd = date.today().toordinal()
    universe_all, uni_meta = resolve_scan_universe(
        capped_limit,
        full_listing=full,
        rotation_day=rd,
        rotation_key="scan_flow",
    )
    off = int(uni_meta.get("offset") or 0)
    if universe_auto_rotate_enabled() and int(uni_meta.get("pool_size") or 0) > capped_limit:
        mode_lbl = str(uni_meta.get("mode") or "liquid")
        st.caption(
            f"Universe **{mode_lbl}** (theo ngày): cửa sổ **{len(universe_all)}** mã "
            f"(offset {off}, pool {uni_meta.get('pool_size')})."
        )
    if capped_limit < universe_limit:
        st.info(f"Gói {plan_label} giới hạn quét {capped_limit} mã. Nâng cấp gói để quét nhiều hơn.")
    selected_subtype_ids = {subtype_label_to_id[x] for x in subtype_labels}
    if selected_subtype_ids:
        s_map = universe_subtype_map()
        universe = tuple([s for s in universe_all if s_map.get(s, "other") in selected_subtype_ids])
    else:
        universe = tuple(universe_all)

    try:
        cache_ttl_sec = max(120, int(os.environ.get("II_SCAN_CACHE_TTL_SEC", "180")))
    except ValueError:
        cache_ttl_sec = 180
    cache_key = (
        tuple(universe),
        str(profile or ""),
        float(min_avg_volume_20),
        float(total_capital_vnd),
        str(plan_id or ""),
    )
    now_ts = time()
    cached_key = st.session_state.get("scan_candidates_cache_key")
    cached_ts = float(st.session_state.get("scan_candidates_cache_ts") or 0.0)
    cached_candidates = st.session_state.get("scan_candidates_cache")
    cached_portfolios = st.session_state.get("scan_portfolios_cache")
    cached_relaxed = bool(st.session_state.get("scan_relaxed_used_cache") or False)
    can_use_cache = (
        cached_key == cache_key
        and (now_ts - cached_ts) <= cache_ttl_sec
        and isinstance(cached_candidates, pd.DataFrame)
        and isinstance(cached_portfolios, (list, dict))
    )
    cache_age_sec = max(0.0, now_ts - cached_ts) if cached_ts > 0 else 0.0
    if can_use_cache:
        assert isinstance(cached_candidates, pd.DataFrame)
        st.session_state["scan_candidates"] = cached_candidates.copy()
        st.session_state["scan_portfolios"] = cached_portfolios
        st.session_state["scan_profile"] = profile
        st.session_state["scan_capital"] = float(total_capital_vnd)
        st.session_state["scan_relaxed_used"] = cached_relaxed
        st.session_state["scan_filter_min_vol"] = float(min_avg_volume_20)
        st.caption(
            f"Cache Scan: **HIT** | tuổi cache: **{_format_cache_age(cache_age_sec)}** | TTL: **{cache_ttl_sec}s**"
        )
        return

    # PostgreSQL durable path: enqueue only — worker executes scan off Streamlit.
    try:
        from core import pg_analysis_jobs as pgj, state_manager as sm
        from core.ui_bg_analysis import read_analysis_job_status, try_consume_analysis_job
        from core.ui_day_cache import cache_key_hash

        use_pg_scan = bool(pgj.scan_pg_jobs_enabled())
    except Exception:
        use_pg_scan = False

    if use_pg_scan:
        jid = cache_key_hash(
            "deep_scan_pg",
            (
                str(user_id or ""),
                tuple(universe),
                str(profile or ""),
                float(min_avg_volume_20),
                float(total_capital_vnd),
                str(plan_id or ""),
            ),
        )
        bundle = try_consume_analysis_job(jid)
        if isinstance(bundle, dict) and isinstance(bundle.get("candidates"), pd.DataFrame):
            candidates = bundle["candidates"]
            portfolios = bundle.get("portfolios")
            relaxed_used = bool(bundle.get("relaxed_used"))
            sm.set_scan_pg_poll_jid(None)
            st.session_state["scan_candidates"] = candidates
            st.session_state["scan_portfolios"] = portfolios if portfolios is not None else build_portfolio_options(
                candidates, total_capital_vnd
            )
            st.session_state["scan_profile"] = profile
            st.session_state["scan_capital"] = float(total_capital_vnd)
            st.session_state["scan_relaxed_used"] = relaxed_used
            st.session_state["scan_filter_min_vol"] = float(min_avg_volume_20)
            st.session_state["scan_candidates_cache_key"] = cache_key
            st.session_state["scan_candidates_cache_ts"] = now_ts
            st.session_state["scan_candidates_cache"] = candidates.copy()
            st.session_state["scan_portfolios_cache"] = st.session_state["scan_portfolios"]
            st.session_state["scan_relaxed_used_cache"] = relaxed_used
            st.caption("Cache Scan: **PG_WORKER** | Deep Scan hoàn tất trên worker Postgres.")
            return

        stt = read_analysis_job_status(jid)
        if stt and stt.get("state") == "error":
            sm.set_scan_pg_poll_jid(None)
            try:
                pgj.delete_job_if_failed(jid)
            except Exception:
                pass
            st.warning(
                "Deep Scan (Postgres worker) lỗi — lần này sẽ không chạy nặng trong Streamlit. "
                f"{str(stt.get('error') or '')[:300]}"
            )
            return
        if stt and stt.get("state") in ("pending", "running"):
            sm.set_scan_pg_poll_jid(jid)
            sm.render_job_progress_placeholder(
                f"Deep Scan **{len(universe)} mã** đang chạy trên worker Postgres (không chặn UI)."
            )
            return

        scan_allowed = True
        if not universe:
            st.warning("Không có mã nào khớp bộ lọc tiểu ngành đã chọn.")
            return
        ok_scan, msg_scan = can_use_feature(user_id, "scan", len(universe), plan_id=plan_id)
        if not ok_scan:
            st.error(msg_scan)
            return
        log_event(user_id, "scan_started", {"symbols": len(universe), "profile": profile, "mode": "pg_worker"})
        pgj.enqueue_deep_scan(
            jid,
            {
                "universe": list(universe),
                "profile": profile,
                "min_avg_volume_20": float(min_avg_volume_20),
                "total_capital_vnd": float(total_capital_vnd),
                "relax_on_empty": True,
                "user_id": user_id,
                "plan_id": plan_id,
            },
        )
        sm.set_scan_pg_poll_jid(jid)
        sm.render_job_progress_placeholder(
            f"Đã xếp hàng Deep Scan **{len(universe)} mã**. Chạy `python worker.py` nếu chưa bật worker."
        )
        return

    scan_allowed = True
    if not universe:
        st.warning("Không có mã nào khớp bộ lọc tiểu ngành đã chọn.")
        candidates = pd.DataFrame()
        scan_allowed = False
    else:
        ok_scan, msg_scan = can_use_feature(user_id, "scan", len(universe), plan_id=plan_id)
        if not ok_scan:
            st.error(msg_scan)
            candidates = pd.DataFrame()
            scan_allowed = False
        else:
            log_event(user_id, "scan_started", {"symbols": len(universe), "profile": profile})
            with st.spinner(f"Đang quét {len(universe)} mã..."):
                candidates = scan_potential_stocks(universe, profile, min_avg_volume_20)
            deep_n = int(st.session_state.get("scan_deep_universe_count") or len(universe))
            st.caption(f"Scan 2 pha: tiền lọc **{len(universe)}** mã -> quét sâu **{deep_n}** mã.")
    relaxed_used = False
    if scan_allowed and candidates.empty and min_avg_volume_20 > 0:
        with st.spinner("Lần quét đầu rỗng, đang thử lại với bộ lọc thanh khoản nới lỏng..."):
            candidates = scan_potential_stocks(universe, profile, 0.0)
        relaxed_used = True
    # Opt-in re-rank theo dòng tiền lớn từ journal (II_SCANNER_FLOW_RERANK_ENABLED=1).
    # Đọc local JSONL ⇒ không thêm network call; default OFF ⇒ giữ behavior cũ.
    try:
        from core.scanner_flow_integration import (
            is_scanner_rerank_enabled,
            rerank_candidates_with_flow_journal,
        )

        if scan_allowed and is_scanner_rerank_enabled() and isinstance(candidates, pd.DataFrame) and not candidates.empty:
            reranked, rerank_meta = rerank_candidates_with_flow_journal(candidates)
            if rerank_meta.get("reason") == "applied" and int(rerank_meta.get("applied_count") or 0) > 0:
                candidates = reranked
                st.caption(
                    "Flow re-rank: áp dụng cho **{applied}** mã (lookback {hours}h, weight {weight:.2f})."
                    .format(
                        applied=int(rerank_meta.get("applied_count") or 0),
                        hours=int(rerank_meta.get("lookback_hours") or 0),
                        weight=float(rerank_meta.get("weight") or 0.0),
                    )
                )
    except Exception:  # noqa: BLE001
        # Phòng hờ: re-rank không bao giờ được phép phá scan flow chính.
        pass
    st.session_state["scan_candidates"] = candidates
    st.session_state["scan_portfolios"] = build_portfolio_options(candidates, total_capital_vnd)
    st.session_state["scan_profile"] = profile
    st.session_state["scan_capital"] = float(total_capital_vnd)
    st.session_state["scan_relaxed_used"] = relaxed_used
    st.session_state["scan_filter_min_vol"] = float(min_avg_volume_20)
    st.session_state["scan_candidates_cache_key"] = cache_key
    st.session_state["scan_candidates_cache_ts"] = now_ts
    st.session_state["scan_candidates_cache"] = candidates.copy()
    st.session_state["scan_portfolios_cache"] = st.session_state["scan_portfolios"]
    st.session_state["scan_relaxed_used_cache"] = relaxed_used
    st.caption(f"Cache Scan: **MISS** | tuổi cache: **0s** | TTL: **{cache_ttl_sec}s**")

