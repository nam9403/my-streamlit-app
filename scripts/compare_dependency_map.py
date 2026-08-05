#!/usr/bin/env python3
"""
Compare dependency map against baseline and warn on architecture drift.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CURRENT_PATH = ROOT / "artifacts" / "architecture" / "dependency_map.json"
BASELINE_PATH = ROOT / "artifacts" / "architecture" / "dependency_map_baseline.json"
THRESHOLDS_PATH = ROOT / "artifacts" / "architecture" / "dependency_thresholds.json"


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _load_thresholds() -> dict:
    if not THRESHOLDS_PATH.exists():
        return {
            "max_total_edge_delta": 15,
            "max_module_edge_delta_default": 8,
            "module_overrides": {},
        }
    raw = _load_json(THRESHOLDS_PATH)
    if not isinstance(raw, dict):
        return {
            "max_total_edge_delta": 15,
            "max_module_edge_delta_default": 8,
            "module_overrides": {},
        }
    return raw


def compare_reports(
    current: dict,
    baseline: dict,
    *,
    max_total_edge_delta: int,
    max_module_edge_delta: int,
    module_overrides: dict[str, int] | None = None,
    module_tiers: dict[str, str] | None = None,
    risk_tier_thresholds: dict[str, int] | None = None,
) -> list[str]:
    warnings: list[str] = []
    overrides = module_overrides or {}
    tiers = module_tiers or {}
    tier_thresholds = risk_tier_thresholds or {}
    current_total = int(current.get("total_import_edges") or 0)
    baseline_total = int(baseline.get("total_import_edges") or 0)
    total_delta = current_total - baseline_total
    if total_delta > max_total_edge_delta:
        warnings.append(
            f"total import edges increased by {total_delta} (baseline={baseline_total}, current={current_total}, limit={max_total_edge_delta})"
        )

    current_modules = current.get("modules") or {}
    baseline_modules = baseline.get("modules") or {}
    if isinstance(current_modules, dict) and isinstance(baseline_modules, dict):
        for module_name, info in sorted(current_modules.items()):
            if not isinstance(info, dict):
                continue
            curr_edges = int(info.get("import_count") or 0)
            base_info = baseline_modules.get(module_name) or {}
            if not isinstance(base_info, dict):
                base_info = {}
            base_edges = int(base_info.get("import_count") or 0)
            delta = curr_edges - base_edges
            tier_name = str(tiers.get(module_name, "normal"))
            tier_limit = int(tier_thresholds.get(tier_name, max_module_edge_delta))
            module_limit = int(overrides.get(module_name, tier_limit))
            if delta > module_limit:
                warnings.append(
                    f"{module_name} import_count increased by {delta} (baseline={base_edges}, current={curr_edges}, limit={module_limit})"
                )
    return warnings


def _parse_utc_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def check_baseline_freshness(*, current: dict, baseline: dict, max_age_days: int) -> str | None:
    cur_raw = str(current.get("generated_at_utc") or "")
    base_raw = str(baseline.get("generated_at_utc") or "")
    cur_ts = _parse_utc_iso(cur_raw)
    base_ts = _parse_utc_iso(base_raw)
    if cur_ts is None or base_ts is None:
        return "baseline freshness check skipped: missing/invalid generated_at_utc"
    age_days = (cur_ts - base_ts).total_seconds() / 86400.0
    if age_days > float(max_age_days):
        return f"baseline is stale: {age_days:.1f} days old (limit={max_age_days})"
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when drift warnings are found.")
    parser.add_argument("--max-total-edge-delta", type=int, default=15)
    parser.add_argument("--max-module-edge-delta", type=int, default=8)
    parser.add_argument("--write-baseline", action="store_true", help="Update baseline from current report.")
    args = parser.parse_args()

    if not CURRENT_PATH.exists():
        print(f"[WARN] Current report not found: {CURRENT_PATH.relative_to(ROOT)}")
        print("[INFO] Run scripts/generate_dependency_map.py first.")
        return 0

    current = _load_json(CURRENT_PATH)
    thresholds = _load_thresholds()

    if args.write_baseline:
        BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        BASELINE_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] Baseline updated: {BASELINE_PATH.relative_to(ROOT)}")
        return 0

    if not BASELINE_PATH.exists():
        print(f"[WARN] Baseline not found: {BASELINE_PATH.relative_to(ROOT)}")
        print("[INFO] Create it with: python scripts/compare_dependency_map.py --write-baseline")
        return 0

    baseline = _load_json(BASELINE_PATH)
    threshold_total = int(thresholds.get("max_total_edge_delta", args.max_total_edge_delta))
    threshold_module_default = int(thresholds.get("max_module_edge_delta_default", args.max_module_edge_delta))
    module_overrides_raw = thresholds.get("module_overrides") or {}
    module_tiers_raw = thresholds.get("module_tiers") or {}
    risk_tier_thresholds_raw = thresholds.get("risk_tier_thresholds") or {}
    module_overrides: dict[str, int] = {}
    if isinstance(module_overrides_raw, dict):
        for key, value in module_overrides_raw.items():
            try:
                module_overrides[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    module_tiers: dict[str, str] = {}
    if isinstance(module_tiers_raw, dict):
        for key, value in module_tiers_raw.items():
            module_tiers[str(key)] = str(value)
    risk_tier_thresholds: dict[str, int] = {}
    if isinstance(risk_tier_thresholds_raw, dict):
        for key, value in risk_tier_thresholds_raw.items():
            try:
                risk_tier_thresholds[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
    warnings = compare_reports(
        current,
        baseline,
        max_total_edge_delta=threshold_total,
        max_module_edge_delta=threshold_module_default,
        module_overrides=module_overrides,
        module_tiers=module_tiers,
        risk_tier_thresholds=risk_tier_thresholds,
    )
    baseline_age_limit = int(thresholds.get("max_baseline_age_days", 30))
    freshness_warning = check_baseline_freshness(
        current=current,
        baseline=baseline,
        max_age_days=baseline_age_limit,
    )
    if freshness_warning:
        warnings.append(freshness_warning)
    if not warnings:
        print("[OK] Dependency drift check passed.")
        return 0

    print("[WARN] Dependency drift detected:")
    for item in warnings:
        print(f"- {item}")
    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())

