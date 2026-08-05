from __future__ import annotations

from datetime import date

import pandas as pd
import pytest


def test_configure_vnstock_credentials_sets_api_key_env(monkeypatch, tmp_path) -> None:
    import scrapers.vnstock_provider as vp

    monkeypatch.setattr(vp, "_CREDENTIALS_CONFIGURED", False)
    monkeypatch.delenv("VNSTOCK_API_KEY", raising=False)
    monkeypatch.setenv("II_VNSTOCK_TOKEN", "vnstock_test_token_1234567890")
    monkeypatch.setattr(vp, "_persist_api_key_file", lambda k: None)

    assert vp.configure_vnstock_credentials(force=True) is True
    assert vp.os.environ.get("VNSTOCK_API_KEY") == "vnstock_test_token_1234567890"


def test_configure_vnstock_credentials_reads_ii_vnstock_api_key(monkeypatch) -> None:
    import scrapers.vnstock_provider as vp

    monkeypatch.setattr(vp, "_CREDENTIALS_CONFIGURED", False)
    monkeypatch.delenv("II_VNSTOCK_TOKEN", raising=False)
    monkeypatch.delenv("VNSTOCK_API_KEY", raising=False)
    monkeypatch.setenv("II_VNSTOCK_API_KEY", "vnstock_c3a2f74b39f543a854a7b8dd9d14580f")
    monkeypatch.setattr(vp, "_persist_api_key_file", lambda k: None)

    assert vp.configure_vnstock_credentials(force=True) is True
    assert vp.os.environ.get("VNSTOCK_API_KEY") == "vnstock_c3a2f74b39f543a854a7b8dd9d14580f"


def test_call_with_retry_on_rate_limit_then_success(monkeypatch) -> None:
    import scrapers.vnstock_provider as vp

    calls = {"n": 0}
    sleeps: list[float] = []

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("Rate Limit Exceeded - Guest limit 20 requests/min")
        return "ok"

    monkeypatch.setattr(vp, "configure_vnstock_credentials", lambda **k: False)
    monkeypatch.setattr(vp, "_retry_max_attempts", lambda: 3)
    monkeypatch.setattr(vp, "_retry_base_sec", lambda: 0.01)
    monkeypatch.setattr(vp.time, "sleep", lambda s: sleeps.append(float(s)))

    out = vp._call_with_retry("test_label", flaky)
    assert out == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2


def test_call_with_retry_non_retryable_raises_immediately(monkeypatch) -> None:
    import scrapers.vnstock_provider as vp

    monkeypatch.setattr(vp, "configure_vnstock_credentials", lambda **k: False)
    monkeypatch.setattr(vp.time, "sleep", lambda s: (_ for _ in ()).throw(AssertionError("no sleep")))

    with pytest.raises(vp.VnstockProviderError, match="bad_symbol"):
        vp._call_with_retry("bad", lambda: (_ for _ in ()).throw(ValueError("bad_symbol")))


def test_fetch_ohlcv_history_uses_retry_wrapper(monkeypatch) -> None:
    import scrapers.vnstock_provider as vp

    df = pd.DataFrame(
        {
            "time": pd.date_range("2024-01-01", periods=3, freq="D"),
            "Open": [10, 11, 12],
            "High": [11, 12, 13],
            "Low": [9, 10, 11],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [1000, 1100, 1200],
        }
    )
    captured: dict[str, object] = {}

    def _fake_raw(sym: str, start: date, end: date, src: str) -> pd.DataFrame:
        captured.update({"sym": sym, "start": start, "end": end, "src": src})
        return df

    monkeypatch.setattr(vp, "_fetch_quote_history_raw", _fake_raw)
    monkeypatch.setattr(vp, "_call_with_retry", lambda label, fn, *a, **k: fn(*a, **k))
    monkeypatch.setattr(vp, "vnstock_available", lambda: True)

    out = vp.fetch_ohlcv_history("FPT", sessions=50)
    assert captured["sym"] == "FPT"
    assert not out.empty
    assert float(out.iloc[-1]["close"]) > 1000.0


def test_parse_finance_ratio_to_indicators_maps_core_metrics() -> None:
    import scrapers.vnstock_provider as vp

    ratio = pd.DataFrame(
        {
            "item_id": ["pe_ratio", "pb_ratio", "roe", "debt_to_equity", "dividend_yield"],
            "item": ["P/E"] * 5,
            "2018": [11.0, 2.0, 17.0, 0.4, 2.5],
            "2018_dup": [12.5, 2.1, 18.0, 0.45, 3.2],
        }
    )
    out = vp.parse_finance_ratio_to_indicators(ratio, symbol="FPT")
    assert out["symbol"] == "FPT"
    assert out["pe_ratio"] == pytest.approx(12.5)
    assert out["pb_ratio"] == pytest.approx(2.1)
    assert out["roe"] == pytest.approx(18.0)
    assert out["debt_to_equity"] == pytest.approx(0.45)
    assert out["dividend_yield_pct"] == pytest.approx(3.2)
    assert int(out["data_quality_score"]) >= 4


def test_parse_company_events_dividends_counts_years() -> None:
    import scrapers.vnstock_provider as vp

    events = pd.DataFrame(
        {
            "event_type": ["cash dividend", "cash dividend", "rights issue"],
            "payout_date": ["2024-05-01", "2023-05-01", "2022-01-01"],
            "value_per_share": [1500.0, 1400.0, 0.0],
        }
    )
    out = vp.parse_company_events_dividends(events, lookback_years=10)
    assert out["dividend_events_count"] == 2
    assert out["dividend_paid_years"] == 2
    assert 2023 in out["dividend_years_list"]
    assert 2024 in out["dividend_years_list"]


def test_parse_company_info_extracts_icb_and_float() -> None:
    import scrapers.vnstock_provider as vp

    info = {
        "icb_code_lv2": "Technology",
        "free_float": 45.5,
        "outstanding_shares": 1200.0,
        "foreigner_percentage": 22.0,
        "company_profile": "FPT Corporation",
    }
    out = vp.parse_company_info(info)
    assert out["icb_sector"] == "Technology"
    assert out["free_float_pct"] == pytest.approx(45.5)
    assert out["outstanding_shares"] == pytest.approx(1200.0)
    assert out["foreign_ownership_pct"] == pytest.approx(22.0)


def test_streamlit_executor_initializer_attaches_captured_parent_context(monkeypatch) -> None:
    from core import streamlit_executor as se

    attached: list[object] = []
    sentinel = object()

    monkeypatch.setattr(se, "capture_streamlit_script_context", lambda: sentinel)

    def _fake_attach(ctx=None) -> None:
        attached.append(ctx)

    monkeypatch.setattr(se, "attach_streamlit_script_context", _fake_attach)
    with se.streamlit_thread_pool_executor(max_workers=1) as ex:
        ex.submit(lambda: None).result()
    assert attached == [sentinel]


def test_parse_finance_ratio_includes_current_ratio() -> None:
    import scrapers.vnstock_provider as vp

    ratio = pd.DataFrame(
        {
            "item_id": ["pe_ratio", "roe", "current_ratio", "debt_to_equity"],
            "2023": [12.0, 0.18, 1.4, 0.6],
            "2024": [11.0, 0.20, 1.7, 0.5],
        }
    )
    out = vp.parse_finance_ratio_to_indicators(ratio, symbol="FPT")
    assert out["current_ratio"] == pytest.approx(1.7)
    assert out["pe_ratio"] == pytest.approx(11.0)
    assert int(out["data_quality_score"]) >= 3


def test_parse_finance_statements_maps_cfo_and_ni() -> None:
    import scrapers.vnstock_provider as vp

    cash = pd.DataFrame(
        {
            "item_id": ["net_cash_inflows_outflows_from_operating_activities"],
            "2023": [100.0],
            "2024": [150.0],
        }
    )
    income = pd.DataFrame(
        {
            "item_id": ["net_profit_loss_after_tax"],
            "2023": [80.0],
            "2024": [120.0],
        }
    )
    out = vp.parse_finance_statements_to_indicators(cash, income, symbol="FPT")
    assert out["operating_cash_flow"] == pytest.approx(150.0)
    assert out["operating_cash_flow_prior"] == pytest.approx(100.0)
    assert out["net_income"] == pytest.approx(120.0)
    assert out["net_income_prior"] == pytest.approx(80.0)

    merged = vp.merge_statement_fields_into_indicators({"data_quality_score": 2}, out)
    assert merged["operating_cash_flow"] == pytest.approx(150.0)
    assert int(merged["data_quality_score"]) >= 3
