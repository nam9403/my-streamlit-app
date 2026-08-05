from __future__ import annotations

from scripts.live_data_stability_benchmark import summarize_stability


def test_summarize_stability_go_when_thresholds_met() -> None:
    rows = [
        {"live_ratio": 0.4, "available_ratio": 1.0},
        {"live_ratio": 0.35, "available_ratio": 1.0},
        {"live_ratio": 0.3, "available_ratio": 1.0},
    ]
    out = summarize_stability(rows, min_sessions=3, min_live_ratio=0.25, min_available_ratio=1.0)
    assert out["decision"] == "GO"
    assert out["sessions"] == 3


def test_summarize_stability_hold_when_any_session_violates() -> None:
    rows = [
        {"live_ratio": 0.4, "available_ratio": 1.0},
        {"live_ratio": 0.2, "available_ratio": 1.0},
        {"live_ratio": 0.5, "available_ratio": 0.5},
    ]
    out = summarize_stability(rows, min_sessions=3, min_live_ratio=0.25, min_available_ratio=1.0)
    assert out["decision"] == "HOLD"
    assert len(out["reasons"]) >= 1
