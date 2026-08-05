from __future__ import annotations

from scripts.smart_market_sync import build_sync_plan, select_round_robin


def test_select_round_robin_wraps_cursor() -> None:
    out, nxt = select_round_robin(["AAA", "BBB", "CCC"], cursor=2, take_n=2)
    assert out == ["CCC", "AAA"]
    assert nxt == 1


def test_build_sync_plan_prioritizes_new_and_rotates_existing() -> None:
    plan = build_sync_plan(
        universe_symbols=["AAA", "BBB", "CCC", "DDD", "EEE"],
        known_symbols=["AAA", "BBB", "CCC"],
        cursor=1,
        new_batch_size=5,
        existing_batch_size=2,
        force_full_existing=False,
    )
    assert plan.batch_new == ["DDD", "EEE"]
    assert plan.batch_existing == ["BBB", "CCC"]
    assert plan.next_cursor == 0


def test_build_sync_plan_force_full_existing() -> None:
    plan = build_sync_plan(
        universe_symbols=["AAA", "BBB", "CCC"],
        known_symbols=["AAA", "BBB", "CCC"],
        cursor=2,
        new_batch_size=1,
        existing_batch_size=2,
        force_full_existing=True,
    )
    assert plan.batch_new == []
    assert plan.batch_existing == ["AAA", "BBB"]
    assert plan.next_cursor == 2
