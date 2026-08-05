#!/usr/bin/env python3
"""
Track live-data stability across many sessions (7-14 days window).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.live_data_gate_check import evaluate_live_data  # noqa: E402


def _load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _append_history(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _window_rows(rows: list[dict[str, Any]], window_days: int) -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - timedelta(days=max(1, int(window_days)))
    out: list[dict[str, Any]] = []
    for row in rows:
        raw = str(row.get("generated_at_utc") or "")
        try:
            ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= cutoff:
            out.append(row)
    return out


def summarize_stability(
    rows: list[dict[str, Any]],
    *,
    min_sessions: int,
    min_live_ratio: float,
    min_available_ratio: float,
) -> dict[str, Any]:
    sessions = len(rows)
    if sessions == 0:
        return {
            "decision": "HOLD",
            "reasons": ["No sessions in selected window."],
            "sessions": 0,
            "min_live_ratio_observed": 0.0,
            "min_available_ratio_observed": 0.0,
            "avg_live_ratio": 0.0,
            "avg_available_ratio": 0.0,
        }
    live_list = [float(x.get("live_ratio") or 0.0) for x in rows]
    avail_list = [float(x.get("available_ratio") or 0.0) for x in rows]
    min_live = min(live_list)
    min_avail = min(avail_list)
    avg_live = sum(live_list) / sessions
    avg_avail = sum(avail_list) / sessions
    reasons: list[str] = []
    if sessions < int(min_sessions):
        reasons.append(f"Insufficient sessions: {sessions} < {int(min_sessions)}.")
    if min_live < float(min_live_ratio):
        reasons.append("At least one session violated min_live_ratio.")
    if min_avail < float(min_available_ratio):
        reasons.append("At least one session violated min_available_ratio.")
    decision = "GO" if not reasons else "HOLD"
    return {
        "decision": decision,
        "reasons": reasons,
        "sessions": sessions,
        "min_live_ratio_observed": round(min_live, 4),
        "min_available_ratio_observed": round(min_avail, 4),
        "avg_live_ratio": round(avg_live, 4),
        "avg_available_ratio": round(avg_avail, 4),
    }


def _to_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Live Data Stability Benchmark",
        "",
        f"- Generated at (UTC): `{summary.get('generated_at_utc')}`",
        f"- Decision: `{summary.get('decision')}`",
        f"- Sessions in window: `{summary.get('sessions')}`",
        f"- Min live ratio observed: `{summary.get('min_live_ratio_observed')}`",
        f"- Min available ratio observed: `{summary.get('min_available_ratio_observed')}`",
        f"- Avg live ratio: `{summary.get('avg_live_ratio')}`",
        f"- Avg available ratio: `{summary.get('avg_available_ratio')}`",
        "",
    ]
    reasons = summary.get("reasons") or []
    if reasons:
        lines.append("## Reasons")
        lines.append("")
        for r in reasons:
            lines.append(f"- {r}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="FPT,VNM,HPG,VCB")
    ap.add_argument("--window-days", type=int, default=14)
    ap.add_argument("--min-sessions", type=int, default=7)
    ap.add_argument("--min-live-ratio", type=float, default=0.25)
    ap.add_argument("--min-available-ratio", type=float, default=1.0)
    ap.add_argument("--history", default="artifacts/performance/live_data_stability_history.jsonl")
    ap.add_argument("--out-json", default="artifacts/performance/live_data_stability_benchmark.json")
    ap.add_argument("--out-md", default="artifacts/performance/live_data_stability_benchmark.md")
    ap.add_argument("--require-go", action="store_true")
    args = ap.parse_args()

    tickers = [x.strip().upper() for x in str(args.tickers).split(",") if x.strip()]
    current = evaluate_live_data(tickers=tickers)
    current_row = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "tickers": tickers,
        "live_ratio": float(current.get("live_ratio") or 0.0),
        "available_ratio": float(current.get("available_ratio") or 0.0),
        "counts": current.get("counts") or {},
    }
    history_path = Path(str(args.history))
    _append_history(history_path, current_row)
    all_rows = _load_history(history_path)
    rows = _window_rows(all_rows, int(args.window_days))
    summary = summarize_stability(
        rows,
        min_sessions=max(1, int(args.min_sessions)),
        min_live_ratio=max(0.0, min(1.0, float(args.min_live_ratio))),
        min_available_ratio=max(0.0, min(1.0, float(args.min_available_ratio))),
    )
    payload = {
        "generated_at_utc": current_row["generated_at_utc"],
        "decision": summary["decision"],
        "reasons": summary["reasons"],
        "window_days": max(1, int(args.window_days)),
        "thresholds": {
            "min_sessions": max(1, int(args.min_sessions)),
            "min_live_ratio": max(0.0, min(1.0, float(args.min_live_ratio))),
            "min_available_ratio": max(0.0, min(1.0, float(args.min_available_ratio))),
        },
        **summary,
        "latest_run": current_row,
    }
    out_json = Path(str(args.out_json))
    out_md = Path(str(args.out_md))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(_to_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if bool(args.require_go) and str(payload.get("decision")) != "GO":
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
