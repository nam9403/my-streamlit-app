#!/usr/bin/env python3
"""
Remove runtime-generated artifacts that should never be tracked.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "data" / "reports"
KEEP_FILENAMES = {".gitkeep"}


def sanitize_runtime_reports(reports_dir: Path = REPORTS_DIR) -> dict[str, int]:
    removed = 0
    kept = 0
    if not reports_dir.exists():
        return {"removed": removed, "kept": kept}
    for file_path in reports_dir.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name in KEEP_FILENAMES:
            kept += 1
            continue
        file_path.unlink(missing_ok=True)
        removed += 1
    return {"removed": removed, "kept": kept}


def main() -> int:
    stats = sanitize_runtime_reports()
    print(f"[OK] Runtime artifacts sanitized: removed={stats['removed']} kept={stats['kept']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

