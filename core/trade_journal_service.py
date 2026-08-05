from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from core import trade_journal_repository


def open_trade(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    symbol: str,
    quantity: float,
    entry_price: float,
    decision_id: int | None = None,
    side: str = "LONG",
    entry_fee: float = 0.0,
    entry_note: str = "",
) -> tuple[bool, str]:
    sym = (symbol or "").strip().upper()
    sd = (side or "LONG").strip().upper()
    if sd not in ("LONG",):
        sd = "LONG"
    qty = float(quantity or 0)
    ep = float(entry_price or 0)
    fee = max(0.0, float(entry_fee or 0))
    if not sym:
        return False, "Mã giao dịch rỗng."
    if qty <= 0 or ep <= 0:
        return False, "Số lượng và giá mở phải > 0."
    did: int | None = int(decision_id or 0)
    if did is not None and did <= 0:
        did = None
    if did is not None and not trade_journal_repository.decision_exists(conn_factory=conn_factory, user_id=user_id, decision_id=did):
        return False, "Decision không tồn tại hoặc không thuộc user."
    trade_journal_repository.insert_trade(
        conn_factory=conn_factory,
        user_id=user_id,
        decision_id=did,
        symbol=sym,
        side=sd,
        quantity=qty,
        entry_price=ep,
        entry_fee=fee,
        entry_note=str(entry_note or "").strip(),
        now_iso=utcnow_iso(),
    )
    return True, "Đã mở trade journal."


def close_trade(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    trade_id: int,
    exit_price: float,
    exit_fee: float = 0.0,
    exit_note: str = "",
) -> tuple[bool, str]:
    tid = int(trade_id or 0)
    xp = float(exit_price or 0)
    xf = max(0.0, float(exit_fee or 0))
    if tid <= 0:
        return False, "Trade ID không hợp lệ."
    if xp <= 0:
        return False, "Giá đóng phải > 0."
    row = trade_journal_repository.get_open_trade_row(conn_factory=conn_factory, user_id=user_id, trade_id=tid)
    if row is None:
        return False, "Không tìm thấy trade OPEN."
    trade_journal_repository.close_trade_row(
        conn_factory=conn_factory,
        user_id=user_id,
        trade_id=tid,
        exit_price=xp,
        exit_fee=xf,
        exit_note=str(exit_note or "").strip(),
        now_iso=utcnow_iso(),
    )
    return True, "Đã đóng trade."


def list_trades(*, conn_factory: Callable[[], Any], user_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = trade_journal_repository.fetch_trades(conn_factory=conn_factory, user_id=user_id, limit=limit)
    out: list[dict[str, Any]] = []
    for r in rows:
        qty = float(r["quantity"] or 0)
        ep = float(r["entry_price"] or 0)
        ef = float(r["entry_fee"] or 0)
        xp = float(r["exit_price"]) if r["exit_price"] is not None else None
        xf = float(r["exit_fee"] or 0) if r["exit_fee"] is not None else 0.0
        realized = None
        realized_pct = None
        if xp is not None:
            realized = (xp - ep) * qty - ef - xf
            cost = ep * qty + ef
            realized_pct = (realized / cost * 100.0) if cost > 0 else 0.0
        out.append(
            {
                "ID": int(r["id"]),
                "Decision ID": int(r["decision_id"]) if r["decision_id"] is not None else None,
                "Mã": str(r["symbol"]),
                "SL": int(round(qty)),
                "Giá mở": round(ep, 2),
                "Phí mở": round(ef, 2),
                "Trạng thái": str(r["status"]),
                "Giá đóng": round(xp, 2) if xp is not None else None,
                "Phí đóng": round(float(xf or 0), 2) if xp is not None else None,
                "Realized PnL": round(realized, 2) if realized is not None else None,
                "Realized %": round(realized_pct, 2) if realized_pct is not None else None,
                "Mở lúc": str(r["opened_at"]),
                "Đóng lúc": str(r["closed_at"] or ""),
                "Ghi chú mở": str(r["entry_note"] or ""),
                "Ghi chú đóng": str(r["exit_note"] or ""),
            }
        )
    return out


def execution_vs_plan_report(
    *,
    user_id: str,
    limit: int,
    list_trades_func: Callable[[str, int], list[dict[str, Any]]],
    list_decisions_func: Callable[[str, int], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    trades = list_trades_func(user_id, limit)
    if not trades:
        return []
    decisions = {d["id"]: d for d in list_decisions_func(user_id, 2000)}
    out: list[dict[str, Any]] = []
    for t in trades:
        did = t.get("Decision ID")
        if did is None or did not in decisions:
            continue
        d = decisions[did]
        plan_entry = float(d.get("entry_price") or 0)
        plan_sl = float(d.get("stop_loss") or 0)
        plan_tp = float(d.get("take_profit") or 0)
        real_entry = float(t.get("Giá mở") or 0)
        real_exit = float(t.get("Giá đóng") or 0) if t.get("Giá đóng") is not None else None
        entry_slippage_pct = ((real_entry - plan_entry) / plan_entry * 100.0) if plan_entry > 0 and real_entry > 0 else 0.0
        exit_vs_tp_pct = ((real_exit - plan_tp) / plan_tp * 100.0) if plan_tp > 0 and real_exit is not None else None
        exit_vs_sl_pct = ((real_exit - plan_sl) / plan_sl * 100.0) if plan_sl > 0 and real_exit is not None else None
        discipline = "GOOD"
        if abs(entry_slippage_pct) > 2.0:
            discipline = "WARN_ENTRY"
        if real_exit is not None and real_exit < plan_sl * 0.99:
            discipline = "BAD_SLIP_BELOW_SL"
        out.append(
            {
                "Trade ID": t.get("ID"),
                "Decision ID": did,
                "Mã": t.get("Mã"),
                "Plan Entry": round(plan_entry, 2),
                "Real Entry": round(real_entry, 2),
                "Entry Slippage %": round(entry_slippage_pct, 2),
                "Plan SL": round(plan_sl, 2),
                "Plan TP": round(plan_tp, 2),
                "Real Exit": round(real_exit, 2) if real_exit is not None else None,
                "Exit vs TP %": round(exit_vs_tp_pct, 2) if exit_vs_tp_pct is not None else None,
                "Exit vs SL %": round(exit_vs_sl_pct, 2) if exit_vs_sl_pct is not None else None,
                "Discipline": discipline,
                "Realized %": t.get("Realized %"),
            }
        )
    return out


def realized_performance(
    *,
    user_id: str,
    days: int,
    list_trades_func: Callable[[str, int], list[dict[str, Any]]],
) -> dict[str, Any]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
    rows = list_trades_func(user_id, 2000)
    closed = [r for r in rows if r.get("Trạng thái") == "CLOSED" and str(r.get("Đóng lúc") or "") >= cutoff[:10]]
    pnl_vals = [float(r.get("Realized PnL") or 0) for r in closed]
    pct_vals = [float(r.get("Realized %") or 0) for r in closed]
    wins = sum(1 for x in pnl_vals if x > 0)
    losses = sum(1 for x in pnl_vals if x < 0)
    return {
        "closed_trades": len(closed),
        "realized_pnl_total": round(sum(pnl_vals), 2) if pnl_vals else 0.0,
        "realized_pct_avg": round(sum(pct_vals) / len(pct_vals), 2) if pct_vals else 0.0,
        "win_rate_pct": round((wins / (wins + losses) * 100.0), 1) if (wins + losses) > 0 else 0.0,
    }
