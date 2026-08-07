from __future__ import annotations

import pytest

from core.config import AppSettings, get_settings


def test_default_bond_yield(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_DEFAULT_BOND_YIELD_PCT", raising=False)
    monkeypatch.delenv("BOND_YIELD_PCT", raising=False)
    get_settings.cache_clear()
    s = get_settings()
    assert isinstance(s, AppSettings)
    assert s.default_bond_yield_pct == 6.5
    assert s.vn_10y_bond_yield_pct == 6.5
    assert s.merge_live_fundamentals is True
    assert s.skip_mock_snapshot is False


def test_bond_yield_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("BOND_YIELD_PCT", raising=False)
    monkeypatch.setenv("II_DEFAULT_BOND_YIELD_PCT", "5.5")
    get_settings.cache_clear()
    assert get_settings().default_bond_yield_pct == 5.5


def test_bond_yield_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_VN_10Y_BOND_YIELD", raising=False)
    monkeypatch.delenv("II_DEFAULT_BOND_YIELD_PCT", raising=False)
    monkeypatch.setenv("BOND_YIELD_PCT", "99")
    get_settings.cache_clear()
    assert get_settings().default_bond_yield_pct == 25.0


def test_vn_10y_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VN_10Y_BOND_YIELD", "6.8")
    monkeypatch.setenv("II_DEFAULT_BOND_YIELD_PCT", "5.0")
    get_settings.cache_clear()
    assert get_settings().default_bond_yield_pct == 6.8
