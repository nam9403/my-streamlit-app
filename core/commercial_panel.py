"""
Wave 6 — commercial surface: waitlist, referral share, weekly paper snippet, conversion.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import streamlit as st


def render_commercial_pilot_panel(
    *,
    user_id: str,
    plan_id: str,
    plan: dict[str, Any] | None,
    log_event: Callable[..., Any],
    can_use_feature: Callable[..., tuple[bool, str]] | None = None,
    get_plan_features: Callable[[str], dict[str, Any]] | None = None,
) -> None:
    pid = str(plan_id or "free").lower()
    p = plan if isinstance(plan, dict) else {}
    # Nested-safe: parent sidebar uses expander — do not nest another expander.
    st.markdown("---")
    st.markdown("**🚀 Pilot / Waitlist & giới thiệu (Wave 6)**")
    with st.container():
        st.caption(
            "Mục tiêu nội bộ: ~50 MAU và ~10% nâng Pro, hoặc waitlist rõ ràng. "
            "Không phải cam kết lợi nhuận."
        )
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📝 Tham gia waitlist Pro", use_container_width=True, key="waitlist_join_btn"):
                log_event(user_id, "waitlist_join", {"from_plan": pid, "source": "commercial_panel"})
                st.success("Đã ghi danh waitlist. Chúng tôi ưu tiên khi mở quota Pro.")
        with c2:
            if st.button("💬 Quan tâm nâng Pro", use_container_width=True, key="upgrade_intent_btn"):
                log_event(user_id, "upgrade_intent", {"from": pid, "to": "pro", "source": "commercial_panel"})
                st.info("Đã ghi nhận tín hiệu nâng cấp.")

        try:
            from core.referral_service import referral_code_for_user, referral_link_hint

            code = referral_code_for_user(user_id)
            if code:
                st.markdown(f"**Mã giới thiệu:** `{code}`")
                st.caption(referral_link_hint(user_id))
                if st.button("📤 Ghi event chia sẻ referral", key="ref_share_btn"):
                    log_event(user_id, "referral_share", {"code": code})
                    st.success("Đã ghi nhận chia sẻ.")
        except Exception:
            pass

        # Weekly paper report — Pro+ edge
        allow_weekly = bool(p.get("paper_weekly"))
        if can_use_feature is not None:
            ok_w, msg_w = can_use_feature(user_id, "paper_weekly", 1, plan_id=pid)
            allow_weekly = bool(ok_w)
        else:
            msg_w = "Gói Free chưa mở paper weekly đầy đủ."
        st.markdown("**Báo cáo tuần (paper)**")
        if allow_weekly:
            weekly = Path("artifacts/operations/paper_weekly_latest.md")
            if weekly.exists():
                text = weekly.read_text(encoding="utf-8", errors="ignore")
                st.code(text[:1800] + ("…" if len(text) > 1800 else ""), language="markdown")
            else:
                st.caption("Chưa có `paper_weekly_latest.md` — chạy nightly/export.")
        else:
            st.caption(msg_w if can_use_feature else "Nâng Pro để xem báo cáo tuần paper đầy đủ.")

        # Edge feature strip
        if get_plan_features is not None:
            try:
                from core.app_onboarding_helpers import plan_feature_matrix

                st.caption("So sánh gói (edge features)")
                import pandas as pd

                st.dataframe(pd.DataFrame(plan_feature_matrix()), use_container_width=True, hide_index=True)
            except Exception:
                pass

        # Conversion snapshot (best-effort, local artifact)
        snap_path = Path("artifacts/operations/growth_conversion_latest.json")
        if snap_path.exists():
            try:
                import json

                snap = json.loads(snap_path.read_text(encoding="utf-8"))
                pilot = snap.get("pilot") or {}
                st.caption(
                    f"Pilot status: **{pilot.get('status') or '—'}** · "
                    f"MAU={pilot.get('active_users_30d')} · "
                    f"pay%={pilot.get('pay_pct')} · "
                    f"waitlist={pilot.get('waitlist_joins')} · "
                    f"{pilot.get('note_vi') or ''}"
                )
            except Exception:
                pass
