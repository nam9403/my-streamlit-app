"""
Wave 4 — weekly paper ops report (+ kill-switch status).

  python scripts/export_paper_weekly_report.py
  python scripts/export_paper_weekly_report.py --resolve
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def _fetch_price(sym: str) -> float | None:
    try:
        from scrapers.financial_data import fetch_financial_snapshot

        snap = fetch_financial_snapshot(sym) or {}
        px = float(snap.get("price") or 0.0)
        return px if px > 0 else None
    except Exception:
        return None


def build_markdown(report: dict) -> str:
    g = report.get("kill_switch") or {}
    w = report.get("week") or {}
    a = report.get("accountability") or {}
    lines = [
        "# Paper weekly ops report (Wave 4)",
        "",
        f"Generated: `{report.get('generated_at_utc')}`",
        "",
        "## Kill-switch",
        "",
        f"- Halt new opens: **{g.get('halt_new_opens')}**",
        f"- Enabled: `{g.get('enabled')}`",
        f"- Consecutive losses: `{g.get('consecutive_losses')}`",
        f"- Lookback n/hit/avg: `{g.get('lookback_n')}` / `{g.get('lookback_hit_rate_pct')}` / `{g.get('lookback_avg_realized_pct')}`",
        f"- Reasons: `{', '.join(g.get('reasons') or []) or '—'}`",
        "",
        "## Last 7 days (closed)",
        "",
        f"- Samples: **{w.get('samples')}**",
        f"- Hit%: **{w.get('hit_rate_pct')}**",
        f"- Avg realized%: **{w.get('avg_realized_pct')}**",
        f"- Open now: **{w.get('open_count')}**",
        "",
        "## Accountability windows",
        "",
    ]
    windows = a.get("windows") if isinstance(a.get("windows"), dict) else {}
    if windows:
        lines.extend(["| Window | Samples | Hit% | Avg% |", "|---|---:|---:|---:|"])
        for k in sorted(windows.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
            row = windows[k] or {}
            lines.append(
                f"| {k}d | {row.get('samples')} | {row.get('hit_rate_pct')} | {row.get('avg_realized_pct')} |"
            )
    else:
        lines.append("_(no closed samples)_")
    lines.extend(
        [
            "",
            str(report.get("note_vi") or ""),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export weekly paper ops report")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--json-out", default="artifacts/operations/paper_weekly_latest.json")
    ap.add_argument("--md-out", default="artifacts/operations/paper_weekly_latest.md")
    args = ap.parse_args(argv)

    from core.paper_ops_guard import evaluate_paper_kill_switch, persist_guard_state
    from core.paper_trade_ledger import (
        hitrate_report,
        hitrate_report_extended,
        load_ledger,
        resolve_due_trades,
    )

    resolve_stat = {"resolved": 0, "failed": 0, "still_open": 0}
    if args.resolve:
        resolve_stat = resolve_due_trades(fetch_price=_fetch_price)

    ledger = load_ledger()
    guard = evaluate_paper_kill_switch(ledger)
    persist_guard_state(guard)

    week = hitrate_report(lookback_days=7)
    accountability = hitrate_report_extended(horizons=(40, 30, 90, 365))

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "resolve": resolve_stat,
        "kill_switch": guard,
        "week": week,
        "accountability": accountability,
        "note_vi": (
            "Wave 4 ops — kill-switch chặn mở paper mới khi chuỗi thua / lookback yếu. "
            "Không cam kết lợi nhuận. Tắt tạm: II_PAPER_KILL_SWITCH=0."
        ),
        "operational_horizon_days": 40,
        "exit_variant": "time40_atr2",
    }

    json_out = ROOT / str(args.json_out)
    md_out = ROOT / str(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(build_markdown(report), encoding="utf-8")
    print(build_markdown(report))
    print(f"Wrote: {json_out}")
    print(f"Wrote: {md_out}")
    print(f"[paper-weekly] halt_new_opens={guard.get('halt_new_opens')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
