from __future__ import annotations

from scripts.compare_dependency_map import check_baseline_freshness, compare_reports


def test_compare_reports_no_warnings_when_within_limits() -> None:
    baseline = {
        "total_import_edges": 10,
        "modules": {"app.py": {"import_count": 8}},
    }
    current = {
        "total_import_edges": 15,
        "modules": {"app.py": {"import_count": 12}},
    }
    warnings = compare_reports(
        current,
        baseline,
        max_total_edge_delta=10,
        max_module_edge_delta=10,
    )
    assert warnings == []


def test_compare_reports_warns_on_total_and_module_spike() -> None:
    baseline = {
        "total_import_edges": 10,
        "modules": {"app.py": {"import_count": 8}},
    }
    current = {
        "total_import_edges": 40,
        "modules": {"app.py": {"import_count": 25}},
    }
    warnings = compare_reports(
        current,
        baseline,
        max_total_edge_delta=5,
        max_module_edge_delta=5,
    )
    assert len(warnings) >= 2
    assert any("total import edges increased" in w for w in warnings)
    assert any("app.py import_count increased" in w for w in warnings)


def test_compare_reports_respects_module_override_limit() -> None:
    baseline = {
        "total_import_edges": 100,
        "modules": {"app.py": {"import_count": 20}},
    }
    current = {
        "total_import_edges": 105,
        "modules": {"app.py": {"import_count": 24}},
    }
    warnings = compare_reports(
        current,
        baseline,
        max_total_edge_delta=10,
        max_module_edge_delta=10,
        module_overrides={"app.py": 2},
    )
    assert any("app.py import_count increased by 4" in w for w in warnings)


def test_compare_reports_uses_risk_tier_threshold_when_no_override() -> None:
    baseline = {
        "total_import_edges": 10,
        "modules": {"core/app_analysis_orchestration.py": {"import_count": 10}},
    }
    current = {
        "total_import_edges": 13,
        "modules": {"core/app_analysis_orchestration.py": {"import_count": 15}},
    }
    warnings = compare_reports(
        current,
        baseline,
        max_total_edge_delta=10,
        max_module_edge_delta=10,
        module_overrides={},
        module_tiers={"core/app_analysis_orchestration.py": "high"},
        risk_tier_thresholds={"high": 3, "normal": 10},
    )
    assert any("core/app_analysis_orchestration.py import_count increased by 5" in w for w in warnings)


def test_check_baseline_freshness_warns_when_stale() -> None:
    current = {"generated_at_utc": "2026-04-23T00:00:00+00:00"}
    baseline = {"generated_at_utc": "2026-01-01T00:00:00+00:00"}
    warning = check_baseline_freshness(current=current, baseline=baseline, max_age_days=30)
    assert warning is not None
    assert "baseline is stale" in warning


def test_check_baseline_freshness_passes_when_recent() -> None:
    current = {"generated_at_utc": "2026-04-23T00:00:00+00:00"}
    baseline = {"generated_at_utc": "2026-04-10T00:00:00+00:00"}
    warning = check_baseline_freshness(current=current, baseline=baseline, max_age_days=30)
    assert warning is None

