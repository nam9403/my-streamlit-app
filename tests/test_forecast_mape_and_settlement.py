"""
Unit tests: MAPE chuẩn + nghiệm thu forecast theo giá đóng cửa đúng due date.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from core.forecast_metrics import (
    mape_point_pct,
    mape_safety_should_downgrade,
    mean_mape_pct,
    settle_realized_price_on_due_date,
)
from core.forecast_service import refresh_matured_forecasts


def test_mape_point_pct_standard_formula() -> None:
    # |100 - 120| / 100 * 100 = 20
    assert mape_point_pct(actual_price=100.0, forecast_price=120.0) == 20.0
    # |110 - 100| / 110 * 100 ≈ 9.0909
    assert abs(mape_point_pct(actual_price=110.0, forecast_price=100.0) - (10.0 / 110.0 * 100.0)) < 1e-9
    assert mape_point_pct(actual_price=0.0, forecast_price=100.0) is None


def test_mean_mape_pct() -> None:
    assert mean_mape_pct([10.0, 20.0, 30.0]) == 20.0
    assert mean_mape_pct([]) is None


def test_mape_safety_should_downgrade() -> None:
    assert mape_safety_should_downgrade(mape_pct=15.0, samples=8) == "WATCH"
    assert mape_safety_should_downgrade(mape_pct=10.0, samples=8) == "HOLD"
    assert mape_safety_should_downgrade(mape_pct=5.0, samples=8) is None
    assert mape_safety_should_downgrade(mape_pct=20.0, samples=2) is None  # insufficient samples


def test_settle_realized_price_uses_due_date_not_today() -> None:
    closes = {
        "2024-06-10": 100.0,
        "2024-06-11": 105.0,
        "2024-06-12": 108.0,
    }

    def fake_close(symbol: str, as_of: str):
        # trả phiên <= as_of gần nhất
        keys = sorted(k for k in closes if k <= as_of[:10])
        if not keys:
            return None, None
        k = keys[-1]
        return closes[k], k

    due = datetime(2024, 6, 11, 15, 0, tzinfo=timezone.utc)
    px, as_of = settle_realized_price_on_due_date(
        symbol="FPT",
        due_at=due,
        get_close_on_or_before=fake_close,
    )
    assert px == 105.0
    assert as_of == "2024-06-11"


def test_refresh_matured_forecasts_no_lookahead(tmp_path, monkeypatch) -> None:
    import core.ohlcv_store as ohlcv_store
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    monkeypatch.setattr(ohlcv_store, "DB_PATH", tmp_path / "ohlcv_store.db")
    # Snapshot hôm nay cố tình khác giá due date — nếu look-ahead sẽ settle sai.
    monkeypatch.setattr(pl, "fetch_financial_snapshot", lambda _sym: {"price": 999.0})
    pl._init_db()

    uid = "mape_user"
    pl.record_forecast_snapshot(
        uid,
        "FPT",
        {
            "probabilistic_forecast": {"expected_price": 120.0, "expected_return_pct": 20.0, "horizon_days": 1},
            "valuation": {"price": 100.0},
        },
    )
    with pl._conn() as c:
        c.execute("UPDATE forecast_records SET created_at='2024-01-01T00:00:00+00:00' WHERE user_id=?", (uid,))

    # Due date = 2024-01-02; seed close = 110 (không phải 999).
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp("2024-01-02")],
            "open": [110.0],
            "high": [111.0],
            "low": [109.0],
            "close": [110.0],
            "volume": [1_000_000.0],
        }
    )
    ohlcv_store.upsert_ohlcv("FPT", df, source="test")

    from core.forecast_metrics import settle_realized_price_on_due_date

    def _settle(*, symbol: str, due_at):
        return settle_realized_price_on_due_date(
            symbol=symbol,
            due_at=due_at,
            get_close_on_or_before=ohlcv_store.get_close_on_or_before,
        )

    refresh_matured_forecasts(
        conn_factory=pl._conn,
        parse_ts=pl._parse_ts,
        fetch_financial_snapshot_func=lambda s: {"price": 999.0},
        user_id=uid,
        symbol="FPT",
        settle_realized_price_func=_settle,
    )

    with pl._conn() as c:
        row = c.execute(
            "SELECT status, realized_price, abs_error_pct FROM forecast_records WHERE user_id=?",
            (uid,),
        ).fetchone()
    assert str(row["status"]) == "resolved"
    assert float(row["realized_price"]) == 110.0
    # MAPE = |110-120|/110*100 ≈ 9.0909
    assert abs(float(row["abs_error_pct"]) - (10.0 / 110.0 * 100.0)) < 1e-6


def test_apply_mape_safety_gate_downgrades_buy() -> None:
    from core.analysis_forecast_service import apply_drift_guardrails

    report = {"final_action": "BUY", "risk_plan": {"max_position_pct": 20.0}}
    out, _mode = apply_drift_guardrails(
        "u1",
        "FPT",
        report,
        "balanced",
        get_forecast_drift_signal=lambda *a, **k: {"status": "stable"},
        get_forecast_drift_streak=lambda *a, **k: {"drift_down_streak": 0},
        get_forecast_accuracy_dashboard=lambda *a, **k: {"resolved": 10, "mape_pct": 16.0},
    )
    assert out["final_action"] == "WATCH"
    assert out["mape_safety_gate"]["applied"] is True
    assert out["mape_safety_gate"]["to_action"] == "WATCH"
