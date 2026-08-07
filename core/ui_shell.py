"""
Streamlit UI shell: sidebar + main body composition.

``app.py`` remains the composition root (env bootstrap + page config + call here).
Panels pull services via ``core.ui_services`` / ``core.state_manager`` — no callback hell from app.py.
"""

from __future__ import annotations

import os
from datetime import timedelta

import streamlit as st

from core import state_manager as sm, ui_services as svc
from core.action_center_panel import build_portfolio_options
from core.analysis_ai_panel import render_ai_chat_style, render_risk_box
from core.analysis_chart_panel import render_analysis_chart_tab
from core.analysis_financial_panel import render_financial_health_tab
from core.analysis_helper_service import extract_ticker, profile_match_note as _profile_match_note
from core.analysis_summary_panel import render_analysis_action_explanation, render_analysis_main_metrics
from core.analysis_view_panel import render_evidence
from core.app_analysis_dashboard_panel import render_analysis_quick_dashboard
from core.app_analysis_orchestration import analysis_cache_key_parts, resolve_analysis_report
from core.app_analysis_tab_primary import render_primary_analysis_tab
from core.app_analysis_tabs_secondary import render_secondary_analysis_tabs
from core.app_auth_gate import enforce_auth_gate
from core.app_autopilot_panel import render_autopilot_panel
from core.app_daily_action_panel import render_daily_action_panel
from core.app_finder_panel import render_finder_panel
from core.app_quickstart_panel import render_app_quickstart_strip
from core.app_reminder_panel import render_action_reminders
from core.app_scan_flow import run_scan_flow
from core.app_shop_layout import render_aisle_band
from core.app_sidebar_account_panel import render_sidebar_account_sections, render_sidebar_auth_section
from core.app_sidebar_runtime_panel import render_sidebar_runtime_sections
from core.app_ui_config import PROFILE_OPTIONS, SUBTYPE_LABEL_TO_ID, WATCHLIST_DEFAULT
from core.app_chat_interface import chat_first_ui_enabled, render_chat_first_interface
from core.app_watch_board_panel import render_watch_board
from core.engagement_panel import render_next_best_action_cta
from core.notification_settings_panel import render_notification_settings
from core.portfolio_overview_panel import render_portfolio_overview
from core.ui_bg_analysis import analysis_job_id
from core.warm_flow import handle_warm_flow, schedule_focus_prefetch

VIEW_TAB_WORK = "🎯 Việc cần làm"
VIEW_TAB_AI = "🧠 Giải thích AI"
VIEW_TAB_FIN = "📊 Số liệu & danh mục"


def render_app() -> None:
    """Full UI after page bootstrap — auth gate, sidebar, main aisles, analysis tabs."""
    flags0 = sm.resolve_fast_shell_flags()
    fast_shell = flags0.fast_shell

    with st.sidebar:
        st.header("⚙️ Bảng điều khiển")
        user_id = render_sidebar_auth_section(
            has_auth_user=svc.pl.has_auth_user,
            verify_user_pin=svc.pl.verify_user_pin,
            register_user_pin=svc.pl.register_user_pin,
        )
        enforce_auth_gate(user_id=user_id, has_auth_user=svc.pl.has_auth_user)
        mutations = svc.build_guarded_mutations(user_id)

        account_state = render_sidebar_account_sections(
            user_id=user_id,
            profile_options=PROFILE_OPTIONS,
            watchlist_default=WATCHLIST_DEFAULT,
            has_auth_user=svc.pl.has_auth_user,
            get_user_plan=svc.pl.get_user_plan,
            get_plan_features=svc.pl.get_plan_features,
            set_user_plan=mutations.set_user_plan,
            render_notification_settings=render_notification_settings,
            load_secret=mutations.load_secret,
            save_secret=mutations.save_secret,
            dispatch_text_notifications=mutations.dispatch_text_notifications,
            log_event=mutations.log_event,
            process_notification_queue=mutations.process_notification_queue,
            migrate_legacy_json_to_sqlite=mutations.migrate_legacy_json_to_sqlite,
            run_background_cycle=mutations.run_background_cycle,
        )
        auth_ready = bool(account_state.auth_ready)
        plan_label = account_state.plan_label
        plan_id = account_state.plan_id
        plan = dict(account_state.plan)
        profile = account_state.profile
        total_capital_vnd = float(account_state.total_capital_vnd)
        tg_bot = account_state.tg_bot
        tg_chat = account_state.tg_chat
        webhook_url = account_state.webhook_url
        email_to = account_state.email_to
        smtp_host = account_state.smtp_host
        smtp_port = int(account_state.smtp_port)
        smtp_user = account_state.smtp_user
        smtp_password = account_state.smtp_password
        smtp_from = account_state.smtp_from
        notify_cfg = account_state.notify_cfg

        sm.refresh_vn_universe_total(svc.universe_symbol_count)
        st.divider()
        sidebar_state = render_sidebar_runtime_sections(
            watchlist_default=WATCHLIST_DEFAULT,
            auth_ready=auth_ready,
            user_id=user_id,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            plan=plan,
            plan_label=plan_label,
            plan_id=plan_id,
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            webhook_url=webhook_url,
            email_to=email_to,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
            mutations=mutations,
        )
        runtime_cfg = sidebar_state.runtime_cfg
        watchlist = list(sidebar_state.watchlist or [])
        ticker = str(sidebar_state.ticker or "")
        autopilot_mode = bool(sidebar_state.autopilot_mode)
        profit_focus_mode = bool(sidebar_state.profit_focus_mode)
        autopilot_limit = int(sidebar_state.autopilot_limit or 30)
        autopilot_refresh = bool(sidebar_state.autopilot_refresh)
        quick_mode = bool(sidebar_state.quick_mode)
        run_analysis = bool(sidebar_state.run_analysis)
        if run_analysis:
            st.session_state["onboarding_deep_analysis_done"] = True
            st.session_state["last_analysis_ticker"] = str(sidebar_state.ticker or "")
        min_avg_volume_20 = float(sidebar_state.min_avg_volume_20 or 0.0)
        universe_limit = int(sidebar_state.universe_limit or 40)
        subtype_labels = list(sidebar_state.subtype_labels or [])
        run_scan = bool(sidebar_state.run_scan)
        low_mem_default = str(os.environ.get("II_UI_LOW_MEM", "0")).strip().lower() in ("1", "true", "yes", "on")
        lite_ui_mode = st.toggle("Lite UI mode (mượt hơn, ít panel nặng)", value=low_mem_default)
        sm.set_lite_ui_mode(lite_ui_mode)
        chat_first_mode = st.toggle(
            "Chat-first UI (Gemini-style + Decision Card)",
            value=chat_first_ui_enabled(),
            key="ii_chat_first_toggle",
            help="Giao diện hội thoại tối giản; tắt để dùng kệ cổ điển.",
        )

    flags = sm.resolve_fast_shell_flags(run_analysis=run_analysis, autopilot_refresh=autopilot_refresh)

    if not lite_ui_mode and not fast_shell:
        handle_warm_flow(
            runtime_cfg=runtime_cfg,
            watchlist_default=WATCHLIST_DEFAULT,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            prewarm_watchlist_cache=svc.prewarm_watchlist_cache,
            run_bg_warm_job=svc.run_bg_warm_job,
            run_background_cycle=mutations.run_background_cycle,
        )
        schedule_focus_prefetch(
            runtime_cfg=runtime_cfg,
            watchlist_default=WATCHLIST_DEFAULT,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            prewarm_watchlist_cache=svc.prewarm_watchlist_cache,
        )

    effective_quick_mode = bool(quick_mode)

    # --- Chat-first hybrid surface (presentation refactor; backend unchanged) ---
    if chat_first_mode:
        def _settings_slot() -> None:
            render_portfolio_overview(user_id, portfolio_snapshot=svc.pl.portfolio_snapshot)
            st.caption("Cấu hình Telegram / PIN / plan nằm ở sidebar trái.")

        try:
            from pathlib import Path

            version = Path(__file__).resolve().parent.parent.joinpath("VERSION").read_text(encoding="utf-8").strip()
        except Exception:
            version = "1.0.2"

        render_chat_first_interface(
            user_id=user_id,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            plan=plan,
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            notify_cfg=notify_cfg,
            autopilot_limit=int(autopilot_limit or 30),
            version=version or "1.0.2",
            load_snapshot_cached=svc.load_snapshot_cached,
            load_strategic_report_cached=svc.load_strategic_report_cached,
            load_autopilot_board=svc.load_autopilot_board,
            can_use_feature=svc.pl.can_use_feature,
            add_alert=mutations.add_alert,
            log_event=mutations.log_event,
            dispatch_text_notifications=mutations.dispatch_text_notifications,
            render_settings_slot=_settings_slot,
        )
        show_classic = st.toggle(
            "📚 Hiện thêm giao diện cổ điển (kệ đầy đủ)",
            value=False,
            key="ii_show_classic_under_chat",
        )
        if not show_classic:
            return

    render_app_quickstart_strip(lite_ui_mode=lite_ui_mode)

    render_aisle_band(
        title="Kệ 1 — Giá & việc trong ngày",
        subtitle="Liếc nhanh giá các mã đang theo dõi; bên dưới là gợi ý việc nên làm hôm nay.",
    )
    render_watch_board(
        watchlist=list(watchlist or []),
        watchlist_default=WATCHLIST_DEFAULT,
        load_snapshot_cached=svc.load_snapshot_cached,
    )

    if not lite_ui_mode:
        render_daily_action_panel(
            user_id=user_id,
            plan=plan,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            effective_quick_mode=effective_quick_mode,
            list_holdings=svc.pl.list_holdings,
            list_universe_symbols=svc.list_universe_symbols,
            build_daily_action_list=svc.build_daily_action_list,
        )

    render_aisle_band(
        title="Kệ 2 — Gợi ý nhanh (Auto Pilot)",
        subtitle="Giống quầy combo: xem gợi ý theo tài sản & phong cách đầu tư của bạn.",
    )
    if flags.should_defer_autopilot:
        st.markdown("### 🤖 Auto Pilot")
        st.caption("Đang trì hoãn tải Auto Pilot để ưu tiên mở app nhanh trên máy cấu hình thấp.")
        if st.button("Tải Auto Pilot ngay", key="load_autopilot_now", use_container_width=True):
            sm.request_autopilot_load()
            st.rerun()
    else:
        ticker, run_analysis = render_autopilot_panel(
            autopilot_mode=autopilot_mode,
            autopilot_refresh=autopilot_refresh,
            profile=profile,
            autopilot_limit=autopilot_limit,
            total_capital_vnd=float(total_capital_vnd),
            effective_quick_mode=effective_quick_mode,
            plan=plan,
            plan_id=plan_id,
            user_id=user_id,
            ticker=ticker,
            run_analysis=run_analysis,
            profit_focus_mode=profit_focus_mode,
            load_autopilot_board=svc.load_autopilot_board,
            build_autopilot_simple_view=svc.build_autopilot_simple_view,
            build_profit_focus_board=svc.build_profit_focus_board,
            simple_view_for_plan=svc.simple_view_for_plan,
            can_auto_execute_symbol=svc.pl.can_auto_execute_symbol,
            add_decision=mutations.add_decision,
            can_use_feature=svc.pl.can_use_feature,
            add_alert=mutations.add_alert,
            log_event=mutations.log_event,
        )

    if not lite_ui_mode:
        render_aisle_band(
            title="Kệ 3 — Tìm & quét thị trường",
            subtitle="Tìm mã phù hợp rồi quét một lượt — giống đi dọc quầy rồi so sánh giá.",
        )
        if fast_shell and not flags.finder_unlocked:
            st.caption(
                "Fast shell: Finder & quét nặng **chưa tải** để giữ mở app nhanh. Bấm nút bên dưới khi bạn cần."
            )
            if st.button("Mở Finder & quét thị trường", key="unlock_finder_shell", use_container_width=True):
                sm.unlock_finder_shell()
                st.rerun()
        else:
            render_finder_panel(
                user_id=user_id,
                profile=profile,
                total_capital_vnd=float(total_capital_vnd),
                effective_quick_mode=effective_quick_mode,
                plan=plan,
                subtype_label_to_id=SUBTYPE_LABEL_TO_ID,
                universe_subtype_map=svc.universe_subtype_map,
                list_universe_symbols=svc.list_universe_symbols,
                build_opportunity_3m_board=svc.build_opportunity_3m_board,
                load_benchmark_return_3m=svc.load_benchmark_return_3m,
            )

        render_action_reminders(
            user_id=user_id,
            overdue_action_reminders=svc.pl.overdue_action_reminders,
            dispatch_text_notifications=mutations.dispatch_text_notifications,
            log_event=mutations.log_event,
            tg_bot=tg_bot,
            tg_chat=tg_chat,
            webhook_url=webhook_url,
            email_to=email_to,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_user=smtp_user,
            smtp_password=smtp_password,
            smtp_from=smtp_from,
        )

    run_scan_flow(
        run_scan=run_scan,
        universe_limit=universe_limit,
        plan=plan,
        plan_label=plan_label,
        subtype_labels=subtype_labels,
        subtype_label_to_id=SUBTYPE_LABEL_TO_ID,
        user_id=user_id,
        plan_id=plan_id,
        profile=profile,
        total_capital_vnd=float(total_capital_vnd),
        min_avg_volume_20=float(min_avg_volume_20),
        list_universe_symbols=svc.list_universe_symbols,
        universe_subtype_map=svc.universe_subtype_map,
        can_use_feature=svc.pl.can_use_feature,
        log_event=mutations.log_event,
        scan_potential_stocks=svc.scan_potential_stocks,
        build_portfolio_options=build_portfolio_options,
    )

    prompt = st.chat_input("Gõ mã tại đây — ví dụ: FPT hoặc phân tích VCB")
    if prompt:
        t2 = extract_ticker(prompt)
        if t2:
            sm.set_selected_ticker(t2)
        else:
            st.info("Chat hiện dùng để nhận diện mã cổ phiếu. Ví dụ: `FPT` hoặc `phân tích VCB`.")
    if sm.get_selected_ticker():
        ticker = sm.get_selected_ticker()

    force_sync_analysis = sm.consume_force_sync_analysis()
    run_analysis_effective = bool(run_analysis or force_sync_analysis)

    report, ohlcv = resolve_analysis_report(
        run_analysis=run_analysis_effective,
        fast_shell=bool(fast_shell),
        user_id=user_id,
        ticker=ticker,
        profile=profile,
        total_capital_vnd=float(total_capital_vnd),
        plan=plan,
        plan_id=plan_id,
        effective_quick_mode=effective_quick_mode,
        can_use_feature=svc.pl.can_use_feature,
        record_usage=mutations.record_usage,
        log_event=mutations.log_event,
        load_snapshot_cached=svc.load_snapshot_cached,
        value_investing_summary=svc.value_investing_summary,
        recommend_task_mode=svc.recommend_task_mode,
        get_forecast_benchmark_by_horizon=svc.pl.get_forecast_benchmark_by_horizon,
        universe_subtype_map=svc.universe_subtype_map,
        get_forecast_group_benchmark=svc.pl.get_forecast_group_benchmark,
        load_strategic_report_cached=svc.load_strategic_report_cached,
        apply_drift_guardrails=svc.apply_drift_guardrails,
        get_forecast_drift_signal=svc.pl.get_forecast_drift_signal,
        get_forecast_drift_streak=svc.pl.get_forecast_drift_streak,
        load_ohlcv_cached=svc.load_ohlcv_cached,
        calibrate_report_forecast_with_history=svc.calibrate_report_forecast_with_history,
        get_forecast_accuracy_dashboard=svc.pl.get_forecast_accuracy_dashboard,
        record_forecast_snapshot=mutations.record_forecast_snapshot,
    )

    if fast_shell and isinstance(report, dict) and report.get("_analysis_bg_status"):
        st.caption(
            "Job phân tích đầy đủ đang chạy **trong nền** — bạn có thể đổi tab hoặc chọn mã khác; "
            "trang sẽ tự làm mới khi xong."
        )
    if fast_shell and isinstance(report, dict) and report.get("_fast_shell_skeleton"):
        st.info(
            "**Fast shell:** phần nặng (7 Whys, tin, kỹ thuật sâu) chỉ chạy khi bạn yêu cầu. "
            "Cùng tham số trong **ngày (ICT)** được lưu tự động — lần sau trong ngày không phải phân tích lại."
        )
        c_bg, c_sy = st.columns(2)
        with c_bg:
            if st.button("Chạy phân tích đầy đủ (nền)", type="primary", key="analysis_run_bg_primary"):
                sm.request_analysis_bg_job(
                    analysis_job_id(
                        analysis_cache_key_parts(
                            user_id=user_id,
                            ticker=ticker,
                            profile=profile,
                            total_capital_vnd=float(total_capital_vnd),
                            plan_id=plan_id,
                            effective_quick_mode=effective_quick_mode,
                            llm_live=bool(plan["llm_live"]),
                        )
                    )
                )
                st.rerun()
        with c_sy:
            if st.button("Phân tích đồng bộ (chờ tại chỗ)", key="analysis_force_sync"):
                sm.request_force_sync_analysis()
                st.rerun()

    valuation = render_analysis_quick_dashboard(ticker=ticker, report=report)
    render_analysis_main_metrics(report)
    if ticker and report:
        st.markdown("### 📈 Biểu đồ giá")
        render_analysis_chart_tab(
            ticker,
            report,
            valuation,
            ohlcv,
            fetch_ohlcv_history=svc.fetch_ohlcv_history,
        )

    render_aisle_band(
        title="Kệ 4 — Chọn nội dung xem thêm (cùng một mã)",
        subtitle="Ba nút dưới đây: việc cần làm (khuyến nghị) · giải thích AI · số liệu & danh mục.",
    )
    view_mode = st.radio(
        "Chọn kệ nội dung",
        options=[VIEW_TAB_WORK, VIEW_TAB_AI, VIEW_TAB_FIN],
        horizontal=True,
        key=sm.KEY_ANALYSIS_VIEW_MODE,
    )

    if view_mode == VIEW_TAB_WORK:
        if lite_ui_mode:
            st.caption("Lite UI: hiển thị phần quyết định cốt lõi để tăng tốc.")
            render_next_best_action_cta(
                user_id,
                ticker,
                report,
                plan_id,
                next_best_action=svc.pl.next_best_action,
                can_use_feature=svc.pl.can_use_feature,
                add_alert=mutations.add_alert,
                add_decision=mutations.add_decision,
                log_event=mutations.log_event,
            )
            render_risk_box(report, profile, profile_match_note=_profile_match_note)
            render_analysis_action_explanation(report)
        else:
            render_primary_analysis_tab(
                container=st.container(),
                user_id=user_id,
                ticker=ticker,
                report=report,
                plan_id=plan_id,
                profile=profile,
                watchlist=watchlist,
                watchlist_default=WATCHLIST_DEFAULT,
                total_capital_vnd=float(total_capital_vnd),
                effective_quick_mode=effective_quick_mode,
                plan=plan,
                notify_cfg=notify_cfg,
                ohlcv=ohlcv,
                mutations=mutations,
            )

    if lite_ui_mode:
        if view_mode == VIEW_TAB_AI:
            render_ai_chat_style(report)
        elif view_mode == VIEW_TAB_FIN:
            with st.expander("📌 Tóm tắt tài chính cốt lõi", expanded=True):
                render_financial_health_tab(report)
            with st.expander("🧾 Bằng chứng dữ liệu chi tiết", expanded=False):
                render_evidence(report)
            render_portfolio_overview(user_id, portfolio_snapshot=svc.pl.portfolio_snapshot)
    else:
        render_secondary_analysis_tabs(
            show_ai=(view_mode == VIEW_TAB_AI),
            show_finance=(view_mode == VIEW_TAB_FIN),
            ticker=ticker,
            report=report,
            valuation=valuation,
            ohlcv=ohlcv,
            user_id=user_id,
            plan_id=plan_id,
            notify_cfg=notify_cfg,
            watchlist=watchlist,
            watchlist_default=WATCHLIST_DEFAULT,
            profile=profile,
            total_capital_vnd=float(total_capital_vnd),
            mutations=mutations,
        )

    if fast_shell:

        @st.fragment(run_every=timedelta(seconds=2))
        def _analysis_bg_poll_fragment() -> None:
            jid = sm.get_analysis_bg_poll_jid()
            if not jid:
                return
            stt = sm.poll_async_job_status(str(jid))
            if stt and stt.get("state") in ("done", "error"):
                st.rerun()

        _analysis_bg_poll_fragment()

        @st.fragment(run_every=timedelta(seconds=2))
        def _finder_pg_poll_fragment() -> None:
            jid = sm.get_finder_pg_poll_jid()
            if not jid:
                return
            stt = sm.poll_async_job_status(str(jid))
            if stt and stt.get("state") in ("done", "error"):
                st.rerun()

        _finder_pg_poll_fragment()

        @st.fragment(run_every=timedelta(seconds=2))
        def _scan_pg_poll_fragment() -> None:
            jid = sm.get_scan_pg_poll_jid()
            if not jid:
                return
            stt = sm.poll_async_job_status(str(jid))
            if stt and stt.get("state") in ("done", "error"):
                st.rerun()

        _scan_pg_poll_fragment()

        @st.fragment(run_every=timedelta(seconds=2))
        def _autopilot_pg_poll_fragment() -> None:
            jid = sm.get_autopilot_pg_poll_jid()
            if not jid:
                return
            stt = sm.poll_async_job_status(str(jid))
            if stt and stt.get("state") in ("done", "error"):
                st.rerun()

        _autopilot_pg_poll_fragment()
