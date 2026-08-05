#!/usr/bin/env python3
"""
Performance gate check based on timing dashboard and thresholds.

Decision:
  - PASS: all required flows satisfy samples + p95/p99 thresholds
  - HOLD: minor violations, investigate before strict release
  - FAIL: major violations, block release
"""
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
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}


def evaluate_gate(dashboard: dict[str, Any], thresholds: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = thresholds.get("profiles") if isinstance(thresholds, dict) else None
    profile_cfg = (profiles or {}).get(profile) if isinstance(profiles, dict) else None
    if not isinstance(profile_cfg, dict):
        return {
            "decision": "FAIL",
            "reasons": [f"Missing threshold profile: {profile}"],
            "violations": [],
            "profile": profile,
        }

    required_min_samples = int(profile_cfg.get("required_min_samples") or 30)
    hold_limit = int(profile_cfg.get("max_violations_for_hold") or 1)
    flow_cfg_raw = profile_cfg.get("flows")
    flow_cfg: dict[str, Any] = flow_cfg_raw if isinstance(flow_cfg_raw, dict) else {}
    by_metric = {str(x.get("metric") or ""): x for x in (dashboard.get("summary") or []) if isinstance(x, dict)}

    violations: list[dict[str, Any]] = []
    missing_metrics: list[str] = []
    for metric, cfg in flow_cfg.items():
        if not isinstance(cfg, dict):
            continue
        row = by_metric.get(metric)
        if row is None:
            missing_metrics.append(metric)
            violations.append({"metric": metric, "type": "missing_metric", "message": "Metric missing from dashboard"})
            continue
        samples = int(row.get("samples") or 0)
        p95 = float(row.get("p95_ms") or 0.0)
        p99 = float(row.get("p99_ms") or 0.0)
        p95_th = float(cfg.get("p95_ms") or 0.0)
        p99_th = float(cfg.get("p99_ms") or 0.0)

        if samples < required_min_samples:
            violations.append(
                {
                    "metric": metric,
                    "type": "insufficient_samples",
                    "samples": samples,
                    "required_min_samples": required_min_samples,
                }
            )
        if p95 > p95_th:
            violations.append({"metric": metric, "type": "p95_breach", "actual_ms": p95, "threshold_ms": p95_th})
        if p99 > p99_th:
            violations.append({"metric": metric, "type": "p99_breach", "actual_ms": p99, "threshold_ms": p99_th})

    decision = "PASS"
    reasons: list[str] = []
    if missing_metrics:
        decision = "FAIL"
        reasons.append("Missing required flow metrics in timing dashboard.")
    elif violations:
        if len(violations) <= max(1, hold_limit):
            decision = "HOLD"
            reasons.append("Minor performance threshold violations detected.")
        else:
            decision = "FAIL"
            reasons.append("Performance threshold violations exceed hold tolerance.")

    return {
        "decision": decision,
        "profile": profile,
        "required_min_samples": required_min_samples,
        "max_violations_for_hold": hold_limit,
        "violations": violations,
        "reasons": reasons,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="dev", help="Threshold profile in config/performance_thresholds.json")
    ap.add_argument(
        "--dashboard-json",
        default=str(ROOT / "artifacts" / "performance" / "timing_dashboard.json"),
        help="Timing dashboard JSON path",
    )
    ap.add_argument(
        "--thresholds-json",
        default=str(ROOT / "config" / "performance_thresholds.json"),
        help="Performance threshold config path",
    )
    ap.add_argument("--require-pass", action="store_true", help="Return non-zero unless decision is PASS.")
    args = ap.parse_args()

    dashboard = _read_json(Path(args.dashboard_json))
    thresholds = _read_json(Path(args.thresholds_json))
    result = evaluate_gate(dashboard, thresholds, str(args.profile))
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dashboard_json": str(Path(args.dashboard_json)),
        "thresholds_json": str(Path(args.thresholds_json)),
        **result,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    decision = str(result.get("decision") or "FAIL").upper()
    if decision == "FAIL":
        return 2
    if bool(args.require_pass) and decision != "PASS":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

