#!/usr/bin/env python3
"""
Append latest engineering scorecard into history and generate trend report.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = ROOT / "artifacts" / "architecture"
SCORECARD_PATH = ARTIFACT_DIR / "engineering_scorecard.json"
HISTORY_PATH = ARTIFACT_DIR / "engineering_scorecard_history.jsonl"
TREND_MD_PATH = ARTIFACT_DIR / "engineering_scorecard_trend.md"
MAX_HISTORY_ITEMS = 50


def _load_latest_scorecard() -> dict[str, Any]:
    raw = json.loads(SCORECARD_PATH.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def _load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _append_history(entry: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _load_history()
    rows.append(entry)
    if len(rows) > MAX_HISTORY_ITEMS:
        rows = rows[-MAX_HISTORY_ITEMS:]
    HISTORY_PATH.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    return rows


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_trend_markdown(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "# Engineering Scorecard Trend\n\nNo history data.\n"
    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None

    def _metric(name: str) -> str:
        latest_value = latest.get(name)
        if prev is None:
            return f"- {name}: `{latest_value}`"
        prev_value = prev.get(name)
        delta = None
        latest_num = _as_float(latest_value)
        prev_num = _as_float(prev_value)
        if latest_num is not None and prev_num is not None:
            delta = latest_num - prev_num
        if delta is None:
            return f"- {name}: `{latest_value}` (prev `{prev_value}`)"
        sign = "+" if delta > 0 else ""
        return f"- {name}: `{latest_value}` (delta `{sign}{delta:.0f}` vs prev `{prev_value}`)"

    lines: list[str] = []
    lines.append("# Engineering Scorecard Trend")
    lines.append("")
    lines.append(f"- Updated at (UTC): `{datetime.now(UTC).isoformat()}`")
    lines.append(f"- Samples kept: `{len(rows)}`")
    lines.append("")
    lines.append("## Latest vs Previous")
    lines.append("")
    lines.append(_metric("app_line_count"))
    lines.append(_metric("test_file_count"))
    lines.append(_metric("test_case_count"))
    lines.append(_metric("dependency_module_count"))
    lines.append(_metric("dependency_total_import_edges"))
    lines.append("")
    lines.append("## Recent Samples")
    lines.append("")
    for row in rows[-10:]:
        ts = row.get("generated_at_utc")
        app_lines = row.get("app_line_count")
        tests = row.get("test_case_count")
        edges = row.get("dependency_total_import_edges")
        lines.append(f"- `{ts}` | app_lines=`{app_lines}` | tests=`{tests}` | import_edges=`{edges}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not SCORECARD_PATH.exists():
        print(f"[WARN] Missing scorecard: {SCORECARD_PATH.relative_to(ROOT)}")
        print("[INFO] Run scripts/generate_engineering_scorecard.py first.")
        return 0
    latest = _load_latest_scorecard()
    rows = _append_history(latest)
    TREND_MD_PATH.write_text(_to_trend_markdown(rows), encoding="utf-8")
    print(f"[OK] Updated {HISTORY_PATH.relative_to(ROOT)}")
    print(f"[OK] Wrote {TREND_MD_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

