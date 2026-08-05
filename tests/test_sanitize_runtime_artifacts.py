from __future__ import annotations

from pathlib import Path

from scripts.sanitize_runtime_artifacts import sanitize_runtime_reports


def test_sanitize_runtime_reports_removes_generated_files(tmp_path: Path) -> None:
    reports_dir = tmp_path / "data" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    keep_file = reports_dir / ".gitkeep"
    keep_file.write_text("", encoding="utf-8")
    generated = reports_dir / "run_001.md"
    generated.write_text("generated", encoding="utf-8")

    stats = sanitize_runtime_reports(reports_dir=reports_dir)
    assert stats["removed"] == 1
    assert stats["kept"] == 1
    assert keep_file.exists()
    assert not generated.exists()

