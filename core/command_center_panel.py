from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd
import streamlit as st


def render_command_center_panel(
    *,
    ticker: str,
    watchlist: list[str],
    auth_ready: bool,
    bg_universe_limit: int,
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
    watchlist_default: list[str],
    process_notification_queue: Callable[..., dict[str, int]],
    run_background_cycle: Callable[..., dict[str, Any]],
    dispatch_text_notifications: Callable[..., dict[str, int]],
    upsert_daily_cx_score: Callable[[str, int, str], None],
    get_recent_cx_scores: Callable[..., list[dict[str, Any]]],
) -> dict[str, bool]:
    quick_run_analysis = False
    quick_autopilot_refresh = False
    quick_warm_async = False

    with st.expander("🧠 Smart Command Center", expanded=False):
        c_cmd1, c_cmd2 = st.columns(2)
        with c_cmd1:
            if st.button("⚡ Phân tích mã chọn", width="stretch"):
                quick_run_analysis = True
            if st.button("♻️ Quét lại cơ hội", width="stretch"):
                quick_autopilot_refresh = True
        with c_cmd2:
            if st.button("♨️ Warm nền ngay", width="stretch"):
                quick_warm_async = True
            if st.button("🛠️ Xử lý queue", width="stretch"):
                q_stat = process_notification_queue(max_jobs=30)
                st.session_state["cmd_last_queue_stat"] = dict(q_stat)
                st.session_state["cmd_last_queue_ts"] = time.time()
                st.caption(
                    f"Queue processed={q_stat['processed']} | sent={q_stat['sent']} | "
                    f"retried={q_stat['retried']} | failed={q_stat['failed']}"
                )
        if st.button("📨 Gửi Daily Playbook test", width="stretch"):
            ping = f"[PLAYBOOK TEST] {ticker} @ {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}"
            ping_stat = dispatch_text_notifications(
                ping,
                telegram_bot_token=tg_bot,
                telegram_chat_id=tg_chat,
                webhook_url=webhook_url,
                email_to=email_to,
                smtp_host=smtp_host,
                smtp_port=smtp_port,
                smtp_user=smtp_user,
                smtp_password=smtp_password,
                smtp_from=smtp_from,
            )
            st.caption(f"Playbook test sent={int(ping_stat.get('sent') or 0)} | failed={int(ping_stat.get('failed') or 0)}")
        rep_cache = st.session_state.get("report_cache") or {}
        last_latency = float(rep_cache.get("latency_seconds") or 0.0)
        warm_stat = st.session_state.get("bg_warm_last_stat") or {}
        warm_ts = float(st.session_state.get("bg_warm_last_ts") or 0.0)
        queue_stat = st.session_state.get("cmd_last_queue_stat") or {}
        queue_ts = float(st.session_state.get("cmd_last_queue_ts") or 0.0)
        now_ts = time.time()
        warm_age_min = ((now_ts - warm_ts) / 60.0) if warm_ts > 0 else -1.0
        queue_age_min = ((now_ts - queue_ts) / 60.0) if queue_ts > 0 else -1.0
        ch_ready = int(bool((tg_bot and tg_chat) or webhook_url or (email_to and smtp_host and smtp_user and smtp_password)))
        q_failed = int(queue_stat.get("failed") or 0)
        q_processed = int(queue_stat.get("processed") or 0)
        health_color = "🟢"
        health_label = "HEALTHY"
        if (last_latency > 0 and last_latency > 6.0) or (q_processed > 0 and q_failed > 0):
            health_color = "🟡"
            health_label = "DEGRADED"
        if (last_latency > 0 and last_latency > 10.0) or (q_processed > 0 and q_failed >= max(1, q_processed // 2)):
            health_color = "🔴"
            health_label = "CRITICAL"
        if ch_ready == 0:
            health_color = "🟡" if health_label == "HEALTHY" else health_color
            health_label = "DEGRADED" if health_label == "HEALTHY" else health_label
        st.caption("Health Snapshot")
        st.caption(f"{health_color} Overall: {health_label}")
        if health_label == "HEALTHY":
            st.success("Hệ thống đang ổn định. Duy trì nhịp theo dõi và phân tích bình thường.")
        elif health_label == "DEGRADED":
            st.warning("Khuyến nghị: chạy Queue + Warm nền + gửi test notification để ổn định lại.")
        else:
            st.error("Khuyến nghị khẩn: xử lý Queue ngay, warm nền, kiểm tra kênh gửi và giảm tải tác vụ nặng.")
        k1, k2, k3, k4 = st.columns(4)
        with k1:
            st.metric("Latency cuối", f"{last_latency:.2f}s" if last_latency > 0 else "N/A")
        with k2:
            if q_processed > 0:
                st.metric("Queue fail", f"{q_failed}/{q_processed}")
            else:
                st.metric("Queue fail", "N/A")
        with k3:
            if warm_age_min >= 0:
                st.metric("Warm gần nhất", f"{warm_age_min:.1f}m")
            else:
                st.metric("Warm gần nhất", "N/A")
        with k4:
            st.metric("Kênh gửi", "Ready" if ch_ready == 1 else "Missing")
        if queue_age_min >= 0:
            st.caption(f"Queue last run: {queue_age_min:.1f} phút trước | Warm ok={int(warm_stat.get('prefetch', {}).get('ok') or 0)}")
        cx_score = 0
        cx_score += 15 if auth_ready else 0
        cx_score += 20 if ch_ready == 1 else 0
        cx_score += 15 if len(watchlist) >= 3 else 5
        if last_latency <= 0:
            cx_score += 10
        elif last_latency <= 3.0:
            cx_score += 20
        elif last_latency <= 6.0:
            cx_score += 12
        else:
            cx_score += 4
        if q_processed <= 0:
            cx_score += 10
        elif q_failed == 0:
            cx_score += 20
        elif q_failed < max(1, q_processed // 4):
            cx_score += 10
        else:
            cx_score += 2
        if warm_age_min < 0:
            cx_score += 5
        elif warm_age_min <= 15:
            cx_score += 10
        elif warm_age_min <= 30:
            cx_score += 6
        else:
            cx_score += 2
        cx_score = max(0, min(100, int(cx_score)))
        cx_band = "Elite"
        if cx_score < 85:
            cx_band = "Good"
        if cx_score < 70:
            cx_band = "Needs tuning"
        if cx_score < 50:
            cx_band = "Risk"
        st.metric("Customer Experience Score", f"{cx_score}/100")
        st.caption(f"CX band: {cx_band}")
        last_cx_write_ts = float(st.session_state.get("cx_last_db_write_ts") or 0.0)
        if (now_ts - last_cx_write_ts) >= 60.0:
            upsert_daily_cx_score(user_id, cx_score, cx_band)
            st.session_state["cx_last_db_write_ts"] = now_ts
        history = st.session_state.get("cx_score_history")
        if not isinstance(history, list):
            history = []
        history.append(
            {
                "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "score": cx_score,
                "band": cx_band,
            }
        )
        st.session_state["cx_score_history"] = history[-20:]
        if len(st.session_state["cx_score_history"]) >= 2:
            prev = int(st.session_state["cx_score_history"][-2]["score"])
            delta = cx_score - prev
            st.caption(f"Trend phiên hiện tại: {delta:+d} điểm so với lần cập nhật trước.")
        with st.expander("Lịch sử Experience Score (phiên hiện tại)", expanded=False):
            st.dataframe(pd.DataFrame(st.session_state["cx_score_history"]), width="stretch", hide_index=True)
        with st.expander("Lịch sử Experience Score (theo ngày)", expanded=False):
            cx_daily = get_recent_cx_scores(user_id, days=14)
            if cx_daily:
                st.dataframe(pd.DataFrame(cx_daily), width="stretch", hide_index=True)
            else:
                st.caption("Chưa có dữ liệu theo ngày.")
        if health_label in ("DEGRADED", "CRITICAL"):
            if st.button("🩺 Auto-fix nhanh (Queue + Warm + Ping test)", width="stretch"):
                q_fix = process_notification_queue(max_jobs=30)
                st.session_state["cmd_last_queue_stat"] = dict(q_fix)
                st.session_state["cmd_last_queue_ts"] = time.time()
                warm_fix = run_background_cycle(
                    universe_limit=max(10, int(bg_universe_limit)),
                    watchlist=watchlist or watchlist_default,
                    queue_jobs=30,
                )
                st.session_state["bg_warm_last_stat"] = warm_fix
                st.session_state["bg_warm_last_ts"] = time.time()
                ping_fix = dispatch_text_notifications(
                    f"[AUTO-FIX TEST] {ticker} @ {datetime.now(timezone.utc).strftime('%H:%M:%SZ')}",
                    telegram_bot_token=tg_bot,
                    telegram_chat_id=tg_chat,
                    webhook_url=webhook_url,
                    email_to=email_to,
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    smtp_from=smtp_from,
                )
                st.success(
                    "Auto-fix hoàn tất | "
                    f"queue sent={int(q_fix.get('sent') or 0)}, failed={int(q_fix.get('failed') or 0)} | "
                    f"warm ok={int((warm_fix.get('prefetch') or {}).get('ok') or 0)} | "
                    f"ping sent={int(ping_fix.get('sent') or 0)}"
                )

    return {
        "quick_run_analysis": bool(quick_run_analysis),
        "quick_autopilot_refresh": bool(quick_autopilot_refresh),
        "quick_warm_async": bool(quick_warm_async),
    }
