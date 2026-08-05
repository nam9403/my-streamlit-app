from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

import pytest

from scrapers import intraday_vn
from scrapers.intraday_vn import (
    IntradayDataError,
    IntradayFetchConfig,
    fetch_intraday_ohlcv,
    is_vn_market_open,
    next_vn_market_open,
    reset_intraday_breaker,
)


class _FakeResp:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeSession:
    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, *, params: dict[str, Any], headers: dict[str, str], timeout: float) -> _FakeResp:
        self.calls.append((url, dict(params)))
        for needle, resp in self._responses.items():
            if needle in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return _FakeResp({"s": "error"}, status_code=500)


def _vnd_payload(n: int = 200, base: float = 25_000.0) -> dict[str, Any]:
    now = int(datetime.now(timezone.utc).timestamp())
    ts = [now - (n - 1 - i) * 300 for i in range(n)]
    closes = [base + i * 5 for i in range(n)]
    return {
        "s": "ok",
        "t": ts,
        "o": [base + i * 5 - 10 for i in range(n)],
        "h": [base + i * 5 + 20 for i in range(n)],
        "l": [base + i * 5 - 25 for i in range(n)],
        "c": closes,
        "v": [10_000.0 + i for i in range(n)],
    }


def _tcbs_payload(n: int = 200, base: float = 25_000.0) -> dict[str, Any]:
    rows = []
    start = datetime.now(timezone.utc) - timedelta(minutes=5 * n)
    for i in range(n):
        ts = (start + timedelta(minutes=5 * i)).isoformat()
        rows.append(
            {
                "tradingDate": ts,
                "open": base + i * 5 - 10,
                "high": base + i * 5 + 20,
                "low": base + i * 5 - 25,
                "close": base + i * 5,
                "volume": 10_000.0 + i,
            }
        )
    return {"data": rows}


@pytest.fixture(autouse=True)
def _clear_intraday_cache() -> None:
    intraday_vn._MEM_CACHE.clear()
    reset_intraday_breaker()
    yield
    intraday_vn._MEM_CACHE.clear()
    reset_intraday_breaker()


def test_fetch_intraday_returns_vndirect_primary() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp(_vnd_payload(150)),
            "apipubaws.tcbs": _FakeResp({"s": "error"}, status_code=500),
        }
    )
    df = fetch_intraday_ohlcv("FPT", resolution="5", lookback_bars=200, session=session)
    assert not df.empty
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert df.attrs["source"] == "intraday_vndirect"
    assert df.attrs["data_trust"]["source"] == "intraday_vndirect"
    assert df["date"].is_monotonic_increasing
    assert df["close"].iloc[-1] > df["close"].iloc[0]


def test_fetch_intraday_falls_back_to_tcbs_on_vnd_error() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "no_data"}, status_code=200),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(100)),
        }
    )
    df = fetch_intraday_ohlcv("HPG", resolution="5", lookback_bars=150, session=session)
    assert not df.empty
    assert df.attrs["source"] == "intraday_tcbs"
    assert df.attrs["data_trust"]["fallback_chain"] == ["vndirect", "tcbs"]


def test_fetch_intraday_raises_when_all_sources_fail() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "no_data"}, status_code=200),
            "apipubaws.tcbs": _FakeResp({"data": []}, status_code=200),
        }
    )
    with pytest.raises(IntradayDataError):
        fetch_intraday_ohlcv("XXX", resolution="5", lookback_bars=100, session=session)


def test_fetch_intraday_handles_http_error_then_fallback() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "error"}, status_code=503),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(80)),
        }
    )
    df = fetch_intraday_ohlcv("VNM", resolution="5", lookback_bars=100, session=session)
    assert df.attrs["source"] == "intraday_tcbs"


def test_fetch_intraday_rejects_daily_resolution() -> None:
    with pytest.raises(IntradayDataError):
        fetch_intraday_ohlcv("FPT", resolution="1D", lookback_bars=100, session=_FakeSession({}))


def test_fetch_intraday_uses_cache_on_second_call() -> None:
    session = _FakeSession({"dchart-api.vndirect": _FakeResp(_vnd_payload(80))})
    df1 = fetch_intraday_ohlcv("FPT", resolution="5", lookback_bars=120, cache_ttl_sec=60, session=session)
    calls_after_first = len(session.calls)
    df2 = fetch_intraday_ohlcv("FPT", resolution="5", lookback_bars=120, cache_ttl_sec=60, session=session)
    assert len(session.calls) == calls_after_first
    assert df1["close"].tolist() == df2["close"].tolist()


def test_fetch_intraday_records_sla_for_each_source() -> None:
    events: list[tuple[str, bool]] = []
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "no_data"}),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    fetch_intraday_ohlcv(
        "MWG",
        resolution="5",
        lookback_bars=80,
        session=session,
        sla_recorder=lambda src, ok: events.append((src, ok)),
    )
    sources = {ev[0] for ev in events}
    assert "intraday_vndirect" in sources
    assert "intraday_tcbs" in sources
    assert any(ev[0] == "intraday_tcbs" and ev[1] for ev in events)


def test_fetch_intraday_tcbs_primary_uses_tcbs_first() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "no_data"}),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(70)),
        }
    )
    df = fetch_intraday_ohlcv("HPG", resolution="5", lookback_bars=90, primary_source="tcbs", session=session)
    assert df.attrs["source"] == "intraday_tcbs"
    assert session.calls[0][0].startswith("https://apipubaws.tcbs.com.vn")


def test_fetch_intraday_invalid_symbol_raises() -> None:
    with pytest.raises(IntradayDataError):
        fetch_intraday_ohlcv("", resolution="5", session=_FakeSession({}))
    with pytest.raises(IntradayDataError):
        fetch_intraday_ohlcv("ABC@!", resolution="5", session=_FakeSession({}))


def test_intraday_config_normalize_clamps_lookback_and_resolution() -> None:
    cfg = IntradayFetchConfig(
        resolution="7",
        lookback_bars=100_000,
        timeout_sec=1000.0,
        cache_ttl_sec=-5.0,
        primary_source="weird",
    ).normalize()
    assert cfg.resolution == "5"
    assert cfg.lookback_bars <= 5000
    assert cfg.timeout_sec <= 30.0
    assert cfg.cache_ttl_sec >= 0.0
    assert cfg.primary_source == "vndirect"


def test_is_vn_market_open_during_morning_session() -> None:
    monday_10h = datetime(2024, 6, 3, 10, 0, tzinfo=intraday_vn.VN_TZ)
    assert is_vn_market_open(monday_10h) is True


def test_is_vn_market_open_during_lunch_break() -> None:
    monday_12h = datetime(2024, 6, 3, 12, 15, tzinfo=intraday_vn.VN_TZ)
    assert is_vn_market_open(monday_12h) is False


def test_is_vn_market_open_during_afternoon_session() -> None:
    monday_14h = datetime(2024, 6, 3, 14, 30, tzinfo=intraday_vn.VN_TZ)
    assert is_vn_market_open(monday_14h) is True


def test_is_vn_market_open_after_close() -> None:
    monday_15h = datetime(2024, 6, 3, 15, 0, tzinfo=intraday_vn.VN_TZ)
    assert is_vn_market_open(monday_15h) is False


def test_is_vn_market_open_weekend() -> None:
    saturday_10h = datetime(2024, 6, 8, 10, 0, tzinfo=intraday_vn.VN_TZ)
    assert is_vn_market_open(saturday_10h) is False


def test_next_vn_market_open_before_morning() -> None:
    pre_open = datetime(2024, 6, 3, 7, 30, tzinfo=intraday_vn.VN_TZ)
    nxt = next_vn_market_open(pre_open)
    assert nxt.date() == pre_open.date()
    assert nxt.time() == time(9, 0)


def test_next_vn_market_open_during_lunch() -> None:
    lunch = datetime(2024, 6, 3, 12, 30, tzinfo=intraday_vn.VN_TZ)
    nxt = next_vn_market_open(lunch)
    assert nxt.time() == time(13, 0)


def test_next_vn_market_open_after_close_moves_to_next_business_day() -> None:
    after = datetime(2024, 6, 3, 16, 0, tzinfo=intraday_vn.VN_TZ)
    nxt = next_vn_market_open(after)
    assert nxt.weekday() < 5
    assert nxt.date() > after.date()


def test_batch_fetch_intraday_skips_failed_symbols() -> None:
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({"s": "no_data"}),
            "apipubaws.tcbs": _FakeResp({"data": []}),
        }
    )
    # Patch the module-level fetchers so batch uses our fake session implicitly.
    original = intraday_vn.fetch_intraday_ohlcv

    def _wrapped(symbol, **kwargs):
        kwargs["session"] = session
        return original(symbol, **kwargs)

    intraday_vn.fetch_intraday_ohlcv = _wrapped  # type: ignore[assignment]
    try:
        out = intraday_vn.batch_fetch_intraday(
            ["FPT", "HPG"], resolution="5", lookback_bars=60
        )
    finally:
        intraday_vn.fetch_intraday_ohlcv = original  # type: ignore[assignment]
    assert out == {}


# -- Circuit breaker / retry / registry tests --------------------------------


def test_rate_limit_429_raises_rate_limit_error_then_falls_back() -> None:
    """VNDirect trả 429 → retry hết thì IntradayRateLimitError ⇒ fallback sang TCBS."""
    session = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({}, status_code=429),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    df = fetch_intraday_ohlcv(
        "FPT", resolution="5", lookback_bars=60, session=session, cache_ttl_sec=0
    )
    assert not df.empty
    assert df.attrs["source"] == "intraday_tcbs"


def test_breaker_opens_after_threshold_and_skips_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sau 3 failure liên tiếp, breaker mở → source bị skip."""
    monkeypatch.setattr(intraday_vn, "_BREAKER_FAILURE_THRESHOLD", 3)
    monkeypatch.setattr(intraday_vn, "_BREAKER_COOLDOWN_SEC", 300.0)
    monkeypatch.setattr(intraday_vn, "_RETRY_MAX_ATTEMPTS", 1)
    session_fail = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({}, status_code=500),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    for _ in range(3):
        df = fetch_intraday_ohlcv(
            "FPT", resolution="5", lookback_bars=60, session=session_fail, cache_ttl_sec=0
        )
        assert df.attrs["source"] == "intraday_tcbs"
    state = intraday_vn.get_intraday_breaker_state()
    assert "vndirect" in state
    assert state["vndirect"]["open_until_ts"] > 0
    # Call lần 4 — vndirect bị skip do breaker open → tcbs vẫn trả
    session_ok = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp(_vnd_payload(60)),  # giả sử OK lại
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    df = fetch_intraday_ohlcv(
        "FPT", resolution="5", lookback_bars=60, session=session_ok, cache_ttl_sec=0
    )
    # Vẫn dùng tcbs vì vndirect bị breaker
    assert df.attrs["source"] == "intraday_tcbs"


def test_breaker_resets_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intraday_vn, "_RETRY_MAX_ATTEMPTS", 1)
    session_fail = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp({}, status_code=500),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    fetch_intraday_ohlcv(
        "FPT", resolution="5", lookback_bars=60, session=session_fail, cache_ttl_sec=0
    )
    state_after_fail = intraday_vn.get_intraday_breaker_state()
    assert state_after_fail["vndirect"]["consecutive_failures"] >= 1

    session_ok = _FakeSession(
        {
            "dchart-api.vndirect": _FakeResp(_vnd_payload(60)),
            "apipubaws.tcbs": _FakeResp(_tcbs_payload(60)),
        }
    )
    fetch_intraday_ohlcv(
        "HPG", resolution="5", lookback_bars=60, session=session_ok, cache_ttl_sec=0
    )
    state_after_ok = intraday_vn.get_intraday_breaker_state()
    assert "vndirect" not in state_after_ok  # reset


def test_register_intraday_source_adds_custom_fetcher() -> None:
    def _custom_fetcher(symbol, cfg, *, session=None):
        import pandas as pd

        return pd.DataFrame(
            {
                "date": [
                    pd.Timestamp.now(tz=intraday_vn.VN_TZ) - timedelta(minutes=i)
                    for i in range(60, 0, -1)
                ],
                "open": [25.0] * 60,
                "high": [26.0] * 60,
                "low": [24.0] * 60,
                "close": [25.5] * 60,
                "volume": [1_000_000.0] * 60,
            }
        )

    try:
        intraday_vn.register_intraday_source("dnse", _custom_fetcher)
        assert "dnse" in intraday_vn.list_intraday_sources()
    finally:
        intraday_vn._SOURCE_FETCHERS.pop("dnse", None)


def test_register_intraday_source_rejects_builtin_overwrite() -> None:
    with pytest.raises(ValueError):
        intraday_vn.register_intraday_source("vndirect", lambda *a, **kw: None)


def test_extra_sources_env_extends_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """II_INTRADAY_EXTRA_SOURCES cho phép thêm custom source vào chain."""
    captured: list[str] = []

    def _custom_fetcher(symbol, cfg, *, session=None):
        captured.append(symbol)
        raise IntradayDataError("custom_failed")

    intraday_vn.register_intraday_source("dnse_test", _custom_fetcher)
    try:
        monkeypatch.setenv("II_INTRADAY_EXTRA_SOURCES", "dnse_test")
        session = _FakeSession(
            {
                "dchart-api.vndirect": _FakeResp({"s": "no_data"}),
                "apipubaws.tcbs": _FakeResp({"data": []}),
            }
        )
        with pytest.raises(IntradayDataError):
            fetch_intraday_ohlcv(
                "FPT",
                resolution="5",
                lookback_bars=60,
                session=session,
                cache_ttl_sec=0,
            )
        assert captured == ["FPT"]  # custom source đã được thử
    finally:
        intraday_vn._SOURCE_FETCHERS.pop("dnse_test", None)


def test_reset_intraday_breaker_clears_specific_source() -> None:
    intraday_vn._breaker_record_failure("vndirect")
    intraday_vn._breaker_record_failure("tcbs")
    assert "vndirect" in intraday_vn.get_intraday_breaker_state()
    assert "tcbs" in intraday_vn.get_intraday_breaker_state()
    reset_intraday_breaker("vndirect")
    state = intraday_vn.get_intraday_breaker_state()
    assert "vndirect" not in state
    assert "tcbs" in state


def test_retry_succeeds_after_one_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source rate-limited 1 lần đầu, lần 2 OK → retry succeed, không fallback."""
    monkeypatch.setattr(intraday_vn, "_RETRY_BASE_BACKOFF_SEC", 0.01)
    call_count = {"n": 0}
    success_payload = _vnd_payload(60)
    rate_limit_resp = _FakeResp({}, status_code=429)
    ok_resp = _FakeResp(success_payload)

    class _RetrySession:
        def get(self, url, *, params, headers, timeout):
            call_count["n"] += 1
            if "dchart-api.vndirect" in url and call_count["n"] == 1:
                return rate_limit_resp
            if "dchart-api.vndirect" in url:
                return ok_resp
            return _FakeResp({"data": []})

    df = fetch_intraday_ohlcv(
        "FPT", resolution="5", lookback_bars=60, session=_RetrySession(), cache_ttl_sec=0
    )
    assert df.attrs["source"] == "intraday_vndirect"
    assert call_count["n"] >= 2
