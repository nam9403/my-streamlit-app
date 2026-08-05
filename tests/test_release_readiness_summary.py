from __future__ import annotations

from scripts.release_readiness_summary import build_summary


def test_build_summary_has_decision_and_checks() -> None:
    summary = build_summary()
    assert "decision" in summary
    assert summary["decision"] in ("GO", "NO-GO")
    checks = summary.get("checks")
    assert isinstance(checks, dict)
    assert "app_size_under_900" in checks
    assert "has_100_plus_tests" in checks
    assert "has_dependency_map" in checks

