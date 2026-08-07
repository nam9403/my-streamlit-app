from __future__ import annotations

import os
import re
from typing import Any, Callable

import streamlit as st

from core.command_center_panel import render_command_center_panel
from core.runtime_flow_contracts import RuntimeFlowConfig


def _env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        val = default
    return max(lo, min(hi, val))


def _mode_defaults(mode: str) -> dict[str, int | bool]:
    m = str(mode or "balanced").strip().lower()
    if m == "smooth":
        return {
            "autopilot_limit": 15,
            "auto_bg_warm": False,
            "bg_interval_min": 12,
            "bg_universe_limit": 15,
            "scan_cache_ttl_sec": 300,
            "defer_autopilot": True,
        }
    if m == "deep":
        return {
            "autopilot_limit": 30,
            "auto_bg_warm": True,
            "bg_interval_min": 8,
            "bg_universe_limit": 30,
            "scan_cache_ttl_sec": 180,
            "defer_autopilot": False,
        }
    return {
        "autopilot_limit": 20,
        "auto_bg_warm": True,
        "bg_interval_min": 10,
        "bg_universe_limit": 20,
        "scan_cache_ttl_sec": 240,
        "defer_autopilot": True,
    }


def render_watchlist_controls(
    *,
    watchlist_default: list[str],
    auth_ready: bool,
    bg_universe_limit_default: int = 30,
    bg_interval_default_min: int = 8,
    extract_ticker: Callable[[str], str],
    tg_bot: str,
    tg_chat: str,
    webhook_url: str,
    email_to: str,
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    smtp_from: str,
    user_id: str,
    process_notification_queue: Callable[..., dict[str, int]],
    run_background_cycle: Callable[..., dict[str, Any]],
    dispatch_text_notifications: Callable[..., dict[str, int]],
    upsert_daily_cx_score: Callable[[str, int, str], None],
    get_recent_cx_scores: Callable[..., list[dict[str, Any]]],
    plan: dict[str, Any] | None = None,
) -> RuntimeFlowConfig:
    default_watch = str(st.session_state.get("onboarding_watch_seed") or ", ".join(watchlist_default))
    raw_watch = st.text_area("Watchlist", value=default_watch, height=80)
    watchlist = [x for x in re.split(r"[\s,;]+", raw_watch.upper().strip()) if re.fullmatch(r"[A-Z0-9]{2,6}", x)]
    picked = st.selectbox("Chọn mã từ watchlist", options=watchlist or watchlist_default, index=0)
    manual = st.text_input("Hoặc nhập mã bất kỳ", value=picked)
    ticker = extract_ticker(manual) or picked
    perf_mode_default = str(st.session_state.get("runtime_perf_mode") or os.environ.get("II_PERF_MODE_DEFAULT", "smooth")).strip().lower()
    if perf_mode_default not in ("smooth", "balanced", "deep"):
        perf_mode_default = "smooth"
    perf_mode = st.selectbox(
        "⚙️ Chế độ vận hành 6S",
        options=["smooth", "balanced", "deep"],
        index=["smooth", "balanced", "deep"].index(perf_mode_default),
        format_func=lambda x: {
            "smooth": "Smooth (ưu tiên mượt/nhanh)",
            "balanced": "Balanced (cân bằng tốc độ/chất lượng)",
            "deep": "Deep (ưu tiên phân tích sâu)",
        }[x],
        help="6S: loại bỏ bước dư thừa theo ngữ cảnh, chuẩn hóa luồng chạy nhưng không cắt tính năng.",
    )
    st.markdown("---")
    st.markdown("**Gợi ý chọn mode 6S**")
    with st.container():
        st.markdown(
            "- **Smooth**: dùng hằng ngày trên máy yếu/VPS nhỏ, ưu tiên mượt và phản hồi nhanh.\n"
            "- **Balanced**: dùng mặc định cho vận hành ổn định, cân bằng tốc độ và độ sâu.\n"
            "- **Deep**: dùng khi cần đào sâu phân tích hoặc kiểm tra kỹ trước quyết định lớn."
        )
    mode_cfg = _mode_defaults(perf_mode)
    st.session_state["runtime_perf_mode"] = perf_mode
    prev_mode = str(st.session_state.get("_runtime_perf_mode_prev") or perf_mode)
    if prev_mode != perf_mode:
        # Reset deferred-autopilot decision when runtime mode changes so new mode applies immediately.
        st.session_state["autopilot_requested"] = False
    st.session_state["_runtime_perf_mode_prev"] = perf_mode
    os.environ["II_SCAN_CACHE_TTL_SEC"] = str(mode_cfg["scan_cache_ttl_sec"])
    st.session_state["defer_autopilot_runtime"] = bool(mode_cfg["defer_autopilot"])
    autopilot_mode = st.toggle(
        "🤖 Auto Pilot cơ hội",
        value=_env_bool("II_AUTOPILOT_MODE_DEFAULT", True),
        help="Mở app là có ngay danh sách cơ hội ưu tiên.",
    )
    profit_focus_mode = st.toggle(
        "💰 Profit Focus Mode",
        value=True,
        help="Chỉ hiện cơ hội đạt chuẩn xuống tiền (Gate + Output + RR).",
    )
    from core.app_onboarding_helpers import plan_autopilot_limit_cap

    plan_cap = plan_autopilot_limit_cap(plan, 80)
    slider_max = max(10, min(80, int(plan_cap)))
    default_ap = min(
        slider_max,
        _env_int("II_AUTOPILOT_LIMIT_DEFAULT", int(mode_cfg["autopilot_limit"]), 10, slider_max),
    )
    autopilot_limit = int(
        st.slider(
            "Số mã Auto Pilot quét",
            min_value=10,
            max_value=slider_max,
            value=default_ap,
            step=5,
            help=f"Giới hạn theo gói hiện tại: ≤{slider_max} (scan_limit).",
        )
    )
    autopilot_limit = plan_autopilot_limit_cap(plan, autopilot_limit)
    st.caption(f"Autopilot limit sau khi áp gói: **{autopilot_limit}** (max {slider_max}).")
    autopilot_refresh = st.button("♻️ Làm mới Auto Pilot", use_container_width=True)
    quick_mode = st.toggle(
        "⚡ Chế độ phản hồi nhanh",
        value=False,
        help="Bật khi cần tốc độ; tắt để phân tích sâu hơn (tin tức, ngữ cảnh và chất lượng giải thích tốt hơn).",
    )
    ultra_fast_mode = st.toggle(
        "🚀 Ultra Fast (cache-first)",
        value=True,
        help="Ưu tiên cache có kiểm soát tuổi dữ liệu để phản hồi gần như tức thời.",
    )
    if ultra_fast_mode:
        os.environ["II_OHLCV_DISK_FIRST"] = "1"
        os.environ.setdefault("II_OHLCV_DISK_MAX_AGE_SEC", "7200")
        os.environ.setdefault("II_PORTAL_LIVE_BUDGET_SEC", "6")
    st.caption("Mode: " + ("Ultra Fast (cache-first + budget)" if ultra_fast_mode else "Standard live-first"))
    auto_bg_warm = st.toggle(
        "♨️ Tự làm nóng cache nền",
        value=_env_bool("II_AUTO_BG_WARM_DEFAULT", bool(mode_cfg["auto_bg_warm"])),
        help="Tự chạy prefetch nhẹ theo chu kỳ để giảm thời gian chờ ở các lần phân tích sau.",
    )
    bg_interval_min = int(
        st.slider(
            "Chu kỳ làm nóng nền (phút)",
            min_value=3,
            max_value=30,
            value=_env_int("II_BG_INTERVAL_DEFAULT_MIN", int(mode_cfg["bg_interval_min"]), 3, 30),
            step=1,
        )
    )
    bg_universe_limit = int(
        st.slider(
            "Số mã nền prefetch",
            min_value=10,
            max_value=80,
            value=_env_int("II_BG_UNIVERSE_LIMIT_DEFAULT", int(mode_cfg["bg_universe_limit"]), 10, 80),
            step=5,
        )
    )
    prewarm_now = st.button("🔥 Làm nóng dữ liệu watchlist", use_container_width=True)
    prewarm_now_async = st.button("♨️ Warm now (non-blocking)", use_container_width=True)
    st.caption("Gợi ý chạy nền: `python scripts/prefetch_cache.py --watchlist FPT,HPG,VNM --universe-limit 30`")
    run_analysis = st.button("🚀 Phân tích ngay", use_container_width=True, type="primary")

    cmd_flags = render_command_center_panel(
        ticker=ticker,
        watchlist=watchlist,
        auth_ready=auth_ready,
        bg_universe_limit=bg_universe_limit,
        tg_bot=tg_bot,
        tg_chat=tg_chat,
        webhook_url=webhook_url,
        email_to=email_to,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        user_id=user_id,
        watchlist_default=watchlist_default,
        process_notification_queue=process_notification_queue,
        run_background_cycle=run_background_cycle,
        dispatch_text_notifications=dispatch_text_notifications,
        upsert_daily_cx_score=upsert_daily_cx_score,
        get_recent_cx_scores=get_recent_cx_scores,
    )
    run_analysis = bool(run_analysis or cmd_flags.get("quick_run_analysis"))
    autopilot_refresh = bool(autopilot_refresh or cmd_flags.get("quick_autopilot_refresh"))
    prewarm_now_async = bool(prewarm_now_async or cmd_flags.get("quick_warm_async"))

    return RuntimeFlowConfig(
        watchlist=watchlist,
        ticker=ticker,
        autopilot_mode=autopilot_mode,
        profit_focus_mode=profit_focus_mode,
        autopilot_limit=autopilot_limit,
        autopilot_refresh=autopilot_refresh,
        quick_mode=quick_mode,
        auto_bg_warm=auto_bg_warm,
        bg_interval_min=bg_interval_min,
        bg_universe_limit=bg_universe_limit,
        prewarm_now=prewarm_now,
        prewarm_now_async=prewarm_now_async,
        run_analysis=run_analysis,
    )
