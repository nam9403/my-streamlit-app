from __future__ import annotations

from core.app_onboarding_helpers import (
    is_watch_seed_ready,
    onboarding_done_score,
    onboarding_progress_text,
)


def test_is_watch_seed_ready_with_minimum_symbols() -> None:
    assert is_watch_seed_ready("FPT,HPG,VNM")
    assert not is_watch_seed_ready("FPT,HPG")


def test_onboarding_done_score_counts_true_flags() -> None:
    score = onboarding_done_score(auth_ready=True, channel_ready=False, watch_seed_ready=True)
    assert score == 2


def test_onboarding_progress_text_clamps_values() -> None:
    assert onboarding_progress_text(5, total_steps=3) == "Onboarding progress: 3/3"
    assert onboarding_progress_text(-1, total_steps=3) == "Onboarding progress: 0/3"

