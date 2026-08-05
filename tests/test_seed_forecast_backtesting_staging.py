from __future__ import annotations

import pytest

from scripts.seed_forecast_backtesting_staging import _build_resolved_rows, _ensure_non_prod, _resolve_env


def test_build_resolved_rows_shape_and_status() -> None:
    rows = _build_resolved_rows(
        user_id="u1",
        symbols=["FPT", "VNM"],
        samples=10,
        target_win_rate_pct=70.0,
        base_price=100.0,
    )
    assert len(rows) == 10
    assert all(len(r) == 12 for r in rows)
    assert all(r[-1] == "resolved" for r in rows)


def test_build_resolved_rows_positive_expected_return() -> None:
    rows = _build_resolved_rows(
        user_id="u1",
        symbols=["FPT"],
        samples=6,
        target_win_rate_pct=60.0,
        base_price=100.0,
    )
    expected_returns = [float(r[6]) for r in rows]
    assert min(expected_returns) > 0


def test_resolve_env_normalizes_values() -> None:
    assert _resolve_env("production") == "prod"
    assert _resolve_env("staging") == "preprod"
    assert _resolve_env("dev") == "dev"


def test_ensure_non_prod_blocks_without_override() -> None:
    with pytest.raises(RuntimeError):
        _ensure_non_prod("prod", allow_prod=False)
    _ensure_non_prod("prod", allow_prod=True)
