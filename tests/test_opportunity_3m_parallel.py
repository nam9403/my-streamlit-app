from __future__ import annotations

import pytest

from core.opportunity_3m_service import _finder_max_workers, _finder_parallel_enabled


def test_finder_max_workers_respects_cap_and_symbol_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_FINDER_MAX_WORKERS", "99")
    assert _finder_max_workers(60) == 12
    monkeypatch.setenv("II_FINDER_MAX_WORKERS", "3")
    assert _finder_max_workers(60) == 3
    assert _finder_max_workers(2) == 2


def test_finder_parallel_default_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("II_FINDER_PARALLEL", raising=False)
    assert _finder_parallel_enabled() is True
    monkeypatch.setenv("II_FINDER_PARALLEL", "0")
    assert _finder_parallel_enabled() is False
