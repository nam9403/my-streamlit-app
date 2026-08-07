"""
Retention cohort + referral surface (P3 admin/ops).
"""

from __future__ import annotations

from typing import Any, Callable

import pandas as pd
import streamlit as st


def _retention_band(active_days_30: int) -> str:
    if active_days_30 >= 12:
        return "Power"
    if active_days_30 >= 5:
        return "Regular"
    if active_days_30 >= 2:
        return "Casual"
    return "At-risk"


def render_growth_cohort_panel(
    *,
    user_id: str,
    get_cohort_kpi: Callable[[str], dict[str, Any]] | None = None,
    get_upgrade_funnel: Callable[..., list[dict[str, Any]]] | None = None,
    get_admin_kpi: Callable[..., dict[str, Any]] | None = None,
    referral_stats: Callable[..., dict[str, Any]] | None = None,
) -> None:
    with st.expander("📈 Growth & retention (P3)", expanded=False):
        if get_cohort_kpi is not None:
            c = get_cohort_kpi(str(user_id or "default_user"))
            band = _retention_band(int(c.get("active_days_30") or 0))
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Active days 7d", int(c.get("active_days_7") or 0))
            c2.metric("Active days 30d", int(c.get("active_days_30") or 0))
            c3.metric("Analysis 30d", int(c.get("analysis_30") or 0))
            c4.metric("Cohort band", band)
            st.caption(
                f"Upgrade intent 30d: {int(c.get('upgrade_intent_30') or 0)} · "
                f"success: {int(c.get('upgrade_success_30') or 0)}"
            )

        if referral_stats is not None:
            try:
                ref = referral_stats(days=30)
                st.markdown("**Referral (30 ngày)**")
                st.caption(
                    f"Signups qua referral: **{ref.get('signups') or 0}** · "
                    f"mã unique: **{ref.get('unique_codes') or 0}**"
                )
                top = ref.get("top_referrers") or []
                if top:
                    st.dataframe(pd.DataFrame(top), use_container_width=True, hide_index=True)
            except Exception:
                st.caption("Referral stats chưa sẵn sàng.")

        if get_upgrade_funnel is not None:
            try:
                funnel = get_upgrade_funnel(days=30)
                if funnel:
                    st.markdown("**Upgrade funnel**")
                    st.dataframe(pd.DataFrame(funnel), use_container_width=True, hide_index=True)
            except Exception:
                pass

        if get_admin_kpi is not None:
            try:
                adm = get_admin_kpi(days=30)
                st.caption(
                    f"Admin: users={adm.get('users_total')} · active 30d={adm.get('active_users_period')} · "
                    f"events={adm.get('events_period')}"
                )
            except Exception:
                pass

        try:
            from core.referral_service import referral_code_for_user, referral_link_hint

            code = referral_code_for_user(user_id)
            if code:
                st.info(f"Mã giới thiệu của bạn: **{code}** — {referral_link_hint(user_id)}")
        except Exception:
            pass

        st.caption(
            "Báo cáo tuần: `python scripts/export_weekly_growth_report.py` → "
            "`artifacts/operations/weekly_growth_report.md`"
        )
