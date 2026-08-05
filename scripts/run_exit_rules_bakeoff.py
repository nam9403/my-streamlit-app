"""
Wave 2 — exit rule bake-off on playbook entries.

  python scripts/run_exit_rules_bakeoff.py --vn30 --limit 30
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


def _parse_horizons(raw: str) -> tuple[int, ...]:
    return tuple(sorted({int(x.strip()) for x in raw.split(",") if x.strip()}))


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Playbook exit rules bake-off (Wave 2)",
        "",
        f"Generated: `{report.get('generated_at_utc')}`",
        "",
        str(report.get("disclaimer_vi") or ""),
        "",
        f"- Symbols OK: **{report.get('symbols_ok')}/{report.get('symbols_total')}**",
        f"- Entry trades: **{report.get('n_trades')}**",
        f"- Entry style: `{report.get('entry_style')}`",
        f"- Best: **{((report.get('best') or {}).get('label'))}** — "
        f"{((report.get('best') or {}).get('summary'))}",
        "",
        "| Rank | Variant | n | Hit% | Avg% | Median% | Avg hold | Reasons |",
        "|---:|---|---:|---:|---:|---:|---:|---|",
    ]
    for i, row in enumerate(report.get("ranked") or [], 1):
        s = row.get("summary") or {}
        reasons = s.get("exit_reasons") or {}
        reason_txt = ", ".join(f"{k}:{v}" for k, v in sorted(reasons.items()))
        lines.append(
            f"| {i} | `{row.get('label')}` | {s.get('samples')} | {s.get('hit_rate_pct')} | "
            f"{s.get('avg_return_pct')} | {s.get('median_return_pct')} | "
            f"{s.get('avg_hold_days')} | {reason_txt} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            str(report.get("recommendation_vi") or ""),
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Exit rules bake-off for playbook entries")
    ap.add_argument("--symbols", default="")
    ap.add_argument("--vn30", action="store_true")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--stride", type=int, default=5)
    ap.add_argument("--sessions", type=int, default=520)
    ap.add_argument("--horizons", default="20,40,60,90")
    ap.add_argument("--json-out", default="artifacts/operations/exit_rules_latest.json")
    ap.add_argument("--md-out", default="artifacts/operations/exit_rules_latest.md")
    args = ap.parse_args(argv)

    from datetime import datetime, timezone

    from core.decision_playbook_backtest import (
        PlaybookBacktestConfig,
        load_ohlcv_for_replay,
        replay_playbook_on_ohlcv,
        sanitize_ohlcv_for_backtest,
    )
    from core.liquid_universe import VN30_SYMBOLS
    from core.playbook_exit_rules import ExitRuleConfig, compare_exit_configs

    if args.vn30 or not str(args.symbols or "").strip():
        symbols = list(VN30_SYMBOLS)[: max(1, int(args.limit))]
    else:
        symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
        symbols = symbols[: max(1, int(args.limit))]

    horizons = _parse_horizons(args.horizons)
    bt_cfg = PlaybookBacktestConfig(
        min_history=120,
        stride=int(args.stride),
        horizons=horizons,
        entry_style="pit_quality",
        use_pit_fundamentals=True,
    ).normalize()

    print(f"[exit-bt] symbols={symbols}", flush=True)
    bench, bench_src = load_ohlcv_for_replay("VNINDEX", sessions=int(args.sessions))
    if bench.empty:
        try:
            from core.strategy_backtest import fetch_long_ohlcv_for_backtest

            raw, rng = fetch_long_ohlcv_for_backtest("E1VFVN30", range_preference="5y")
            bench = sanitize_ohlcv_for_backtest(raw)
            bench_src = f"yahoo_E1VFVN30:{rng}"
        except Exception:
            pass
    print(f"[exit-bt] bench={bench_src} bars={len(bench)}", flush=True)

    ohlcv_map: dict[str, Any] = {}
    trades: list[dict[str, Any]] = []
    ok = 0
    for sym in symbols:
        df, src = load_ohlcv_for_replay(sym, sessions=int(args.sessions))
        print(f"[exit-bt] {sym}: bars={len(df)} src={src}", flush=True)
        if df.empty:
            continue
        res = replay_playbook_on_ohlcv(
            df,
            symbol=sym,
            benchmark_ohlcv=bench if not bench.empty else None,
            config=bt_cfg,
        )
        if not res.get("ok"):
            continue
        ok += 1
        ohlcv_map[sym] = df
        trades.extend(list(res.get("trades") or []))
        print(f"  -> trades={res.get('n_trades')}", flush=True)

    variants: list[tuple[str, ExitRuleConfig]] = [
        ("time20", ExitRuleConfig(time_stop_days=20, atr_stop_mult=None, giveback_arm_pct=None)),
        ("time40", ExitRuleConfig(time_stop_days=40, atr_stop_mult=None, giveback_arm_pct=None)),
        ("time60", ExitRuleConfig(time_stop_days=60, atr_stop_mult=None, giveback_arm_pct=None)),
        ("time90", ExitRuleConfig(time_stop_days=90, atr_stop_mult=None, giveback_arm_pct=None)),
        ("time40_atr2", ExitRuleConfig(time_stop_days=40, atr_stop_mult=2.0, giveback_arm_pct=None)),
        ("time60_atr2", ExitRuleConfig(time_stop_days=60, atr_stop_mult=2.0, giveback_arm_pct=None)),
        ("time40_gb", ExitRuleConfig(time_stop_days=40, atr_stop_mult=None, giveback_arm_pct=8.0, giveback_pct=4.0)),
        ("time60_gb", ExitRuleConfig(time_stop_days=60, atr_stop_mult=None, giveback_arm_pct=8.0, giveback_pct=4.0)),
        (
            "time60_atr2_gb",
            ExitRuleConfig(time_stop_days=60, atr_stop_mult=2.0, giveback_arm_pct=8.0, giveback_pct=4.0),
        ),
        (
            "time40_atr2_gb",
            ExitRuleConfig(time_stop_days=40, atr_stop_mult=2.0, giveback_arm_pct=8.0, giveback_pct=4.0),
        ),
    ]
    cmp = compare_exit_configs(ohlcv_map, trades, variants)
    ranked = list(cmp.get("ranked") or [])

    def _op_score(row: dict[str, Any]) -> float:
        s = row.get("summary") or {}
        try:
            avg = float(s.get("avg_return_pct") or -999)
            med = float(s.get("median_return_pct") or -999)
            hit = float(s.get("hit_rate_pct") or 0)
            hold = float(s.get("avg_hold_days") or 60)
        except (TypeError, ValueError):
            return -999.0
        # Ưu tiên hit + median; phạt hold quá dài (bull drift)
        return avg + 0.6 * med + 0.04 * hit - 0.015 * max(0.0, hold - 40.0)

    # Operational shortlist: pure/ATR time stops ở 40–60d (khớp OOS excess)
    op_labels = {"time40", "time60", "time40_atr2", "time60_atr2"}
    op_cands = [r for r in ranked if str(r.get("label")) in op_labels]
    op_best = max(op_cands, key=_op_score) if op_cands else (ranked[0] if ranked else {})
    best = cmp.get("best") or {}
    best_label = str(op_best.get("label") or best.get("label") or "")
    best_sum = op_best.get("summary") or best.get("summary") or {}

    rec_horizon = 60
    if best_label.startswith("time20"):
        rec_horizon = 20
    elif best_label.startswith("time40"):
        rec_horizon = 40
    elif best_label.startswith("time90"):
        rec_horizon = 90
    elif best_label.startswith("time60"):
        rec_horizon = 60

    raw_best_label = str(best.get("label") or "")
    recommendation = (
        f"Vận hành (paper/nightly): horizon **{rec_horizon}d** theo `{best_label}` "
        f"(score cân bằng hit/median/hold; n={best_sum.get('samples')}, "
        f"hit={best_sum.get('hit_rate_pct')}%, avg={best_sum.get('avg_return_pct')}%, "
        f"median={best_sum.get('median_return_pct')}%). "
        f"Raw-avg leader là `{raw_best_label}` — không dùng làm mặc định nếu hold dài làm phình avg. "
        "Cần paper live; không cam kết lợi nhuận."
    )

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer_vi": (
            "Exit bake-off học tập trên entry pit_quality — path sim no look-ahead trong cửa sổ giữ. "
            "Không cam kết lợi nhuận tương lai."
        ),
        "symbols": symbols,
        "symbols_ok": ok,
        "symbols_total": len(symbols),
        "n_trades": len(trades),
        "entry_style": "pit_quality",
        "benchmark_source": bench_src,
        "recommended_horizon_days": rec_horizon,
        "recommended_variant": best_label,
        "raw_avg_best_variant": raw_best_label,
        "recommendation_vi": recommendation,
        "best": op_best,
        "raw_avg_best": best,
        "ranked": ranked,
    }

    json_out = ROOT / str(args.json_out)
    md_out = ROOT / str(args.md_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(build_markdown(report), encoding="utf-8")
    print(build_markdown(report), flush=True)
    print(f"Wrote: {json_out}", flush=True)
    print(f"Wrote: {md_out}", flush=True)
    print(f"[exit-bt] recommended_horizon_days={rec_horizon}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
