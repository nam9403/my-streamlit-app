"""
Replay decision playbook (P0/P1) trên OHLCV lịch sử — đánh giá hit-rate vs VNINDEX.

  python scripts/replay_decision_playbook_backtest.py --symbols FPT,HPG,VNM,VCB,MWG
  python scripts/replay_decision_playbook_backtest.py --vn30 --limit 10 --stride 5
  python scripts/replay_decision_playbook_backtest.py --vn30 --limit 15 --sessions 520

Artifacts:
  artifacts/operations/playbook_backtest_latest.json
  artifacts/operations/playbook_backtest_latest.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

os.environ.setdefault("II_SNAPSHOT_PREFER_LIVE", "0")
os.environ.setdefault("II_OHLCV_DISK_FIRST", "1")
os.environ.setdefault("II_READ_STALE_DISK", "1")


def _parse_int_list(raw: str) -> tuple[int, ...]:
    return tuple(sorted({int(x.strip()) for x in raw.split(",") if x.strip()}))


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _horizon_table(summary: dict[str, Any]) -> list[str]:
    by_h = summary.get("by_horizon") if isinstance(summary.get("by_horizon"), dict) else {}
    if not by_h:
        return ["_(không có trade)_", ""]
    lines = [
        "| Horizon | Samples | Hit% | Avg% | Median% | Excess vs bench% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for h in sorted(by_h.keys(), key=lambda x: int(x)):
        row = by_h[h] or {}
        lines.append(
            f"| {h}d | {row.get('samples', 0)} | {_fmt(row.get('hit_rate_pct'))} | "
            f"{_fmt(row.get('avg_return_pct'))} | {_fmt(row.get('median_return_pct'))} | "
            f"{_fmt(row.get('avg_excess_vs_bench_pct'))} |"
        )
    return lines + [""]


def build_markdown(report: dict[str, Any]) -> str:
    pooled = report.get("pooled_summary") or {}
    watch = report.get("watch_control_summary") or {}
    avoid = report.get("avoid_control_summary") or {}
    lines = [
        "# Decision playbook historical backtest",
        "",
        f"Generated: `{report.get('generated_at_utc')}`",
        "",
        str(report.get("disclaimer_vi") or ""),
        "",
        f"- Symbols OK: **{report.get('symbols_ok')}/{report.get('symbols_total')}**",
        f"- Pooled entry trades (BUY/CONDITIONAL_BUY): **{report.get('pooled_trades')}**",
        f"- ARMED+READY pool (pre-style): **{report.get('armed_pool_size')}**",
        f"- Method: `{report.get('method_note_vi') or 'playbook replay + valuation proxy'}`",
        "",
        "## Entry signals (BUY / CONDITIONAL_BUY)",
        "",
    ]
    lines.extend(_horizon_table(pooled if isinstance(pooled, dict) else {}))
    lines.extend(["## Control: nếu mua khi WATCH/HOLD", ""])
    lines.extend(_horizon_table(watch if isinstance(watch, dict) else {}))
    lines.extend(["## Control: nếu mua khi AVOID (đo bảo vệ)", ""])
    lines.extend(_horizon_table(avoid if isinstance(avoid, dict) else {}))
    verdict = report.get("entry_vs_watch") or {}
    lines.extend(
        [
            "## Verdict: entry vs WATCH",
            "",
            f"- Entry beats WATCH (avg): **{verdict.get('entry_beats_watch')}** "
            f"({verdict.get('wins_avg')}/{verdict.get('compared')} horizons)",
            f"- {verdict.get('note_vi') or ''}",
            "",
        ]
    )
    avoid_v = report.get("avoid_vs_watch") or {}
    lines.extend(
        [
            "## Verdict: AVOID vs WATCH (protective gate)",
            "",
            f"- AVOID is protective: **{avoid_v.get('avoid_is_protective')}** "
            f"({avoid_v.get('protective_wins')}/{avoid_v.get('compared')} horizons)",
            f"- {avoid_v.get('note_vi') or ''}",
            "",
        ]
    )
    sweep = report.get("filter_sweep") or {}
    best = sweep.get("best") or {}
    lines.extend(
        [
            "## Filter sweep (offline trên ARMED+READY pool)",
            "",
            f"- Variants tested: **{sweep.get('variants_tested')}**",
            f"- Any variant beats WATCH: **{sweep.get('any_beats_watch')}**",
            f"- Best: `{best.get('label')}` — trades={best.get('n_trades')}, "
            f"avg60={_fmt(best.get('avg_return_60d'))}, "
            f"ex20={_fmt(best.get('avg_excess_20d'))}, "
            f"beats={((best.get('entry_vs_watch') or {}).get('entry_beats_watch'))}",
            "",
            "| Rank | Label | Trades | Avg60% | Ex20% | Ex60% | Beats WATCH | Wins |",
            "|---:|---|---:|---:|---:|---:|---|---:|",
        ]
    )
    for i, row in enumerate(sweep.get("top5") or [], 1):
        lines.append(
            f"| {i} | `{row.get('label')}` | {row.get('n_trades')} | "
            f"{_fmt(row.get('avg_return_60d'))} | {_fmt(row.get('avg_excess_20d'))} | "
            f"{_fmt(row.get('avg_excess_60d'))} | {row.get('entry_beats_watch')} | {row.get('wins_avg')} |"
        )
    lines.append("")
    lines.extend(["## Per symbol", "", "| Symbol | Trades | Notes |", "|---|---:|---|"])
    for row in report.get("per_symbol") or []:
        sym = row.get("symbol")
        n = row.get("n_trades")
        ac = row.get("action_counts") or {}
        note = ", ".join(f"{k}:{v}" for k, v in sorted(ac.items())) if ac else ("fail" if not row.get("ok") else "—")
        lines.append(f"| {sym} | {n} | {note} |")
    lines.extend(
        [
            "",
            "---",
            "",
            "Cách đọc: Hit% / Avg% sau phí round-trip; Excess = return mã − VNINDEX cùng cửa sổ. "
            "Nếu entry tốt hơn WATCH control và excess > 0 trên 60–90d → rule có tín hiệu sơ bộ.",
        ]
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay decision playbook on historical OHLCV.")
    ap.add_argument("--symbols", default="", help="Comma-separated tickers")
    ap.add_argument("--vn30", action="store_true", help="Use VN30 universe")
    ap.add_argument("--limit", type=int, default=12, help="Max symbols")
    ap.add_argument("--sessions", type=int, default=520)
    ap.add_argument("--min-history", type=int, default=120)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--horizons", default="20,60,90")
    ap.add_argument("--cost-pct", type=float, default=0.30, help="Round-trip fee+slippage %")
    ap.add_argument(
        "--entry-style",
        default="pit_quality",
        choices=("value_accum", "breakout", "both", "pit_quality", "pit_strict", "armed_pool"),
        help="pit_quality (default); pit_strict; value_accum; breakout; both; armed_pool",
    )
    ap.add_argument("--no-pit", action="store_true", help="Disable PIT BCTC (use static cache only)")
    ap.add_argument("--json-out", default="artifacts/operations/playbook_backtest_latest.json")
    ap.add_argument("--md-out", default="artifacts/operations/playbook_backtest_latest.md")
    args = ap.parse_args(argv)

    from core.decision_playbook_backtest import (
        PlaybookBacktestConfig,
        aggregate_universe_results,
        load_ohlcv_for_replay,
        replay_playbook_on_ohlcv,
    )
    from core.liquid_universe import VN30_SYMBOLS

    if args.vn30 or not str(args.symbols or "").strip():
        symbols = list(VN30_SYMBOLS)[: max(1, int(args.limit))]
    else:
        symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
        symbols = symbols[: max(1, int(args.limit))]

    horizons = _parse_int_list(args.horizons)
    cfg = PlaybookBacktestConfig(
        min_history=int(args.min_history),
        stride=int(args.stride),
        horizons=horizons,
        roundtrip_cost_pct=float(args.cost_pct),
        entry_style=str(args.entry_style),
        use_pit_fundamentals=not bool(args.no_pit),
    ).normalize()

    print(f"[playbook-bt] symbols={symbols}", flush=True)
    bench, bench_src = load_ohlcv_for_replay("VNINDEX", sessions=int(args.sessions))
    if bench.empty:
        bench, bench_src = load_ohlcv_for_replay("VN30", sessions=int(args.sessions))
    if bench.empty:
        try:
            from core.strategy_backtest import fetch_long_ohlcv_for_backtest

            bench_raw, rng = fetch_long_ohlcv_for_backtest("E1VFVN30", range_preference="5y")
            from core.decision_playbook_backtest import sanitize_ohlcv_for_backtest

            bench = sanitize_ohlcv_for_backtest(bench_raw)
            bench_src = f"yahoo_E1VFVN30:{rng}"
        except Exception:
            pass
    print(f"[playbook-bt] benchmark_src={bench_src} bars={len(bench)}", flush=True)

    results: list[dict[str, Any]] = []
    for sym in symbols:
        ohlcv, src = load_ohlcv_for_replay(sym, sessions=int(args.sessions))
        print(f"[playbook-bt] {sym}: bars={len(ohlcv)} src={src}", flush=True)
        if ohlcv.empty or len(ohlcv) < cfg.min_history + max(cfg.horizons):
            results.append({"symbol": sym, "ok": False, "reason": "insufficient_history", "trades": [], "n_trades": 0})
            continue
        res = replay_playbook_on_ohlcv(ohlcv, symbol=sym, benchmark_ohlcv=bench if not bench.empty else None, config=cfg)
        results.append(res)
        s = res.get("summary") or {}
        print(
            f"  -> trades={res.get('n_trades')} actions={res.get('action_counts')} "
            f"summary_samples={s.get('samples')}",
            flush=True,
        )

    report = aggregate_universe_results(results, horizons=cfg.horizons)
    report["method_note_vi"] = (
        f"Replay playbook P1 tuned; entry_style={cfg.entry_style}; "
        f"ARMED+READY+filters; cost={cfg.roundtrip_cost_pct}% round-trip; stride={cfg.stride}."
    )
    report["config"] = {
        "symbols": symbols,
        "sessions": int(args.sessions),
        "min_history": cfg.min_history,
        "stride": cfg.stride,
        "horizons": list(cfg.horizons),
        "cost_pct": cfg.roundtrip_cost_pct,
        "entry_style": cfg.entry_style,
        "benchmark_source": bench_src,
        "benchmark_bars": len(bench),
    }
    report["results"] = [
        {
            "symbol": r.get("symbol"),
            "ok": r.get("ok"),
            "n_trades": r.get("n_trades"),
            "action_counts": r.get("action_counts"),
            "summary": r.get("summary"),
            "watch_summary": r.get("watch_summary"),
            "trades_sample": (r.get("trades") or [])[:15],
            "armed_pool_sample": (r.get("armed_pool") or [])[:10],
        }
        for r in results
    ]
    # Keep JSON lean: drop full pools from nested results (already summarized).
    for r in results:
        r.pop("watch_control", None)
        r.pop("avoid_control", None)
        r.pop("armed_pool", None)

    json_out = ROOT / str(args.json_out)
    md_out = ROOT / str(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = build_markdown(report)
    md_out.write_text(md, encoding="utf-8")
    print(md)
    print(f"Wrote: {json_out}")
    print(f"Wrote: {md_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
