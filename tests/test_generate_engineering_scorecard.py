from __future__ import annotations

from scripts.generate_engineering_scorecard import build_scorecard


def test_build_scorecard_contains_expected_keys() -> None:
    scorecard = build_scorecard()
    assert "generated_at_utc" in scorecard
    assert "app_line_count" in scorecard
    assert "test_file_count" in scorecard
    assert "test_case_count" in scorecard
    assert "dependency_module_count" in scorecard
    assert "dependency_total_import_edges" in scorecard
    status = scorecard.get("status")
    assert isinstance(status, dict)
    assert "app_size_under_900" in status
    assert "has_100_plus_tests" in status
    assert "has_dependency_map" in status

