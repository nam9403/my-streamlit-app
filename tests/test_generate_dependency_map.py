from __future__ import annotations

from scripts.generate_dependency_map import build_dependency_map


def test_build_dependency_map_has_expected_shape() -> None:
    report = build_dependency_map()
    assert "generated_at_utc" in report
    assert int(report["module_count"]) >= 1
    assert int(report["total_import_edges"]) >= 0
    modules = report["modules"]
    assert isinstance(modules, dict)
    assert "app.py" in modules
    app_info = modules["app.py"]
    assert isinstance(app_info, dict)
    assert "import_count" in app_info
    assert "imports" in app_info
    assert isinstance(app_info["imports"], list)

