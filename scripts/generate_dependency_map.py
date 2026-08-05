#!/usr/bin/env python3
"""
Generate dependency map report for app orchestration modules.
"""
from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT / "core"
REPORT_DIR = ROOT / "artifacts" / "architecture"
JSON_REPORT_PATH = REPORT_DIR / "dependency_map.json"
MD_REPORT_PATH = REPORT_DIR / "dependency_map.md"


def _parse_imports(py_file: Path) -> list[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(str(node.module))
    return sorted(modules)


def build_dependency_map() -> dict[str, object]:
    targets = [ROOT / "app.py"] + sorted(CORE_DIR.glob("app_*.py"))
    modules: dict[str, dict[str, Any]] = {}
    for target in targets:
        rel = str(target.relative_to(ROOT)).replace("\\", "/")
        imports = _parse_imports(target)
        modules[rel] = {
            "import_count": len(imports),
            "imports": imports,
        }
    total_import_edges = sum(int(info.get("import_count", 0)) for info in modules.values())
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "module_count": len(modules),
        "total_import_edges": total_import_edges,
        "modules": modules,
    }


def _to_markdown(report: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Dependency Map Report")
    lines.append("")
    lines.append(f"- Generated at (UTC): `{report['generated_at_utc']}`")
    lines.append(f"- Modules: `{report['module_count']}`")
    lines.append(f"- Total import edges: `{report['total_import_edges']}`")
    lines.append("")
    lines.append("## Modules")
    lines.append("")
    modules = report["modules"]
    assert isinstance(modules, dict)
    for module_name in sorted(modules.keys()):
        info = modules[module_name]
        assert isinstance(info, dict)
        import_count = int(info["import_count"])
        lines.append(f"### `{module_name}`")
        lines.append(f"- Import count: `{import_count}`")
        imports = info["imports"]
        assert isinstance(imports, list)
        preview = imports[:20]
        for item in preview:
            lines.append(f"- `{item}`")
        if import_count > len(preview):
            lines.append(f"- ... ({import_count - len(preview)} more)")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = build_dependency_map()
    JSON_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    MD_REPORT_PATH.write_text(_to_markdown(report), encoding="utf-8")
    print(f"[OK] Wrote {JSON_REPORT_PATH.relative_to(ROOT)}")
    print(f"[OK] Wrote {MD_REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

