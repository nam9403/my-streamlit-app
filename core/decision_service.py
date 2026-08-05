from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from core import decision_repository


def add_decision(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    symbol: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    thesis: str = "",
    horizon_days: int = 30,
) -> tuple[bool, str]:
    sym = (symbol or "").strip().upper()
    sd = (side or "BUY").strip().upper()
    if sd not in ("BUY", "WATCH"):
        sd = "BUY"
    if not sym:
        return False, "Mã cổ phiếu rỗng."
    if entry_price <= 0 or stop_loss <= 0 or take_profit <= 0:
        return False, "Entry/SL/TP phải > 0."
    if sd == "BUY" and not (stop_loss < entry_price < take_profit):
        return False, "Cần thỏa SL < Entry < TP."
    hz = max(7, min(int(horizon_days or 30), 365))
    decision_repository.insert_decision(
        conn_factory=conn_factory,
        user_id=user_id,
        symbol=sym,
        side=sd,
        entry_price=float(entry_price),
        stop_loss=float(stop_loss),
        take_profit=float(take_profit),
        thesis=str(thesis or "").strip(),
        horizon_days=hz,
        created_at=utcnow_iso(),
    )
    return True, "Đã lưu quyết định."


def list_decisions(*, conn_factory: Callable[[], Any], user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = decision_repository.fetch_decisions(conn_factory=conn_factory, user_id=user_id, limit=limit)
    return [
        {
            "id": int(r["id"]),
            "symbol": str(r["symbol"]),
            "side": str(r["side"]),
            "entry_price": float(r["entry_price"]),
            "stop_loss": float(r["stop_loss"]),
            "take_profit": float(r["take_profit"]),
            "thesis": str(r["thesis"] or ""),
            "horizon_days": int(r["horizon_days"]),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


def evaluate_decisions(
    *,
    user_id: str,
    limit: int,
    list_decisions_func: Callable[[str, int], list[dict[str, Any]]],
    fetch_financial_snapshot_func: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for d in list_decisions_func(user_id, limit):
        sym = d["symbol"]
        snap = fetch_financial_snapshot_func(sym) or {}
        px = float(snap.get("price") or 0)
        entry = float(d["entry_price"] or 0)
        sl = float(d["stop_loss"] or 0)
        tp = float(d["take_profit"] or 0)
        rr_target = (tp - entry) / max(entry - sl, 1e-6) if entry > 0 and sl > 0 else 0.0
        ret_pct = ((px - entry) / entry * 100.0) if entry > 0 and px > 0 else 0.0
        status = "OPEN"
        if px > 0:
            if px <= sl:
                status = "STOP_LOSS_HIT"
            elif px >= tp:
                status = "TAKE_PROFIT_HIT"
        out.append(
            {
                "ID": d["id"],
                "Mã": sym,
                "Side": d["side"],
                "Entry": round(entry, 2),
                "Giá hiện tại": round(px, 2) if px > 0 else None,
                "SL": round(sl, 2),
                "TP": round(tp, 2),
                "RR target": round(rr_target, 2),
                "P/L %": round(ret_pct, 2),
                "Trạng thái": status,
                "Luận điểm": d["thesis"],
                "Horizon": d["horizon_days"],
                "Tạo lúc": d["created_at"],
            }
        )
    return out


def decision_scorecard(*, user_id: str, limit: int, evaluate_decisions_func: Callable[[str, int], list[dict[str, Any]]]) -> dict[str, Any]:
    rows = evaluate_decisions_func(user_id, limit)
    if not rows:
        return {"decisions": 0, "discipline_score": 0.0, "rr_avg": 0.0, "win_rate_closed_pct": 0.0, "pl_avg_pct": 0.0}
    rr_vals = [float(r.get("RR target") or 0) for r in rows if float(r.get("RR target") or 0) > 0]
    rr_avg = sum(rr_vals) / len(rr_vals) if rr_vals else 0.0
    closed = [r for r in rows if r.get("Trạng thái") in ("STOP_LOSS_HIT", "TAKE_PROFIT_HIT")]
    tp_n = sum(1 for r in closed if r.get("Trạng thái") == "TAKE_PROFIT_HIT")
    sl_n = sum(1 for r in closed if r.get("Trạng thái") == "STOP_LOSS_HIT")
    win_rate = (tp_n / (tp_n + sl_n) * 100.0) if (tp_n + sl_n) > 0 else 0.0
    pl_vals = [float(r.get("P/L %") or 0) for r in rows]
    pl_avg = sum(pl_vals) / len(pl_vals) if pl_vals else 0.0
    rr_score = min(40.0, rr_avg / 2.0 * 40.0)
    close_score = min(30.0, win_rate / 100.0 * 30.0)
    pnl_score = max(0.0, min(30.0, (pl_avg + 10.0) / 20.0 * 30.0))
    discipline = max(0.0, min(100.0, rr_score + close_score + pnl_score))
    return {
        "decisions": len(rows),
        "discipline_score": round(discipline, 1),
        "rr_avg": round(rr_avg, 2),
        "win_rate_closed_pct": round(win_rate, 1),
        "pl_avg_pct": round(pl_avg, 2),
    }


def postmortem_report(
    *,
    user_id: str,
    days: int,
    limit: int,
    evaluate_decisions_func: Callable[[str, int], list[dict[str, Any]]],
    parse_ts: Callable[[str], datetime | None],
) -> list[dict[str, Any]]:
    rows = evaluate_decisions_func(user_id, limit)
    horizon = max(1, int(days))
    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for r in rows:
        created = parse_ts(str(r.get("Tạo lúc") or ""))
        if created is None:
            continue
        age = int((now - created).total_seconds() // 86400)
        if age < horizon:
            continue
        status = str(r.get("Trạng thái") or "OPEN")
        pl = float(r.get("P/L %") or 0)
        lesson = "Giữ kỷ luật theo kế hoạch."
        if status == "STOP_LOSS_HIT":
            lesson = "Tín hiệu sai hoặc vào lệnh sớm, cần chờ xác nhận tốt hơn."
        elif status == "TAKE_PROFIT_HIT":
            lesson = "Thực thi tốt theo kế hoạch RR."
        elif status == "OPEN" and pl < -5:
            lesson = "Nên rà soát lại luận điểm và điều kiện vô hiệu."
        out.append(
            {
                "Mã": r.get("Mã"),
                "Age (ngày)": age,
                "Trạng thái": status,
                "P/L %": round(pl, 2),
                "Bài học": lesson,
                "Luận điểm": r.get("Luận điểm"),
            }
        )
    return out


def monthly_value_report(
    *,
    user_id: str,
    get_kpi_dashboard_func: Callable[[str, int], dict[str, Any]],
    get_cohort_kpi_func: Callable[[str], dict[str, Any]],
    decision_scorecard_func: Callable[[str, int], dict[str, Any]],
) -> dict[str, Any]:
    kpi30 = get_kpi_dashboard_func(user_id, 30)
    cohort = get_cohort_kpi_func(user_id)
    sc = decision_scorecard_func(user_id, 200)
    return {
        "plan_id": kpi30.get("plan_id"),
        "events_30d": int(kpi30.get("events_total") or 0),
        "analysis_30d": int(cohort.get("analysis_30") or 0),
        "alerts_dispatched_30d": int(cohort.get("alerts_dispatched_30") or 0),
        "decisions_logged": int(sc.get("decisions") or 0),
        "discipline_score": float(sc.get("discipline_score") or 0.0),
        "avg_pl_pct": float(sc.get("pl_avg_pct") or 0.0),
        "win_rate_closed_pct": float(sc.get("win_rate_closed_pct") or 0.0),
        "value_summary": (
            f"30 ngày qua: {int(cohort.get('analysis_30') or 0)} lần phân tích, "
            f"{int(cohort.get('alerts_dispatched_30') or 0)} cảnh báo gửi đi, "
            f"discipline score {float(sc.get('discipline_score') or 0.0):.1f}/100."
        ),
    }
