"""
Telegram bot helpers: Mini Decision Card, watchlist, top board, local alerts.

Không phụ thuộc Streamlit — dùng được từ daemon / scripts.
"""

from __future__ import annotations

import html
import json
import logging
import os
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
WATCHLIST_PATH = ROOT / "data" / "runtime" / "local_telegram_watchlist.json"
ALERT_DEDUP_PATH = ROOT / "data" / "runtime" / "telegram_alert_dedup.json"

_VN_TZ = timezone(timedelta(hours=7))

_POS_NEWS_KW = re.compile(
    r"ký\s*kết|thắng\s*thầu|cổ\s*tức|tăng\s*vốn|lãi\s*ròng\s*tăng|"
    r"mua\s*lại\s*cổ\s*phiếu|kỷ\s*lục|tăng\s*trưởng\s*mạnh|hợp\s*đồng\s*lớn",
    re.I,
)
_NEG_NEWS_KW = re.compile(
    r"gian\s*lận|phá\s*sản|điều\s*tra|thanh\s*tra|kiện|lỗ\s*ròng|"
    r"cắt\s*giảm|sa\s*thải|bán\s*tháo|sụt\s*giảm|rủi\s*ro\s*nợ|"
    r"hoãn\s*chia\s*cổ\s*tức|cảnh\s*báo",
    re.I,
)

HELP_TEXT_HTML = (
    "<b>Investment Intelligence — Telegram Bot</b>\n\n"
    "Lệnh nhanh:\n"
    "• /p <code>MÃ</code> — Mini Decision Card (vd: <code>/p PNJ</code>)\n"
    "• /top — Top 5 Autopilot sáng nay\n"
    "• /watch <code>MÃ</code> — Thêm mã vào watchlist local\n"
    "• /unwatch <code>MÃ</code> — Gỡ mã khỏi watchlist\n"
    "• /watchlist — Xem danh sách theo dõi\n"
    "• /help — Menu này\n\n"
    "Bot tự đẩy Morning Digest ~08:15 và cảnh báo watchlist mỗi 15 phút trong giờ giao dịch."
)


def vn_now() -> datetime:
    return datetime.now(_VN_TZ)


def is_vn_trading_day(dt: datetime | None = None) -> bool:
    d = dt or vn_now()
    if d.weekday() >= 5:
        return False
    try:
        from core.vn_market_calendar import expected_vn_trading_days
        import pandas as pd

        day = pd.Timestamp(d.date())
        days = expected_vn_trading_days(day, day)
        return len(days) > 0
    except Exception:
        return d.weekday() < 5


def is_vn_session_hours(dt: datetime | None = None) -> bool:
    """Phiên HOSE gần đúng: 09:00–11:30 và 13:00–15:00 (UTC+7)."""
    d = dt or vn_now()
    if not is_vn_trading_day(d):
        return False
    t = d.time()
    morning = time(9, 0) <= t <= time(11, 30)
    afternoon = time(13, 0) <= t <= time(15, 0)
    return morning or afternoon


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _clean_symbols(symbols: list[Any]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in symbols:
        s = str(x or "").strip().upper()
        if not s or s in seen:
            continue
        if not re.fullmatch(r"[A-Z0-9]{2,6}", s):
            continue
        seen.add(s)
        out.append(s)
    return out


def load_watchlist(path: Path | None = None) -> list[str]:
    p = path or WATCHLIST_PATH
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, dict):
        items = raw.get("symbols") or raw.get("watchlist") or []
    elif isinstance(raw, list):
        items = raw
    else:
        items = []
    return _clean_symbols(list(items))


def save_watchlist(symbols: list[str], path: Path | None = None) -> list[str]:
    p = path or WATCHLIST_PATH
    cleaned = _clean_symbols(list(symbols))
    _ensure_parent(p)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "symbols": cleaned,
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return cleaned


def add_to_watchlist(symbol: str, path: Path | None = None) -> tuple[list[str], bool]:
    sym = str(symbol or "").strip().upper()
    cur = load_watchlist(path)
    if not re.fullmatch(r"[A-Z0-9]{2,6}", sym):
        return cur, False
    if sym in cur:
        return cur, False
    cur.append(sym)
    return save_watchlist(cur, path), True


def remove_from_watchlist(symbol: str, path: Path | None = None) -> tuple[list[str], bool]:
    sym = str(symbol or "").strip().upper()
    cur = load_watchlist(path)
    if sym not in cur:
        return cur, False
    cur = [x for x in cur if x != sym]
    return save_watchlist(cur, path), True


def _fmt_num(v: Any, *, digits: int = 1, suffix: str = "", money: bool = False) -> str:
    if v is None or v == "":
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return html.escape(str(v)[:40])
    if money or abs(f) >= 1000:
        return f"{f:,.0f}{suffix}"
    return f"{f:.{digits}f}{suffix}"


def _action_emoji(action: str) -> str:
    a = str(action or "WATCH").upper()
    if a == "BUY":
        return "🟢"
    if a == "HOLD":
        return "🟡"
    if a == "AVOID":
        return "🔴"
    return "🟠"


def format_mini_decision_card_html(analysis: dict[str, Any]) -> str:
    """HTML Mini Decision Card từ payload get_deep_analysis / report."""
    rep = analysis.get("report") if isinstance(analysis.get("report"), dict) else analysis
    if not isinstance(rep, dict):
        rep = {}
    symbol = str(analysis.get("symbol") or rep.get("symbol") or "—").upper()
    name = str(analysis.get("company_name") or rep.get("name") or "")

    try:
        from core.decision_action_gate import (
            action_display_vi,
            apply_trade_plan_visibility,
            resolve_display_action,
            trade_plan_is_active,
        )

        rep_v = apply_trade_plan_visibility(rep)
        resolved = resolve_display_action(rep_v)
        action = str(resolved.get("display_action") or "WATCH")
        action_vi = action_display_vi(action)
        show_plan = trade_plan_is_active(rep_v) and bool(resolved.get("show_trade_plan"))
    except Exception:
        rep_v = rep
        action = str(rep.get("final_action") or "WATCH").upper()
        action_vi = action
        show_plan = action in ("BUY", "HOLD")

    val = rep_v.get("valuation") if isinstance(rep_v.get("valuation"), dict) else {}
    phase = rep_v.get("phase") if isinstance(rep_v.get("phase"), dict) else {}
    eq = rep_v.get("earnings_quality") if isinstance(rep_v.get("earnings_quality"), dict) else {}
    rp = rep_v.get("risk_plan") if isinstance(rep_v.get("risk_plan"), dict) else {}

    mos = val.get("margin_of_safety_composite_pct")
    fscore = val.get("piotroski_score")
    ph = str(phase.get("phase") or "—")
    cfo_raw = eq.get("operating_cash_flow")
    snap = rep_v.get("snapshot") if isinstance(rep_v.get("snapshot"), dict) else {}
    if cfo_raw is None:
        cfo_raw = snap.get("operating_cash_flow")
    try:
        from core.decision_action_gate import classify_cfo_status as _cfo

        cfo_status = _cfo(cfo_raw, is_bank=bool(val.get("is_bank_sector")))
    except Exception:
        cfo_status = "UNKNOWN"

    emoji = _action_emoji(action)
    lines = [
        f"{emoji} <b>{html.escape(symbol)}</b> — <b>KHUYẾN NGHỊ: {html.escape(action_vi)}</b> ({html.escape(action)})",
    ]
    if name:
        lines.append(html.escape(name[:80]))
    lines.append(
        f"MOS: <b>{html.escape(_fmt_num(mos, suffix='%'))}</b> · "
        f"F-Score: <b>{html.escape(_fmt_num(fscore, digits=0))}/9</b>"
    )
    lines.append(f"CFO: <b>{html.escape(str(cfo_status))}</b> · Phase: <b>{html.escape(ph)}</b>")
    price = val.get("price")
    if price is not None:
        lines.append(f"Giá: <b>{html.escape(_fmt_num(price, money=True))}</b>")

    pe_flag = bool(val.get("pe_anomaly_flag") or val.get("eps_anomaly_flag"))
    if pe_flag:
        warn = str(val.get("eps_pe_anomaly_warning_vi") or "P/E có dấu hiệu méo do LN đột biến.")
        lines.append(f"⚠️ <i>{html.escape(warn[:160])}</i>")

    if show_plan:
        lines.append("")
        lines.append("<b>Kế hoạch giao dịch</b>")
        lines.append(
            f"Entry: {_fmt_num(rp.get('entry_price'), money=True)} · "
            f"SL: {_fmt_num(rp.get('stop_loss_price'), money=True)} · "
            f"TP: {_fmt_num(rp.get('take_profit_price'), money=True)}"
        )
    else:
        lines.append("")
        lines.append("<i>Không đề xuất Entry/SL/TP (QUAN SÁT / TRÁNH).</i>")

    err = analysis.get("error") or analysis.get("partial_error")
    if err:
        lines.append(f"\n⚠️ Dữ liệu một phần: <code>{html.escape(str(err)[:80])}</code>")

    lines.append("\n<i>Không phải lời khuyên đầu tư.</i>")
    return "\n".join(lines)


def format_top5_html(rows: list[dict[str, Any]], *, board_meta: dict[str, Any] | None = None) -> str:
    meta = board_meta or {}
    updated = str(meta.get("updated_at") or meta.get("board_updated_at") or "—")
    lines = [
        "<b>Autopilot Top 5</b>",
        f"Board: <code>{html.escape(updated[:32])}</code>",
        "",
    ]
    if not rows:
        lines.append("Chưa có dữ liệu board. Chạy nightly scan trước.")
        return "\n".join(lines)
    for i, row in enumerate(rows[:5], start=1):
        sym = str(row.get("Mã") or row.get("symbol") or "—").upper()
        action = str(row.get("Khuyến nghị") or row.get("action") or "WATCH")
        mos = row.get("MOS%") if "MOS%" in row else row.get("mos_pct")
        score = row.get("Proprietary Score") or row.get("blend_score") or row.get("__score")
        price = row.get("Giá") or row.get("price")
        emoji = _action_emoji(action)
        lines.append(
            f"{i}. {emoji} <b>{html.escape(sym)}</b> · {html.escape(str(action))} · "
            f"MOS {_fmt_num(mos, suffix='%')} · score {_fmt_num(score)} · giá {_fmt_num(price, money=True)}"
        )
        play_bits = []
        for key, label in (("Thesis", "T"), ("Setup", "S"), ("Trigger", "Tr")):
            val = str(row.get(key) or "").strip()
            if val:
                play_bits.append(f"{label} {html.escape(val)}")
        if play_bits:
            lines.append("   " + " · ".join(play_bits))
        why = str(row.get("Why not BUY") or "").strip()
        if why and str(action).upper() != "BUY":
            short = why if len(why) <= 90 else why[:87] + "…"
            lines.append(f"   why_not: <i>{html.escape(short)}</i>")
        if row.get("EventBlackout") in (True, "True", "true", 1, "1"):
            lines.append("   ⚠️ event blackout")
    lines.append("\nGõ <code>/p MÃ</code> để xem Decision Card.")
    return "\n".join(lines)


def load_top5_from_board(*, top_n: int = 5) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Đọc autopilot_nightly_board.json → Top N theo score."""
    meta: dict[str, Any] = {}
    try:
        from core.autopilot_nightly_board import compute_meta, load_board, top_n_from_board

        board = load_board()
        if not board:
            return [], {"error": "missing_board"}
        meta = compute_meta(board)
        meta["updated_at"] = board.get("updated_at")
        df = top_n_from_board(board, top_n=int(top_n), ready_only=True, recommended_only=True)
        if df is None or df.empty:
            return [], meta
        rows = [dict(r) for _, r in df.head(int(top_n)).iterrows()]
        return rows, meta
    except Exception as exc:
        logger.warning("load_top5_from_board failed: %s", exc.__class__.__name__)
        return [], {"error": exc.__class__.__name__}


def _load_dedup(path: Path | None = None) -> dict[str, Any]:
    p = path or ALERT_DEDUP_PATH
    if not p.exists():
        return {"keys": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return raw
    except Exception:
        pass
    return {"keys": {}}


def _save_dedup(data: dict[str, Any], path: Path | None = None) -> None:
    p = path or ALERT_DEDUP_PATH
    _ensure_parent(p)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _dedup_allow(key: str, *, cooldown_sec: int = 3600, path: Path | None = None) -> bool:
    data = _load_dedup(path)
    keys = data.setdefault("keys", {})
    now = datetime.now(timezone.utc).timestamp()
    stale = [k for k, ts in keys.items() if now - float(ts or 0) > max(cooldown_sec * 3, 86400)]
    for k in stale:
        keys.pop(k, None)
    last = float(keys.get(key) or 0)
    if now - last < cooldown_sec:
        return False
    keys[key] = now
    _save_dedup(data, path)
    return True


def scan_watchlist_alerts(
    symbols: list[str] | None = None,
    *,
    price_move_pct: float = 3.0,
    cooldown_sec: int = 3600,
) -> list[dict[str, Any]]:
    """
    Cảnh báo local: biến động giá |Δ| > threshold hoặc tin tích cực/tiêu cực mới.
    Fail-soft theo từng mã.
    """
    from core.sentinel import ohlcv_last_session_change_pct

    syms = symbols if symbols is not None else load_watchlist()
    threshold = float(os.environ.get("II_TG_PRICE_ALERT_PCT", str(price_move_pct)) or price_move_pct)
    alerts: list[dict[str, Any]] = []

    for raw in syms:
        sym = str(raw or "").strip().upper()
        if not sym:
            continue
        reasons: list[str] = []
        chg: float | None = None
        news_bias = "neutral"
        headline = ""

        try:
            from scrapers.portal import fetch_ohlcv_history

            df = fetch_ohlcv_history(sym, sessions=5)
            chg = ohlcv_last_session_change_pct(df)
            if chg is not None and abs(float(chg)) >= threshold:
                reasons.append(f"Giá biến động {float(chg):+.2f}% (≥{threshold:g}%)")
        except Exception:
            pass

        try:
            from scrapers.portal import fetch_latest_news

            news = fetch_latest_news(sym, limit=4)
            for n in news or []:
                title = str(n.get("title") or "")
                if _NEG_NEWS_KW.search(title):
                    news_bias = "negative"
                    headline = title[:120]
                    reasons.append(f"Tin tiêu cực: {headline}")
                    break
                if _POS_NEWS_KW.search(title):
                    news_bias = "positive"
                    headline = title[:120]
                    reasons.append(f"Tin tích cực: {headline}")
                    break
        except Exception:
            pass

        if not reasons:
            continue
        dedup_key = f"{sym}|{news_bias}|{round(float(chg or 0), 1)}"
        if not _dedup_allow(dedup_key, cooldown_sec=cooldown_sec):
            continue
        alerts.append(
            {
                "symbol": sym,
                "change_pct": chg,
                "news_bias": news_bias,
                "headline": headline,
                "reasons": reasons,
                "text_html": (
                    f"🚨 <b>Watchlist Alert — {html.escape(sym)}</b>\n"
                    + "\n".join(f"• {html.escape(r)}" for r in reasons)
                ),
            }
        )
    return alerts


def build_morning_digest_html(*, top_n: int = 5) -> str:
    try:
        from core.morning_digest_service import format_paper_pnl_digest_html, load_digest_payload

        df, meta, _text = load_digest_payload(top_n=top_n)
        rows: list[dict[str, Any]] = []
        if df is not None and not getattr(df, "empty", True):
            rows = [dict(r) for _, r in df.head(top_n).iterrows()]
        paper_html = format_paper_pnl_digest_html(meta.get("paper") if isinstance(meta, dict) else None)
        top_html = format_top5_html(rows, board_meta=meta)
        warn = ""
        if meta.get("health_severity") in ("warn", "critical"):
            warn = f"\n⚠️ Board health: <code>{html.escape(str(meta.get('health_severity')))}</code>"
        paper_block = f"{paper_html}\n\n" if paper_html else ""
        return (
            f"<b>☀️ Morning Autopilot Digest</b>\n"
            f"{vn_now().strftime('%Y-%m-%d %H:%M')} (VN)\n\n"
            f"{paper_block}{top_html}{warn}"
        )
    except Exception as exc:
        rows, meta = load_top5_from_board(top_n=top_n)
        body = format_top5_html(rows, board_meta=meta)
        return (
            f"<b>☀️ Morning Autopilot Digest</b>\n{vn_now().strftime('%Y-%m-%d %H:%M')} (VN)\n\n"
            f"{body}\n\n<i>fallback: {html.escape(exc.__class__.__name__)}</i>"
        )


def resolve_bot_credentials(*, user_id: str = "default_user") -> tuple[str, str]:
    """Token + owner chat id từ env hoặc secret vault."""
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = str(os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    try:
        from core.product_layer import load_secret

        token = token or str(load_secret(user_id, "telegram_bot_token") or "").strip()
        chat = chat or str(load_secret(user_id, "telegram_chat_id") or "").strip()
    except Exception:
        pass
    return token, chat


def allowed_chat_ids(owner_chat_id: str = "") -> set[str]:
    raw = str(os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS") or "").strip()
    ids = {x.strip() for x in raw.split(",") if x.strip()}
    if owner_chat_id:
        ids.add(str(owner_chat_id).strip())
    return ids
