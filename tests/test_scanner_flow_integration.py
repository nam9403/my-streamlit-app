"""Tests cho ``core.scanner_flow_integration``.

Mục tiêu cover:
- Disabled-by-default (không có env) ⇒ trả nguyên trạng.
- Enabled + journal rỗng / lỗi I/O ⇒ trả nguyên trạng + reason rõ ràng.
- Enabled + journal có signal ⇒ DataFrame mới có ``Flow boost`` /
  ``Flow note``, confidence của symbol khớp được điều chỉnh.
- ``_latest_signal_per_symbol`` chọn đúng signal mới nhất khi có nhiều
  bản ghi cùng symbol.
- Env overrides cho ``II_SCANNER_FLOW_RERANK_WEIGHT`` &
  ``II_SCANNER_FLOW_RERANK_LOOKBACK_HOURS``.
"""

from __future__ import annotations

import pandas as pd
import pytest

from core.scanner_flow_integration import (
    _latest_signal_per_symbol,
    is_scanner_rerank_enabled,
    rerank_candidates_with_flow_journal,
)


def _candidates_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Mã": ["FPT", "HPG", "VNM"],
            "Confidence %": [60.0, 55.0, 50.0],
            "Hành động hôm nay": ["BUY", "HOLD", "WATCH"],
        }
    )


def _signal_row(
    symbol: str,
    *,
    big: bool = True,
    delta: str = "bullish",
    intensity: float = 8.0,
    z: float = 2.5,
    ts: str = "2026-05-11T10:00:00+00:00",
) -> dict:
    return {
        "symbol": symbol,
        "is_big_boy": big,
        "delta_status": delta,
        "intensity_score": intensity,
        "z_volume": z,
        "aggregated_volume": 5_000_000.0,
        "pseudo_delta": 0.4,
        "cumulative_delta": 1.0,
        "anomaly_score": -0.1,
        "last_close": 27_000.0,
        "last_volume": 5_000_000.0,
        "context_note": "",
        "journaled_at_utc": ts,
        "timeframe": "5m",
    }


def test_disabled_by_default_returns_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("II_SCANNER_FLOW_RERANK_ENABLED", raising=False)
    df = _candidates_df()
    out, meta = rerank_candidates_with_flow_journal(df)
    assert meta["enabled"] is False
    assert meta["reason"] == "disabled"
    assert "Flow boost" not in out.columns
    pd.testing.assert_frame_equal(out.reset_index(drop=True), df.reset_index(drop=True))


def test_explicit_enabled_with_empty_journal_returns_copy() -> None:
    df = _candidates_df()
    out, meta = rerank_candidates_with_flow_journal(
        df,
        enabled=True,
        journal_reader=lambda **_: [],
    )
    assert meta["enabled"] is True
    assert meta["reason"] == "journal_empty"
    assert meta["applied_count"] == 0
    assert "Flow boost" not in out.columns
    pd.testing.assert_frame_equal(out.reset_index(drop=True), df.reset_index(drop=True))


def test_journal_reader_exception_returns_copy() -> None:
    def _raises(**_kwargs: object) -> list[dict]:
        raise OSError("disk failure")

    df = _candidates_df()
    out, meta = rerank_candidates_with_flow_journal(
        df,
        enabled=True,
        journal_reader=_raises,
    )
    assert meta["enabled"] is True
    assert meta["reason"] == "journal_error"
    assert meta["applied_count"] == 0
    pd.testing.assert_frame_equal(out.reset_index(drop=True), df.reset_index(drop=True))


def test_apply_boost_when_signals_match_candidate() -> None:
    df = _candidates_df()
    base_fpt = float(df.loc[df["Mã"] == "FPT", "Confidence %"].iloc[0])
    rows = [_signal_row("FPT", intensity=8.0)]
    out, meta = rerank_candidates_with_flow_journal(
        df,
        enabled=True,
        journal_reader=lambda **_: rows,
        weight=0.25,
    )
    assert meta["enabled"] is True
    assert meta["reason"] == "applied"
    assert meta["applied_count"] == 1
    assert meta["journal_signal_count"] == 1
    assert "Flow boost" in out.columns
    assert "Flow note" in out.columns
    new_fpt = float(out.loc[out["Mã"] == "FPT", "Confidence %"].iloc[0])
    assert new_fpt > base_fpt


def test_non_intersecting_symbols_yields_zero_applied() -> None:
    df = _candidates_df()
    rows = [_signal_row("AAA"), _signal_row("BBB")]
    out, meta = rerank_candidates_with_flow_journal(
        df,
        enabled=True,
        journal_reader=lambda **_: rows,
    )
    assert meta["enabled"] is True
    assert meta["applied_count"] == 0
    assert meta["journal_signal_count"] == 2
    assert "Flow boost" in out.columns


def test_empty_candidates_short_circuits() -> None:
    out, meta = rerank_candidates_with_flow_journal(
        pd.DataFrame(),
        enabled=True,
        journal_reader=lambda **_: [_signal_row("FPT")],
    )
    assert meta["enabled"] is True
    assert meta["reason"] == "empty_candidates"
    assert meta["applied_count"] == 0
    assert isinstance(out, pd.DataFrame)
    assert out.empty


def test_non_dataframe_input_returned_as_is() -> None:
    out, meta = rerank_candidates_with_flow_journal([{"Mã": "FPT"}], enabled=True)  # type: ignore[arg-type]
    assert meta["enabled"] is False
    assert meta["reason"] == "not_dataframe"
    assert isinstance(out, list)


def test_latest_signal_per_symbol_picks_most_recent_ts() -> None:
    rows = [
        _signal_row("FPT", intensity=3.0, ts="2026-05-11T08:00:00+00:00"),
        _signal_row("FPT", intensity=9.0, ts="2026-05-11T10:00:00+00:00"),
        _signal_row("FPT", intensity=5.0, ts="2026-05-11T09:00:00+00:00"),
    ]
    latest = _latest_signal_per_symbol(rows)
    assert "FPT" in latest
    assert latest["FPT"]["intensity_score"] == 9.0


def test_latest_signal_per_symbol_handles_blank_symbol_and_non_dict() -> None:
    rows = [
        _signal_row("", ts="2026-05-11T10:00:00+00:00"),
        {"symbol": None, "journaled_at_utc": "2026-05-11T10:00:00+00:00"},
        "not_a_dict",  # type: ignore[list-item]
        _signal_row("FPT", ts="2026-05-11T10:00:00+00:00"),
    ]
    latest = _latest_signal_per_symbol(rows)  # type: ignore[arg-type]
    assert set(latest.keys()) == {"FPT"}


def test_env_flag_enables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_ENABLED", "1")
    assert is_scanner_rerank_enabled() is True
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_ENABLED", "0")
    assert is_scanner_rerank_enabled() is False


def test_env_lookback_hours_passed_to_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_LOOKBACK_HOURS", "48")
    captured: dict[str, int] = {}

    def _reader(**kwargs: object) -> list[dict]:
        captured["hours"] = int(kwargs.get("hours") or 0)
        return []

    df = _candidates_df()
    _, meta = rerank_candidates_with_flow_journal(
        df, enabled=True, journal_reader=_reader
    )
    assert captured["hours"] == 48
    assert meta["lookback_hours"] == 48


def test_env_weight_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_WEIGHT", "0.5")
    df = _candidates_df()
    rows = [_signal_row("FPT", intensity=8.0)]
    _, meta = rerank_candidates_with_flow_journal(
        df, enabled=True, journal_reader=lambda **_: rows
    )
    assert meta["weight"] == pytest.approx(0.5)


def test_invalid_env_weight_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_WEIGHT", "not_a_number")
    df = _candidates_df()
    rows = [_signal_row("FPT", intensity=8.0)]
    _, meta = rerank_candidates_with_flow_journal(
        df, enabled=True, journal_reader=lambda **_: rows
    )
    assert meta["weight"] == pytest.approx(0.25)


def test_invalid_env_lookback_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_LOOKBACK_HOURS", "abc")
    captured: dict[str, int] = {}

    def _reader(**kwargs: object) -> list[dict]:
        captured["hours"] = int(kwargs.get("hours") or 0)
        return []

    df = _candidates_df()
    rerank_candidates_with_flow_journal(
        df, enabled=True, journal_reader=_reader
    )
    assert captured["hours"] == 24


def test_explicit_weight_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_WEIGHT", "0.5")
    df = _candidates_df()
    rows = [_signal_row("FPT", intensity=8.0)]
    _, meta = rerank_candidates_with_flow_journal(
        df, enabled=True, journal_reader=lambda **_: rows, weight=0.1
    )
    assert meta["weight"] == pytest.approx(0.1)


def test_explicit_disabled_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("II_SCANNER_FLOW_RERANK_ENABLED", "1")
    df = _candidates_df()
    out, meta = rerank_candidates_with_flow_journal(df, enabled=False)
    assert meta["enabled"] is False
    assert meta["reason"] == "disabled"
    assert "Flow boost" not in out.columns
