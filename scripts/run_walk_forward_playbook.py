"""
Walk-forward OOS for playbook (Wave 1).

  python scripts/run_walk_forward_playbook.py --vn30 --limit 30 --mode locked
  python scripts/run_walk_forward_playbook.py --vn30 --limit 15 --mode train_select
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Walk-forward OOS playbook evaluation")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--vn30", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--sessions", type=int, default=520)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--mode", choices=("locked", "train_select"), default="locked")
    ap.add_argument("--fold-months", type=int, default=6)
    ap.add_argument("--min-train-months", type=int, default=18)
    ap.add_argument("--embargo-days", type=int, default=10)
    ap.add_argument("--rolling", action="store_true")
    ap.add_argument("--primary-horizon", type=int, default=60)
    ap.add_argument("--horizons", default="20,40,60,90")
    ap.add_argument("--json-out", default="artifacts/operations/walk_forward_latest.json")
    ap.add_argument("--md-out", default="artifacts/operations/walk_forward_latest.md")
    ap.add_argument(
        "--scorecard-out",
        default="artifacts/operations/expert_edge_scorecard.json",
    )
    args = ap.parse_args(argv)

    from core.decision_playbook_backtest import (
        PlaybookBacktestConfig,
        load_ohlcv_for_replay,
        replay_playbook_on_ohlcv,
        sanitize_ohlcv_for_backtest,
    )
    from core.liquid_universe import VN30_SYMBOLS
    from core.walk_forward_playbook import (
        WalkForwardConfig,
        format_walk_forward_markdown,
        run_walk_forward_on_pools,
    )

    if args.vn30 or not str(args.symbols or "").strip():
        symbols = list(VN30_SYMBOLS)[: max(1, int(args.limit))]
    else:
        symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
        symbols = symbols[: max(1, int(args.limit))]

    horizons = tuple(sorted({int(x.strip()) for x in str(args.horizons).split(",") if x.strip()}))
    # Replay with production-like playbook; armed_pool = all ARMED+READY (pre-style)
    bt_cfg = PlaybookBacktestConfig(
        min_history=120,
        stride=int(args.stride),
        horizons=horizons,
        entry_style="pit_quality",
        use_pit_fundamentals=True,
    ).normalize()

    print(f"[wf] symbols={symbols} mode={args.mode}", flush=True)
    bench, bench_src = load_ohlcv_for_replay("VNINDEX", sessions=int(args.sessions))
    if bench.empty:
        try:
            from core.strategy_backtest import fetch_long_ohlcv_for_backtest

            raw, rng = fetch_long_ohlcv_for_backtest("E1VFVN30", range_preference="5y")
            bench = sanitize_ohlcv_for_backtest(raw)
            bench_src = f"yahoo_E1VFVN30:{rng}"
        except Exception:
            pass
    print(f"[wf] bench={bench_src} bars={len(bench)}", flush=True)

    armed: list[dict[str, Any]] = []
    watch: list[dict[str, Any]] = []
    avoid: list[dict[str, Any]] = []
    for sym in symbols:
        ohlcv, src = load_ohlcv_for_replay(sym, sessions=int(args.sessions))
        print(f"[wf] {sym}: bars={len(ohlcv)} src={src}", flush=True)
        if ohlcv.empty:
            continue
        res = replay_playbook_on_ohlcv(
            ohlcv,
            symbol=sym,
            benchmark_ohlcv=bench if not bench.empty else None,
            config=bt_cfg,
        )
        if not res.get("ok"):
            continue
        armed.extend(list(res.get("armed_pool") or []))
        watch.extend(list(res.get("watch_control") or []))
        avoid.extend(list(res.get("avoid_control") or []))
        print(
            f"  -> armed={res.get('n_armed_pool')} watch={res.get('n_watch_control')} "
            f"avoid={res.get('n_avoid_control')}",
            flush=True,
        )

    wf_cfg = WalkForwardConfig(
        mode=str(args.mode),
        fold_months=int(args.fold_months),
        min_train_months=int(args.min_train_months),
        embargo_days=int(args.embargo_days),
        rolling=bool(args.rolling),
        primary_horizon=int(args.primary_horizon),
        horizons=horizons,
        entry_style="pit_quality",
    ).normalize()

    report = run_walk_forward_on_pools(
        armed_pool=armed,
        watch_control=watch,
        avoid_control=avoid,
        config=wf_cfg,
        locked_cfg=PlaybookBacktestConfig(entry_style="pit_quality").normalize(),
    )
    report["symbols"] = symbols
    report["benchmark_source"] = bench_src
    report["armed_pool_size"] = len(armed)

    json_out = ROOT / str(args.json_out)
    md_out = ROOT / str(args.md_out)
    score_out = ROOT / str(args.scorecard_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    # Slim folds for JSON size
    slim = dict(report)
    slim_folds = []
    for f in report.get("folds") or []:
        slim_folds.append(
            {
                k: f.get(k)
                for k in (
                    "fold",
                    "train_start",
                    "train_end",
                    "test_start",
                    "test_end",
                    "selected_label",
                    "selected_config",
                    "primary_samples",
                    "enough_samples",
                    "entry_avg_primary",
                    "watch_avg_primary",
                    "entry_excess_primary",
                    "beats_watch_primary",
                    "positive_excess_primary",
                    "fold_pass",
                )
            }
        )
    slim["folds"] = slim_folds
    json_out.write_text(json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(format_walk_forward_markdown(report), encoding="utf-8")

    scorecard = {
        "updated_at_utc": report.get("generated_at_utc"),
        "wave": "1_walk_forward",
        "mode": report.get("mode"),
        "gate_pass": report.get("gate_pass"),
        "n_folds_pass": report.get("n_folds_pass"),
        "n_folds_scored": report.get("n_folds_scored"),
        "oos_pooled_trades": report.get("oos_pooled_trades"),
        "oos_entry_beats_watch": (report.get("oos_entry_vs_watch") or {}).get("entry_beats_watch"),
        "oos_by_horizon": ((report.get("oos_pooled_summary") or {}).get("by_horizon") or {}),
        "baseline_rule": "pit_quality (PIT + Rev&LN ≥ 0 + ARMED/READY)",
        "artifacts": {
            "walk_forward_json": str(json_out.relative_to(ROOT)).replace("\\", "/"),
            "walk_forward_md": str(md_out.relative_to(ROOT)).replace("\\", "/"),
        },
    }
    score_out.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")

    print(format_walk_forward_markdown(report), flush=True)
    print(f"Wrote: {json_out}", flush=True)
    print(f"Wrote: {md_out}", flush=True)
    print(f"Wrote: {score_out}", flush=True)
    print(f"[wf] GATE_PASS={report.get('gate_pass')}", flush=True)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
