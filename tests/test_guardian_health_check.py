from __future__ import annotations

from scripts.guardian_health_check import evaluate_guardian_health


def test_guardian_health_ok_case() -> None:
    status, reasons = evaluate_guardian_health(
        {"checked": 20, "failures": 0, "suppressed_cooldown": 4},
        max_failures=3,
        min_checked=5,
        max_suppressed_ratio=0.85,
    )
    assert status == "ok"
    assert reasons == []


def test_guardian_health_warn_and_critical() -> None:
    status, reasons = evaluate_guardian_health(
        {"checked": 3, "failures": 6, "suppressed_cooldown": 3},
        max_failures=3,
        min_checked=5,
        max_suppressed_ratio=0.6,
    )
    assert status == "critical"
    assert len(reasons) >= 1
