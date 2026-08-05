from __future__ import annotations

from scripts.update_engineering_scorecard_history import _to_trend_markdown


def test_to_trend_markdown_contains_key_sections() -> None:
    rows = [
        {
            "generated_at_utc": "2026-04-22T00:00:00+00:00",
            "app_line_count": 1200,
            "test_file_count": 40,
            "test_case_count": 100,
            "dependency_module_count": 10,
            "dependency_total_import_edges": 200,
        },
        {
            "generated_at_utc": "2026-04-23T00:00:00+00:00",
            "app_line_count": 1100,
            "test_file_count": 42,
            "test_case_count": 120,
            "dependency_module_count": 12,
            "dependency_total_import_edges": 180,
        },
    ]
    md = _to_trend_markdown(rows)
    assert "Engineering Scorecard Trend" in md
    assert "Latest vs Previous" in md
    assert "Recent Samples" in md
    assert "app_line_count" in md

