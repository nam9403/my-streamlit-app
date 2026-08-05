#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _extract_metrics(summary: dict[str, Any]) -> dict[str, float] | None:
    results = summary.get("results")
    if not isinstance(results, dict):
        return None
    hot = results.get("hot_paths")
    timeline = results.get("timeline")
    if not isinstance(hot, dict) or not isinstance(timeline, dict):
        return None

    hot_out = str(hot.get("stdout_tail") or "")
    timeline_out = str(timeline.get("stdout_tail") or "")

    # Parse small set of robust scalar metrics from benchmark output tails.
    def _num_after(key: str, text: str) -> float | None:
        marker = f'"{key}":'
        i = text.find(marker)
        if i < 0:
            return None
        tail = text[i + len(marker) : i + len(marker) + 32]
        token = "".join(ch for ch in tail if ch in "0123456789.-")
        try:
            return float(token)
        except ValueError:
            return None

    list_cold = _num_after("list_tradable_cold_ms", hot_out)
    list_warm = _num_after("list_tradable_warm_ms", hot_out)
    perf_elapsed = _num_after("elapsed_sec", hot_out)

    # From profile timeline, use the first stage line for strategic report as a key signal.
    strategic_sec = None
    for line in timeline_out.splitlines():
        if "generate_strategic_report(no_llm):" in line:
            # e.g. "...: 0.065s ..."
            try:
                part = line.split("generate_strategic_report(no_llm):", 1)[1]
                sec = float(part.split("s", 1)[0].strip())
                strategic_sec = sec
                break
            except (IndexError, ValueError):
                continue

    if None in (list_cold, list_warm, perf_elapsed, strategic_sec):
        return None
    return {
        "list_tradable_cold_ms": float(list_cold),
        "list_tradable_warm_ms": float(list_warm),
        "perf_benchmark_elapsed_sec": float(perf_elapsed),
        "strategic_report_no_llm_sec": float(strategic_sec),
    }


def _compare(current: dict[str, float], baseline: dict[str, float], max_regress_pct: float) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    for key, cur in current.items():
        base = baseline.get(key)
        if base is None:
            continue
        allow = float(base) * (1.0 + max_regress_pct / 100.0)
        if cur > allow:
            violations.append(
                {
                    "metric": key,
                    "baseline": round(float(base), 6),
                    "current": round(float(cur), 6),
                    "allowed_max": round(float(allow), 6),
                    "regress_pct": round(((float(cur) / max(float(base), 1e-9)) - 1.0) * 100.0, 2),
                }
            )
    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description="Strict pre-release performance gate for 6S runtime.")
    ap.add_argument(
        "--summary-json",
        default=str(ROOT / "artifacts" / "performance" / "runtime_6s_benchmark_summary.json"),
        help="Path to runtime_6s_benchmark_summary.json",
    )
    ap.add_argument(
        "--baseline-json",
        default=str(ROOT / "config" / "runtime_6s_perf_baseline.json"),
        help="Path to baseline metrics JSON",
    )
    ap.add_argument(
        "--out-json",
        default=str(ROOT / "artifacts" / "performance" / "pre_release_perf_gate.json"),
        help="Path for gate result output JSON",
    )
    ap.add_argument("--max-regress-pct", type=float, default=20.0, help="Max allowed regression percent per metric.")
    ap.add_argument(
        "--bootstrap-baseline",
        action="store_true",
        help="Write current metrics to baseline file if baseline is missing.",
    )
    args = ap.parse_args()

    summary_path = Path(args.summary_json)
    baseline_path = Path(args.baseline_json)
    out_path = Path(args.out_json)

    summary = _read_json(summary_path)
    current = _extract_metrics(summary)
    if current is None:
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision": "FAIL",
            "reason": "Cannot parse runtime benchmark metrics.",
            "summary_json": str(summary_path),
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    baseline = _read_json(baseline_path)
    if not baseline:
        if bool(args.bootstrap_baseline):
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_payload = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "metrics": current,
            }
            baseline_path.write_text(json.dumps(baseline_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            baseline = baseline_payload
        else:
            payload = {
                "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                "decision": "FAIL",
                "reason": "Baseline file is missing. Re-run with --bootstrap-baseline once.",
                "baseline_json": str(baseline_path),
            }
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2

    base_metrics = baseline.get("metrics")
    if not isinstance(base_metrics, dict):
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "decision": "FAIL",
            "reason": "Invalid baseline metrics format.",
            "baseline_json": str(baseline_path),
        }
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 2

    violations = _compare(current, {k: float(v) for k, v in base_metrics.items()}, float(args.max_regress_pct))
    decision = "PASS" if not violations else "FAIL"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "max_regress_pct": float(args.max_regress_pct),
        "summary_json": str(summary_path),
        "baseline_json": str(baseline_path),
        "current_metrics": current,
        "baseline_metrics": base_metrics,
        "violations": violations,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if decision == "PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
