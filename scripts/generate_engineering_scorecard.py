#!/usr/bin/env python3
"""
Generate engineering scorecard for architecture/quality tracking.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = ROOT / "artifacts" / "architecture"
DEPENDENCY_MAP_PATH = ARTIFACT_DIR / "dependency_map.json"
SCORECARD_JSON_PATH = ARTIFACT_DIR / "engineering_scorecard.json"
SCORECARD_MD_PATH = ARTIFACT_DIR / "engineering_scorecard.md"
APP_FILE = ROOT / "app.py"
TESTS_DIR = ROOT / "tests"


def _count_test_cases(tests_dir: Path = TESTS_DIR) -> int:
    total = 0
    for file_path in tests_dir.glob("test_*.py"):
        text = file_path.read_text(encoding="utf-8")
        total += len(re.findall(r"^def test_", text, flags=re.MULTILINE))
    return total


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_scorecard() -> dict[str, object]:
    dependency_map: dict[str, Any] = {}
    if DEPENDENCY_MAP_PATH.exists():
        dependency_map = json.loads(DEPENDENCY_MAP_PATH.read_text(encoding="utf-8"))
    app_line_count = len(APP_FILE.read_text(encoding="utf-8").splitlines()) if APP_FILE.exists() else 0
    test_file_count = len(list(TESTS_DIR.glob("test_*.py"))) if TESTS_DIR.exists() else 0
    test_case_count = _count_test_cases(TESTS_DIR) if TESTS_DIR.exists() else 0
    module_count = _as_int(dependency_map.get("module_count"))
    total_import_edges = _as_int(dependency_map.get("total_import_edges"))
    scorecard = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "app_line_count": app_line_count,
        "test_file_count": test_file_count,
        "test_case_count": test_case_count,
        "dependency_module_count": module_count,
        "dependency_total_import_edges": total_import_edges,
        "status": {
            "app_size_under_900": app_line_count <= 900,
            "has_100_plus_tests": test_case_count >= 100,
            "has_dependency_map": bool(dependency_map),
        },
    }
    return scorecard


def _to_markdown(scorecard: dict[str, object]) -> str:
    status = scorecard.get("status") or {}
    assert isinstance(status, dict)
    lines: list[str] = []
    lines.append("# Engineering Scorecard")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{scorecard.get('generated_at_utc')}`")
    lines.append(f"- app.py lines: `{scorecard.get('app_line_count')}`")
    lines.append(f"- Test files: `{scorecard.get('test_file_count')}`")
    lines.append(f"- Test cases: `{scorecard.get('test_case_count')}`")
    lines.append(f"- Dependency modules: `{scorecard.get('dependency_module_count')}`")
    lines.append(f"- Dependency import edges: `{scorecard.get('dependency_total_import_edges')}`")
    lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.append(f"- app size under 900: `{status.get('app_size_under_900')}`")
    lines.append(f"- has 100+ tests: `{status.get('has_100_plus_tests')}`")
    lines.append(f"- has dependency map: `{status.get('has_dependency_map')}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    scorecard = build_scorecard()
    SCORECARD_JSON_PATH.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    SCORECARD_MD_PATH.write_text(_to_markdown(scorecard), encoding="utf-8")
    print(f"[OK] Wrote {SCORECARD_JSON_PATH.relative_to(ROOT)}")
    print(f"[OK] Wrote {SCORECARD_MD_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

