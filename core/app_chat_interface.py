"""
Chat-first hybrid UI (Gemini/ChatGPT-style) + in-thread Decision Cards.

Presentation only — analysis/scan/notify go through ``core.ui_services`` /
``core.product_layer`` facades. No quant logic changes here.

Enable via ``II_CHAT_FIRST_UI=1`` (default) or session toggle in the shell.
"""

from __future__ import annotations

import html
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable

import streamlit as st

from core.analysis_helper_service import extract_ticker
from core.decision_action_gate import (
    apply_trade_plan_visibility,
    resolve_display_action,
    trade_plan_is_active,
)
from core.decision_card_panel import build_decision_card_payload

CHAT_MSG_KEY = "ii_chat_messages"
CHAT_PENDING_KEY = "ii_chat_pending_prompt"
CHAT_SETTINGS_KEY = "ii_chat_show_settings"

_ACTION_COLORS = {
    "BUY": ("#0d7a3a", "#e8f5ee"),
    "HOLD": ("#1a5fb4", "#e8f0fa"),
    "WATCH": ("#b8860b", "#fbf5e6"),
    "AVOID": ("#c0392b", "#fbeceb"),
}

_PHASE_VI = {
    "accumulation": "Tích lũy",
    "breakout": "Bùng nổ",
    "neutral": "Trung tính",
    "distribution": "Phân phối",
}


def chat_first_ui_enabled(*, default: bool = True) -> bool:
    raw = str(os.environ.get("II_CHAT_FIRST_UI", "1" if default else "0") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def inject_chat_ui_css() -> None:
    st.markdown(
        """
<style>
  .ii-chat-header {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 10px 4px 14px 4px; margin-bottom: 4px;
    border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  }
  .ii-chat-brand {
    font-family: "Segoe UI", "Helvetica Neue", sans-serif;
    font-size: 1.15rem; font-weight: 700; color: #0f172a; letter-spacing: -0.02em;
  }
  .ii-chat-brand span { font-weight: 500; color: #64748b; font-size: 0.85rem; margin-left: 6px; }
  .ii-status-pill {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 0.78rem; padding: 4px 10px; border-radius: 999px;
    background: #f1f5f9; color: #334155; border: 1px solid #e2e8f0;
  }
  .ii-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .ii-dot-ok { background: #16a34a; }
  .ii-dot-warn { background: #ca8a04; }
  .ii-dot-off { background: #94a3b8; }
  .ii-empty-hero {
    text-align: center; padding: 48px 16px 28px 16px; max-width: 720px; margin: 0 auto;
  }
  .ii-empty-hero h2 {
    font-size: 1.55rem; font-weight: 650; color: #0f172a; margin: 0 0 10px 0;
    letter-spacing: -0.03em; line-height: 1.35;
  }
  .ii-empty-hero p { color: #64748b; margin: 0 0 22px 0; font-size: 0.98rem; }
  .ii-chip-row { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 8px; }
  .ii-decision-card {
    border-radius: 16px; padding: 18px 20px; margin: 4px 0 10px 0;
    border: 1.5px solid #e2e8f0; background: #ffffff;
    box-shadow: 0 2px 8px rgba(15,23,42,0.05);
  }
  .ii-dc-head {
    display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between;
    gap: 12px; margin-bottom: 4px;
  }
  .ii-dc-title-row {
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 10px 14px;
  }
  .ii-dc-title { font-size: 1.35rem; font-weight: 800; color: #0f172a; letter-spacing: -0.02em; }
  .ii-dc-price {
    font-size: 24px; font-weight: 800; color: #0f172a; letter-spacing: -0.03em;
    line-height: 1.15; margin-top: 10px;
  }
  .ii-dc-price span { font-size: 0.95rem; font-weight: 600; color: #64748b; margin-left: 2px; }
  .ii-dc-fair {
    margin-top: 8px; font-size: 0.98rem; color: #334155; line-height: 1.5;
  }
  .ii-dc-fair b { color: #0f172a; }
  .ii-dc-mos-pos { color: #15803d; font-weight: 700; }
  .ii-dc-mos-neg { color: #b91c1c; font-weight: 700; }
  .ii-dc-mos-neu { color: #64748b; font-weight: 700; }
  .ii-dc-sub { font-size: 0.85rem; color: #64748b; margin-top: 6px; }
  .ii-badge {
    display: inline-block; font-weight: 700; font-size: 0.82rem;
    padding: 7px 14px; border-radius: 999px; letter-spacing: 0.02em;
    white-space: nowrap; align-self: flex-start;
  }
  .ii-dc-col {
    background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px;
    padding: 12px 14px; min-height: 168px; margin-bottom: 4px;
  }
  .ii-dc-col h4 {
    margin: 0 0 10px 0; font-size: 0.8rem; letter-spacing: 0.02em;
    color: #475569; font-weight: 700; text-transform: none;
  }
  .ii-dc-metric {
    font-size: 0.88rem; color: #334155; margin: 7px 0; line-height: 1.45;
  }
  .ii-dc-metric b { color: #0f172a; }
  .ii-dc-weak { color: #b91c1c; font-weight: 700; }
  .ii-dc-ok { color: #15803d; font-weight: 700; }
  .ii-plan-box {
    margin-top: 12px; padding: 12px 14px; border-radius: 12px;
    border: 1px solid #bbf7d0; background: #f0fdf4; color: #14532d;
    font-size: 0.9rem;
  }
  .ii-banner-watch {
    margin-top: 12px; padding: 12px 14px; border-radius: 12px;
    border: 1px solid #fde68a; background: #fffbeb; color: #92400e;
    font-size: 0.88rem; line-height: 1.45;
  }
  .ii-banner-avoid {
    margin-top: 12px; padding: 12px 14px; border-radius: 12px;
    border: 1px solid #fecaca; background: #fef2f2; color: #991b1b;
    font-size: 0.88rem; line-height: 1.45;
  }
  .ii-dc-foot { margin-top: 10px; font-size: 0.78rem; color: #94a3b8; }
  div[data-testid="stChatInput"] textarea {
    border-radius: 18px !important;
  }
</style>
        """,
        unsafe_allow_html=True,
    )


def _fmt(v: Any, *, digits: int = 1, suffix: str = "", money: bool = False) -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if money or abs(f) >= 1000:
        return f"{f:,.0f}{suffix}"
    return f"{f:.{digits}f}{suffix}"


def _cfo_status(cfo: Any) -> tuple[str, str]:
    if cfo is None or cfo == "":
        return "Thiếu CFO", "warn"
    try:
        v = float(cfo)
    except (TypeError, ValueError):
        return "CFO ?", "warn"
    if v < 0:
        return f"CFO âm ({_fmt(v, money=True)})", "bad"
    if v == 0:
        return "CFO = 0", "warn"
    return f"CFO dương ({_fmt(v, money=True)})", "ok"


def _ensure_chat_state() -> list[dict[str, Any]]:
    if CHAT_MSG_KEY not in st.session_state or not isinstance(st.session_state.get(CHAT_MSG_KEY), list):
        st.session_state[CHAT_MSG_KEY] = []
    return st.session_state[CHAT_MSG_KEY]


def _push_user(text: str) -> None:
    msgs = _ensure_chat_state()
    msgs.append(
        {
            "role": "user",
            "kind": "text",
            "content": str(text or "").strip(),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )


def _push_assistant(**payload: Any) -> None:
    msgs = _ensure_chat_state()
    row = {"role": "assistant", "ts": datetime.now(timezone.utc).isoformat()}
    row.update(payload)
    msgs.append(row)


def _cache_status_label() -> tuple[str, str]:
    """Return (label, level: ok|warn|off)."""
    try:
        from scrapers.portal import get_source_sla_report

        sla = get_source_sla_report() or {}
        if not isinstance(sla, dict) or not sla:
            return "Cache: sẵn sàng", "ok"
        fails = 0
        for v in sla.values():
            if isinstance(v, dict) and not v.get("ok", True):
                fails += 1
        if fails:
            return f"Cache/SLA: {fails} nguồn yếu", "warn"
        return "Cache: ổn", "ok"
    except Exception:
        return "Cache: —", "off"


def _telegram_status(*, tg_bot: str, tg_chat: str) -> tuple[str, str]:
    bot_ok = bool(str(tg_bot or "").strip())
    chat_ok = bool(str(tg_chat or "").strip())
    if bot_ok and chat_ok:
        return "Telegram: đã cấu hình", "ok"
    if bot_ok or chat_ok:
        return "Telegram: thiếu bot/chat", "warn"
    return "Telegram: chưa cấu hình", "off"


def render_chat_header(
    *,
    version: str = "1.0.2",
    tg_bot: str = "",
    tg_chat: str = "",
    on_settings_click: Callable[[], None] | None = None,
) -> None:
    tg_label, tg_lvl = _telegram_status(tg_bot=tg_bot, tg_chat=tg_chat)
    cache_label, cache_lvl = _cache_status_label()
    dot = {"ok": "ii-dot-ok", "warn": "ii-dot-warn", "off": "ii-dot-off"}

    left, right = st.columns([3.2, 1.0])
    with left:
        st.markdown(
            f"""
<div class="ii-chat-header">
  <div class="ii-chat-brand">Investment Intelligence <span>v{html.escape(version)}</span></div>
</div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            f"""
<span class="ii-status-pill"><span class="ii-dot {dot.get(tg_lvl, 'ii-dot-off')}"></span>{html.escape(tg_label)}</span>
&nbsp;
<span class="ii-status-pill"><span class="ii-dot {dot.get(cache_lvl, 'ii-dot-off')}"></span>{html.escape(cache_label)}</span>
            """,
            unsafe_allow_html=True,
        )
    with right:
        if st.button("⚙️ Cài đặt / Portfolio", key="ii_chat_settings_btn", use_container_width=True):
            st.session_state[CHAT_SETTINGS_KEY] = not bool(st.session_state.get(CHAT_SETTINGS_KEY))
            if on_settings_click:
                on_settings_click()
            st.rerun()


def render_empty_state(*, chip_callback: Callable[[str], None]) -> None:
    st.markdown(
        """
<div class="ii-empty-hero">
  <h2>Hôm nay bạn muốn phân tích hay tìm kiếm cơ hội cổ phiếu nào?</h2>
  <p>Nhập mã cổ phiếu, hoặc chọn nhanh một hành động bên dưới.</p>
</div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3, c4 = st.columns(4)
    chips = [
        (c1, "⚡ Autopilot Top 10 Sáng", "autopilot"),
        (c2, "📊 Phân tích PNJ", "analyze:PNJ"),
        (c3, "📈 Phân tích ACB", "analyze:ACB"),
        (c4, "🔔 Trạng thái Telegram", "telegram_status"),
    ]
    for col, label, token in chips:
        with col:
            if st.button(label, key=f"ii_chip_{token}", use_container_width=True):
                chip_callback(token)


def _pe_sanity_short(val: dict[str, Any]) -> str:
    notes = val.get("pe_sanity_notes") or []
    if isinstance(notes, list) and notes:
        return str(notes[0])[:90]
    warn = str(val.get("value_trap_warning") or "").strip()
    if "P/E" in warn or "EPS" in warn:
        return warn[:90]
    return "P/E ổn" if val.get("pe_current") not in (None, "") else "P/E —"


def _pe_sanity_label_vi(val: dict[str, Any]) -> str:
    raw = _pe_sanity_short(val)
    if raw in ("P/E ổn", "P/E —"):
        return "Hợp lý" if raw == "P/E ổn" else "Chưa xác định"
    if "méo" in raw.lower() or "lệch" in raw.lower() or "anomaly" in raw.lower():
        return "Cần thận trọng"
    return raw[:70]


def _mos_comment_vi(mos: Any) -> str:
    try:
        m = float(mos)
    except (TypeError, ValueError):
        return ""
    if m < 0:
        return "Thị giá cao hơn định giá"
    if m >= 20:
        return "Biên an toàn rộng"
    if m >= 10:
        return "Biên an toàn vừa phải"
    if m > 0:
        return "Biên an toàn hẹp"
    return "Hòa với định giá"


def _mos_header_bits(mos: Any) -> tuple[str, str, str]:
    """Trả (emoji_prefix, css_class, comment) cho dòng định giá/MOS."""
    try:
        m = float(mos)
    except (TypeError, ValueError):
        return "🛡️", "ii-dc-mos-neu", ""
    comment = _mos_comment_vi(m)
    if m < 0:
        return "🔴", "ii-dc-mos-neg", comment
    if m > 0:
        return "🟢", "ii-dc-mos-pos", comment
    return "🛡️", "ii-dc-mos-neu", comment


def _readiness_vi(raw: Any) -> str:
    key = str(raw or "").strip().upper()
    return {
        "HIGH": "Cao",
        "MEDIUM": "Trung bình",
        "MED": "Trung bình",
        "LOW": "Thấp",
        "CRITICAL": "Rất thấp",
    }.get(key, "Chưa xác định" if not key else key)


def _verdict_vi(raw: Any) -> str:
    key = str(raw or "").strip().upper()
    return {
        "NO-GO": "CHƯA ĐẠT DÒNG TIỀN",
        "GO": "ĐẠT",
        "CAUTION": "THẬN TRỌNG",
        "PASS": "ĐẠT",
        "HOLD": "GIỮ",
        "WATCH": "QUAN SÁT",
    }.get(key, "Chưa xác định" if not key else str(raw))


def _cfo_line_vi(cfo: Any) -> str:
    label, _lvl = _cfo_status(cfo)
    if label == "Thiếu CFO":
        return "Dòng tiền HĐKD (CFO): Đang cập nhật"
    if label.startswith("CFO âm"):
        return label.replace("CFO âm", "Dòng tiền HĐKD (CFO): Âm", 1)
    if label.startswith("CFO dương"):
        return label.replace("CFO dương", "Dòng tiền HĐKD (CFO): Dương", 1)
    if label == "CFO = 0":
        return "Dòng tiền HĐKD (CFO): Bằng 0"
    return f"Dòng tiền HĐKD (CFO): {label}"


def _earnings_quality_vi(label: str) -> str:
    raw = str(label or "").strip()
    low = raw.lower()
    if not raw or raw in ("—", "-"):
        return "Chưa xác định"
    if "thiếu cfo" in low:
        return "Cần thêm dữ liệu CFO"
    if ("cfo" in low and "âm" in low) or "cfo âm" in low:
        return "Cần thận trọng (CFO yếu)"
    return raw


def _smart_money_vi(label: Any) -> str:
    raw = str(label or "").strip()
    if not raw or raw in ("—", "Chưa đủ DL"):
        return "Chưa đủ dữ liệu"
    cleaned = re.sub(r"(?i)^smart\s*money\s*", "", raw).strip()
    return cleaned or "Trung tính"


def _fair_price_from_val(val: dict[str, Any]) -> Any:
    """Published fair price — ưu tiên best fair / composite; Graham vẫn fallback."""
    for key in (
        "best_fair_value",
        "composite_target_price",
        "graham_capped_fair",
        "intrinsic_value_graham",
        "graham_number",
        "safe_buy_price",
    ):
        v = val.get(key)
        try:
            if v is not None and float(v) > 0:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _action_badge_vi(action: str) -> str:
    """Same Vietnamese labels as Autopilot / action_display_vi (HOLD→GIỮ, WATCH→QUAN SÁT)."""
    from core.decision_action_gate import action_display_vi, normalize_action

    return action_display_vi(normalize_action(action))


def _disp(
    v: Any,
    *,
    digits: int = 1,
    suffix: str = "",
    money: bool = False,
    missing: str = "Chưa xác định",
) -> str:
    """Fail-soft display — không hiện None/NaN/—."""
    if v is None or v == "":
        return missing
    try:
        f = float(v)
    except (TypeError, ValueError):
        s = str(v).strip()
        if not s or s.lower() in ("none", "nan", "—", "-"):
            return missing
        return s
    if f != f:  # NaN
        return missing
    if money or abs(f) >= 1000:
        return f"{f:,.0f}{suffix}"
    return f"{f:.{digits}f}{suffix}"


def _fscore_provisional(*, cfo: Any, cr: Any, fin: dict[str, Any] | None = None, snap: dict[str, Any] | None = None) -> bool:
    """True khi thiếu CFO/CR — F-Score chỉ tạm tính, tránh hiểu nhầm 'Yếu'."""
    if cfo is None or cfo == "":
        return True
    if cr is None or cr == "":
        return True
    fin = fin if isinstance(fin, dict) else {}
    snap = snap if isinstance(snap, dict) else {}
    # Một số snapshot gắn cờ thiếu BCTC / piotroski partial
    for src in (fin, snap):
        if src.get("piotroski_partial_from") or src.get("financials_incomplete"):
            return True
        miss = src.get("missing_financial_fields") or src.get("missing_items")
        if isinstance(miss, (list, tuple, set)):
            joined = " ".join(str(x).lower() for x in miss)
            if "cfo" in joined or "cash" in joined or "current_ratio" in joined or "cr" in joined or "bctc" in joined:
                return True
    return False


def _fscore_text(fscore: Any, *, provisional: bool = False) -> str:
    try:
        n = int(float(fscore))
    except (TypeError, ValueError):
        return "Chưa xác định" if not provisional else "Đang chờ nạp BCTC"
    if provisional:
        return f"{n}/9 (Tạm tính - Đang chờ nạp BCTC) 🔴"
    if n <= 3:
        return f"{n}/9 — Yếu 🔴"
    if n <= 6:
        return f"{n}/9 — Trung bình"
    if n <= 8:
        return f"{n}/9 — Mạnh 🟢"
    return f"{n}/9 — Rất mạnh 🟢"


def _cfo_thesis_vi(cfo: Any, eq_label: str = "") -> str:
    line = _cfo_line_vi(cfo)
    # Bỏ prefix dài cho khối luận điểm
    short = line.replace("Dòng tiền HĐKD (CFO): ", "")
    if "Đang cập nhật" in short or "Cần thêm" in eq_label:
        return "Cần thêm dữ liệu"
    if short.startswith("Âm"):
        return f"Âm — cần thận trọng ({short})"
    if short.startswith("Dương"):
        return f"Dương ({short.replace('Dương ', '').strip() or 'ổn định'})"
    return short


def _cr_line_vi(cr: Any) -> str:
    try:
        v = float(cr)
    except (TypeError, ValueError):
        return "Thanh khoản (CR): Đang cập nhật"
    if v >= 1.5:
        return f"Thanh khoản (CR): {v:.2f} — Ổn định 🟢"
    if v >= 1.0:
        return f"Thanh khoản (CR): {v:.2f} — Cần theo dõi"
    return f"Thanh khoản (CR): {v:.2f} — Yếu 🔴"


def _pe_line_vi(val: dict[str, Any], price: Any) -> str:
    pe = val.get("pe_current")
    if pe in (None, ""):
        try:
            eps = float(val.get("eps_for_graham") or val.get("eps") or 0)
            px = float(price or 0)
            pe = (px / eps) if eps > 0 and px > 0 else None
        except (TypeError, ValueError):
            pe = None
    pe_txt = _disp(pe, digits=2, missing="Đang cập nhật")
    sanity = _pe_sanity_label_vi(val)
    return f"P/E hiện tại: {pe_txt} — Đánh giá: {sanity}"


def _strip_dividend_label(raw: str) -> str:
    """Tránh lặp 'Cổ tức: Cổ tức:' khi nhãn ngoài đã có sẵn."""
    s = str(raw or "").strip()
    for _ in range(4):
        nxt = re.sub(r"(?i)^\s*cổ\s*tức\s*[:：\-–—]?\s*", "", s).strip()
        if nxt == s:
            break
        s = nxt
    return s or "Đang cập nhật"


def _dividend_line_vi(rep: dict[str, Any], fin: dict[str, Any], snap: dict[str, Any]) -> str:
    """Trả nội dung cổ tức *không* kèm prefix 'Cổ tức:' (prefix gắn lúc render)."""
    for src in (fin, snap, rep):
        if not isinstance(src, dict):
            continue
        for k in ("dividend_yield_pct", "dividend_yield", "cash_dividend_yield_pct"):
            v = src.get(k)
            try:
                if v is not None and float(v) > 0:
                    fv = float(v)
                    # vnstock đôi khi trả 0.068 thay vì 6.8
                    if fv <= 1.5:
                        fv *= 100.0
                    return f"Tiền mặt — Yield ~{fv:.1f}%/năm"
            except (TypeError, ValueError):
                continue
        div_amt = src.get("dividend_per_share") or src.get("cash_dividend")
        try:
            if div_amt is not None and float(div_amt) > 0:
                return f"Tiền mặt ~{_disp(div_amt, money=True, missing='Đang cập nhật')} đ/cp"
        except (TypeError, ValueError):
            pass
    story = rep.get("story_catalysts") if isinstance(rep.get("story_catalysts"), dict) else {}
    dy = story.get("dividend_yield_pct") if isinstance(story, dict) else None
    try:
        if dy is not None and float(dy) > 0:
            fv = float(dy)
            if fv <= 1.5:
                fv *= 100.0
            return f"Tiền mặt — Yield ~{fv:.1f}%/năm"
    except (TypeError, ValueError):
        pass
    return "Đang cập nhật"


def _catalyst_lines(rep: dict[str, Any], sm_label: str, ph_vi: str) -> list[str]:
    lines: list[str] = []
    news = rep.get("news") if isinstance(rep.get("news"), list) else []
    for n in news[:2]:
        if isinstance(n, dict):
            t = str(n.get("title") or "").strip()
            if t:
                lines.append(t[:110] + ("…" if len(t) > 110 else ""))
        elif isinstance(n, str) and n.strip():
            lines.append(n.strip()[:110])
    macro = rep.get("macro") if isinstance(rep.get("macro"), dict) else {}
    bias = macro.get("bias_label_vi") or macro.get("note_vi") or macro.get("summary_vi")
    if bias:
        lines.append(str(bias)[:110])
    story = rep.get("story_catalysts") if isinstance(rep.get("story_catalysts"), dict) else {}
    for key in ("headline", "catalyst_summary", "summary_vi"):
        t = str(story.get(key) or "").strip()
        if t and t not in lines:
            lines.append(t[:110])
            break
    if sm_label and sm_label not in ("Chưa đủ dữ liệu", "Trung tính"):
        lines.append(f"Dòng tiền lớn: {sm_label}")
    if ph_vi:
        lines.append(f"Xu hướng kỹ thuật: {ph_vi}")
    if not lines:
        lines.append("Chưa có chất xúc tác nổi bật — đang cập nhật tin tức/vĩ mô.")
    return lines[:4]


def _invalidation_radar_vi(
    *,
    fscore: Any,
    cfo: Any,
    mos: Any,
    ph: str,
    action: str,
) -> list[str]:
    rules: list[str] = []
    try:
        fs = int(float(fscore))
        thr = 5 if fs >= 5 else max(3, fs)
        rules.append(f"Hạ khuyến nghị nếu F-Score < {thr}.")
    except (TypeError, ValueError):
        rules.append("Hạ khuyến nghị nếu sức khỏe tài chính (F-Score) suy yếu rõ.")
    _lab, lvl = _cfo_status(cfo)
    if lvl == "bad":
        rules.append("Giữ cảnh báo: dòng tiền HĐKD đang Âm — cần xác minh BCTC.")
    else:
        rules.append("Hạ khuyến nghị nếu dòng tiền HĐKD (CFO) chuyển Âm.")
    try:
        m = float(mos)
        if m >= 0:
            rules.append("Theo dõi nếu biên an toàn (MOS) chuyển âm sâu.")
    except (TypeError, ValueError):
        pass
    if ph == "distribution":
        rules.append("Xu hướng đang Phân phối — hủy giải ngân nếu giá thủng nền kèm thanh khoản tăng.")
    elif action in ("BUY", "HOLD"):
        rules.append("Hủy giải ngân nếu giá thủng vùng cắt lỗ kèm khối lượng tăng mạnh.")
    return rules[:4]


def _nav_priority_vi(action: str, mos: Any, readiness: str) -> str:
    a = str(action or "").upper()
    r = str(readiness or "").upper()
    try:
        m = float(mos) if mos is not None else None
    except (TypeError, ValueError):
        m = None
    if a == "BUY" and r in ("HIGH", "MEDIUM", "MED") and m is not None and m >= 15:
        return "15% – 20% Tổng tài khoản (Ưu tiên Cao)"
    if a == "BUY":
        return "8% – 12% Tổng tài khoản (Ưu tiên Trung bình)"
    if a == "HOLD":
        return "Giữ tỷ trọng hiện hữu — không giải ngân thêm vội"
    return "Chưa đề xuất tỷ trọng — đang quan sát"


def _company_title(symbol: str, company_name: str, val: dict[str, Any]) -> str:
    name = _company_name_only(symbol, company_name, val)
    return f"📌 {str(symbol).upper()} — {name}"


def _company_name_only(symbol: str, company_name: str, val: dict[str, Any]) -> str:
    name = (company_name or "").strip()
    if not name or name == "—":
        name = str(val.get("name") or val.get("industry_display_vi") or "").strip()
    if not name:
        name = str(val.get("industry_subtype_label_vi") or "Đang cập nhật tên doanh nghiệp")
    # Tránh lặp "FPT — FPT"
    if name.upper() == str(symbol or "").strip().upper():
        return str(val.get("industry_display_vi") or val.get("industry_subtype_label_vi") or name)
    return name


def _pe_number_txt(val: dict[str, Any], price: Any) -> str:
    pe = val.get("pe_current")
    if pe in (None, ""):
        try:
            eps = float(val.get("eps_for_graham") or val.get("eps") or 0)
            px = float(price or 0)
            pe = (px / eps) if eps > 0 and px > 0 else None
        except (TypeError, ValueError):
            pe = None
    return _disp(pe, digits=2, missing="—")


def _extract_ohlcv_price_series(ohlcv: Any) -> tuple[list[Any], list[float]]:
    """Fail-soft (dates, closes) — local copy to avoid Streamlit hot-reload ImportError."""
    if ohlcv is None:
        return [], []
    try:
        import pandas as pd

        if isinstance(ohlcv, pd.DataFrame):
            if ohlcv.empty or "close" not in ohlcv.columns:
                return [], []
            closes_raw = pd.to_numeric(ohlcv["close"], errors="coerce")
            dates_raw = ohlcv["date"] if "date" in ohlcv.columns else [None] * len(ohlcv)
            dates: list[Any] = []
            closes: list[float] = []
            for dt, v in zip(list(dates_raw), closes_raw.tolist()):
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if f == f and f > 0:
                    dates.append(dt)
                    closes.append(f)
            return dates, closes
    except Exception:
        pass
    if isinstance(ohlcv, (list, tuple)):
        closes2: list[float] = []
        for v in ohlcv:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f == f and f > 0:
                closes2.append(f)
        return [None] * len(closes2), closes2
    return [], []


def _series_looks_fresh(
    dates: list[Any],
    closes: list[float],
    *,
    live_price: Any = None,
    max_age_days: int = 14,
    max_price_divergence: float = 0.12,
) -> bool:
    """Reject stale/mismatched OHLCV so chart endpoint matches Giá hiện tại."""
    if len(closes) < 2:
        return False
    # Calendar freshness of last bar.
    last_dt = None
    for d in reversed(dates or []):
        if d is None or d == "":
            continue
        try:
            import pandas as pd

            ts = pd.to_datetime(d, errors="coerce")
            if ts is not None and str(ts) != "NaT":
                last_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
                break
        except Exception:
            continue
    if last_dt is not None:
        try:
            age = (datetime.now(timezone.utc).date() - last_dt.date()).days
            if age > int(max_age_days):
                return False
        except Exception:
            pass
    # Live price vs last close — catch stale store still within age window.
    if live_price not in (None, ""):
        try:
            px = float(live_price)
            last = float(closes[-1])
            if px > 0 and last > 0:
                div = abs(px - last) / max(px, last)
                if div > float(max_price_divergence):
                    return False
        except (TypeError, ValueError):
            pass
    return True


def _align_chart_endpoint_to_live(
    dates: list[Any],
    closes: list[float],
    live_price: Any,
) -> tuple[list[Any], list[float]]:
    """Pin last chart point to live quote when mildly divergent (intraday)."""
    if live_price in (None, "") or len(closes) < 2:
        return dates, closes
    try:
        px = float(live_price)
        last = float(closes[-1])
    except (TypeError, ValueError):
        return dates, closes
    if px <= 0 or last <= 0:
        return dates, closes
    div = abs(px - last) / max(px, last)
    if div < 0.002 or div > 0.12:
        # Identical enough, or too large (needs full refresh — don't fake cliff).
        return dates, closes
    out_d = list(dates)
    out_c = list(closes)
    out_c[-1] = px
    try:
        out_d[-1] = datetime.now(timezone.utc)
    except Exception:
        pass
    return out_d, out_c


def _load_mini_chart_series(
    symbol: str,
    *,
    live_price: Any = None,
) -> tuple[list[Any], list[float]]:
    """Load ~1y closes+dates for Decision Card chart (prefer fresh portal over stale store)."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return [], []
    sessions = 280  # ~1 năm phiên giao dịch

    candidates: list[tuple[list[Any], list[float]]] = []

    # 1) Session cache from full analysis (if same ticker).
    try:
        cached = st.session_state.get("ohlcv_cache")
        dates, closes = _extract_ohlcv_price_series(cached)
        if len(closes) >= 2:
            last_sym = str(
                st.session_state.get("last_analyzed_ticker") or st.session_state.get("ticker") or ""
            ).upper()
            if not last_sym or last_sym == sym:
                candidates.append((dates[-sessions:], closes[-sessions:]))
    except Exception:
        pass

    # 2) Portal fetch first — refreshes when store calendar-stale.
    try:
        from scrapers.portal import fetch_ohlcv_history

        dates, closes = _extract_ohlcv_price_series(fetch_ohlcv_history(sym, sessions=sessions))
        if len(closes) >= 2:
            candidates.append((dates, closes))
    except Exception:
        pass

    # 3) Local OHLCV store fallback.
    try:
        from core.ohlcv_store import load_recent_ohlcv

        dates, closes = _extract_ohlcv_price_series(load_recent_ohlcv(sym, sessions=sessions))
        if len(closes) >= 2:
            candidates.append((dates, closes))
    except Exception:
        pass

    # Prefer series that matches live price / recent dates.
    fresh = [
        (d, c)
        for d, c in candidates
        if _series_looks_fresh(d, c, live_price=live_price)
    ]
    if fresh:
        chosen_dates, chosen_closes = fresh[0]
    elif candidates:
        # Giá UI đang mock/sai (vd. 98k) trong khi OHLCV thị trường ~70k — vẫn vẽ chuỗi thị trường.
        # Ưu tiên series có ngày gần nhất.
        def _last_ts(pair: tuple[list[Any], list[float]]) -> float:
            try:
                import pandas as pd

                return float(pd.Timestamp(pair[0][-1]).timestamp())
            except Exception:
                return 0.0

        chosen_dates, chosen_closes = max(candidates, key=_last_ts)
        try:
            last_px = float(chosen_closes[-1])
            if live_price and live_price > 0 and last_px > 0:
                rel = abs(last_px - float(live_price)) / max(last_px, float(live_price))
                if rel > 0.12:
                    # Endpoint chart = nến cuối; card sẽ được refresh giá live riêng.
                    pass
        except Exception:
            pass
    else:
        return [], []
    if not chosen_closes:
        return [], []
    return _align_chart_endpoint_to_live(chosen_dates, chosen_closes, live_price)


def render_decision_card_in_chat(
    report: dict[str, Any] | None,
    *,
    symbol: str,
    company_name: str = "",
    key_prefix: str = "dc",
    on_add_telegram_alert: Callable[[str], None] | None = None,
) -> None:
    """Thẻ Quyết định — dashboard hiện đại (presentation only)."""
    from core.decision_card_dashboard import (
        build_decision_dashboard_html,
        build_price_chart_svg,
        render_decision_dashboard,
    )
    from core.decision_action_gate import align_report_action_with_autopilot_board

    # Lock action to Autopilot board when available — one label for Top + deep card.
    report = align_report_action_with_autopilot_board(
        report if isinstance(report, dict) else {},
        symbol=symbol,
    )
    rep = apply_trade_plan_visibility(report if isinstance(report, dict) else {})
    gate = resolve_display_action(rep)
    card = build_decision_card_payload(rep, symbol=symbol)
    action = str(card.get("action") or "WATCH").upper()
    accent, soft = _ACTION_COLORS.get(action, ("#64748b", "#f8fafc"))
    badge = _action_badge_vi(action)

    val = rep.get("valuation") if isinstance(rep.get("valuation"), dict) else {}
    fin = rep.get("financials") if isinstance(rep.get("financials"), dict) else {}
    phase = rep.get("phase") if isinstance(rep.get("phase"), dict) else {}
    deep = rep.get("deep_insight") if isinstance(rep.get("deep_insight"), dict) else {}
    eq = deep.get("earnings_quality") if isinstance(deep.get("earnings_quality"), dict) else {}
    sm = deep.get("smart_money_flow") if isinstance(deep.get("smart_money_flow"), dict) else {}
    rp = rep.get("risk_plan") if isinstance(rep.get("risk_plan"), dict) else {}
    snap = rep.get("snapshot") if isinstance(rep.get("snapshot"), dict) else {}

    cfo = fin.get("operating_cash_flow")
    if cfo is None:
        cfo = snap.get("operating_cash_flow")
    cfo_prior = fin.get("operating_cash_flow_prior")
    if cfo_prior is None:
        cfo_prior = snap.get("operating_cash_flow_prior")
    cfo_txt, _ = _cfo_status(cfo)
    eq_label = _earnings_quality_vi(str(eq.get("label") or ""))
    ph = str(phase.get("phase") or "neutral")
    ph_vi = _PHASE_VI.get(ph, "Trung tính")
    sm_label = _smart_money_vi(sm.get("label") or sm.get("bias") or "")
    fscore = val.get("piotroski_score")
    mos = val.get("margin_of_safety_composite_pct")
    price = card.get("price") if card.get("price") not in (None, "") else val.get("price")
    if price in (None, ""):
        price = snap.get("price")
    fair = _fair_price_from_val(val)
    _mos_emoji, _mos_cls, mos_comment = _mos_header_bits(mos)
    try:
        mos_f = float(mos) if mos not in (None, "") else None
    except (TypeError, ValueError):
        mos_f = None
    mos_disp = _disp(mos, suffix="%", missing="Đang cập nhật")
    if mos_f is not None and mos_f > 0 and not str(mos_disp).startswith("+") and mos_disp != "Đang cập nhật":
        mos_disp = f"+{mos_disp}"

    cr = fin.get("current_ratio")
    if cr is None:
        cr = val.get("current_ratio") or snap.get("current_ratio")
    fscore_prov = _fscore_provisional(cfo=cfo, cr=cr, fin=fin, snap=snap)
    cr_ready = False
    try:
        cr_ready = cr is not None and cr != "" and float(cr) > 0
    except (TypeError, ValueError):
        cr_ready = False

    show_plan = trade_plan_is_active(rep) and bool(
        gate.get("show_trade_plan") or gate.get("risk_management_visible")
    ) and action in ("BUY", "HOLD", "CONDITIONAL_BUY")
    entry_allowed = bool(gate.get("entry_allowed", action in ("BUY", "CONDITIONAL_BUY")))
    if "entry_allowed" in rep:
        entry_allowed = bool(rep.get("entry_allowed"))
    pe_anomaly = bool(val.get("pe_anomaly_flag") or val.get("eps_anomaly_flag"))
    anomaly_msg = str(
        val.get("eps_pe_anomaly_warning_vi")
        or "P/E có dấu hiệu méo do lợi nhuận đột biến. Biên an toàn đã được điều chỉnh thận trọng."
    ).strip()

    buy_hi = rp.get("buy_zone_high") or rp.get("entry_price") or card.get("entry")
    buy_lo = rp.get("buy_zone_low")
    safe_zone = ""
    if entry_allowed and buy_hi not in (None, ""):
        safe_zone = f"≤ {_disp(buy_hi, money=True, missing='Đang cập nhật')} đ"
        if buy_lo not in (None, ""):
            safe_zone = (
                f"{_disp(buy_lo, money=True, missing='Đang cập nhật')} – "
                f"{_disp(buy_hi, money=True, missing='Đang cập nhật')} đ"
            )
    elif action == "HOLD":
        safe_zone = "Không mở mua mới"
    nav_line = _nav_priority_vi(action, mos, str(card.get("readiness") or ""))
    pos_pct = rp.get("max_position_pct")
    if show_plan and entry_allowed and pos_pct not in (None, ""):
        try:
            nav_line = f"{float(pos_pct):.0f}% Tổng tài khoản (theo kế hoạch rủi ro)"
        except (TypeError, ValueError):
            pass
    elif action == "HOLD":
        nav_line = "0% giải ngân mới — quản trị vị thế đang nắm"

    name_only = _company_name_only(symbol, company_name, {**val, **snap})
    legend = str(val.get("instant_conclusion") or "Đang cập nhật")
    catalyst_lines = _catalyst_lines(rep, sm_label, ph_vi)
    radar = _invalidation_radar_vi(fscore=fscore, cfo=cfo, mos=mos, ph=ph, action=action)
    dividend_line = _strip_dividend_label(_dividend_line_vi(rep, fin, snap))
    price_txt = _disp(price, money=True, missing="Đang cập nhật")
    fair_txt = _disp(fair, money=True, missing="Đang cập nhật")
    integrity_blocked = bool(
        card.get("mos_integrity_blocked")
        or card.get("fair_value_unreliable")
        or card.get("fair_price_unreliable")
        or val.get("mos_integrity_blocked")
        or val.get("fair_value_unreliable")
    )
    integrity_note = str(
        card.get("mos_integrity_note_vi")
        or val.get("fair_value_suppress_reason_vi")
        or val.get("mos_integrity_note_vi")
        or ""
    ).strip()
    if not integrity_note and integrity_blocked:
        notes = val.get("pe_sanity_notes") or []
        if isinstance(notes, list) and notes:
            integrity_note = str(notes[0] or "").strip()
        if not integrity_note:
            integrity_note = (
                "Định giá Graham vẫn theo mô hình, nhưng nghi EPS/P/E lệch đơn vị — không dùng để giải ngân."
            )
    mos_raw_val = card.get("mos_pct_raw")
    if mos_raw_val in (None, ""):
        mos_raw_val = val.get("margin_of_safety_composite_pct_raw")
    mos_raw_disp = ""
    try:
        if mos_raw_val not in (None, ""):
            mos_raw_f = float(mos_raw_val)
            mos_raw_disp = f"{mos_raw_f:+.1f}%"
    except (TypeError, ValueError):
        mos_raw_disp = ""
    if integrity_blocked:
        mos_comment = (
            f"Đã siết (MOS thô {mos_raw_disp}) — không dùng để giải ngân"
            if mos_raw_disp
            else "Định giá Graham tham khảo — không dùng để giải ngân"
        )

    locked_reason = (
        f"Chưa đủ điều kiện an toàn để đề xuất điểm Mua/Cắt lỗ "
        f"(Khuyến nghị: {badge})."
    )
    if "âm" in cfo_txt.lower() or str(card.get("verdict") or "").upper() == "NO-GO":
        locked_reason += (
            f" Lý do chính: {_verdict_vi(card.get('verdict'))}"
            + (" · Dòng tiền HĐKD âm" if "âm" in cfo_txt.lower() else "")
        )

    entry_disp = (
        html.escape(_disp(rp.get("entry_price") or card.get("entry"), money=True, missing="Đang cập nhật")) + " đ"
        if entry_allowed
        else "Không mở mua mới"
    )
    sl_disp = html.escape(
        _disp(rp.get("stop_loss_price") or card.get("sl"), money=True, missing="Đang cập nhật")
    )
    tp_disp = html.escape(
        _disp(rp.get("take_profit_price") or card.get("tp"), money=True, missing="Đang cập nhật")
    )
    plan_note = str(rp.get("display_note_vi") or "").strip()
    plan_note_html = (
        f"<br/><span style='color:#64748b;font-size:0.92em;'>{html.escape(plan_note)}</span>"
        if plan_note
        else ""
    )
    if entry_allowed:
        plan_inner = (
            f"<b>Vùng giá giải ngân an toàn:</b> {html.escape(safe_zone or 'Đang cập nhật')}<br/><br/>"
            f"<b>Tỷ trọng đề xuất (% NAV):</b> {html.escape(nav_line)}<br/><br/>"
            f"<b>Giá mua / Cắt lỗ / Chốt lời:</b> "
            f"{entry_disp} · {sl_disp} đ · {tp_disp} đ"
            f"{plan_note_html}"
        )
    else:
        # HOLD: khóa Entry, bắt buộc hiện SL / quản trị rủi ro
        plan_inner = (
            f"<b>Vùng mua (Entry):</b> {entry_disp}<br/><br/>"
            f"<b>Tỷ trọng giải ngân mới:</b> {html.escape(nav_line)}<br/><br/>"
            f"<b>Cắt lỗ (SL) / Chốt lời (TP):</b> {sl_disp} đ · {tp_disp} đ<br/><br/>"
            f"<b>Vùng quản trị rủi ro:</b> theo dõi SL / trailing stop để bảo vệ vị thế đang nắm."
            f"{plan_note_html}"
        )

    chart_dates, chart_closes = _load_mini_chart_series(str(symbol).upper(), live_price=price)
    price_chart_html = build_price_chart_svg(chart_closes, dates=chart_dates)

    body = build_decision_dashboard_html(
        symbol=str(symbol).upper(),
        company_name=name_only,
        price_txt=price_txt,
        fair_txt=fair_txt,
        mos_disp=mos_disp,
        mos_f=mos_f,
        mos_comment=mos_comment,
        legend=legend if legend not in ("—", "") else "Đang cập nhật",
        badge=badge,
        accent=accent,
        soft=soft,
        fscore_txt=_fscore_text(fscore, provisional=fscore_prov),
        fscore=fscore,
        fscore_prov=fscore_prov,
        cfo_txt=_cfo_thesis_vi(cfo, eq_label),
        cfo=cfo,
        cfo_prior=cfo_prior,
        cr_txt=_cr_line_vi(cr),
        cr_ready=cr_ready,
        pe_txt=_pe_line_vi(val, price),
        pe_num=_pe_number_txt(val, price),
        eq_label=eq_label,
        dividend_line=dividend_line,
        catalyst_lines=catalyst_lines,
        confidence_pct=card.get("confidence_pct"),
        readiness_vi=_readiness_vi(card.get("readiness")),
        show_plan=show_plan,
        plan_html_inner=plan_inner,
        locked_reason=locked_reason,
        radar=radar,
        price_chart_html=price_chart_html,
        valuation_integrity_blocked=integrity_blocked,
        valuation_integrity_note=integrity_note,
        fair_method_label=str(
            card.get("fair_method_label_vi") or val.get("best_fair_label_vi") or ""
        ),
        mos_raw_disp=mos_raw_disp,
    )

    with st.container(border=False):
        render_decision_dashboard(body)
        if pe_anomaly:
            st.warning(f"⚠️ Cảnh báo định giá: {anomaly_msg}")
        elif integrity_blocked and integrity_note:
            st.warning(f"⚠️ Cảnh báo định giá: {integrity_note}")

        b1, b2 = st.columns(2)
        with b1:
            with st.expander("✨ Xem Báo Cáo 7 Lý Do Chi Tiết (7 Whys)", expanded=False):
                whys = rep.get("whys_steps") or (rep.get("recommendation") or {}).get("whys_steps") or []
                if isinstance(whys, list) and whys:
                    for i, w in enumerate(whys[:12], 1):
                        st.markdown(f"{i}. {w}")
                else:
                    thesis = rep.get("thesis") or rep.get("summary_vi") or rep.get("advice")
                    if thesis:
                        st.write(thesis)
                    else:
                        st.caption("Chưa có báo cáo 7 lý do — đang cập nhật hoặc mở giao diện phân tích sâu.")
                risks = rep.get("risks") or []
                if isinstance(risks, list) and risks:
                    st.markdown("**Rủi ro**")
                    for r in risks[:6]:
                        st.markdown(f"- {r}")
        with b2:
            if st.button(
                "🔔 Thêm Mã Này Vào Cảnh Báo Telegram",
                key=f"{key_prefix}_tg_{symbol}",
                use_container_width=True,
            ):
                if on_add_telegram_alert:
                    on_add_telegram_alert(str(symbol).upper())
                else:
                    st.warning("Chưa gắn handler cảnh báo Telegram.")


def _load_analysis_report(
    symbol: str,
    *,
    profile: str,
    capital: float,
    load_snapshot_cached: Callable[..., Any],
    load_strategic_report_cached: Callable[..., Any],
    quick_mode: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None, None, "Ticker rỗng."
    try:
        snap = load_snapshot_cached(sym)
    except Exception as exc:
        return None, None, f"Snapshot lỗi: {exc.__class__.__name__}"
    if not snap:
        return None, None, f"Không lấy được snapshot cho {sym}."
    # Giá phải mới tại thời điểm khách yêu cầu — không dùng OHLCV/kho cũ.
    try:
        from scrapers.financial_data import ensure_request_time_live_price

        snap = ensure_request_time_live_price(dict(snap), sym)
    except Exception:
        snap = dict(snap) if isinstance(snap, dict) else snap
    try:
        rep = load_strategic_report_cached(
            sym,
            snap,
            profile,
            float(capital),
            quick_mode=bool(quick_mode),
        )
    except Exception as exc:
        return snap if isinstance(snap, dict) else None, None, f"Report lỗi: {exc.__class__.__name__}"
    if not isinstance(rep, dict):
        return snap if isinstance(snap, dict) else None, None, "Report rỗng."
    # Đồng bộ giá live vào valuation hiển thị (tránh cache cũ).
    try:
        px = float((snap or {}).get("price") or 0)
        if px > 0 and isinstance(rep.get("valuation"), dict):
            rep = dict(rep)
            val = dict(rep["valuation"])
            val["price"] = px
            if snap.get("price_source"):
                val["price_source"] = snap.get("price_source")
            if snap.get("price_crosscheck_note_vi"):
                rep["price_crosscheck_note_vi"] = snap.get("price_crosscheck_note_vi")
            rep["valuation"] = val
            rep["snapshot"] = snap
    except Exception:
        pass
    return snap if isinstance(snap, dict) else None, apply_trade_plan_visibility(rep), None


def _handle_prompt(
    prompt: str,
    *,
    profile: str,
    capital: float,
    tg_bot: str,
    tg_chat: str,
    load_snapshot_cached: Callable[..., Any],
    load_strategic_report_cached: Callable[..., Any],
    load_autopilot_board: Callable[..., Any],
    autopilot_limit: int,
    can_use_feature: Callable[..., Any] | None,
    user_id: str,
    plan: dict[str, Any] | None,
    add_alert: Callable[..., Any] | None,
    log_event: Callable[..., Any] | None,
    dispatch_text_notifications: Callable[..., Any] | None,
    notify_cfg: dict[str, Any] | None,
) -> None:
    text = str(prompt or "").strip()
    if not text:
        return

    low = text.lower()
    token = text
    if text.startswith("analyze:"):
        token = text
        _push_user(f"Phân tích {text.split(':', 1)[-1].upper()}")
    elif text == "autopilot":
        _push_user("Autopilot Top 10 Sáng")
    elif text == "telegram_status":
        _push_user("Trạng thái Telegram")
    else:
        _push_user(text)

    # --- Telegram status ---
    if token == "telegram_status" or ("telegram" in low and "trạng thái" in low) or low.strip() in (
        "telegram",
        "tg",
        "trạng thái telegram",
    ):
        label, lvl = _telegram_status(tg_bot=tg_bot, tg_chat=tg_chat)
        _push_assistant(
            kind="text",
            content=(
                f"**{label}**\n\n"
                f"- Bot token: {'đã có' if str(tg_bot or '').strip() else 'chưa có'}\n"
                f"- Chat ID: {'đã có' if str(tg_chat or '').strip() else 'chưa có'}\n"
                f"- Mức: `{lvl}`\n\n"
                "Cấu hình trong sidebar **Cài đặt thông báo** (hoặc nút ⚙️)."
            ),
        )
        return

    # --- Autopilot board ---
    if token == "autopilot" or "autopilot" in low or "top 10" in low:
        if can_use_feature and user_id:
            try:
                ok, reason = can_use_feature(user_id, "scan", requested=1)
                if not ok:
                    _push_assistant(kind="text", content=f"Không đủ quota Autopilot: {reason}")
                    return
            except Exception:
                pass
        try:
            df = load_autopilot_board(
                str(profile or "growth"),
                int(autopilot_limit or 30),
                200_000.0,
            )
        except Exception as exc:
            _push_assistant(kind="text", content=f"Autopilot lỗi: {exc.__class__.__name__}")
            return
        if df is None or getattr(df, "empty", True):
            _push_assistant(
                kind="text",
                content="Autopilot chưa có dữ liệu. Chạy nightly scan hoặc bật ép quét live trong chế độ cổ điển.",
            )
            return
        lines = ["**Autopilot Top 10** (board hiện tại · MOS = định giá công bố):", ""]
        from core.decision_action_gate import action_display_vi, normalize_action

        for i, row in df.head(10).iterrows():
            sym = str(row.get("Mã") or "")
            kn_raw = str(row.get("Khuyến nghị") or row.get("gate_action") or "WATCH")
            kn = action_display_vi(normalize_action(kn_raw))
            mos = row.get("MOS%")
            er = row.get("Expected Return %")
            fair = row.get("Fair")
            fair_bit = f" · Đ.giá {_fmt(fair, money=True)}" if fair not in (None, "") else ""
            lines.append(
                f"{len(lines) - 1}. **{sym}** · {kn} · MOS {_fmt(mos, suffix='%')} · ER {_fmt(er, suffix='%')}{fair_bit}"
            )
        lines.append("")
        lines.append(
            "MOS Autopilot đồng bộ best-fair (cùng công thức Decision Card). "
            "Gõ mã (vd: `BID`) để mở thẻ chi tiết."
        )
        _push_assistant(kind="text", content="\n".join(lines))
        if log_event and user_id:
            try:
                log_event(user_id, "chat_autopilot", {"rows": int(len(df))})
            except Exception:
                pass
        return

    # --- Analyze symbol ---
    sym = ""
    if token.startswith("analyze:"):
        sym = token.split(":", 1)[-1].strip().upper()
    else:
        # Prefer explicit patterns
        m = re.search(r"(?:phân tích|analyze|check)\s+([A-Za-z0-9]{2,6})", text, flags=re.I)
        if m:
            sym = m.group(1).upper()
        else:
            sym = extract_ticker(text) or ""

    if not sym:
        _push_assistant(
            kind="text",
            content=(
                "Mình chưa nhận ra mã cổ phiếu. Thử:\n"
                "- `PNJ` hoặc `phân tích ACB`\n"
                "- Chip **Autopilot Top 10 Sáng**\n"
                "- Chip **Trạng thái Telegram**"
            ),
        )
        return

    if can_use_feature and user_id:
        try:
            ok, reason = can_use_feature(user_id, "analysis", requested=1)
            if not ok:
                _push_assistant(kind="text", content=f"Không đủ quota phân tích: {reason}")
                return
        except Exception:
            pass

    snap, rep, err = _load_analysis_report(
        sym,
        profile=profile,
        capital=capital,
        load_snapshot_cached=load_snapshot_cached,
        load_strategic_report_cached=load_strategic_report_cached,
        quick_mode=False,
    )
    if err or not rep:
        _push_assistant(kind="text", content=err or f"Không phân tích được {sym}.")
        return

    name = ""
    if isinstance(snap, dict):
        name = str(snap.get("name") or snap.get("industry") or "")
    _push_assistant(kind="decision_card", symbol=sym, company_name=name, report=rep)
    if log_event and user_id:
        try:
            from core.decision_action_gate import align_report_action_with_autopilot_board

            synced = align_report_action_with_autopilot_board(rep, symbol=sym)
            gate = resolve_display_action(synced)
            log_event(
                user_id,
                "chat_analyze",
                {"symbol": sym, "action": gate.get("display_action"), "verdict": synced.get("analysis_verdict")},
            )
        except Exception:
            pass


def render_chat_messages(
    *,
    on_add_telegram_alert: Callable[[str], None] | None = None,
) -> None:
    msgs = _ensure_chat_state()
    for i, msg in enumerate(msgs):
        role = str(msg.get("role") or "assistant")
        with st.chat_message(role):
            kind = str(msg.get("kind") or "text")
            if kind == "decision_card":
                render_decision_card_in_chat(
                    msg.get("report"),
                    symbol=str(msg.get("symbol") or ""),
                    company_name=str(msg.get("company_name") or ""),
                    key_prefix=f"hist_{i}",
                    on_add_telegram_alert=on_add_telegram_alert,
                )
            else:
                st.markdown(str(msg.get("content") or ""))


def render_chat_first_interface(
    *,
    user_id: str,
    profile: str,
    total_capital_vnd: float,
    plan: dict[str, Any] | None,
    tg_bot: str = "",
    tg_chat: str = "",
    notify_cfg: dict[str, Any] | None = None,
    autopilot_limit: int = 30,
    version: str = "1.0.2",
    load_snapshot_cached: Callable[..., Any],
    load_strategic_report_cached: Callable[..., Any],
    load_autopilot_board: Callable[..., Any],
    can_use_feature: Callable[..., Any] | None = None,
    add_alert: Callable[..., Any] | None = None,
    log_event: Callable[..., Any] | None = None,
    dispatch_text_notifications: Callable[..., Any] | None = None,
    render_settings_slot: Callable[[], None] | None = None,
) -> None:
    """
    Main chat-first surface. Call from ``ui_shell.render_app`` when chat UI is enabled.
    """
    inject_chat_ui_css()
    render_chat_header(version=version, tg_bot=tg_bot, tg_chat=tg_chat)

    if bool(st.session_state.get(CHAT_SETTINGS_KEY)) and render_settings_slot:
        with st.container(border=True):
            st.markdown("##### ⚙️ Cài đặt / Portfolio (nhanh)")
            render_settings_slot()

    def _queue_chip(token: str) -> None:
        st.session_state[CHAT_PENDING_KEY] = token
        st.rerun()

    msgs = _ensure_chat_state()
    if not msgs:
        render_empty_state(chip_callback=_queue_chip)
    else:
        def _alert(sym: str) -> None:
            if not add_alert or not user_id:
                st.warning("Cần đăng nhập để thêm cảnh báo.")
                return
            try:
                add_alert(user_id, sym, "price_move", 5.0, note="chat_decision_card")
                st.success(f"Đã thêm cảnh báo theo dõi cho **{sym}**.")
                if dispatch_text_notifications and str(tg_bot or "").strip() and str(tg_chat or "").strip():
                    try:
                        dispatch_text_notifications(
                            user_id,
                            f"🔔 Đã theo dõi {sym} từ Decision Card (Investment Intelligence).",
                            notify_cfg or {},
                        )
                    except Exception:
                        pass
            except Exception as exc:
                st.error(f"Không thêm được cảnh báo: {exc.__class__.__name__}")

        render_chat_messages(on_add_telegram_alert=_alert)

    pending = str(st.session_state.pop(CHAT_PENDING_KEY, "") or "").strip()
    prompt = st.chat_input("Nhập mã cổ phiếu hoặc câu hỏi… (vd: PNJ, Autopilot, Telegram)")
    effective = pending or (str(prompt).strip() if prompt else "")

    if effective:
        with st.spinner("Đang xử lý…"):
            _handle_prompt(
                effective,
                profile=profile,
                capital=float(total_capital_vnd or 100_000_000.0),
                tg_bot=tg_bot,
                tg_chat=tg_chat,
                load_snapshot_cached=load_snapshot_cached,
                load_strategic_report_cached=load_strategic_report_cached,
                load_autopilot_board=load_autopilot_board,
                autopilot_limit=int(autopilot_limit or 30),
                can_use_feature=can_use_feature,
                user_id=user_id,
                plan=plan,
                add_alert=add_alert,
                log_event=log_event,
                dispatch_text_notifications=dispatch_text_notifications,
                notify_cfg=notify_cfg,
            )
        st.rerun()

    cols = st.columns([1, 1, 2])
    with cols[0]:
        if st.button("🧹 Xóa hội thoại", key="ii_chat_clear"):
            st.session_state[CHAT_MSG_KEY] = []
            st.rerun()
    with cols[1]:
        st.caption("Chat-first UI · backend qua ui_services")
