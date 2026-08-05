#!/usr/bin/env python3
"""
Architecture boundary checks to keep refactor progress stable.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_FILE = ROOT / "app.py"
MAX_APP_LINES = 300


def _parse_import_modules(py_file: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(str(alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(str(node.module))
    return modules


def check_app_file_size(app_file: Path = APP_FILE, max_lines: int = MAX_APP_LINES) -> list[str]:
    if not app_file.exists():
        return [f"app file not found: {app_file}"]
    line_count = len(app_file.read_text(encoding="utf-8").splitlines())
    if line_count > max_lines:
        return [f"app.py too large: {line_count} lines (limit {max_lines})"]
    return []


def check_app_panels_import_boundary(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    panel_files = sorted((root / "core").glob("app_*.py"))
    for py_file in panel_files:
        modules = _parse_import_modules(py_file)
        if "core.product_layer" in modules:
            errors.append(f"{py_file.relative_to(root)} must not import core.product_layer directly")
        if "app" in modules:
            errors.append(f"{py_file.relative_to(root)} must not import app.py")
    return errors


def main() -> int:
    errors: list[str] = []
    errors.extend(check_app_file_size())
    errors.extend(check_app_panels_import_boundary())
    if errors:
        print("[FAIL] Architecture boundary check failed:")
        for item in errors:
            print(f"- {item}")
        return 1
    print("[OK] Architecture boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

