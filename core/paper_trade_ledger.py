"""
Paper-trade ledger for Autopilot Top picks (P1).

Disk-first JSON ledger — no decision_id required.
Nightly scan opens paper trades; resolve job closes after horizon.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_REL = Path("data") / "runtime" / "paper_trade_ledger.json"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def ledger_path() -> Path:
    raw = str(os.environ.get("II_PAPER_TRADE_LEDGER_PATH") or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else (project_root() / p)
    return project_root() / _DEFAULT_REL


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": 1, "updated_at": _iso(_utc_now()), "trades": []}


def load_ledger(path: Path | None = None) -> dict[str, Any]:
    p = path or ledger_path()
    if not p.exists():
        return empty_ledger()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("paper_ledger_load_failed error=%s", exc.__class__.__name__)
        return empty_ledger()
    if not isinstance(raw, dict):
        return empty_ledger()
    if not isinstance(raw.get("trades"), list):
        raw["trades"] = []
    return raw


def save_ledger(ledger: dict[str, Any], path: Path | None = None) -> Path:
    p = path or ledger_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(ledger or empty_ledger())
    payload["updated_at"] = _iso(_utc_now())
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(prefix="paper_ledger_", suffix=".json", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        Path(tmp).replace(p)
    except Exception:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return p


def open_paper_trades_from_top(
    rows: list[dict[str, Any]],
    *,
    source: str = "autopilot_nightly",
    horizon_days: int = 40,
    quantity: float = 100.0,
    path: Path | None = None,
) -> dict[str, Any]:
    """
    Open paper LONG for Top rows that pass P0 action allowlist.

    Only BUY / CONDITIONAL_BUY — never LONG on WATCH/AVOID/HOLD.
    Default horizon 40d — Wave2 operational lock (time40_atr2 balanced score).
    """
    from core.data_integrity import paper_action_allows_long

    ledger = load_ledger(path)
    # Wave 4: kill-switch — chặn mở mới khi chuỗi thua / lookback yếu
    kill_meta: dict[str, Any] = {"halt_new_opens": False, "reasons": []}
    try:
        from core.paper_ops_guard import evaluate_paper_kill_switch, persist_guard_state

        kill_meta = evaluate_paper_kill_switch(ledger)
        persist_guard_state(kill_meta)
        if kill_meta.get("halt_new_opens"):
            return {
                "opened": 0,
                "skipped": len(rows) if isinstance(rows, list) else 0,
                "skipped_non_buy_action": 0,
                "open_total": sum(1 for t in (ledger.get("trades") or []) if t.get("status") == "OPEN"),
                "kill_switch_halt": True,
                "kill_switch": kill_meta,
            }
    except Exception:
        pass

    trades = list(ledger.get("trades") or [])
    open_keys = {
        (str(t.get("symbol") or "").upper(), str(t.get("source") or ""))
        for t in trades
        if str(t.get("status") or "").upper() == "OPEN"
    }
    opened = 0
    skipped = 0
    skipped_action = 0
    now = _utc_now()
    due = now + timedelta(days=max(7, int(horizon_days)))
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        sym = str(row.get("Mã") or row.get("symbol") or "").strip().upper()
        px = float(row.get("Giá") or row.get("entry_price") or 0.0)
        action = str(row.get("Khuyến nghị") or row.get("gate_action") or row.get("action") or "")
        if not sym or px <= 0:
            skipped += 1
            continue
        if not paper_action_allows_long(action):
            skipped += 1
            skipped_action += 1
            continue
        if row.get("is_gate_restricted") is True:
            skipped += 1
            skipped_action += 1
            continue
        # Tuned: nếu board có Setup/Trigger thì bắt buộc ARMED + READY
        setup = str(row.get("Setup") or row.get("setup") or "").strip().upper()
        trigger = str(row.get("Trigger") or row.get("trigger") or "").strip().upper()
        if setup and setup not in ("ARMED",):
            skipped += 1
            skipped_action += 1
            continue
        if trigger and trigger not in ("READY",):
            skipped += 1
            skipped_action += 1
            continue
        # Alpha tune: thesis attractive / growth đồng thuận nếu board có số
        attractive = row.get("attractive")
        if attractive is None:
            attractive = row.get("ThesisAttractive")
        if attractive is None and isinstance(row.get("thesis"), dict):
            attractive = row["thesis"].get("attractive")
        if attractive is False:
            skipped += 1
            skipped_action += 1
            continue
        rev = row.get("revenue_growth_yoy")
        if rev is None:
            rev = row.get("Rev YoY")
        if rev is None:
            rev = row.get("Rev YoY%")
        if rev is None:
            rev = row.get("rev_yoy")
        ni = row.get("profit_growth_yoy")
        if ni is None:
            ni = row.get("Profit YoY")
        if ni is None:
            ni = row.get("Profit YoY%")
        if ni is None:
            ni = row.get("profit_yoy")
        try:
            if rev is not None and ni is not None and (float(rev) < 0.0 or float(ni) < 0.0):
                skipped += 1
                skipped_action += 1
                continue
        except (TypeError, ValueError):
            pass
        if row.get("EventBlackout") is True:
            skipped += 1
            skipped_action += 1
            continue
        key = (sym, source)
        if key in open_keys:
            skipped += 1
            continue
        # Wave 2.4: portfolio caps
        try:
            from core.portfolio_caps import PortfolioCapConfig, evaluate_portfolio_caps

            sector = str(row.get("Tiểu ngành") or row.get("sector") or "")
            gate = evaluate_portfolio_caps(
                open_trades=trades,
                candidate={"symbol": sym, "sector": sector, "opened_at": _iso(now)},
                config=PortfolioCapConfig(),
                as_of=now,
            )
            if not gate.get("allow"):
                skipped += 1
                skipped_action += 1
                continue
        except Exception:
            pass
        trades.append(
            {
                "id": str(uuid.uuid4()),
                "symbol": sym,
                "side": "LONG",
                "quantity": float(quantity),
                "entry_price": px,
                "opened_at": _iso(now),
                "due_at": _iso(due),
                "horizon_days": int(horizon_days),
                "status": "OPEN",
                "exit_price": None,
                "closed_at": None,
                "realized_pct": None,
                "direction_hit": None,
                "source": source,
                "action": action,
                "sector": str(row.get("Tiểu ngành") or row.get("sector") or "") or None,
                "expected_return_pct": float(row.get("Expected Return %") or row.get("expected_return_pct") or 0.0),
                "mos_pct": float(row.get("MOS%") or row.get("mos_pct") or 0.0),
            }
        )
        open_keys.add(key)
        opened += 1
    ledger["trades"] = trades[-2000:]
    save_ledger(ledger, path)
    return {
        "opened": opened,
        "skipped": skipped,
        "skipped_non_buy_action": skipped_action,
        "open_total": sum(1 for t in ledger["trades"] if t.get("status") == "OPEN"),
        "kill_switch_halt": False,
        "kill_switch": kill_meta,
    }


def resolve_due_trades(
    *,
    fetch_price,
    path: Path | None = None,
    force_all_open: bool = False,
) -> dict[str, Any]:
    """
    Close OPEN trades past due_at using fetch_price(symbol) -> float|None.
    direction_hit: 1 if realized_pct > 0 for LONG.
    """
    ledger = load_ledger(path)
    now = _utc_now()
    resolved = 0
    failed = 0
    still_open = 0
    for t in ledger.get("trades") or []:
        if str(t.get("status") or "").upper() != "OPEN":
            continue
        due_raw = str(t.get("due_at") or "")
        try:
            due = datetime.fromisoformat(due_raw.replace("Z", "+00:00"))
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
        except Exception:
            due = now
        if (not force_all_open) and due > now:
            still_open += 1
            continue
        sym = str(t.get("symbol") or "").upper()
        try:
            px = fetch_price(sym)
            price = float(px or 0.0)
        except Exception:
            price = 0.0
        if price <= 0:
            failed += 1
            continue
        entry = float(t.get("entry_price") or 0.0)
        realized_pct = ((price - entry) / entry * 100.0) if entry > 0 else 0.0
        t["exit_price"] = round(price, 2)
        t["closed_at"] = _iso(now)
        t["status"] = "CLOSED"
        t["realized_pct"] = round(realized_pct, 3)
        t["direction_hit"] = 1 if realized_pct > 0 else 0
        resolved += 1
    save_ledger(ledger, path)
    return {"resolved": resolved, "failed": failed, "still_open": still_open}


def hitrate_report(*, lookback_days: int = 365, path: Path | None = None) -> dict[str, Any]:
    ledger = load_ledger(path)
    since = _utc_now() - timedelta(days=max(7, int(lookback_days)))
    closed = _closed_since(ledger, since)
    n = len(closed)
    if n <= 0:
        return {
            "samples": 0,
            "hit_rate_pct": None,
            "avg_realized_pct": None,
            "open_count": _open_count(ledger),
            "lookback_days": int(lookback_days),
        }
    hits = sum(int(t.get("direction_hit") or 0) for t in closed)
    avg = sum(float(t.get("realized_pct") or 0.0) for t in closed) / n
    return {
        "samples": n,
        "hit_rate_pct": round(hits / n * 100.0, 2),
        "avg_realized_pct": round(avg, 3),
        "open_count": _open_count(ledger),
        "lookback_days": int(lookback_days),
    }


def _closed_since(ledger: dict[str, Any], since: datetime) -> list[dict[str, Any]]:
    closed: list[dict[str, Any]] = []
    for t in ledger.get("trades") or []:
        if str(t.get("status") or "").upper() != "CLOSED":
            continue
        raw = str(t.get("closed_at") or t.get("opened_at") or "")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if dt >= since:
            closed.append(t)
    return closed


def hitrate_report_extended(*, horizons: tuple[int, ...] = (30, 90, 365), path: Path | None = None) -> dict[str, Any]:
    """Aggregate hit-rate by lookback window and by entry action."""
    ledger = load_ledger(path)
    windows: dict[str, Any] = {}
    for days in horizons:
        since = _utc_now() - timedelta(days=max(7, int(days)))
        closed = _closed_since(ledger, since)
        n = len(closed)
        if n <= 0:
            windows[str(days)] = {"samples": 0, "hit_rate_pct": None, "avg_realized_pct": None}
            continue
        hits = sum(int(t.get("direction_hit") or 0) for t in closed)
        avg = sum(float(t.get("realized_pct") or 0.0) for t in closed) / n
        windows[str(days)] = {
            "samples": n,
            "hit_rate_pct": round(hits / n * 100.0, 2),
            "avg_realized_pct": round(avg, 3),
        }

    by_action: dict[str, Any] = {}
    closed_all = _closed_since(ledger, _utc_now() - timedelta(days=max(horizons)))
    for act in ("BUY", "CONDITIONAL_BUY", "HOLD", "WATCH", "AVOID", ""):
        subset = [t for t in closed_all if str(t.get("action") or "").upper() == act] if act else [
            t for t in closed_all if not str(t.get("action") or "").strip()
        ]
        if not subset:
            continue
        key = act or "UNKNOWN"
        hits = sum(int(t.get("direction_hit") or 0) for t in subset)
        avg = sum(float(t.get("realized_pct") or 0.0) for t in subset) / len(subset)
        by_action[key] = {
            "samples": len(subset),
            "hit_rate_pct": round(hits / len(subset) * 100.0, 2),
            "avg_realized_pct": round(avg, 3),
        }

    return {
        "generated_at": _iso(_utc_now()),
        "open_count": _open_count(ledger),
        "windows": windows,
        "by_action": by_action,
        "recent_closed": recent_closed_trades(limit=12, anonymize=True, path=path),
    }


def recent_closed_trades(*, limit: int = 10, anonymize: bool = True, path: Path | None = None) -> list[dict[str, Any]]:
    ledger = load_ledger(path)
    closed = [t for t in (ledger.get("trades") or []) if str(t.get("status") or "").upper() == "CLOSED"]
    closed.sort(key=lambda t: str(t.get("closed_at") or ""), reverse=True)
    out: list[dict[str, Any]] = []
    for t in closed[: max(1, int(limit))]:
        sym = str(t.get("symbol") or "")
        label = f"Mã #{hash(sym) % 900 + 100}" if anonymize and sym else sym
        out.append(
            {
                "symbol_label": label,
                "action": str(t.get("action") or ""),
                "entry_price": t.get("entry_price"),
                "exit_price": t.get("exit_price"),
                "realized_pct": t.get("realized_pct"),
                "direction_hit": t.get("direction_hit"),
                "horizon_days": t.get("horizon_days"),
                "closed_at": t.get("closed_at"),
            }
        )
    return out


def format_hitrate_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Paper-trade accountability",
        "",
        f"Generated: {report.get('generated_at') or '—'}",
        "",
        "## Hit-rate by window",
        "",
        "| Window (days) | Samples | Hit-rate % | Avg realized % |",
        "|---|---:|---:|---:|",
    ]
    for days, block in sorted((report.get("windows") or {}).items(), key=lambda x: int(x[0])):
        lines.append(
            f"| {days} | {block.get('samples')} | {block.get('hit_rate_pct') if block.get('hit_rate_pct') is not None else '—'} "
            f"| {block.get('avg_realized_pct') if block.get('avg_realized_pct') is not None else '—'} |"
        )
    lines.extend(["", "## By entry action", ""])
    by_action = report.get("by_action") or {}
    if not by_action:
        lines.append("_No closed trades yet._")
    else:
        lines.extend(["| Action | Samples | Hit-rate % | Avg realized % |", "|---|---:|---:|---:|"])
        for act, block in sorted(by_action.items()):
            lines.append(
                f"| {act} | {block.get('samples')} | {block.get('hit_rate_pct')} | {block.get('avg_realized_pct')} |"
            )
    lines.extend(["", f"Open trades: **{report.get('open_count') or 0}**", ""])
    recent = report.get("recent_closed") or []
    if recent:
        lines.extend(["## Recent closed (anonymized)", ""])
        lines.extend(["| Label | Action | Realized % | Hit | Horizon |", "|---|---|---:|---:|---:|"])
        for row in recent:
            lines.append(
                f"| {row.get('symbol_label')} | {row.get('action') or '—'} | {row.get('realized_pct')} "
                f"| {row.get('direction_hit')} | {row.get('horizon_days')} |"
            )
    return "\n".join(lines) + "\n"


def _open_count(ledger: dict[str, Any]) -> int:
    return sum(1 for t in (ledger.get("trades") or []) if str(t.get("status") or "").upper() == "OPEN")
