"""
Public-ish trust surface: anonymized paper/forecast hit-rate + disclaimer (P2).
"""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st


_DISCLAIMER = (
    "Disclaimer: Hệ thống hỗ trợ quyết định, không phải lời khuyên đầu tư cá nhân. "
    "Lịch sử gợi ý / paper-trade mang tính tham chiếu, có thể lệch thực tế. "
    "Bạn tự chịu trách nhiệm khi giao dịch."
)


def render_trust_panel(
    *,
    get_forecast_portfolio_dashboard: Callable[..., dict[str, Any]] | None = None,
    user_id: str = "default_user",
) -> None:
    with st.expander("🛡️ Trust & minh bạch hiệu quả", expanded=False):
        st.caption(_DISCLAIMER)
        # Paper-trade aggregate (anonymous system ledger)
        try:
            from core.paper_trade_ledger import hitrate_report, hitrate_report_extended, recent_closed_trades

            hr30 = hitrate_report(lookback_days=30)
            hr40 = hitrate_report(lookback_days=40)
            hr365 = hitrate_report(lookback_days=365)
            ext = hitrate_report_extended(horizons=(40, 30, 90, 365))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Paper 40d", int(hr40.get("samples") or 0))
            c2.metric("Hit-rate 40d %", hr40.get("hit_rate_pct") if hr40.get("hit_rate_pct") is not None else "—")
            c3.metric("Hit-rate 365d %", hr365.get("hit_rate_pct") if hr365.get("hit_rate_pct") is not None else "—")
            c4.metric("Đang mở", int(ext.get("open_count") or 0))
            try:
                from core.paper_ops_guard import evaluate_paper_kill_switch, load_guard_state
                from core.paper_trade_ledger import load_ledger

                guard = load_guard_state() or evaluate_paper_kill_switch(load_ledger())
                if guard.get("halt_new_opens"):
                    st.warning(
                        "Paper kill-switch ON — tạm dừng mở lệnh mới. "
                        f"Lý do: {', '.join(guard.get('reasons') or []) or '—'}"
                    )
                else:
                    st.caption("Paper kill-switch: OFF (cho phép mở mới).")
            except Exception:
                pass
            st.caption(
                "Nguồn: paper ledger hệ thống (ẩn danh). "
                "Weekly: `artifacts/operations/paper_weekly_latest.md` · "
                "Báo cáo: `artifacts/operations/paper_trade_accountability.md`."
            )
            try:
                import json
                from pathlib import Path

                digest_path = Path("artifacts/operations/morning_digest_latest.json")
                if digest_path.exists():
                    dig = json.loads(digest_path.read_text(encoding="utf-8"))
                    paper_m = ((dig.get("meta") or {}).get("paper") or {}) if isinstance(dig, dict) else {}
                    tops = dig.get("top_symbols") or []
                    send = dig.get("send") or {}
                    st.caption(
                        f"Morning digest gần nhất: {len(tops)} mã · "
                        f"paper closed={paper_m.get('samples', '—')} · "
                        f"dry_run={bool(send.get('dry_run'))} · "
                        f"sent={send.get('sent', 0)}"
                    )
            except Exception:
                pass
            recent = recent_closed_trades(limit=8, anonymize=True)
            if recent:
                st.markdown("**Mẫu lệnh đã đóng (ẩn danh)**")
                st.dataframe(recent, use_container_width=True, hide_index=True)
        except Exception:
            st.caption("Paper ledger chưa sẵn sàng.")

        if get_forecast_portfolio_dashboard is not None:
            try:
                dash = get_forecast_portfolio_dashboard(user_id=user_id, lookback_days=365)
                overall = (dash or {}).get("overall") or {}
                if int(overall.get("samples") or 0) > 0:
                    st.markdown("**Forecast đã nghiệm thu (user hiện tại, ẩn chi tiết mã)**")
                    d1, d2, d3 = st.columns(3)
                    d1.metric("Samples", int(overall.get("samples") or 0))
                    d2.metric("Hit-rate %", overall.get("hit_rate_pct"))
                    d3.metric("Alpha %", overall.get("alpha_pct"))
            except Exception:
                pass

        st.info(
            "Tăng trust: nightly scan + `python scripts/resolve_paper_trades.py` + "
            "`python scripts/export_paper_accountability_report.py --resolve` + "
            "`python scripts/export_public_trust_page.py` + `python scripts/export_slo_snapshot.py`."
        )
        st.caption(
            "Playbook P1 trên thẻ quyết định: Thesis / Setup / Trigger → "
            "BUY hoặc CONDITIONAL_BUY (có vùng mua + điều kiện hủy)."
        )
