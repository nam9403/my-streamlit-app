from __future__ import annotations

from pathlib import Path

from scripts.check_architecture_boundaries import check_app_file_size, check_app_panels_import_boundary


def test_check_app_file_size_passes_for_small_file(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text("print('ok')\n", encoding="utf-8")
    errors = check_app_file_size(app_file=app_file, max_lines=10)
    assert errors == []


def test_check_app_file_size_fails_for_large_file(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text("\n".join(["x=1"] * 12), encoding="utf-8")
    errors = check_app_file_size(app_file=app_file, max_lines=10)
    assert errors
    assert "too large" in errors[0]


def test_check_app_panels_import_boundary_detects_forbidden_import(tmp_path: Path) -> None:
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    panel_file = core_dir / "app_test_panel.py"
    panel_file.write_text("from core.product_layer import x\n", encoding="utf-8")
    errors = check_app_panels_import_boundary(root=tmp_path)
    assert errors
    assert "must not import core.product_layer directly" in errors[0]

