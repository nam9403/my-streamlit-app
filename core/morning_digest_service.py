"""
Morning Telegram / multi-channel digest from Autopilot nightly Top 10 (P2).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def build_decision_card_lines(row: dict[str, Any], *, rank: int = 1) -> list[str]:
    sym = str(row.get("Mã") or row.get("symbol") or "").upper()
    action = str(row.get("Khuyến nghị") or row.get("action") or "WATCH")
    price = row.get("Giá") or row.get("price")
    mos = row.get("MOS%") or row.get("mos_pct")
    exp = row.get("Expected Return %") or row.get("expected_return_pct")
    horizon = row.get("Khung thời gian") or row.get("horizon") or ""
    risk = row.get("Risk % (ước tính)") or row.get("risk_pct")
    lines = [f"{rank}. {sym} · {action}"]
    bits = []
    if price is not None:
        try:
            bits.append(f"giá {float(price):,.0f}")
        except (TypeError, ValueError):
            pass
    if mos is not None:
        try:
            bits.append(f"MOS {float(mos):.1f}%")
        except (TypeError, ValueError):
            pass
    if exp is not None:
        try:
            bits.append(f"E[R] {float(exp):.1f}%")
        except (TypeError, ValueError):
            pass
    if risk is not None:
        try:
            bits.append(f"risk {float(risk):.1f}%")
        except (TypeError, ValueError):
            pass
    readiness = row.get("Readiness") or row.get("decision_readiness")
    if readiness:
        bits.append(f"ready {readiness}")
    missing = row.get("Thiếu DL") or row.get("missing_summary")
    if missing and str(missing).strip() not in ("—", ""):
        bits.append(f"thiếu {missing}")
    if bits:
        lines.append("   " + " | ".join(bits))
    if horizon:
        lines.append(f"   khung: {horizon}")
    # P2: Thesis / Setup / Trigger compact line
    thesis = str(row.get("Thesis") or "").strip()
    setup = str(row.get("Setup") or "").strip()
    trigger = str(row.get("Trigger") or "").strip()
    regime = str(row.get("Regime") or "").strip()
    play_bits = []
    if thesis:
        play_bits.append(f"thesis {thesis}")
    if setup:
        play_bits.append(f"setup {setup}")
    if trigger:
        play_bits.append(f"trigger {trigger}")
    if regime:
        play_bits.append(f"regime {regime}")
    if play_bits:
        lines.append("   " + " · ".join(play_bits))
    playbook = str(row.get("Playbook") or row.get("Entry hint") or "").strip()
    if playbook:
        short = playbook if len(playbook) <= 120 else playbook[:117] + "…"
        lines.append(f"   playbook: {short}")
    cancel = str(row.get("Cancel if") or "").strip()
    if action.upper() == "CONDITIONAL_BUY" and cancel:
        short_c = cancel if len(cancel) <= 100 else cancel[:97] + "…"
        lines.append(f"   cancel: {short_c}")
    why = str(row.get("Why not BUY") or row.get("why_not_buy") or "").strip()
    if why and action.upper() != "BUY":
        short_w = why if len(why) <= 100 else why[:97] + "…"
        lines.append(f"   why_not: {short_w}")
    if row.get("EventBlackout") in (True, "True", "true", 1, "1"):
        lines.append("   event: blackout")
    note = row.get("Ghi chú Legend") or row.get("decision_alignment_note")
    if note and str(note).strip() not in ("—", ""):
        short = str(note).strip()
        if len(short) > 100:
            short = short[:97] + "…"
        lines.append(f"   note: {short}")
    return lines


def format_paper_pnl_digest_lines(paper_report: dict[str, Any] | None = None) -> list[str]:
    """Wave 5.4 — compact paper P&L block for morning digest / Telegram (ops horizon 40d)."""
    rep = paper_report
    if rep is None:
        try:
            from core.paper_trade_ledger import hitrate_report

            rep = hitrate_report(lookback_days=40)
        except Exception as exc:
            logger.warning("paper_pnl_digest_failed error=%s", exc.__class__.__name__)
            return ["Paper: không đọc được ledger."]
    samples = int(rep.get("samples") or 0)
    open_n = int(rep.get("open_count") or 0)
    hit = rep.get("hit_rate_pct")
    avg = rep.get("avg_realized_pct")
    lookback = int(rep.get("lookback_days") or 40)
    lines = [f"Paper ledger ({lookback}d · ops lock time40_atr2):"]
    if samples <= 0:
        lines.append(f"   closed=0 · open={open_n} · chưa đủ mẫu để chấm edge live")
        return lines
    hit_txt = f"{float(hit):.1f}%" if hit is not None else "—"
    avg_txt = f"{float(avg):+.2f}%" if avg is not None else "—"
    lines.append(f"   closed={samples} · hit={hit_txt} · avg={avg_txt} · open={open_n}")
    return lines


def format_paper_pnl_digest_html(paper_report: dict[str, Any] | None = None) -> str:
    """HTML twin of format_paper_pnl_digest_lines for Telegram bot."""
    import html as _html

    lines = format_paper_pnl_digest_lines(paper_report)
    if not lines:
        return ""
    head = _html.escape(lines[0])
    body = _html.escape(lines[1]) if len(lines) > 1 else ""
    return f"<b>📊 {head}</b>\n<code>{body}</code>" if body else f"<b>📊 {head}</b>"


def load_paper_digest_report() -> dict[str, Any]:
    try:
        from core.paper_trade_ledger import hitrate_report

        return hitrate_report(lookback_days=40)
    except Exception as exc:
        logger.warning("load_paper_digest_report_failed error=%s", exc.__class__.__name__)
        return {"samples": 0, "open_count": 0, "error": exc.__class__.__name__, "lookback_days": 40}


def build_morning_digest_text(
    top_df: pd.DataFrame | None,
    *,
    board_meta: dict[str, Any] | None = None,
    max_cards: int = 5,
    paper_report: dict[str, Any] | None = None,
    include_paper: bool = True,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["☀️ Morning Digest — Autopilot", f"Cập nhật: {now}", ""]
    meta = board_meta or {}
    if meta:
        cov = meta.get("coverage_pct")
        scanned = meta.get("scanned_count")
        target = meta.get("target_count")
        if cov is not None:
            lines.append(f"Board đêm: coverage {cov}% ({scanned}/{target})")
        age = meta.get("age_hours")
        if age is not None:
            lines.append(f"Tuổi board: {float(age):.1f}h")
        lines.append("")
    if include_paper:
        lines.extend(format_paper_pnl_digest_lines(paper_report))
        lines.append("")
    if top_df is None or (hasattr(top_df, "empty") and top_df.empty):
        lines.append("Chưa có Top picks (board trống hoặc stale).")
        lines.append("Chạy: python scripts/run_autopilot_nightly_scan.py")
        return "\n".join(lines)
    lines.append("Top cơ hội (mobile card):")
    n = 0
    for _, row in top_df.head(max(1, int(max_cards))).iterrows():
        n += 1
        lines.extend(build_decision_card_lines(dict(row), rank=n))
    lines.append("")
    lines.append("⚠️ Không phải lời khuyên đầu tư. Tự quyết định & quản trị rủi ro.")
    return "\n".join(lines)


def load_digest_payload(*, top_n: int = 10) -> tuple[pd.DataFrame | None, dict[str, Any], str]:
    """Prefer nightly board; fallback empty. Always attach paper 40d snapshot into meta."""
    meta: dict[str, Any] = {}
    paper = load_paper_digest_report()
    try:
        from core.autopilot_nightly_board import (
            board_health_report,
            load_board,
            top_n_from_board,
            try_serve_top_board,
        )

        df, serve_meta = try_serve_top_board(profile="growth", top_n=int(top_n), refresh_prices=True)
        meta = dict(serve_meta or {})
        if df is None or df.empty:
            board = load_board()
            if board:
                df = top_n_from_board(board, top_n=int(top_n), ready_only=True)
                meta = {**(board.get("meta") or {}), "source": "board_raw"}
        health = board_health_report()
        meta["health_ok"] = bool(health.get("ok"))
        meta["health_severity"] = health.get("severity")
        meta["paper"] = paper
        text = build_morning_digest_text(
            df, board_meta=meta, max_cards=min(5, int(top_n)), paper_report=paper
        )
        return df, meta, text
    except Exception as exc:
        logger.warning("load_digest_payload_failed error=%s", exc.__class__.__name__)
        meta = {"error": exc.__class__.__name__, "paper": paper}
        text = build_morning_digest_text(
            None, board_meta=meta, paper_report=paper
        )
        return None, meta, text
