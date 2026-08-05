"""Dải 'lối vào siêu thị' — P2: hồ sơ → Autopilot → phân tích 1 mã."""

from __future__ import annotations

import html
import os

import streamlit as st

from core.app_onboarding_helpers import p2_onboarding_done_score, p2_onboarding_progress_text

_SESSION_HIDE = "app_quickstart_strip_hidden"


def _profile_ready_from_session() -> bool:
    profile = st.session_state.get("investor_profile") or st.session_state.get("profile")
    try:
        capital = float(st.session_state.get("total_capital_vnd") or 0)
    except (TypeError, ValueError):
        capital = 0.0
    return bool(profile) and capital >= 10_000_000.0


def render_app_quickstart_strip(*, lite_ui_mode: bool) -> None:
    """Hiển thị đầu vùng nội dung chính."""
    raw = str(os.environ.get("II_SHOW_QUICKSTART", "1")).strip().lower()
    if raw in ("0", "false", "no", "off"):
        return
    if st.session_state.get(_SESSION_HIDE) or st.session_state.get("onboarding_p2_done"):
        return

    profile_ok = _profile_ready_from_session()
    ap_ok = bool(
        st.session_state.get("autopilot_onboarding_seen") or st.session_state.get("autopilot_df") is not None
    )
    deep_ok = bool(
        st.session_state.get("onboarding_deep_analysis_done") or st.session_state.get("last_analysis_ticker")
    )
    done = p2_onboarding_done_score(
        profile_ready=profile_ok,
        autopilot_ready=ap_ok,
        deep_analysis_ready=deep_ok,
    )
    progress_note = html.escape(p2_onboarding_progress_text(done))

    t_main = html.escape("Bắt đầu — 3 bước quyết định")
    t_badges = html.escape(
        f"Hồ sơ {'✓' if profile_ok else '…'} · Autopilot {'✓' if ap_ok else '…'} · Phân tích {'✓' if deep_ok else '…'}"
    )
    s1t = html.escape("1. Hồ sơ")
    s1b = html.escape("Cột trái → Cài đặt tài khoản: chọn khẩu vị + vốn (≥10 triệu). Free/Pro giới hạn quét khác nhau.")
    s2t = html.escape("2. Autopilot")
    s2b = html.escape(
        "Bật Auto Pilot — Top 10 từ quét đêm (~400 mã thanh khoản) nếu board sẵn; "
        "ưu tiên CONDITIONAL_BUY / BUY có playbook."
    )
    if lite_ui_mode:
        s3t = html.escape("3. Xem kết quả Lite")
        s3b = (
            "Chọn mã #1 từ Autopilot, bấm <strong>Phân tích ngay</strong>, "
            "xem thẻ quyết định + playbook trên Lite UI."
        )
    else:
        s3t = html.escape("3. Phân tích 1 mã")
        s3b = html.escape(
            "Chọn 1 mã (vd ACB/SHB), bấm Phân tích ngay — xem Thesis/Setup/Trigger, risk plan, DSS."
        )

    st.markdown(
        f"""
<div class="shop-welcome-wrap">
  <div class="shop-welcome-head">
    <div class="shop-welcome-title">{t_main}</div>
    <div class="shop-welcome-badges">{t_badges} · {progress_note}</div>
  </div>
  <div class="shop-step-grid">
    <div class="shop-step-card">
      <div class="shop-step-num">1</div>
      <div class="shop-step-title">{s1t}</div>
      <div class="shop-step-body">{s1b}</div>
    </div>
    <div class="shop-step-card">
      <div class="shop-step-num">2</div>
      <div class="shop-step-title">{s2t}</div>
      <div class="shop-step-body">{s2b}</div>
    </div>
    <div class="shop-step-card">
      <div class="shop-step-num">3</div>
      <div class="shop-step-title">{s3t}</div>
      <div class="shop-step-body">{s3b}</div>
    </div>
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1.4, 1])
    with c1:
        if st.button("→ Hồ sơ", key="qs_goto_profile", help="Mở bước hồ sơ ở sidebar"):
            # Don't write widget key `onboarding_p2_step` after radio exists — use intent + rerun.
            st.session_state["onboarding_p2_goto"] = "B1: Hồ sơ"
            st.toast("Mở Cài đặt tài khoản / Onboarding P2 → B1 ở cột trái.")
            st.rerun()
    with c2:
        if st.button("→ Autopilot", key="qs_goto_autopilot", help="Gợi ý bật Auto Pilot"):
            st.session_state["onboarding_p2_goto"] = "B2: Autopilot"
            st.session_state["force_show_autopilot"] = True
            st.toast("Bật Auto Pilot trong «Danh mục theo dõi».")
            st.rerun()
    with c3:
        if st.button("→ Phân tích mẫu", key="qs_goto_deep", help="Đặt mã mẫu để phân tích"):
            st.session_state["onboarding_p2_goto"] = "B3: Phân tích 1 mã"
            if not st.session_state.get("ticker"):
                st.session_state["ticker"] = "ACB"
            st.toast("Chọn mã rồi bấm Phân tích ngay.")
            st.rerun()
    with c4:
        if st.button("Ẩn hướng dẫn", key="hide_quickstart_strip", help="Ẩn trên trình duyệt này"):
            st.session_state[_SESSION_HIDE] = True
            st.rerun()

    if done >= 3:
        st.session_state["onboarding_p2_done"] = True


__all__ = ["render_app_quickstart_strip"]
