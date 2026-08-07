"""
Render primary analysis tab (tab1) — self-wired panels + ui_services.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from core import ui_services as svc
from core.action_center_panel import (
    build_action_center,
    build_final_opportunity_table,
    render_action_center_expander,
    render_scan_results_expander,
)
from core.analysis_ai_panel import render_risk_box
from core.analysis_forecast_panel import (
    render_dss_readiness_panel,
    render_forecast_accuracy,
    render_forecast_backtesting_report,
    render_forecast_benchmark,
    render_forecast_leaderboard,
    render_forecast_portfolio_dashboard,
    render_forecast_regime_dashboard,
    render_model_drift_panel,
    render_sector_mode_suggestions,
)
from core.analysis_helper_service import health_badge, profile_match_note
from core.analysis_outlook_panel import render_macro_micro_outlook, render_probabilistic_forecast
from core.analysis_runtime_service import load_snapshot_cached, load_strategic_report_cached
from core.analysis_summary_panel import render_analysis_action_explanation
from core.decision_card_panel import render_mobile_decision_card
from core.analysis_view_panel import (
    render_health_cards,
    render_readiness_checklist,
    render_report_downloads,
    render_risk_plan,
)
from core.engagement_panel import render_aha_and_value, render_next_best_action_cta
from core.forecast_accountability_panel import render_forecast_accountability_actions
from core.intraday_flow_panel import render_intraday_flow_panel
from core.report_export import investment_report_html, investment_report_markdown
from core.ui_services import GuardedMutations
from scrapers.financial_data import universe_subtype_map


def render_primary_analysis_tab(
    *,
    container: Any,
    user_id: str,
    ticker: str,
    report: dict[str, Any],
    plan_id: str,
    profile: str,
    watchlist: list[str],
    watchlist_default: list[str],
    total_capital_vnd: float,
    effective_quick_mode: bool,
    plan: dict[str, Any],
    notify_cfg: Any,
    ohlcv: pd.DataFrame,
    mutations: GuardedMutations | None = None,
) -> None:
    mut = mutations
    add_alert = mut.add_alert if mut else svc.pl.add_alert
    add_decision = mut.add_decision if mut else svc.pl.add_decision
    log_event = mut.log_event if mut else svc.pl.log_event
    export_forecast_health_report = mut.export_forecast_health_report if mut else svc.pl.export_forecast_health_report
    export_model_accountability_report = (
        mut.export_model_accountability_report if mut else svc.pl.export_model_accountability_report
    )
    export_monthly_accountability_markdown = (
        mut.export_monthly_accountability_markdown if mut else svc.pl.export_monthly_accountability_markdown
    )
    send_monthly_accountability_email = (
        mut.send_monthly_accountability_email if mut else svc.pl.send_monthly_accountability_email
    )

    with container:
        st.markdown("#### ✅ Quyết định nhanh")
        open_trade = mut.open_trade if mut else svc.pl.open_trade
        render_mobile_decision_card(
            report,
            symbol=ticker,
            expanded=True,
            user_id=user_id,
            add_decision=add_decision,
            open_trade=open_trade,
            log_event=log_event,
            can_use_feature=svc.pl.can_use_feature,
            record_usage=svc.pl.record_usage,
            plan_id=plan_id,
        )
        render_next_best_action_cta(
            user_id,
            ticker,
            report,
            plan_id,
            next_best_action=svc.pl.next_best_action,
            can_use_feature=svc.pl.can_use_feature,
            add_alert=add_alert,
            add_decision=add_decision,
            log_event=log_event,
        )
        render_risk_box(report, profile, profile_match_note=profile_match_note)
        render_analysis_action_explanation(report)
        render_macro_micro_outlook(report)
        render_probabilistic_forecast(report)
        deep_insight = report.get("deep_insight") if isinstance(report, dict) else None
        smart_money_summary = None
        if isinstance(deep_insight, dict):
            sm_flow = deep_insight.get("smart_money_flow")
            if isinstance(sm_flow, dict):
                smart_money_summary = sm_flow
        valuation = report.get("valuation") if isinstance(report, dict) else None
        subtype = ""
        if isinstance(valuation, dict):
            subtype = str(valuation.get("industry_subtype") or valuation.get("industry_subtype_label_vi") or "")
        try:
            render_intraday_flow_panel(
                container=st.container(),
                symbol=ticker,
                ohlcv=ohlcv,
                smart_money_summary=smart_money_summary,
                context={"industry_subtype": subtype} if subtype else None,
                timeframe="1D",
            )
        except Exception as exc:
            st.info(f"Không thể render panel dòng tiền lớn: {exc}")
        render_forecast_accuracy(
            user_id, ticker, get_forecast_accuracy_dashboard=svc.pl.get_forecast_accuracy_dashboard
        )
        render_forecast_benchmark(
            user_id, ticker, get_forecast_benchmark_by_horizon=svc.pl.get_forecast_benchmark_by_horizon
        )
        render_model_drift_panel(
            user_id,
            ticker,
            get_forecast_drift_signal=svc.pl.get_forecast_drift_signal,
            get_forecast_drift_streak=svc.pl.get_forecast_drift_streak,
        )
        render_forecast_portfolio_dashboard(
            user_id, get_forecast_portfolio_dashboard=svc.pl.get_forecast_portfolio_dashboard
        )
        render_forecast_regime_dashboard(
            user_id, get_forecast_regime_dashboard=svc.pl.get_forecast_regime_dashboard
        )
        render_forecast_backtesting_report(
            user_id, get_forecast_backtesting_report=svc.pl.get_forecast_backtesting_report
        )
        render_dss_readiness_panel(user_id, report, get_dss_readiness_report=svc.pl.get_dss_readiness_report)
        with st.expander("Bảng xếp hạng dự báo", expanded=False):
            render_forecast_leaderboard(user_id, get_forecast_leaderboard=svc.pl.get_forecast_leaderboard)
        with st.expander("Gợi ý mode theo ngành", expanded=False):
            render_sector_mode_suggestions(
                user_id,
                get_forecast_leaderboard=svc.pl.get_forecast_leaderboard,
                universe_subtype_map=universe_subtype_map,
            )
        render_forecast_accountability_actions(
            user_id,
            ticker,
            report,
            notify_cfg,
            export_forecast_health_report=export_forecast_health_report,
            get_forecast_drift_streak=svc.pl.get_forecast_drift_streak,
            export_model_accountability_report=export_model_accountability_report,
            export_monthly_accountability_markdown=export_monthly_accountability_markdown,
            send_monthly_accountability_email=send_monthly_accountability_email,
            log_event=log_event,
        )
        st.info(profile_match_note(profile, report))
        with st.expander("🧪 Backtest nâng cao (benchmark cố định)", expanded=False):
            bench_options = {
                "Auto (hiện tại)": "",
                "VN-Index (^VNINDEX)": "^VNINDEX",
                "VN30 (VN30.VN)": "VN30.VN",
                "ETF E1VFVN30": "E1VFVN30.VN",
            }
            bench_label_pick = st.selectbox(
                "Benchmark", list(bench_options.keys()), index=0, key="adv_backtest_benchmark"
            )
            fee_bps_pick = st.slider(
                "Phí giao dịch (bps)", min_value=0, max_value=30, value=10, step=1, key="adv_backtest_fee"
            )
            slip_bps_pick = st.slider(
                "Trượt giá (bps)", min_value=0, max_value=30, value=10, step=1, key="adv_backtest_slip"
            )
            if st.button("Chạy backtest nâng cao", use_container_width=True, key="adv_backtest_run"):
                try:
                    res_adv, lbl_adv = svc.run_full_backtest_for_ticker(
                        ticker,
                        yahoo_range="max",
                        fee_bps=float(fee_bps_pick),
                        slippage_bps=float(slip_bps_pick),
                        benchmark_symbol=bench_options.get(bench_label_pick) or None,
                    )
                    st.success(
                        f"App={res_adv.app_return_pct:.2f}% | Benchmark={res_adv.bench_return_pct:.2f}% "
                        f"| Alpha={res_adv.alpha_pct:.2f}% | Trades={len(res_adv.trades)} ({lbl_adv})"
                    )
                    if res_adv.trades:
                        df_tr = pd.DataFrame(res_adv.trades)
                        st.dataframe(df_tr, use_container_width=True, hide_index=True)
                        st.download_button(
                            "Tải trade log CSV",
                            data=df_tr.to_csv(index=False).encode("utf-8"),
                            file_name=f"trade_log_{ticker}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv",
                            key="adv_backtest_trades_csv",
                        )
                except Exception as e:
                    st.error(f"Backtest nâng cao lỗi: {e}")
        rp = report.get("risk_plan") or {}
        try:
            from core.decision_action_gate import trade_plan_is_active

            plan_active = trade_plan_is_active(report)
        except Exception:
            plan_active = str(report.get("final_action") or "").upper() in ("BUY", "HOLD")
        default_sl = float(rp.get("stop_loss_price") or 0) if plan_active else 0.0
        default_tp = float(rp.get("take_profit_price") or 0) if plan_active else 0.0
        c_alert1, c_alert2 = st.columns(2)
        with c_alert1:
            if st.button("Tạo cảnh báo thủng SL", use_container_width=True, disabled=not plan_active):
                ok_alert, msg_alert = svc.pl.can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                if not ok_alert:
                    st.error(msg_alert)
                elif default_sl > 0:
                    add_alert(user_id, ticker, "price_below", default_sl, "Auto from risk plan (SL)")
                    log_event(user_id, "alert_created", {"symbol": ticker, "type": "price_below", "auto": True})
                    st.success(f"Đã tạo alert SL cho {ticker} tại {default_sl:,.2f}.")
                else:
                    st.warning("Không có mức SL hợp lệ để tạo alert.")
        with c_alert2:
            if st.button("Tạo cảnh báo chạm TP", use_container_width=True, disabled=not plan_active):
                ok_alert, msg_alert = svc.pl.can_use_feature(user_id, "alert", 1, plan_id=plan_id)
                if not ok_alert:
                    st.error(msg_alert)
                elif default_tp > 0:
                    add_alert(user_id, ticker, "price_above", default_tp, "Auto from risk plan (TP)")
                    log_event(user_id, "alert_created", {"symbol": ticker, "type": "price_above", "auto": True})
                    st.success(f"Đã tạo alert TP cho {ticker} tại {default_tp:,.2f}.")
                else:
                    st.warning("Không có mức TP hợp lệ để tạo alert.")
        if not plan_active:
            st.caption("Alert SL/TP chỉ bật khi khuyến nghị là **MUA** hoặc **GIỮ**.")

        with st.expander("📌 Phân tích bổ sung (mở khi cần)", expanded=False):
            render_aha_and_value(
                user_id,
                user_aha_progress=svc.pl.user_aha_progress,
                customer_value_snapshot=svc.pl.customer_value_snapshot,
                next_best_action=svc.pl.next_best_action,
                today_action_board=svc.pl.today_action_board,
                proof_of_value_report=svc.pl.proof_of_value_report,
                value_maturity_score=svc.pl.value_maturity_score,
                overdue_action_reminders=svc.pl.overdue_action_reminders,
            )
            render_health_cards(report, health_badge=health_badge)
            render_readiness_checklist(report, ohlcv)

        with st.expander("📋 Kế hoạch vốn chi tiết", expanded=False):
            render_risk_plan(report)
            plan_now = report.get("risk_plan") or {}
            phase_now = (report.get("phase") or {}).get("metrics") or {}
            sizing_now = svc.pl.adaptive_position_sizing(
                user_id,
                base_max_position_pct=float(plan_now.get("max_position_pct") or 20.0),
                confidence_score=float(report.get("confidence_score") or 0),
                gate_passed=bool(report.get("gate_passed")),
                vol_multiple=float(phase_now.get("vol_multiple") or 1.0),
                coach_verdict="GO" if str(report.get("final_action") or "") == "BUY" else "CAUTION",
            )
            st.caption(
                f"🧠 Adaptive Position Sizing: {sizing_now['suggested_position_pct']}% "
                f"({sizing_now['risk_bucket']}) | Discipline {sizing_now['discipline_score']}"
            )
            st.caption(sizing_now["reason"])

        render_action_center_expander(
            user_id,
            watchlist,
            watchlist_default,
            profile,
            float(total_capital_vnd),
            build_action_center=build_action_center,
            log_event=log_event,
        )
        render_scan_results_expander(
            st.session_state,
            profile,
            total_capital_vnd,
            effective_quick_mode,
            bool(plan["llm_live"]),
            build_final_opportunity_table=build_final_opportunity_table,
            load_snapshot_cached=load_snapshot_cached,
            load_strategic_report_cached=load_strategic_report_cached,
        )
        render_report_downloads(
            report,
            investment_report_markdown=investment_report_markdown,
            investment_report_html=investment_report_html,
        )
