#!/usr/bin/env python3
"""
Generate a concise GO/NO-GO readiness summary from architecture artifacts.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
ART_DIR = ROOT / "artifacts" / "architecture"
SCORECARD_PATH = ART_DIR / "engineering_scorecard.json"
DEP_MAP_PATH = ART_DIR / "dependency_map.json"
SUMMARY_JSON_PATH = ART_DIR / "release_readiness_summary.json"
SUMMARY_MD_PATH = ART_DIR / "release_readiness_summary.md"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_summary() -> dict[str, object]:
    from core.product_layer import get_admin_kpi  # noqa: E402

    scorecard = _load_json(SCORECARD_PATH)
    dep_map = _load_json(DEP_MAP_PATH)

    status_raw = scorecard.get("status")
    status: dict[str, Any] = status_raw if isinstance(status_raw, dict) else {}
    app_ok = bool(status.get("app_size_under_900", False))
    tests_ok = bool(status.get("has_100_plus_tests", False))
    dep_ok = bool(status.get("has_dependency_map", False))
    total_edges = _as_int(dep_map.get("total_import_edges"))
    modules = _as_int(dep_map.get("module_count"))
    admin = get_admin_kpi(days=30)
    obs = admin.get("notification_observability") or {}
    health = obs.get("runtime_health") or {}
    high_retry_ratio = float(health.get("high_retry_ratio") or 0.0)
    oldest_pending_age_minutes = float(health.get("oldest_pending_age_minutes") or 0.0)

    checks = {
        "app_size_under_900": app_ok,
        "has_100_plus_tests": tests_ok,
        "has_dependency_map": dep_ok,
        "dependency_edges_available": total_edges > 0,
        "dependency_modules_available": modules > 0,
        "queue_high_retry_ratio_under_0_6": high_retry_ratio <= 0.6,
        "queue_oldest_pending_under_360m": oldest_pending_age_minutes <= 360.0,
    }
    failed = [name for name, ok in checks.items() if not ok]
    go = len(failed) == 0
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "decision": "GO" if go else "NO-GO",
        "failed_checks": failed,
        "metrics": {
            "app_line_count": _as_int(scorecard.get("app_line_count")),
            "test_case_count": _as_int(scorecard.get("test_case_count")),
            "dependency_module_count": modules,
            "dependency_total_import_edges": total_edges,
            "queue_high_retry_ratio": round(high_retry_ratio, 4),
            "queue_oldest_pending_age_minutes": round(oldest_pending_age_minutes, 2),
        },
        "checks": checks,
    }


def _to_markdown(summary: dict[str, object]) -> str:
    metrics_raw = summary.get("metrics")
    metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
    checks_raw = summary.get("checks")
    checks: dict[str, Any] = checks_raw if isinstance(checks_raw, dict) else {}
    failed_raw = summary.get("failed_checks")
    failed: list[Any] = failed_raw if isinstance(failed_raw, list) else []
    lines: list[str] = []
    lines.append("# Release Readiness Summary")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{summary.get('generated_at_utc')}`")
    lines.append(f"- Decision: `{summary.get('decision')}`")
    lines.append("")
    lines.append("## Key Metrics")
    lines.append("")
    lines.append(f"- app_line_count: `{metrics.get('app_line_count')}`")
    lines.append(f"- test_case_count: `{metrics.get('test_case_count')}`")
    lines.append(f"- dependency_module_count: `{metrics.get('dependency_module_count')}`")
    lines.append(f"- dependency_total_import_edges: `{metrics.get('dependency_total_import_edges')}`")
    lines.append("")
    lines.append("## Checks")
    lines.append("")
    for key in sorted(checks.keys()):
        lines.append(f"- {key}: `{checks[key]}`")
    lines.append("")
    if failed:
        lines.append("## Failed Checks")
        lines.append("")
        for item in failed:
            lines.append(f"- `{item}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Return exit code 1 when decision is NO-GO.")
    args = parser.parse_args()

    ART_DIR.mkdir(parents=True, exist_ok=True)
    summary = build_summary()
    SUMMARY_JSON_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    SUMMARY_MD_PATH.write_text(_to_markdown(summary), encoding="utf-8")
    print(f"[OK] Wrote {SUMMARY_JSON_PATH.relative_to(ROOT)}")
    print(f"[OK] Wrote {SUMMARY_MD_PATH.relative_to(ROOT)}")
    print(f"[INFO] Decision: {summary.get('decision')}")
    if args.strict and summary.get("decision") != "GO":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

