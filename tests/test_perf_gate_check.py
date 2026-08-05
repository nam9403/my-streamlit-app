from __future__ import annotations

from scripts.perf_gate_check import evaluate_gate


def _thresholds() -> dict:
    return {
        "profiles": {
            "dev": {
                "required_min_samples": 30,
                "max_violations_for_hold": 2,
                "flows": {
                    "flow.a": {"p95_ms": 20.0, "p99_ms": 40.0},
                    "flow.b": {"p95_ms": 10.0, "p99_ms": 20.0},
                },
            }
        }
    }


def test_perf_gate_pass_when_all_metrics_meet_thresholds() -> None:
    dashboard = {
        "summary": [
            {"metric": "flow.a", "samples": 35, "p95_ms": 10.0, "p99_ms": 20.0},
            {"metric": "flow.b", "samples": 35, "p95_ms": 5.0, "p99_ms": 8.0},
        ]
    }
    result = evaluate_gate(dashboard, _thresholds(), "dev")
    assert result["decision"] == "PASS"
    assert result["violations"] == []


def test_perf_gate_hold_for_minor_violations() -> None:
    dashboard = {
        "summary": [
            {"metric": "flow.a", "samples": 29, "p95_ms": 10.0, "p99_ms": 20.0},
            {"metric": "flow.b", "samples": 35, "p95_ms": 5.0, "p99_ms": 8.0},
        ]
    }
    result = evaluate_gate(dashboard, _thresholds(), "dev")
    assert result["decision"] == "HOLD"
    assert len(result["violations"]) == 1


def test_perf_gate_fail_for_multiple_breaches() -> None:
    dashboard = {
        "summary": [
            {"metric": "flow.a", "samples": 35, "p95_ms": 30.0, "p99_ms": 50.0},
            {"metric": "flow.b", "samples": 35, "p95_ms": 15.0, "p99_ms": 25.0},
        ]
    }
    result = evaluate_gate(dashboard, _thresholds(), "dev")
    assert result["decision"] == "FAIL"
    assert len(result["violations"]) >= 3

