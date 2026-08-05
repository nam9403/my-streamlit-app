from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd


def test_scanner_build_views_and_daily_actions(monkeypatch) -> None:
    import core.scanner_service as ss

    monkeypatch.setattr(ss, "load_snapshot_cached", lambda sym: {"price": 100.0})

    reports = {
        "AAA": {
            "final_action": "BUY",
            "gate_passed": True,
            "output_gate_passed": True,
            "confidence_score": 80.0,
            "valuation": {"price": 100.0, "margin_of_safety_composite_pct": 20.0, "piotroski_score": 8},
            "risk_plan": {"entry_price": 100.0, "stop_loss_price": 95.0, "take_profit_price": 116.0, "max_position_pct": 12.0},
            "phase": {"phase": "accumulation"},
        },
        "BBB": {
            "final_action": "AVOID",
            "gate_passed": False,
            "output_gate_passed": False,
            "confidence_score": 40.0,
            "valuation": {"price": 80.0, "margin_of_safety_composite_pct": 2.0, "piotroski_score": 3},
            "risk_plan": {"entry_price": 0.0, "stop_loss_price": 0.0, "take_profit_price": 0.0, "max_position_pct": 5.0},
            "phase": {"phase": "distribution"},
        },
    }
    monkeypatch.setattr(
        ss,
        "load_strategic_report_cached",
        lambda sym, *a, **k: reports[sym],
    )

    simple = ss.build_autopilot_simple_view.__wrapped__(("AAA", "BBB"), "growth", 100_000_000.0, True, False)  # type: ignore[attr-defined]
    assert not simple.empty
    assert "Mã" in simple.columns

    pf = ss.build_profit_focus_board.__wrapped__(("AAA", "BBB"), "growth", 100_000_000.0, True, False)  # type: ignore[attr-defined]
    assert not pf.empty
    assert pf.iloc[0]["Mã"] == "AAA"

    daily = ss.build_daily_action_list.__wrapped__(("AAA", "BBB"), "growth", 100_000_000.0, ("BBB",), True, False)  # type: ignore[attr-defined]
    assert not daily.empty
    by_sym = {str(r["Mã"]): str(r["Hành động hôm nay"]) for _, r in daily.iterrows()}
    assert by_sym["AAA"] in ("BUY", "WATCH")
    assert by_sym["BBB"] in ("SELL", "HOLD")


def test_strategy_backtest_helper_paths(monkeypatch) -> None:
    import core.strategy_backtest as sb

    monkeypatch.setattr(sb, "_yahoo_chart", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    s, lbl = sb.fetch_specific_benchmark_series("VN30.VN", "max")
    assert s is None
    assert lbl == ""

    n = 100
    ohlcv = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100, 110, n),
            "volume": np.linspace(1e5, 2e5, n),
        }
    )
    monkeypatch.setattr(sb, "fetch_long_ohlcv_for_backtest", lambda *a, **k: (ohlcv, "max"))
    monkeypatch.setattr(sb, "fetch_vn_benchmark_series", lambda *a, **k: (None, ""))
    res, label = sb.run_full_backtest_for_ticker("FPT")
    assert isinstance(label, str) and label
    assert "Benchmark:" in res.note


def test_report_export_markdown_and_html() -> None:
    from core.report_export import investment_report_html, investment_report_markdown

    summary = {
        "symbol": "FPT",
        "name": "FPT Corp",
        "currency": "VND",
        "data_source": "unit_test",
        "price": 100_000,
        "intrinsic_value_graham": 120_000,
        "target_price_forward_pe": 130_000,
        "target_price_pb_fair": 125_000,
        "composite_target_price": 128_000,
        "margin_of_safety_pct": 20.0,
        "margin_of_safety_composite_pct": 18.0,
        "piotroski_score": 7,
        "valuation_transparency_line": "**weights**",
        "advice": "Theo doi",
    }
    md = investment_report_markdown(summary)
    html = investment_report_html(summary)
    assert "Báo cáo định giá" in md
    assert "F-Score" in md
    assert "<html" in html.lower()
    assert "FPT Corp" in html


def test_forecast_accountability_service_core(monkeypatch, tmp_path: Path) -> None:
    import core.forecast_accountability_service as fas

    now = datetime.now(timezone.utc)
    rows = [
        {
            "created_at": (now - timedelta(days=2)).isoformat(),
            "direction_hit": 1,
            "abs_error_pct": 5.0,
            "expected_return_pct": 4.0,
            "realized_return_pct": 8.0,
        },
        {
            "created_at": (now - timedelta(days=10)).isoformat(),
            "direction_hit": 0,
            "abs_error_pct": 12.0,
            "expected_return_pct": 6.0,
            "realized_return_pct": 1.0,
        },
    ]
    monkeypatch.setattr(
        fas.forecast_repository,
        "fetch_resolved_rows_for_dashboard",
        lambda **k: rows,
    )
    def parse_ts(s: str):
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    dash = fas.get_forecast_portfolio_dashboard(conn_factory=lambda: None, parse_ts=parse_ts, user_id="u1")
    assert int(dash["overall"]["samples"]) == 2
    regime = fas.get_forecast_regime_dashboard(conn_factory=lambda: None, user_id="u1")
    assert "bull" in regime and "sideway" in regime and "bear" in regime

    path = fas.export_forecast_health_report(
        root=tmp_path,
        utcnow_iso=lambda: now.isoformat(),
        user_id="u1",
        get_forecast_portfolio_dashboard_func=lambda uid: dash,
        get_forecast_regime_dashboard_func=lambda uid: regime,
        get_forecast_leaderboard_func=lambda uid, n: [],
    )
    assert Path(path).exists()

    ok, msg = fas.send_monthly_accountability_email(
        user_id="u1",
        email_to="",
        smtp_host="smtp",
        export_monthly_accountability_markdown_func=lambda uid: str(tmp_path / "x.md"),
        short_error=lambda scope, exc: str(exc),
        logger_warning=lambda *a, **k: None,
    )
    assert ok is False
    assert "Thiếu email" in msg


def test_scanner_load_board_empty_and_simple_view_empty(monkeypatch) -> None:
    import core.scanner_service as ss

    monkeypatch.setattr(ss, "list_universe_symbols", lambda limit=30, offset=0: ["AAA"])
    monkeypatch.setattr(ss, "scan_potential_stocks", lambda *a, **k: pd.DataFrame())
    out = ss.load_autopilot_board.__wrapped__("growth", 30, 100_000.0, _rotation_day=1)  # type: ignore[attr-defined]
    assert out.empty
    assert "Khuyến nghị" in out.columns

    empty = ss.simple_view_for_plan(pd.DataFrame(), "free")
    assert empty.empty


def test_strategy_backtest_error_branches_and_yearly_returns(monkeypatch) -> None:
    import core.strategy_backtest as sb

    no_date_df = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
    with np.testing.assert_raises(ValueError):
        sb.run_phase_signal_backtest(no_date_df, pd.Series([1.0, 2.0, 3.0]), warmup=1)

    short_df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=10, freq="D"),
            "open": [1.0] * 10,
            "high": [1.0] * 10,
            "low": [1.0] * 10,
            "close": [1.0] * 10,
            "volume": [1.0] * 10,
        }
    )
    bench = pd.Series(short_df["close"].values, index=short_df["date"].dt.normalize())
    with np.testing.assert_raises(ValueError):
        sb.run_phase_signal_backtest(short_df, bench, warmup=60)

    dates = list(pd.date_range("2024-01-01", periods=6, freq="180D"))
    equity = np.array([100.0, 110.0, 120.0, 130.0, 140.0, 150.0], dtype=float)
    yearly = sb.equity_yearly_returns_pct(dates, equity, series_label="app")
    assert "Năm" in yearly.columns
    assert "Tăng % (app)" in yearly.columns

    with np.testing.assert_raises(ValueError):
        sb.equity_yearly_returns_pct(dates, np.array([100.0], dtype=float))

    called: list[tuple[str, str]] = []

    def fake_yahoo(sym: str, rng: str = "2y") -> pd.DataFrame:
        called.append((sym, rng))
        if sym.endswith(".HM"):
            n = 100
            return pd.DataFrame(
                {
                    "date": pd.date_range("2024-01-01", periods=n, freq="B"),
                    "open": np.linspace(1, 2, n),
                    "high": np.linspace(1, 2, n),
                    "low": np.linspace(1, 2, n),
                    "close": np.linspace(1, 2, n),
                    "volume": np.linspace(1, 2, n),
                }
            )
        raise ValueError("not found")

    monkeypatch.setattr(sb, "_yahoo_chart", fake_yahoo)
    df, used = sb.fetch_long_ohlcv_for_backtest("fpt", range_preference="max")
    assert len(df) == 100
    assert used == "max"
    assert any(sym.endswith(".HM") for sym, _ in called)


def test_report_export_extra_and_monthly_markdown(tmp_path: Path) -> None:
    from core.forecast_accountability_service import export_monthly_accountability_markdown
    from core.report_export import premium_storytelling_report_markdown

    minimal = {
        "ticker": "AAA",
        "valuation": {"symbol": "AAA", "name": "AAA Corp", "industry_cluster_id": "unknown"},
        "financials": {},
        "phase": {},
        "risk_plan": {},
        "news": [],
    }
    out = premium_storytelling_report_markdown(minimal)
    assert "Ngành khác" in out
    assert "Điểm tin gần nhất" not in out

    md_path = export_monthly_accountability_markdown(
        root=tmp_path,
        utcnow_iso=lambda: "2026-01-01T00:00:00+00:00",
        user_id="u1",
        get_forecast_portfolio_dashboard_func=lambda uid, lb: {
            "weekly": {"samples": 2, "hit_rate_pct": 50.0, "mape_pct": 4.0, "alpha_pct": 1.0},
            "monthly": {},
            "overall": {"samples": 5, "hit_rate_pct": 60.0, "mape_pct": 5.0, "alpha_pct": -0.5},
        },
        get_forecast_regime_dashboard_func=lambda uid, lb: {"bull": {}, "sideway": {}, "bear": {}},
        get_kpi_dashboard_func=lambda uid, days: {"events_total": 1, "alerts_total": 2, "holdings_total": 3},
        proof_of_value_report_func=lambda uid: {"value_score": 0.8, "maturity_score": 0.7},
        get_forecast_leaderboard_func=lambda uid, n: [{"symbol": "AAA", "score": 12.3, "hit_rate_pct": 70.0, "mape_pct": 3.2, "alpha_pct": 1.4}],
    )
    text = Path(md_path).read_text(encoding="utf-8")
    assert "Monthly Model Accountability Report" in text
    assert "Top 10 Leaderboard" in text


def test_forecast_accountability_export_model_and_email_exception(monkeypatch, tmp_path: Path) -> None:
    import core.forecast_accountability_service as fas

    path = fas.export_model_accountability_report(
        root=tmp_path,
        utcnow_iso=lambda: "2026-01-01T00:00:00+00:00",
        user_id="u1",
        get_forecast_portfolio_dashboard_func=lambda uid: {"overall": {"samples": 1}},
        get_forecast_regime_dashboard_func=lambda uid: {"bull": {"samples": 1}},
        get_forecast_leaderboard_func=lambda uid, n: [],
        get_kpi_dashboard_func=lambda uid, d: {"events_total": 1},
        proof_of_value_report_func=lambda uid: {"value_score": 1.0},
    )
    assert Path(path).exists()

    md = tmp_path / "m.md"
    md.write_text("hello", encoding="utf-8")
    warnings: list[str] = []

    class BadSMTP:
        def __init__(self, host: str, port: int, timeout: int = 10) -> None:
            _ = (host, port, timeout)

        def __enter__(self):
            raise OSError("smtp down")

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(fas.smtplib, "SMTP", BadSMTP)
    ok, msg = fas.send_monthly_accountability_email(
        user_id="u1",
        email_to="a@b.com",
        smtp_host="smtp.local",
        smtp_user="u",
        smtp_password="p",
        export_monthly_accountability_markdown_func=lambda uid: str(md),
        short_error=lambda scope, exc: f"{scope}:{exc}",
        logger_warning=lambda *a, **k: warnings.append(str(a[0]) if a else "warn"),
    )
    assert ok is False
    assert "monthly_email" in msg
    assert warnings


def test_scanner_scan_prefilter_and_empty_universe(monkeypatch) -> None:
    import core.scanner_service as ss

    universe = tuple(f"S{i:03d}" for i in range(360))

    def fake_snapshot(sym: str):
        return {"symbol": sym, "price": 10.0}

    def fake_ohlcv(sym: str) -> pd.DataFrame:
        idx = int(sym[1:])
        vol = 500_000.0 if idx < 200 else 50_000.0
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=30, freq="D"),
                "open": [1.0] * 30,
                "high": [1.0] * 30,
                "low": [1.0] * 30,
                "close": [1.0] * 30,
                "volume": [vol] * 30,
            }
        )

    monkeypatch.setattr(ss, "load_snapshot_cached", fake_snapshot)
    monkeypatch.setattr(ss, "load_ohlcv_cached", fake_ohlcv)
    monkeypatch.setattr(
        ss,
        "load_strategic_report_cached",
        lambda sym, *a, **k: {
            "valuation": {"price": 10.0, "margin_of_safety_composite_pct": 12.0, "piotroski_score": 7, "industry_subtype_label_vi": "T"},
            "financials": {"revenue_growth_yoy": 8.0},
            "phase": {"phase": "accumulation", "metrics": {"vol_multiple": 1.2}},
        },
    )
    out = ss.scan_potential_stocks.__wrapped__(universe, "growth", 100_000.0)  # type: ignore[attr-defined]
    assert len(out) <= 350
    assert all(int(v) >= 100_000 for v in out["Avg Vol20"].fillna(0))
    assert int(ss.st.session_state["scan_full_universe_count"]) == 360
    assert int(ss.st.session_state["scan_deep_universe_count"]) <= 350

    empty = ss.scan_potential_stocks.__wrapped__(tuple(), "growth", 100_000.0)  # type: ignore[attr-defined]
    assert empty.empty
    assert "Expected Return %" in empty.columns


def test_scanner_scan_error_statuses(monkeypatch) -> None:
    import core.scanner_service as ss

    def fake_snapshot(sym: str):
        if sym == "NONE":
            return None
        return {"symbol": sym, "price": 10.0}

    def fake_report(sym: str, *a, **k):
        if sym == "ERR":
            raise RuntimeError("boom")
        return {
            "valuation": {"price": 10.0, "margin_of_safety_composite_pct": 5.0, "piotroski_score": 5, "industry_subtype_label_vi": "T"},
            "financials": {"revenue_growth_yoy": 1.0},
            "phase": {"phase": "neutral", "metrics": {"vol_multiple": 1.0}},
        }

    monkeypatch.setattr(ss, "load_snapshot_cached", fake_snapshot)
    monkeypatch.setattr(ss, "load_strategic_report_cached", fake_report)
    monkeypatch.setattr(ss, "load_ohlcv_cached", lambda sym: pd.DataFrame())
    out = ss.scan_potential_stocks.__wrapped__(("NONE", "ERR"), "growth", 100_000.0)  # type: ignore[attr-defined]
    statuses = set(out["Trạng thái"].astype(str).tolist())
    assert "Không có snapshot" in statuses
    assert "Lỗi phân tích" in statuses


def test_forecast_dashboards_empty_and_smtp_config_branch(monkeypatch) -> None:
    import core.forecast_accountability_service as fas

    monkeypatch.setattr(fas.forecast_repository, "fetch_resolved_rows_for_dashboard", lambda **k: [])

    def parse_ts(_: str):
        return None

    pf = fas.get_forecast_portfolio_dashboard(conn_factory=lambda: None, parse_ts=parse_ts, user_id="")
    rg = fas.get_forecast_regime_dashboard(conn_factory=lambda: None, user_id="")
    assert int(pf["overall"]["samples"]) == 0
    assert int(rg["bull"]["samples"]) == 0

    ok, msg = fas.send_monthly_accountability_email(
        user_id="u1",
        email_to="a@b.com",
        smtp_host="",
        smtp_user="",
        smtp_password="",
        export_monthly_accountability_markdown_func=lambda uid: "",
        short_error=lambda scope, exc: str(exc),
        logger_warning=lambda *a, **k: None,
    )
    assert ok is False
    assert "Thiếu cấu hình SMTP" in msg


def test_strategy_backtest_phase_trade_and_ma50_skip(monkeypatch) -> None:
    import core.strategy_backtest as sb

    n = 90
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="D"),
            "open": np.linspace(100, 120, n),
            "high": np.linspace(101, 121, n),
            "low": np.linspace(99, 119, n),
            "close": np.linspace(100, 120, n),
            "volume": np.linspace(1e5, 2e5, n),
        }
    )
    bench = pd.Series(df["close"].values, index=df["date"].dt.normalize())

    class _PhaseObj:
        def __init__(self, phase: str) -> None:
            self.phase = phase

    def fake_phase(_df: pd.DataFrame, _ti: pd.DataFrame, i: int):
        if i <= 62:
            return _PhaseObj("accumulation")
        return _PhaseObj("distribution")

    # First run: distribution but still above MA50 => do not exit.
    monkeypatch.setattr(sb, "detect_market_phase_at_index", fake_phase)
    monkeypatch.setattr(
        sb,
        "compute_technical_indicators",
        lambda df: pd.DataFrame({"ma50": df["close"].astype(float) - 5.0, "close": df["close"].astype(float), "volume": df["volume"].astype(float), "vol_ma20": df["volume"].astype(float)}),
    )
    res_hold = sb.run_phase_signal_backtest(df, bench, warmup=60, buy_on_breakout=False, skip_distribution_if_above_ma50=True)
    sides_hold = [str(t.get("side")) for t in res_hold.trades]
    assert "BUY" in sides_hold
    assert "SELL" not in sides_hold

    # Second run: force exit by making MA50 above current price.
    monkeypatch.setattr(
        sb,
        "compute_technical_indicators",
        lambda df: pd.DataFrame({"ma50": df["close"].astype(float) + 5.0, "close": df["close"].astype(float), "volume": df["volume"].astype(float), "vol_ma20": df["volume"].astype(float)}),
    )
    res_exit = sb.run_phase_signal_backtest(df, bench, warmup=60, buy_on_breakout=False, skip_distribution_if_above_ma50=True)
    sides_exit = [str(t.get("side")) for t in res_exit.trades]
    assert "BUY" in sides_exit
    assert "SELL" in sides_exit


def test_strategy_backtest_detect_phase_exception_and_no_skip(monkeypatch) -> None:
    import core.strategy_backtest as sb

    n = 95
    df = pd.DataFrame(
        {
            "date": pd.date_range("2025-01-01", periods=n, freq="D"),
            "open": np.linspace(100, 110, n),
            "high": np.linspace(101, 111, n),
            "low": np.linspace(99, 109, n),
            "close": np.linspace(100, 110, n),
            "volume": np.linspace(1e5, 2e5, n),
        }
    )
    bench = pd.Series(df["close"].values, index=df["date"].dt.normalize())

    class _PhaseObj:
        def __init__(self, phase: str) -> None:
            self.phase = phase

    counter = {"n": 0}

    def fake_phase(_df: pd.DataFrame, _ti: pd.DataFrame, i: int):
        counter["n"] += 1
        if counter["n"] == 1:
            return _PhaseObj("breakout")
        if counter["n"] == 2:
            raise RuntimeError("phase error")
        return _PhaseObj("distribution")

    monkeypatch.setattr(sb, "detect_market_phase_at_index", fake_phase)
    res = sb.run_phase_signal_backtest(df, bench, warmup=60, buy_on_breakout=True, skip_distribution_if_above_ma50=False)
    sides = [str(t.get("side")) for t in res.trades]
    assert "BUY" in sides
    assert "SELL" in sides
    assert "không bán nếu giá>MA50" not in res.note


def test_report_export_formatting_and_html_escape() -> None:
    from core.report_export import _fmt_num, investment_report_html

    assert _fmt_num(None) == "—"
    assert _fmt_num("not-number") == "not-number"
    assert _fmt_num(1234.567, digits=1) == "1,234.6"

    summary = {
        "symbol": "ABC",
        "name": "<script>alert(1)</script>",
        "currency": "VND",
        "data_source": "unit",
        "price": None,
        "intrinsic_value_graham": 100000,
        "target_price_forward_pe": 100000,
        "target_price_pb_fair": 100000,
        "composite_target_price": 100000,
        "margin_of_safety_pct": None,
        "margin_of_safety_composite_pct": 10.0,
        "piotroski_score": 6,
        "valuation_transparency_line": "**_unsafe_**",
        "advice": "<b>advice</b>",
    }
    html_out = investment_report_html(summary)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_out
    assert "&lt;b&gt;advice&lt;/b&gt;" in html_out
    assert "Nguồn" in html_out


def test_forecast_dashboard_handles_invalid_timestamps_and_missing_fields(monkeypatch) -> None:
    import core.forecast_accountability_service as fas

    rows = [
        {
            "created_at": "invalid-ts",
            "direction_hit": None,
            "abs_error_pct": None,
            "expected_return_pct": None,
            "realized_return_pct": None,
        },
        {
            "created_at": "2026-01-01T00:00:00+00:00",
            # intentionally missing direction_hit/abs_error_pct
            "expected_return_pct": 2.0,
            "realized_return_pct": 5.0,
        },
    ]
    monkeypatch.setattr(fas.forecast_repository, "fetch_resolved_rows_for_dashboard", lambda **k: rows)

    def parse_ts(value: str):
        if value.startswith("2026-01-01"):
            return datetime.fromisoformat(value)
        return None

    dash = fas.get_forecast_portfolio_dashboard(conn_factory=lambda: None, parse_ts=parse_ts, user_id="u1", lookback_days=365)
    assert int(dash["overall"]["samples"]) == 1
    # weekly/monthly may exclude invalid-ts row, but must still be stable numbers
    assert "samples" in dash["weekly"]
    assert "samples" in dash["monthly"]
    assert dash["overall"]["hit_rate_pct"] is not None


def test_forecast_regime_threshold_boundaries(monkeypatch) -> None:
    import core.forecast_accountability_service as fas

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {"created_at": now, "direction_hit": 1, "abs_error_pct": 2.0, "expected_return_pct": 1.0, "realized_return_pct": 5.0},
        {"created_at": now, "direction_hit": 0, "abs_error_pct": 6.0, "expected_return_pct": 2.0, "realized_return_pct": -5.0},
        {"created_at": now, "direction_hit": 1, "abs_error_pct": 3.0, "expected_return_pct": 2.0, "realized_return_pct": 0.0},
    ]
    monkeypatch.setattr(fas.forecast_repository, "fetch_resolved_rows_for_dashboard", lambda **k: rows)
    out = fas.get_forecast_regime_dashboard(conn_factory=lambda: None, user_id="u1", lookback_days=180)
    assert int(out["bull"]["samples"]) == 1
    assert int(out["bear"]["samples"]) == 1
    assert int(out["sideway"]["samples"]) == 1


def test_send_monthly_accountability_email_success(monkeypatch, tmp_path: Path) -> None:
    import core.forecast_accountability_service as fas

    md_path = tmp_path / "monthly.md"
    md_path.write_text("# report\n", encoding="utf-8")
    sent: list[dict[str, str]] = []

    class GoodSMTP:
        def __init__(self, host: str, port: int, timeout: int = 10) -> None:
            _ = (host, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            _ = (user, password)

        def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
            sent.append({"from": from_addr, "to": ",".join(to_addrs), "msg": msg})

    monkeypatch.setattr(fas.smtplib, "SMTP", GoodSMTP)
    ok, out = fas.send_monthly_accountability_email(
        user_id="u1",
        email_to="to@example.com",
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_user="from@example.com",
        smtp_password="secret",
        smtp_from="noreply@example.com",
        export_monthly_accountability_markdown_func=lambda uid: str(md_path),
        short_error=lambda scope, exc: f"{scope}:{exc}",
        logger_warning=lambda *a, **k: None,
    )
    assert ok is True
    assert out.endswith("monthly.md")
    assert sent and "to@example.com" in sent[0]["to"]


def test_scanner_load_board_without_status_column_and_plan_normalization(monkeypatch) -> None:
    import core.scanner_service as ss

    monkeypatch.setattr(ss, "list_universe_symbols", lambda limit=30, offset=0: ["AAA", "BBB", "CCC"])
    # No "Trạng thái" column -> branch should use df.copy()
    fake_scan = pd.DataFrame(
        [
            {"Mã": "AAA", "Khuyến nghị": "WATCH", "MOS%": 8.0, "Expected Return %": 10.0, "Risk % (ước tính)": 8.0},
            {"Mã": "BBB", "Khuyến nghị": "BUY", "MOS%": 5.0, "Expected Return %": 9.0, "Risk % (ước tính)": 7.0},
            {"Mã": "CCC", "Khuyến nghị": "HOLD", "MOS%": 6.0, "Expected Return %": 9.5, "Risk % (ước tính)": 9.0},
        ]
    )
    monkeypatch.setattr(ss, "scan_potential_stocks", lambda *a, **k: fake_scan)
    out = ss.load_autopilot_board.__wrapped__("growth", 30, 100_000.0, _rotation_day=1)  # type: ignore[attr-defined]
    assert not out.empty
    # BUY should rank above WATCH even with slightly lower expected return
    assert str(out.iloc[0]["Mã"]) == "BBB"

    df = pd.DataFrame(
        [
            {
                "Mã": "AAA",
                "Hành động": "BUY",
                "Giá hiện tại": 10.0,
                "Giá trị nội tại": 12.0,
                "Biên an toàn %": 20.0,
                "Giá vào": 9.8,
                "SL": 9.0,
                "TP": 12.0,
                "Tỷ trọng %": 10.0,
            }
        ]
    )
    expert_df = ss.simple_view_for_plan(df, "  ExPeRt ")
    assert "Giá vào" in expert_df.columns


def test_scanner_simple_profit_daily_empty_branches(monkeypatch) -> None:
    import core.scanner_service as ss

    # Snapshot always missing -> all builders return empty schema
    monkeypatch.setattr(ss, "load_snapshot_cached", lambda sym: None)
    simple = ss.build_autopilot_simple_view.__wrapped__(("AAA",), "growth", 100_000_000.0, True, False)  # type: ignore[attr-defined]
    profit = ss.build_profit_focus_board.__wrapped__(("AAA",), "growth", 100_000_000.0, True, False)  # type: ignore[attr-defined]
    daily = ss.build_daily_action_list.__wrapped__(("AAA",), "growth", 100_000_000.0, tuple(), True, False)  # type: ignore[attr-defined]
    assert simple.empty and "Hành động" in simple.columns
    assert profit.empty and "Điểm ưu tiên" in profit.columns
    assert daily.empty and "Hành động hôm nay" in daily.columns


def test_report_export_helper_normalizers() -> None:
    from core.report_export import _as_dict, _as_list

    assert _as_dict({"a": 1}) == {"a": 1}
    assert _as_dict(["x"]) == {}
    assert _as_list([1, 2]) == [1, 2]
    assert _as_list({"x": 1}) == []
