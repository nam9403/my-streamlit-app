"""
Auto Pilot and Profit Focus panel orchestration.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from time import time
from typing import Any

import pandas as pd
import streamlit as st


def _clear_if_available(func: Any) -> None:
    clear_method = getattr(func, "clear", None)
    if callable(clear_method):
        clear_method()

def _format_cache_age(age_sec: float) -> str:
    sec = max(0, int(age_sec))
    if sec < 60:
        return f"{sec}s"
    minutes, seconds = divmod(sec, 60)
    return f"{minutes}m {seconds}s"


def _build_thesis_input(
    *,
    symbol: str,
    profile: str,
    total_capital_vnd: float,
    quick_mode: bool,
    llm_live: bool,
) -> dict[str, Any]:
    from core.analysis_runtime_service import load_snapshot_cached, load_strategic_report_cached
    from core.news_macro_service import detect_story_catalysts, get_combined_story_score, get_micro_bundle, score_catalyst

    sym = str(symbol or "").strip().upper()
    snap = load_snapshot_cached(sym) or {}
    rep = load_strategic_report_cached(
        sym,
        snap,
        profile,
        float(total_capital_vnd),
        quick_mode=bool(quick_mode),
        llm_live=bool(llm_live),
    ) or {}
    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    fin = rep.get("financials") if isinstance(rep.get("financials"), dict) else {}
    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    risk = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    catalyst = 0.0
    story_score = 0.0
    story = {}
    news_titles: list[str] = []
    try:
        catalyst = float(score_catalyst(sym, allow_network=False))
    except Exception:
        catalyst = 0.0
    try:
        story = detect_story_catalysts(sym)
        story_score = float(get_combined_story_score(sym))
    except Exception:
        story = {}
        story_score = 0.0
    try:
        micro = get_micro_bundle(sym, allow_network=False, news_limit=8)
        news_titles = [str(x.get("title") or "") for x in list(micro.get("news") or [])[:8]]
    except Exception:
        news_titles = []

    return {
        "ticker": sym,
        "price": val.get("price") or snap.get("price"),
        "mos_pct": val.get("margin_of_safety_composite_pct"),
        "f_score": val.get("piotroski_score"),
        "current_ratio": val.get("current_ratio") or fin.get("current_ratio") or snap.get("current_ratio"),
        "operating_cash_flow": fin.get("operating_cash_flow") or snap.get("operating_cash_flow"),
        "net_income": fin.get("net_income") or snap.get("net_income"),
        "revenue_growth_yoy": fin.get("revenue_growth_yoy"),
        "profit_growth_yoy": fin.get("profit_growth_yoy"),
        "legend": val.get("instant_conclusion"),
        "decision_readiness": rep.get("decision_readiness"),
        "final_action": rep.get("final_action"),
        "catalyst_score": catalyst,
        "combined_story_score": story_score,
        "story_catalysts": story,
        "news_titles": news_titles,
        "phase": phase.get("phase"),
        "phase_reason": phase.get("reason"),
        "risk_plan": {
            "entry_price": risk.get("entry_price"),
            "stop_loss_price": risk.get("stop_loss_price"),
            "take_profit_price": risk.get("take_profit_price"),
        },
        "missing_items": rep.get("missing_items"),
    }


def render_autopilot_panel(
    *,
    autopilot_mode: bool,
    autopilot_refresh: bool,
    profile: str,
    autopilot_limit: int,
    total_capital_vnd: float,
    effective_quick_mode: bool,
    plan: dict[str, Any],
    plan_id: str,
    user_id: str,
    ticker: str,
    run_analysis: bool,
    profit_focus_mode: bool,
    load_autopilot_board: Callable[..., pd.DataFrame],
    build_autopilot_simple_view: Callable[..., pd.DataFrame],
    build_profit_focus_board: Callable[..., pd.DataFrame],
    simple_view_for_plan: Callable[..., pd.DataFrame],
    can_auto_execute_symbol: Callable[..., tuple[bool, str]],
    add_decision: Callable[..., tuple[bool, str]],
    can_use_feature: Callable[..., tuple[bool, str]],
    add_alert: Callable[..., Any],
    log_event: Callable[..., Any],
) -> tuple[str, bool]:
    if not autopilot_mode:
        return ticker, run_analysis

    st.markdown("### 🤖 Auto Pilot - Cơ hội ưu tiên hôm nay")
    try:
        from core.app_onboarding_helpers import plan_packaging_caption

        st.caption(plan_packaging_caption(plan_id, plan))
    except Exception:
        pass
    force_live = st.toggle(
        "Ép quét live (bỏ board đêm)",
        value=bool(st.session_state.get("autopilot_force_live", False)),
        key="autopilot_force_live_toggle",
        help="Tắt: Top 10 từ quét đêm (~400 mã). Bật: quét cửa sổ rotation trong ngày.",
    )
    st.session_state["autopilot_force_live"] = bool(force_live)

    if autopilot_refresh:
        _clear_if_available(load_autopilot_board)
        _clear_if_available(build_autopilot_simple_view)
        _clear_if_available(build_profit_focus_board)
    cache_key = (str(profile or ""), int(autopilot_limit or 30), 300_000.0, bool(force_live))
    cache_ttl_sec = 180
    now_ts = time()
    cached_key = st.session_state.get("autopilot_df_cache_key")
    cached_ts = float(st.session_state.get("autopilot_df_cache_ts") or 0.0)
    cached_df = st.session_state.get("autopilot_df")
    can_use_cached = (
        (not autopilot_refresh)
        and cached_key == cache_key
        and (now_ts - cached_ts) <= cache_ttl_sec
        and isinstance(cached_df, pd.DataFrame)
        and (not cached_df.empty)
    )
    cache_age_sec = max(0.0, now_ts - cached_ts) if cached_ts > 0 else 0.0
    cache_status = "HIT" if can_use_cached else "MISS"
    if can_use_cached:
        assert isinstance(cached_df, pd.DataFrame)
        autopilot_df = cached_df.copy()
    else:
        # Prefer Postgres worker when enabled — no heavy scan inside Streamlit.
        use_pg = False
        try:
            from core import pg_analysis_jobs as pgj, state_manager as sm
            from core.ui_bg_analysis import read_analysis_job_status, try_consume_analysis_job
            from core.ui_day_cache import cache_key_hash

            use_pg = bool(pgj.autopilot_pg_jobs_enabled()) and (not force_live)
        except Exception:
            use_pg = False

        if use_pg:
            jid = cache_key_hash(
                "autopilot_pg",
                (str(user_id or ""), str(profile or ""), int(autopilot_limit or 30), 300_000.0, int(date.today().toordinal())),
            )
            bundle = try_consume_analysis_job(jid)
            if isinstance(bundle, dict) and isinstance(bundle.get("autopilot_df"), pd.DataFrame):
                autopilot_df = bundle["autopilot_df"].copy()
                sm.set_autopilot_pg_poll_jid(None)
                st.session_state["autopilot_df_cache_key"] = cache_key
                st.session_state["autopilot_df_cache_ts"] = now_ts
                cache_age_sec = 0.0
                cache_status = "PG_WORKER"
            else:
                stt = read_analysis_job_status(jid)
                if stt and stt.get("state") in ("pending", "running"):
                    sm.set_autopilot_pg_poll_jid(jid)
                    sm.render_job_progress_placeholder("Auto Pilot đang chạy trên worker Postgres…")
                    return ticker, run_analysis
                if stt and stt.get("state") == "error":
                    sm.set_autopilot_pg_poll_jid(None)
                    try:
                        pgj.delete_job_if_failed(jid)
                    except Exception:
                        pass
                    st.warning(f"Auto Pilot worker lỗi: {str(stt.get('error') or '')[:300]}")
                    return ticker, run_analysis
                pgj.enqueue_autopilot_board(
                    jid,
                    {
                        "profile": profile,
                        "universe_limit": int(autopilot_limit or 30),
                        "min_avg_volume_20": 300_000.0,
                        "rotation_day": int(date.today().toordinal()),
                        "user_id": user_id,
                    },
                )
                sm.set_autopilot_pg_poll_jid(jid)
                sm.render_job_progress_placeholder(
                    "Đã xếp hàng Auto Pilot trên Postgres. Chạy `python worker.py` nếu chưa bật worker."
                )
                return ticker, run_analysis
        else:
            autopilot_df = load_autopilot_board(
                profile,
                universe_limit=autopilot_limit,
                min_avg_volume_20=300_000.0,
                _rotation_day=date.today().toordinal(),
                _force_live=bool(force_live),
            )
            st.session_state["autopilot_df_cache_key"] = cache_key
            st.session_state["autopilot_df_cache_ts"] = now_ts
            cache_age_sec = 0.0
    st.session_state["autopilot_df"] = autopilot_df
    try:
        from core.scanner_service import get_last_autopilot_universe_meta

        uni_meta = get_last_autopilot_universe_meta()
    except Exception:
        uni_meta = {}
    if uni_meta:
        mode = str(uni_meta.get("mode") or "rotate_full")
        pool = int(uni_meta.get("pool_size") or uni_meta.get("listing_total") or 0)
        w0 = int(uni_meta.get("window_start") or 1)
        w1 = int(uni_meta.get("window_end") or int(autopilot_limit or 30))
        n = int(uni_meta.get("symbols_count") or 0)
        if mode == "nightly_board":
            cov = float(uni_meta.get("coverage_pct") or 0.0)
            ready = int(uni_meta.get("ready_count") or 0)
            liq = int(uni_meta.get("liquidity_filtered_count") or 0)
            data_err = int(uni_meta.get("data_error_count") or 0)
            pre_skip = int(uni_meta.get("prefilter_skipped_count") or 0)
            ready_rate = float(uni_meta.get("ready_rate_pct") or 0.0)
            u_mode = str(uni_meta.get("universe_mode") or "dynamic_liquid")
            board_title = str(uni_meta.get("board_title_vi") or "Top 10")
            age = uni_meta.get("age_hours")
            age_txt = f"{float(age):.1f}h trước" if age is not None else str(uni_meta.get("updated_at") or "—")
            pr = uni_meta.get("price_refresh") or {}
            st.caption(
                f"Universe: **quét đêm ({u_mode})** — **{board_title}** từ **{n}/{pool}** mã đã quét "
                f"(coverage **{cov:.0f}%**, sẵn sàng **{ready}** ~**{ready_rate:.0f}%**, "
                f"lọc thanh khoản **{liq}**, lỗi dữ liệu **{data_err}**"
                + (f", bỏ qua trước quét **{pre_skip}**" if pre_skip else "")
                + f", cập nhật **{age_txt}**"
                + (
                    f", làm mới giá **{int(pr.get('refreshed') or 0)}/{int(pr.get('attempted') or 0)}**"
                    if pr
                    else ""
                )
                + "). "
                "Lọc thanh khoản = mã illiquid (không phải lỗi hệ thống). "
                "Mã CFO âm / NO-GO bị hạ hạng hoặc loại khỏi Top khuyên mua. "
                f"Không phải cửa sổ rotation {int(autopilot_limit or 30)} mã trong ngày."
            )
        elif mode == "rotate_full":
            st.caption(
                f"Universe: **toàn thị trường VN** (HOSE+HNX+UPCOM) — "
                f"cửa sổ hôm nay **{w0}–{w1}** / **{pool}** mã "
                f"(quét {n} mã, xoay tuần tự mỗi ngày để phủ dần full listing)."
            )
        elif mode == "vn30":
            st.caption(f"Universe: **VN30 only** — đang quét **{n}** mã.")
        else:
            st.caption(
                f"Universe: **{mode}** — cửa sổ **{w0}–{w1}** / pool **{pool}** "
                f"(quét {n} mã)."
            )
    st.caption(
        f"Cache Auto Pilot: **{cache_status}** | tuổi cache: "
        f"**{_format_cache_age(cache_age_sec)}** | TTL: **{int(cache_ttl_sec)}s**"
    )
    # P1: News/Macro bias (disk-only) + paper-trade hit-rate caption
    try:
        if not autopilot_df.empty and "Mã" in autopilot_df.columns:
            top_sym = str(autopilot_df.iloc[0].get("Mã") or "").upper()
            if top_sym:
                from core.news_macro_service import format_news_macro_bias_caption

                st.caption(format_news_macro_bias_caption(top_sym, allow_network=False))
            if "News/Macro Bias" in autopilot_df.columns:
                st.caption("Cột **News/Macro Bias** = điểm xúc tác disk-only (không HTTP lúc quét).")
    except Exception:
        pass
    try:
        from core.paper_trade_ledger import hitrate_report

        hr = hitrate_report(lookback_days=30)
        if int(hr.get("samples") or 0) > 0:
            st.caption(
                f"Paper-trade 30 ngày: hit-rate **{hr.get('hit_rate_pct')}%** "
                f"(n={hr.get('samples')}, avg **{hr.get('avg_realized_pct')}%**)."
            )
        hr_all = hitrate_report(lookback_days=365)
        if int(hr_all.get("samples") or 0) > 0:
            st.caption(
                f"Paper-trade ledger (365d): hit-rate **{hr_all.get('hit_rate_pct')}%** "
                f"(n={hr_all.get('samples')}, avg realized **{hr_all.get('avg_realized_pct')}%**, "
                f"đang mở **{hr_all.get('open_count')}**)."
            )
        elif int(hr_all.get("open_count") or 0) > 0:
            st.caption(f"Paper-trade ledger: đang mở **{hr_all.get('open_count')}** lệnh giả lập (chưa đủ mẫu đóng).")
    except Exception:
        pass
    if not autopilot_df.empty:
        try:
            top = autopilot_df.iloc[0]
            note = str(top.get("Ghi chú Legend") or "").strip()
            missing = str(top.get("Thiếu DL") or "").strip()
            if note and note != "—":
                st.caption(f"Top #1 — Legend vs action: {note}")
            if missing and missing != "—":
                st.caption(f"Top #1 — thiếu dữ liệu: **{missing}** (completeness gate).")
        except Exception:
            pass
    if autopilot_df.empty:
        st.caption("Auto Pilot chưa tìm thấy cơ hội đủ dữ liệu ở lần quét này.")
        return ticker, run_analysis

    st.session_state["autopilot_onboarding_seen"] = True
    try:
        from core.decision_action_gate import action_display_vi, normalize_action

        view_df = autopilot_df.copy()
        if "Khuyến nghị" in view_df.columns:
            view_df["Khuyến nghị"] = view_df["Khuyến nghị"].map(
                lambda x: action_display_vi(normalize_action(x))
            )
        st.dataframe(view_df, use_container_width=True, hide_index=True)
    except Exception:
        st.dataframe(autopilot_df, use_container_width=True, hide_index=True)
    top_symbol = str(autopilot_df.iloc[0].get("Mã") or "").upper()
    st.caption(f"Gợi ý mặc định: **{top_symbol}** (xếp hạng #1 từ Auto Pilot)")
    simple_symbols = tuple(str(x).upper() for x in autopilot_df["Mã"].head(5).tolist())
    simple_df = build_autopilot_simple_view(
        simple_symbols,
        profile,
        float(total_capital_vnd),
        quick_mode=effective_quick_mode,
        llm_live=bool(plan["llm_live"]),
    )
    st.markdown("#### ✅ Simple View (ra quyết định nhanh)")
    st.caption(
        "Giá vào / SL / TP chỉ hiện khi khuyến nghị là **MUA** hoặc **GIỮ**; "
        "khi **TRÁNH**/**QUAN SÁT** hệ thống không đề xuất mức vào lệnh (không phải mất dữ liệu do tối ưu tốc độ)."
    )
    if simple_df.empty:
        st.caption("Chưa dựng được bảng Simple View ở lần quét này.")
    else:
        simple_view = simple_view_for_plan(simple_df, plan_id)
        st.dataframe(simple_view, use_container_width=True, hide_index=True)
        if plan_id == "free":
            st.info(
                "🔒 Gói Free chỉ hiển thị bản rút gọn. Nâng Pro/Expert để mở full "
                "Entry/SL/TP và hành động 1-click."
            )
            if st.button("🚀 Mở khóa Pro để xem full plan", use_container_width=True, key="cta_unlock_simple_view"):
                log_event(user_id, "upgrade_cta_click", {"placement": "simple_view_paywall", "target_plan": "pro"})
                st.success("Đã ghi nhận nhu cầu nâng cấp Pro.")
        cta_cols = st.columns([2, 1])
        with cta_cols[0]:
            apply_symbol = st.selectbox(
                "Chọn mã để áp dụng kế hoạch 1-click",
                options=simple_df["Mã"].tolist(),
                key="autopilot_apply_symbol",
            )
        with cta_cols[1]:
            apply_now = st.button(
                "✅ Áp dụng kế hoạch 1-click",
                use_container_width=True,
                disabled=(plan_id == "free"),
            )
        # Lazy: chỉ tính News/Macro Bias cho mã đang chọn — không chạy trong vòng scan.
        try:
            from core.news_macro_service import format_news_macro_bias_caption

            st.caption(format_news_macro_bias_caption(str(apply_symbol or ""), allow_network=False))
        except Exception:
            pass
        thesis_col1, thesis_col2 = st.columns([3, 1])
        with thesis_col1:
            thesis_btn = st.button(
                "✨ Luận Điểm Đầu Tư AI & Chất Xúc Tác (1-Page)",
                use_container_width=True,
                key="autopilot_ai_thesis_btn",
            )
        with thesis_col2:
            if st.button("🧹 Xóa luận điểm", use_container_width=True, key="autopilot_ai_thesis_clear"):
                st.session_state.pop("autopilot_ai_thesis_md", None)
                st.session_state.pop("autopilot_ai_thesis_symbol", None)
        if thesis_btn:
            with st.spinner("AI đang tổng hợp nội lực tài chính & câu chuyện thị trường..."):
                try:
                    from core.llm_thesis_service import AIThesisGenerator

                    payload = _build_thesis_input(
                        symbol=str(apply_symbol or ""),
                        profile=profile,
                        total_capital_vnd=float(total_capital_vnd),
                        quick_mode=effective_quick_mode,
                        llm_live=bool(plan["llm_live"]),
                    )
                    thesis_md = AIThesisGenerator().generate_executive_thesis(payload)
                except Exception:
                    thesis_md = "Hệ thống AI hiện đang bận, vui lòng thử lại sau giây lát."
            st.session_state["autopilot_ai_thesis_md"] = str(thesis_md or "").strip()
            st.session_state["autopilot_ai_thesis_symbol"] = str(apply_symbol or "").upper()
        if st.session_state.get("autopilot_ai_thesis_md"):
            with st.container(border=True):
                sym_mark = str(st.session_state.get("autopilot_ai_thesis_symbol") or "").upper()
                if sym_mark:
                    st.markdown(f"#### 🧠 AI Executive Thesis Card · `{sym_mark}`")
                st.markdown(str(st.session_state.get("autopilot_ai_thesis_md") or ""))
        if apply_now:
            sel = simple_df[simple_df["Mã"] == apply_symbol].head(1)
            if sel.empty:
                st.warning("Không tìm thấy mã đã chọn trong Simple View.")
            else:
                can_exec, msg_exec = can_auto_execute_symbol(user_id, str(apply_symbol).upper(), cooldown_hours=24)
                if not can_exec:
                    st.warning(msg_exec)
                else:
                    row = sel.iloc[0]
                    side = str(row.get("Hành động") or "WATCH").upper()
                    row_readiness = str(
                        row.get("Decision readiness")
                        or row.get("Readiness")
                        or row.get("Mức sẵn sàng")
                        or "MEDIUM"
                    ).upper()
                    entry = float(row.get("Giá vào") or 0)
                    sl = float(row.get("SL") or 0)
                    tp = float(row.get("TP") or 0)
                    if side == "BUY" and row_readiness == "LOW":
                        st.error(
                            f"{str(apply_symbol).upper()}: readiness LOW -> tạm khóa 1-click BUY để giảm rủi ro."
                        )
                    elif entry <= 0 or sl <= 0 or tp <= 0:
                        st.warning("Dữ liệu Entry/SL/TP chưa đủ để áp dụng 1-click.")
                    else:
                        ok_dec, msg_dec = add_decision(
                            user_id,
                            str(apply_symbol).upper(),
                            "BUY" if side == "BUY" else "WATCH",
                            entry,
                            sl,
                            tp,
                            "1-click from Auto Pilot Simple View",
                            30,
                        )
                        ok_a1, ok_a2 = False, False
                        if ok_dec:
                            ok_check1, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                            if ok_check1:
                                add_alert(
                                    user_id,
                                    str(apply_symbol).upper(),
                                    "price_below",
                                    sl,
                                    "1-click SL from Auto Pilot",
                                )
                                ok_a1 = True
                            ok_check2, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                            if ok_check2:
                                add_alert(
                                    user_id,
                                    str(apply_symbol).upper(),
                                    "price_above",
                                    tp,
                                    "1-click TP from Auto Pilot",
                                )
                                ok_a2 = True
                            log_event(
                                user_id,
                                "autopilot_oneclick_applied",
                                {
                                    "symbol": str(apply_symbol).upper(),
                                    "side": side,
                                    "decision_saved": True,
                                    "alert_sl": ok_a1,
                                    "alert_tp": ok_a2,
                                },
                            )
                            st.success(
                                f"Đã áp dụng kế hoạch cho {str(apply_symbol).upper()}: "
                                f"decision=OK | alert SL={'OK' if ok_a1 else 'SKIP'} | "
                                f"alert TP={'OK' if ok_a2 else 'SKIP'}."
                            )
                        else:
                            st.error(msg_dec)
        if "Hành động" not in simple_df.columns:
            st.caption("Simple View thiếu cột Hành động — bỏ qua Batch 1-click.")
            buy_df = simple_df.head(0).copy()
        else:
            buy_df = simple_df[simple_df["Hành động"] == "BUY"].head(3).copy()
        if not buy_df.empty:
            if st.button(
                "🚀 Batch 1-click Top 3 BUY",
                use_container_width=True,
                disabled=(plan_id == "free"),
            ):
                batch_results: list[str] = []
                for _, b in buy_df.iterrows():
                    sym = str(b.get("Mã") or "").upper()
                    row_readiness = str(
                        b.get("Decision readiness")
                        or b.get("Readiness")
                        or b.get("Mức sẵn sàng")
                        or "MEDIUM"
                    ).upper()
                    can_exec, msg_exec = can_auto_execute_symbol(user_id, sym, cooldown_hours=24)
                    if not can_exec:
                        batch_results.append(f"{sym}: SKIP ({msg_exec})")
                        continue
                    if row_readiness == "LOW":
                        batch_results.append(f"{sym}: SKIP (readiness LOW)")
                        continue
                    entry = float(b.get("Giá vào") or 0)
                    sl = float(b.get("SL") or 0)
                    tp = float(b.get("TP") or 0)
                    if not sym or entry <= 0 or sl <= 0 or tp <= 0:
                        batch_results.append(f"{sym or 'N/A'}: SKIP (thiếu Entry/SL/TP)")
                        continue
                    ok_dec, msg_dec = add_decision(
                        user_id,
                        sym,
                        "BUY",
                        entry,
                        sl,
                        tp,
                        "Batch 1-click from Auto Pilot Simple View",
                        30,
                    )
                    if not ok_dec:
                        batch_results.append(f"{sym}: FAIL decision ({msg_dec})")
                        continue
                    ok_sl = ok_tp = False
                    can1, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                    if can1:
                        add_alert(user_id, sym, "price_below", sl, "Batch 1-click SL from Auto Pilot")
                        ok_sl = True
                    can2, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                    if can2:
                        add_alert(user_id, sym, "price_above", tp, "Batch 1-click TP from Auto Pilot")
                        ok_tp = True
                    batch_results.append(f"{sym}: decision=OK | SL={'OK' if ok_sl else 'SKIP'} | TP={'OK' if ok_tp else 'SKIP'}")
                log_event(
                    user_id,
                    "autopilot_batch_oneclick_applied",
                    {"symbols": [str(x).upper() for x in buy_df["Mã"].tolist()], "count": int(len(buy_df))},
                )
                st.success("Batch 1-click hoàn tất cho Top BUY.")
                for line in batch_results:
                    st.caption(f"- {line}")
        elif plan_id == "free":
            st.caption("Nâng Pro để dùng chế độ batch execution khi có tín hiệu BUY.")
    if profit_focus_mode:
        profit_symbols = tuple(str(x).upper() for x in autopilot_df["Mã"].head(15).tolist())
        pf_df = build_profit_focus_board(
            profit_symbols,
            profile,
            float(total_capital_vnd),
            quick_mode=effective_quick_mode,
            llm_live=bool(plan["llm_live"]),
        )
        st.markdown("#### 💎 Profit Focus Board (đạt chuẩn xuống tiền)")
        if pf_df.empty:
            st.caption("Chưa có mã đạt đủ chuẩn Profit Focus ở lần quét này.")
        else:
            st.dataframe(pf_df, use_container_width=True, hide_index=True)
            if plan_id in ("pro", "expert"):
                pf_top3 = pf_df.head(3).copy()
                if not pf_top3.empty and st.button("🚀 1-click Execute Top 3 Profit Focus", use_container_width=True):
                    results: list[str] = []
                    for _, row in pf_top3.iterrows():
                        sym = str(row.get("Mã") or "").upper()
                        can_exec, msg_exec = can_auto_execute_symbol(user_id, sym, cooldown_hours=24)
                        if not can_exec:
                            results.append(f"{sym}: SKIP ({msg_exec})")
                            continue
                        entry = float(row.get("Entry") or 0)
                        sl = float(row.get("SL") or 0)
                        tp = float(row.get("TP") or 0)
                        action = str(row.get("Hành động") or "WATCH").upper()
                        row_readiness = str(
                            row.get("Decision readiness")
                            or row.get("Readiness")
                            or row.get("Mức sẵn sàng")
                            or "MEDIUM"
                        ).upper()
                        if action == "BUY" and row_readiness == "LOW":
                            results.append(f"{sym}: SKIP (readiness LOW)")
                            continue
                        if not sym or entry <= 0 or sl <= 0 or tp <= 0:
                            results.append(f"{sym or 'N/A'}: SKIP (thiếu Entry/SL/TP)")
                            continue
                        ok_dec, msg_dec = add_decision(
                            user_id,
                            sym,
                            "BUY" if action == "BUY" else "WATCH",
                            entry,
                            sl,
                            tp,
                            "1-click from Profit Focus Board",
                            30,
                        )
                        if not ok_dec:
                            results.append(f"{sym}: FAIL decision ({msg_dec})")
                            continue
                        ok_sl = ok_tp = False
                        can1, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                        if can1:
                            add_alert(user_id, sym, "price_below", sl, "Profit Focus SL")
                            ok_sl = True
                        can2, _ = can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                        if can2:
                            add_alert(user_id, sym, "price_above", tp, "Profit Focus TP")
                            ok_tp = True
                        results.append(f"{sym}: decision=OK | SL={'OK' if ok_sl else 'SKIP'} | TP={'OK' if ok_tp else 'SKIP'}")
                    log_event(
                        user_id,
                        "profit_focus_batch_executed",
                        {"symbols": [str(x).upper() for x in pf_top3["Mã"].tolist()], "count": int(len(pf_top3))},
                    )
                    st.success("Đã execute Top 3 Profit Focus.")
                    for line in results:
                        st.caption(f"- {line}")
            else:
                st.info("🔒 1-click execute Profit Focus dành cho Pro/Expert.")
    if top_symbol and st.button("⚡ Dùng mã #1 để phân tích ngay", use_container_width=True):
        ticker = top_symbol
        run_analysis = True
    return ticker, run_analysis

