"""
Sidebar account/onboarding/billing orchestration panel.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import streamlit as st

from core.app_account_helpers import normalize_notify_channels, resolve_plan_index
from core.app_auth_gate import (
    clear_authenticated_session,
    is_authenticated_session,
    start_authenticated_session,
)
from core.app_onboarding_helpers import (
    is_watch_seed_ready,
    onboarding_done_score,
    onboarding_progress_text,
    p2_onboarding_done_score,
    p2_onboarding_progress_text,
    plan_feature_matrix,
    plan_packaging_caption,
    plan_usage_caption,
)
from core.app_view_helpers import normalize_watch_seed


@dataclass
class SidebarAccountState:
    user_id: str
    auth_ready: bool
    plan_label: str
    plan_id: str
    plan: dict[str, Any]
    profile: str
    total_capital_vnd: float
    tg_bot: str
    tg_chat: str
    webhook_url: str
    email_to: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    notify_cfg: Any


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def render_sidebar_auth_section(
    *,
    has_auth_user: Callable[[str], bool],
    verify_user_pin: Callable[[str, str], bool],
    register_user_pin: Callable[..., tuple[bool, str]],
) -> str:
    """
    Render duy nhất các thao tác được phép trước auth (đăng nhập/đăng ký).

    Trả user_id đang được yêu cầu để composition root gọi enforce_auth_gate()
    ngay sau hàm này, trước khi render các panel có mutation.
    """
    with st.expander("🔐 Đăng nhập", expanded=True):
        session_uid = str(st.session_state.get("user_id") or "").strip()
        user_id = str(st.text_input("Mã khách hàng", value=session_uid or "default_user") or "").strip()
        user_pin = st.text_input("PIN truy cập", value="", type="password")
        try:
            qp = st.query_params
            default_ref = str(qp.get("ref") or "").strip().upper()
        except Exception:
            default_ref = ""
        referrer_code = str(
            st.text_input("Mã giới thiệu (tuỳ chọn)", value=default_ref, key="signup_ref_code") or ""
        ).strip()
        c_auth1, c_auth2 = st.columns(2)
        with c_auth1:
            if st.button("Đăng nhập", width="stretch"):
                if has_auth_user(user_id):
                    if verify_user_pin(user_id, user_pin):
                        start_authenticated_session(user_id)
                        st.success("Đăng nhập thành công.")
                    else:
                        clear_authenticated_session()
                        st.error("PIN không đúng.")
                else:
                    clear_authenticated_session()
                    st.warning("Tài khoản chưa tồn tại. Bấm 'Đăng ký'.")
        with c_auth2:
            if st.button("Đăng ký", width="stretch"):
                clear_authenticated_session()
                ok_reg, msg_reg = register_user_pin(user_id, user_pin, referrer_code=referrer_code)
                if ok_reg:
                    st.success(f"{msg_reg} Vui lòng đăng nhập để tiếp tục.")
                else:
                    st.warning(msg_reg)

        if is_authenticated_session(user_id):
            st.caption(f"Đã xác thực: {user_id}")
            if st.button("Đăng xuất", width="stretch"):
                clear_authenticated_session()
                st.rerun()
        elif st.session_state.get("auth_ok"):
            # User input đã đổi so với identity của phiên: vô hiệu hóa ngay.
            clear_authenticated_session()
            st.warning("Mã khách hàng đã thay đổi. Vui lòng đăng nhập lại.")
    return user_id


def render_sidebar_account_sections(
    *,
    user_id: str,
    profile_options: dict[str, str],
    watchlist_default: list[str],
    has_auth_user: Callable[[str], bool],
    get_user_plan: Callable[[str, str], str],
    get_plan_features: Callable[[str], dict[str, Any]],
    set_user_plan: Callable[[str, str], None],
    render_notification_settings: Callable[..., Any],
    load_secret: Callable[..., Any],
    save_secret: Callable[..., Any],
    dispatch_text_notifications: Callable[..., Any],
    log_event: Callable[..., Any],
    process_notification_queue: Callable[..., dict[str, Any]],
    migrate_legacy_json_to_sqlite: Callable[[], dict[str, Any]],
    run_background_cycle: Callable[..., dict[str, Any]],
) -> SidebarAccountState:
    with st.expander("Cài đặt tài khoản", expanded=True):
        has_auth = has_auth_user(user_id)
        persisted_plan = get_user_plan(user_id, "free")
        plan_opts = ["Free", "Pro", "Expert"]
        plan_index = resolve_plan_index(persisted_plan, plan_opts)
        plan_label = st.selectbox("Gói dịch vụ", options=plan_opts, index=plan_index)
        plan_id = plan_label.lower()
        plan = get_plan_features(plan_id)
        set_user_plan(user_id, plan_id)
        profile_label = st.selectbox("Khẩu vị đầu tư", options=list(profile_options.keys()), index=1)
        profile = profile_options[profile_label]
        total_capital_vnd = float(
            st.number_input("Tổng vốn đầu tư (VND)", min_value=10_000_000.0, value=100_000_000.0, step=10_000_000.0)
        )
        st.caption(plan_packaging_caption(plan_id, plan))
        try:
            from core.product_layer import get_usage_today, list_alerts

            alerts_used = len(list_alerts(user_id))
            analysis_used = int(get_usage_today(user_id, "analysis") or 0)
            st.caption(
                plan_usage_caption(
                    plan_id=plan_id,
                    plan=plan,
                    alerts_used=alerts_used,
                    analysis_used=analysis_used,
                )
            )
        except Exception:
            pass
        notify_cfg = render_notification_settings(
            user_id,
            load_secret=load_secret,
            save_secret=save_secret,
            dispatch_text_notifications=dispatch_text_notifications,
        )
        notify_channels = normalize_notify_channels(notify_cfg)
        tg_bot = str(notify_channels["tg_bot"])
        tg_chat = str(notify_channels["tg_chat"])
        webhook_url = str(notify_channels["webhook_url"])
        email_to = str(notify_channels["email_to"])
        smtp_host = str(notify_channels["smtp_host"])
        smtp_port = _coerce_int(notify_channels["smtp_port"], 587)
        smtp_user = str(notify_channels["smtp_user"])
        smtp_password = str(notify_channels["smtp_password"])
        smtp_from = str(notify_channels["smtp_from"])
        auth_ready = bool(has_auth and is_authenticated_session(user_id))
        with st.expander("🚀 Onboarding P2 (3 bước)", expanded=not bool(st.session_state.get("onboarding_p2_done"))):
            profile_ready = bool(profile) and float(total_capital_vnd or 0) >= 10_000_000.0
            autopilot_ready = bool(st.session_state.get("autopilot_onboarding_seen") or st.session_state.get("autopilot_df") is not None)
            deep_ready = bool(st.session_state.get("onboarding_deep_analysis_done") or st.session_state.get("last_analysis_ticker"))
            # Apply quickstart navigation *before* the radio widget owns this key.
            _goto = st.session_state.pop("onboarding_p2_goto", None)
            _opts = ["B1: Hồ sơ", "B2: Autopilot", "B3: Phân tích 1 mã"]
            if _goto in _opts:
                st.session_state["onboarding_p2_step"] = _goto
            step_now = st.radio(
                "Chọn bước",
                options=_opts,
                horizontal=True,
                key="onboarding_p2_step",
            )
            if step_now.startswith("B1"):
                if profile_ready:
                    st.success("B1 OK: khẩu vị + vốn đã chọn.")
                else:
                    st.info("B1: chọn khẩu vị đầu tư và tổng vốn ở phần trên.")
            elif step_now.startswith("B2"):
                st.info("B2: bật **Auto Pilot** ở «Danh mục theo dõi», xem Top 10 (board đêm nếu có).")
                if st.button("Đánh dấu đã xem Autopilot", key="mark_ap_seen"):
                    st.session_state["autopilot_onboarding_seen"] = True
                    log_event(user_id, "onboarding_autopilot_seen", {"source": "sidebar"})
                    st.success("Đã ghi nhận B2.")
                if autopilot_ready:
                    st.success("B2 OK: Autopilot đã sẵn sàng / đã xem.")
            else:
                st.info("B3: chọn 1 mã (vd FPT/ACB) rồi bấm **🚀 Phân tích ngay** để xem phân tích chuyên sâu.")
                if st.button("Đánh dấu đã phân tích 1 mã", key="mark_deep_done"):
                    st.session_state["onboarding_deep_analysis_done"] = True
                    st.session_state["last_analysis_ticker"] = st.session_state.get("last_analysis_ticker") or "DONE"
                    log_event(user_id, "onboarding_deep_done", {"source": "sidebar"})
                    st.success("Đã ghi nhận B3.")
                if deep_ready:
                    st.success("B3 OK: đã có lần phân tích sâu.")
            done_p2 = p2_onboarding_done_score(
                profile_ready=profile_ready,
                autopilot_ready=autopilot_ready,
                deep_analysis_ready=deep_ready,
            )
            st.progress(done_p2 / 3.0, text=p2_onboarding_progress_text(done_p2))
            if done_p2 >= 3:
                if not st.session_state.get("onboarding_p2_done"):
                    log_event(user_id, "onboarding_p2_done", {"source": "sidebar"})
                st.session_state["onboarding_p2_done"] = True
                st.success("Onboarding P2 hoàn tất — bạn có thể ẩn hướng dẫn Quickstart.")

        try:
            from core.product_layer import can_use_feature as pl_can_use
        except Exception:
            pl_can_use = None
        from core.commercial_panel import render_commercial_pilot_panel

        render_commercial_pilot_panel(
            user_id=user_id,
            plan_id=plan_id,
            plan=plan,
            log_event=log_event,
            can_use_feature=pl_can_use,
            get_plan_features=get_plan_features,
        )

        with st.expander("🚀 Onboarding nền (auth / kênh / watch)", expanded=False):
            channel_ready = notify_cfg.has_any_channel()
            watch_seed = str(st.session_state.get("onboarding_watch_seed") or "FPT,HPG,VNM")
            watch_seed_ready = is_watch_seed_ready(watch_seed, minimum_symbols=3)
            step_now = st.radio(
                "Chọn bước nền",
                options=["B1: Tài khoản", "B2: Kênh gửi", "B3: Watchlist"],
                horizontal=True,
                key="onboarding_legacy_step",
            )
            if step_now == "B1: Tài khoản":
                if auth_ready:
                    st.success("B1 hoàn tất: tài khoản đã sẵn sàng.")
                else:
                    st.info("B1 chưa hoàn tất: đăng nhập bằng PIN để mở đầy đủ tính năng.")
            elif step_now == "B2: Kênh gửi":
                if channel_ready:
                    st.success("B2 hoàn tất: đã có ít nhất 1 kênh gửi hoạt động.")
                else:
                    st.info("B2 chưa hoàn tất: điền Telegram/Webhook/Email rồi bấm gửi test.")
            else:
                seed_default = str(st.session_state.get("onboarding_watch_seed") or "FPT,HPG,VNM")
                seed_watch = st.text_input("Watchlist gợi ý (phân tách bằng dấu phẩy)", value=seed_default)
                st.session_state["onboarding_watch_seed"] = seed_watch
                if st.button("Áp dụng watchlist gợi ý", width="stretch"):
                    cleaned = normalize_watch_seed(seed_watch.replace(" ", ","))
                    if cleaned:
                        st.session_state["onboarding_watch_seed"] = ",".join(cleaned)
                        st.success("Đã lưu watchlist gợi ý. Chọn mã bên dưới và bấm '🚀 Phân tích ngay'.")
                    else:
                        st.warning("Watchlist chưa hợp lệ. Ví dụ: FPT,HPG,VNM")
            done_score = onboarding_done_score(
                auth_ready=auth_ready,
                channel_ready=channel_ready,
                watch_seed_ready=watch_seed_ready,
            )
            st.progress(done_score / 3.0, text=onboarding_progress_text(done_score, total_steps=3))
        with st.expander("💳 Billing / Upgrade", expanded=False):
            import pandas as pd

            st.dataframe(pd.DataFrame(plan_feature_matrix()), width="stretch", hide_index=True)
            target_plan_label = st.selectbox("Nâng lên gói", options=["Pro", "Expert"], index=0)
            target_plan_id = target_plan_label.lower()
            if st.button("✅ Xác nhận nâng cấp (mock checkout)", width="stretch"):
                set_user_plan(user_id, target_plan_id)
                log_event(user_id, "upgrade_success", {"from": plan_id, "to": target_plan_id})
                st.success(f"Đã nâng gói lên {target_plan_label} (mock).")
            if st.button("🧪 Tôi quan tâm nâng cấp", width="stretch"):
                log_event(user_id, "upgrade_intent", {"from": plan_id, "to": target_plan_id})
                st.info("Đã ghi nhận tín hiệu quan tâm nâng cấp.")
            try:
                from core.referral_service import referral_code_for_user, referral_link_hint

                ref_code = referral_code_for_user(user_id)
                if ref_code:
                    st.caption(f"Giới thiệu bạn bè: mã **{ref_code}** — {referral_link_hint(user_id)}")
            except Exception:
                pass
        with st.expander("🛠️ Notification Queue", expanded=False):
            if st.button("Xử lý hàng đợi notification", width="stretch"):
                q_stat = process_notification_queue(max_jobs=30)
                st.session_state["cmd_last_queue_stat"] = dict(q_stat)
                st.session_state["cmd_last_queue_ts"] = time.time()
                st.caption(
                    f"Queue processed={q_stat['processed']} | sent={q_stat['sent']} | "
                    f"retried={q_stat['retried']} | failed={q_stat['failed']}"
                )
            if st.button("Migrate user_state.json -> SQLite", width="stretch"):
                mg = migrate_legacy_json_to_sqlite()
                st.caption(
                    f"Migrated users={mg['users']} | holdings={mg['holdings']} | "
                    f"alerts={mg['alerts']} | events={mg['events']}"
                )
            if st.button("Chạy 1 vòng background jobs", width="stretch"):
                bj = run_background_cycle(universe_limit=30, watchlist=watchlist_default, queue_jobs=30)
                st.caption(
                    f"Prefetch ok={bj['prefetch']['ok']}/{bj['prefetch']['total']} | "
                    f"Queue processed={bj['queue']['processed']}"
                )
    return SidebarAccountState(
        user_id=user_id,
        auth_ready=auth_ready,
        plan_label=plan_label,
        plan_id=plan_id,
        plan=plan,
        profile=profile,
        total_capital_vnd=float(total_capital_vnd),
        tg_bot=tg_bot,
        tg_chat=tg_chat,
        webhook_url=webhook_url,
        email_to=email_to,
        smtp_host=smtp_host,
        smtp_port=int(smtp_port),
        smtp_user=smtp_user,
        smtp_password=smtp_password,
        smtp_from=smtp_from,
        notify_cfg=notify_cfg,
    )

