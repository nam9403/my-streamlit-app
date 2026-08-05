#!/usr/bin/env python3
"""
Build a timing dashboard (p50/p90/p95/p99) from JSONL metrics.

Usage:
  python scripts/build_timing_dashboard.py
  python scripts/build_timing_dashboard.py --in data/reports/logs/timing_metrics.jsonl --min-samples 3
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_FLOWS = [
    "product_layer.get_admin_kpi",
    "product_layer.process_notification_queue",
    "product_layer.get_notification_queue_diagnostics",
    "product_layer.retry_failed_notifications",
    "product_layer.get_kpi_dashboard",
]


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    vals = sorted(float(v) for v in values)
    if len(vals) == 1:
        return vals[0]
    idx = (len(vals) - 1) * q
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return vals[lo]
    frac = idx - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def load_events(path: Path, *, window_hours: float | None = None) -> list[dict]:
    out: list[dict] = []
    if not path.exists():
        return out
    cutoff = None
    if window_hours is not None and float(window_hours) > 0:
        cutoff = datetime.now(timezone.utc).timestamp() - float(window_hours) * 3600.0
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        metric = str(item.get("metric") or "").strip()
        duration_ms = item.get("duration_ms")
        if not metric:
            continue
        if not isinstance(duration_ms, (int, float, str)):
            continue
        try:
            duration = float(duration_ms)
        except ValueError:
            continue
        if cutoff is not None:
            ts_raw = str(item.get("ts") or "").strip()
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if ts < cutoff:
                continue
        item["duration_ms"] = duration
        item["metric"] = metric
        out.append(item)
    return out


def build_summary(events: list[dict], min_samples: int = 1) -> list[dict]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for e in events:
        grouped[str(e["metric"])].append(float(e["duration_ms"]))
    rows: list[dict] = []
    for metric, durations in grouped.items():
        if len(durations) < max(1, int(min_samples)):
            continue
        row = {
            "metric": metric,
            "samples": len(durations),
            "min_ms": round(min(durations), 2),
            "p50_ms": round(_percentile(durations, 0.50), 2),
            "p90_ms": round(_percentile(durations, 0.90), 2),
            "p95_ms": round(_percentile(durations, 0.95), 2),
            "p99_ms": round(_percentile(durations, 0.99), 2),
            "avg_ms": round(sum(durations) / len(durations), 2),
            "std_ms": round(
                math.sqrt(sum((x - (sum(durations) / len(durations))) ** 2 for x in durations) / len(durations)),
                2,
            ),
            "max_ms": round(max(durations), 2),
        }
        rows.append(row)
    rows.sort(key=lambda x: (float(x["p95_ms"]), float(x["avg_ms"])), reverse=True)
    return rows


def build_required_flow_coverage(
    summary: list[dict],
    *,
    required_flows: list[str],
    required_min_samples: int,
) -> dict[str, object]:
    by_metric = {str(x.get("metric") or ""): x for x in summary}
    rows: list[dict[str, object]] = []
    for flow in required_flows:
        item = by_metric.get(flow) or {}
        samples = int(item.get("samples") or 0)
        rows.append(
            {
                "metric": flow,
                "samples": samples,
                "required_min_samples": int(required_min_samples),
                "meets_sample_target": samples >= int(required_min_samples),
            }
        )
    covered = sum(1 for r in rows if bool(r["meets_sample_target"]))
    total = len(rows)
    return {
        "required_flows": rows,
        "required_flow_count": total,
        "covered_flow_count": covered,
        "coverage_ratio": round((covered / total), 4) if total > 0 else 0.0,
        "all_required_flows_covered": covered == total if total > 0 else True,
    }


def build_markdown(
    summary: list[dict],
    source: Path,
    total_events: int,
    min_samples: int,
    required_coverage: dict[str, object],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Timing Dashboard Mini",
        "",
        f"- Generated at (UTC): `{now}`",
        f"- Source: `{source.as_posix()}`",
        f"- Total parsed timing events: `{total_events}`",
        f"- Minimum samples per metric: `{min_samples}`",
        "",
    ]
    if not summary:
        lines.extend(
            [
                "No timing metrics found yet.",
                "",
                "Run app flows (scanner, queue, admin KPI) and generate again.",
            ]
        )
        return "\n".join(lines) + "\n"
    lines.extend(
        [
            "## Percentiles by flow",
            "",
            "| Flow | Samples | Min | p50 | p90 | p95 | p99 | Avg | Std | Max |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in summary:
        lines.append(
            f"| `{row['metric']}` | {row['samples']} | {row['min_ms']:.2f} | {row['p50_ms']:.2f} | {row['p90_ms']:.2f} | {row['p95_ms']:.2f} | {row['p99_ms']:.2f} | {row['avg_ms']:.2f} | {row['std_ms']:.2f} | {row['max_ms']:.2f} |"
        )
    req_rows_raw = required_coverage.get("required_flows") or []
    req_rows = [row for row in req_rows_raw if isinstance(row, dict)] if isinstance(req_rows_raw, list) else []
    lines.extend(
        [
            "",
            "## Required flow sample coverage",
            "",
            f"- Required flows covered: `{required_coverage.get('covered_flow_count')}/{required_coverage.get('required_flow_count')}`",
            f"- Coverage ratio: `{required_coverage.get('coverage_ratio')}`",
            f"- All required flows covered: `{required_coverage.get('all_required_flows_covered')}`",
            "",
            "| Flow | Samples | Required min samples | Meets target |",
            "|---|---:|---:|:---:|",
        ]
    )
    for row in req_rows:
        lines.append(
            f"| `{row['metric']}` | {row['samples']} | {row['required_min_samples']} | {'yes' if row['meets_sample_target'] else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Optimization targets",
            "",
            f"- Slowest p95 flow: `{summary[0]['metric']}` ({summary[0]['p95_ms']:.2f} ms)",
            "- Prioritize reducing p95 first, then avg.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default=str(ROOT / "data" / "reports" / "logs" / "timing_metrics.jsonl"))
    ap.add_argument("--out-json", default=str(ROOT / "artifacts" / "performance" / "timing_dashboard.json"))
    ap.add_argument("--out-md", default=str(ROOT / "artifacts" / "performance" / "timing_dashboard.md"))
    ap.add_argument("--min-samples", type=int, default=1)
    ap.add_argument("--window-hours", type=float, default=0.0, help="Only include timing events in recent N hours.")
    ap.add_argument("--required-min-samples", type=int, default=30)
    ap.add_argument(
        "--required-flow",
        action="append",
        default=[],
        help="Required flow metric name (repeatable). Defaults to project core flows.",
    )
    args = ap.parse_args()

    in_path = Path(args.inp)
    events = load_events(in_path, window_hours=(None if float(args.window_hours) <= 0 else float(args.window_hours)))
    summary = build_summary(events, min_samples=max(1, int(args.min_samples)))

    required_flows = [str(x).strip() for x in (args.required_flow or []) if str(x).strip()] or list(REQUIRED_FLOWS)
    required_coverage = build_required_flow_coverage(
        summary,
        required_flows=required_flows,
        required_min_samples=max(1, int(args.required_min_samples)),
    )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": in_path.as_posix(),
        "total_events": len(events),
        "min_samples": int(args.min_samples),
        "window_hours": float(args.window_hours),
        "required_min_samples": int(args.required_min_samples),
        "required_flows": required_flows,
        "required_coverage": required_coverage,
        "summary": summary,
    }
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(
        build_markdown(summary, in_path, len(events), int(args.min_samples), required_coverage),
        encoding="utf-8",
    )
    print(f"[OK] Wrote {out_json}")
    print(f"[OK] Wrote {out_md}")
    if summary:
        top = summary[0]
        print(f"[INFO] Slowest p95: {top['metric']} ({top['p95_ms']:.2f} ms)")
    else:
        print("[INFO] No timing events found yet.")
    print(
        "[INFO] Required flow coverage: "
        f"{required_coverage['covered_flow_count']}/{required_coverage['required_flow_count']} "
        f"(all_covered={required_coverage['all_required_flows_covered']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
