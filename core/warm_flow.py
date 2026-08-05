from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import streamlit as st

from core.runtime_flow_contracts import RuntimeFlowConfig


def handle_warm_flow(
    *,
    runtime_cfg: RuntimeFlowConfig,
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    prewarm_watchlist_cache: Callable[..., None],
    run_bg_warm_job: Callable[..., dict[str, Any]],
    run_background_cycle: Callable[..., dict[str, Any]],
) -> None:
    symbols = runtime_cfg.symbols(watchlist_default)

    if runtime_cfg.prewarm_now:
        with st.spinner("Đang làm nóng cache dữ liệu cho watchlist..."):
            prewarm_watchlist_cache(
                symbols,
                profile,
                float(total_capital_vnd),
                bool(runtime_cfg.quick_mode),
            )
        st.success("Đã làm nóng xong cache. Lần phân tích kế tiếp sẽ nhanh hơn.")

    if runtime_cfg.prewarm_now_async and not bool(st.session_state.get("bg_warm_job_running", False)):
        ex = st.session_state.get("bg_warm_executor")
        if ex is None:
            ex = ThreadPoolExecutor(max_workers=1)
            st.session_state["bg_warm_executor"] = ex
        fut = ex.submit(
            run_bg_warm_job,
            symbols,
            int(runtime_cfg.bg_universe_limit),
            10,
            False,
        )
        st.session_state["bg_warm_future"] = fut
        st.session_state["bg_warm_job_running"] = True
        st.session_state["bg_warm_job_status"] = "running"
        st.info("Đã khởi chạy warm nền. Bạn có thể tiếp tục thao tác, kết quả sẽ cập nhật tự động.")

    fut = st.session_state.get("bg_warm_future")
    if fut is not None and bool(st.session_state.get("bg_warm_job_running", False)):
        if fut.done():
            st.session_state["bg_warm_job_running"] = False
            try:
                stat = fut.result()
                st.session_state["bg_warm_last_stat"] = stat
                st.session_state["bg_warm_job_status"] = "done"
                st.session_state["bg_warm_last_ts"] = time.time()
            except Exception as e:
                st.session_state["bg_warm_job_status"] = "error"
                st.session_state["bg_warm_job_error"] = str(e)
                st.session_state["bg_warm_last_ts"] = time.time()
        else:
            st.caption("Warm nền đang chạy...")

    if runtime_cfg.auto_bg_warm:
        now_ts = time.time()
        interval_s = max(180, int(runtime_cfg.bg_interval_min) * 60)
        # Dùng khóa riêng (không trộn với bg_warm_last_ts của Warm now async) để throttle chu kỳ tự động.
        last_auto_ts = float(st.session_state.get("auto_bg_cycle_last_ts") or 0.0)

        fut_auto = st.session_state.get("auto_bg_cycle_future")
        if fut_auto is not None and bool(st.session_state.get("auto_bg_cycle_running", False)):
            if fut_auto.done():
                st.session_state["auto_bg_cycle_running"] = False
                st.session_state["auto_bg_cycle_future"] = None
                try:
                    bj = fut_auto.result()
                    st.session_state["bg_warm_last_stat"] = bj
                except Exception:
                    st.session_state["bg_warm_last_stat"] = {"prefetch": {}, "queue": {}}

        if (
            now_ts - last_auto_ts >= interval_s
            and not bool(st.session_state.get("auto_bg_cycle_running", False))
        ):
            ex = st.session_state.get("auto_bg_cycle_executor")
            if ex is None:
                ex = ThreadPoolExecutor(max_workers=1)
                st.session_state["auto_bg_cycle_executor"] = ex

            def _run_auto_cycle() -> dict[str, Any]:
                return run_background_cycle(
                    universe_limit=int(runtime_cfg.bg_universe_limit),
                    watchlist=symbols[:12],
                    queue_jobs=10,
                    warm_financial_live=False,
                )

            st.session_state["auto_bg_cycle_future"] = ex.submit(_run_auto_cycle)
            st.session_state["auto_bg_cycle_running"] = True
            st.session_state["auto_bg_cycle_last_ts"] = now_ts
        elif bool(st.session_state.get("auto_bg_cycle_running", False)):
            st.caption("⏳ Làm nóng nền tự động đang chạy (không chặn giao diện)...")

        last_info = st.session_state.get("bg_warm_last_stat") or {}
        pre = last_info.get("prefetch") or {}
        if pre:
            st.caption(
                f"Auto warm: ok={pre.get('ok', 0)}/{pre.get('total', 0)} "
                f"(chu kỳ {int(runtime_cfg.bg_interval_min)} phút, universe {int(runtime_cfg.bg_universe_limit)} mã)."
            )
    status = str(st.session_state.get("bg_warm_job_status") or "")
    if status == "done":
        st.caption("Warm now (non-blocking): hoàn tất.")
    elif status == "error":
        st.warning(f"Warm now (non-blocking) lỗi: {st.session_state.get('bg_warm_job_error')}")


def schedule_focus_prefetch(
    *,
    runtime_cfg: RuntimeFlowConfig,
    watchlist_default: list[str],
    profile: str,
    total_capital_vnd: float,
    prewarm_watchlist_cache: Callable[..., None],
) -> None:
    """
    Lightweight prefetch for currently focused symbols.
    Runs asynchronously and throttled to keep UI smooth.
    """
    check_fut = st.session_state.get("focus_prefetch_future")
    if check_fut is not None and bool(st.session_state.get("focus_prefetch_running", False)):
        if check_fut.done():
            st.session_state["focus_prefetch_running"] = False
            try:
                st.session_state["focus_prefetch_last_stat"] = check_fut.result()
            except Exception:
                st.session_state["focus_prefetch_last_stat"] = {"ok": 0, "symbols": []}

    base_symbols = runtime_cfg.symbols(watchlist_default)
    focus_symbols: list[str] = []
    if runtime_cfg.ticker:
        focus_symbols.append(str(runtime_cfg.ticker).strip().upper())
    for sym in base_symbols:
        s = str(sym or "").strip().upper()
        if s and s not in focus_symbols:
            focus_symbols.append(s)
        if len(focus_symbols) >= 4:
            break
    if not focus_symbols:
        return

    interval_s = max(30.0, float(st.session_state.get("focus_prefetch_interval_sec") or 75.0))
    now_ts = time.time()
    last_ts = float(st.session_state.get("focus_prefetch_last_ts") or 0.0)
    if (now_ts - last_ts) < interval_s:
        return
    if bool(st.session_state.get("focus_prefetch_running", False)):
        return

    ex = st.session_state.get("focus_prefetch_executor")
    if ex is None:
        ex = ThreadPoolExecutor(max_workers=1)
        st.session_state["focus_prefetch_executor"] = ex

    def _run_prefetch() -> dict[str, Any]:
        prewarm_watchlist_cache(
            focus_symbols,
            profile,
            float(total_capital_vnd),
            True,  # keep lightweight: quick mode on
        )
        return {"symbols": focus_symbols, "ok": len(focus_symbols)}

    fut = ex.submit(_run_prefetch)
    st.session_state["focus_prefetch_future"] = fut
    st.session_state["focus_prefetch_running"] = True
    st.session_state["focus_prefetch_last_ts"] = now_ts
