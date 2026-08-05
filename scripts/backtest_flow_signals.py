#!/usr/bin/env python3
"""CLI backtest cho FlowSignal trên OHLCV lịch sử (free, không cần license).

Cách dùng nhanh:

    python scripts/backtest_flow_signals.py \
        --symbols FPT,HPG,VNM,VCB,MWG \
        --sessions 500 \
        --stride 5 \
        --horizons 1,5,20 \
        --output artifacts/flow_backtest/flow_backtest_2026.json \
        --markdown artifacts/flow_backtest/flow_backtest_2026.md

Output:
- JSON: per-symbol per-signal + summary + universe pooled summary +
  recommended ``min_intensity`` theo từng horizon.
- Markdown: bảng human-readable để dán vào release notes / Slack.

Script chỉ dùng:
- ``scrapers.portal.fetch_ohlcv_history`` (free, đã có)
- ``core.flow_backtest_service`` (vừa thêm)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.flow_backtest_service import (  # noqa: E402
    DEFAULT_HORIZONS,
    DEFAULT_INTENSITY_BUCKETS,
    BacktestConfig,
    aggregate_universe_backtest,
    backtest_flow_signals,
    recommend_min_intensity,
    save_recommendation_artifact,
)
from scrapers.portal import PortalDataError, fetch_ohlcv_history  # noqa: E402


def _parse_int_list(raw: str) -> tuple[int, ...]:
    return tuple(sorted({int(x.strip()) for x in raw.split(",") if x.strip()}))


def _parse_float_list(raw: str) -> tuple[float, ...]:
    return tuple(sorted({float(x.strip()) for x in raw.split(",") if x.strip()}))


def _format_summary_md(summary: list[dict[str, Any]], horizons: tuple[int, ...]) -> str:
    if not summary:
        return "_(không có signal nào để tổng hợp)_\n"
    header = ["Bucket", "Count"]
    for h in horizons:
        header += [f"Hit% {h}d", f"Avg% {h}d", f"Med% {h}d"]
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for b in summary:
        row = [str(b.get("bucket")), str(int(b.get("count") or 0))]
        for h in horizons:
            row += [
                _fmt(b.get(f"hit_rate_{h}d")),
                _fmt(b.get(f"avg_return_{h}d")),
                _fmt(b.get(f"median_return_{h}d")),
            ]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.2f}"
    except (TypeError, ValueError):
        return str(v)


def _build_markdown(report: dict[str, Any]) -> str:
    horizons = tuple(report["config"]["horizons"])
    out: list[str] = []
    out.append(f"# Flow signal backtest — {report['generated_at_utc']}")
    out.append("")
    out.append(f"- Symbols (n={report['n_symbols']}): `{', '.join(report['symbols'])}`")
    out.append(f"- Sessions / symbol: {report['config']['sessions']}")
    out.append(f"- Stride: {report['config']['stride']} bars")
    out.append(f"- Horizons (days): {list(horizons)}")
    out.append(f"- Intensity buckets: {report['config']['intensity_buckets']}")
    out.append(f"- Require big_boy: {report['config']['require_big_boy']}")
    out.append("")
    out.append("## Pooled universe summary")
    out.append("")
    out.append(f"- Total signals pooled: **{report['pooled']['n_signals_pooled']}**")
    out.append("")
    out.append(_format_summary_md(report["pooled"]["summary"], horizons))
    out.append("## Recommended `min_intensity`")
    out.append("")
    for h in horizons:
        rec = report["recommendations"].get(f"horizon_{h}d") or {}
        rec_val = rec.get("recommended")
        reason = rec.get("reason") or ""
        if rec_val is None:
            out.append(f"- **{h}d**: chưa đủ dữ liệu/edge dương — {reason}")
        else:
            out.append(f"- **{h}d**: **{rec_val}** — {reason}")
    out.append("")
    out.append("## Per-symbol breakdown")
    out.append("")
    for sym, res in report["per_symbol"].items():
        n_sig = res.get("n_signals", 0)
        n_rep = res.get("n_replays", 0)
        out.append(f"### {sym} (signals={n_sig}, replays={n_rep})")
        out.append("")
        out.append(_format_summary_md(res.get("summary") or [], horizons))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest FlowSignal trên OHLCV lịch sử")
    ap.add_argument("--symbols", default="FPT,HPG,VNM,VCB,MWG",
                    help="Danh sách mã, cách nhau bằng dấu phẩy (mặc định 5 mã VN30).")
    ap.add_argument("--sessions", type=int, default=500,
                    help="Số phiên OHLCV lấy về mỗi mã (default 500 ≈ 2 năm daily).")
    ap.add_argument("--min-history", type=int, default=150,
                    help="Số phiên warm-up trước khi bắt đầu replay (default 150).")
    ap.add_argument("--stride", type=int, default=5,
                    help="Khoảng cách bar giữa các lần replay (default 5).")
    ap.add_argument("--horizons", default="1,5,20",
                    help="Forward-return horizons (ngày), cách bằng dấu phẩy.")
    ap.add_argument("--buckets", default=",".join(str(b) for b in DEFAULT_INTENSITY_BUCKETS),
                    help="Cận dưới các intensity bucket.")
    ap.add_argument("--no-require-big-boy", action="store_true",
                    help="Tính cả signal is_big_boy=False (useful để debug).")
    ap.add_argument("--output", default="artifacts/flow_backtest/flow_backtest_latest.json",
                    help="Đường dẫn JSON output.")
    ap.add_argument("--markdown", default="artifacts/flow_backtest/flow_backtest_latest.md",
                    help="Đường dẫn Markdown output (đặt rỗng để skip).")
    ap.add_argument("--min-count", type=int, default=5,
                    help="Số mẫu tối thiểu mỗi bucket khi đề xuất min_intensity.")
    ap.add_argument("--min-avg-return-pct", type=float, default=0.0,
                    help="Avg-return tối thiểu (%) để bucket được chấp nhận.")
    ap.add_argument("--min-hit-rate-pct", type=float, default=50.0,
                    help="Hit-rate tối thiểu (%) để bucket được chấp nhận.")
    ap.add_argument("--recommendation-path",
                    default="artifacts/flow_backtest/recommendation_latest.json",
                    help="File JSON để runtime tự đọc lại min_intensity (đặt rỗng để skip).")
    ap.add_argument("--recommendation-horizon", type=int, default=5,
                    help="Horizon (ngày) mà runtime sẽ dùng khi đọc recommendation.")
    args = ap.parse_args(argv)

    symbols = [s.strip().upper() for s in str(args.symbols).split(",") if s.strip()]
    if not symbols:
        print("Cần ít nhất 1 mã.", file=sys.stderr)
        return 2

    horizons = _parse_int_list(args.horizons) or DEFAULT_HORIZONS
    buckets = _parse_float_list(args.buckets) or DEFAULT_INTENSITY_BUCKETS
    cfg = BacktestConfig(
        min_history=int(args.min_history),
        stride=int(args.stride),
        horizons=horizons,
        intensity_buckets=buckets,
        require_big_boy=not bool(args.no_require_big_boy),
    ).normalize()

    per_symbol: dict[str, dict[str, Any]] = {}
    skipped: list[str] = []
    for sym in symbols:
        try:
            ohlcv = fetch_ohlcv_history(sym, sessions=int(args.sessions))
        except PortalDataError:
            skipped.append(sym)
            continue
        if ohlcv is None or len(ohlcv) <= cfg.min_history:
            skipped.append(sym)
            continue
        try:
            res = backtest_flow_signals(ohlcv, symbol=sym, config=cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] backtest failed for {sym}: {exc}", file=sys.stderr)
            skipped.append(sym)
            continue
        per_symbol[sym] = res

    pooled = aggregate_universe_backtest(per_symbol, buckets=buckets, horizons=horizons)
    recommendations: dict[str, Any] = {}
    for h in horizons:
        rec = recommend_min_intensity(
            pooled["summary"],
            horizon_days=h,
            min_count=int(args.min_count),
            min_avg_return_pct=float(args.min_avg_return_pct),
            min_hit_rate_pct=float(args.min_hit_rate_pct),
        )
        recommendations[f"horizon_{h}d"] = rec

    report: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": list(per_symbol.keys()),
        "skipped": skipped,
        "n_symbols": len(per_symbol),
        "config": {
            "sessions": int(args.sessions),
            "min_history": cfg.min_history,
            "stride": cfg.stride,
            "horizons": list(horizons),
            "intensity_buckets": list(buckets),
            "require_big_boy": cfg.require_big_boy,
        },
        "per_symbol": per_symbol,
        "pooled": pooled,
        "recommendations": recommendations,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    if args.markdown:
        md_path = Path(args.markdown)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(_build_markdown(report), encoding="utf-8")

    rec_path: Path | None = None
    if args.recommendation_path:
        rec_path = save_recommendation_artifact(
            recommendations,
            horizon_days=int(args.recommendation_horizon),
            path=Path(args.recommendation_path),
            metadata={
                "n_symbols": len(per_symbol),
                "n_signals_pooled": pooled["n_signals_pooled"],
                "symbols": list(per_symbol.keys()),
                "sessions": int(args.sessions),
                "stride": cfg.stride,
                "min_count": int(args.min_count),
                "min_hit_rate_pct": float(args.min_hit_rate_pct),
            },
        )

    print(
        json.dumps(
            {
                "symbols_run": list(per_symbol.keys()),
                "skipped": skipped,
                "pooled_signals": pooled["n_signals_pooled"],
                "recommendations": {k: v.get("recommended") for k, v in recommendations.items()},
                "json": str(out_path),
                "markdown": str(args.markdown) if args.markdown else None,
                "recommendation_artifact": str(rec_path) if rec_path else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
