from __future__ import annotations

from pathlib import Path

import pandas as pd


def test_refactor_smoke_end_to_end_flow(tmp_path, monkeypatch) -> None:
    import core.ohlcv_store as ohlcv_store
    import core.product_layer as pl

    monkeypatch.setenv("II_REQUIRE_APP_SECRET_KEY", "0")
    monkeypatch.delenv("II_APP_SECRET_KEY", raising=False)
    monkeypatch.setattr(pl, "ROOT", tmp_path)
    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    monkeypatch.setattr(ohlcv_store, "DB_PATH", tmp_path / "ohlcv_store.db")
    monkeypatch.setattr(pl, "fetch_financial_snapshot", lambda _sym: {"price": 999.0})
    pl._init_db()

    uid = "smoke_user"

    # Plan/usage + analytics
    pl.set_user_plan(uid, "free")
    assert pl.get_user_plan(uid) == "free"
    pl.record_usage(uid, "analysis", 1)
    ok_feature, _ = pl.can_use_feature(uid, "analysis", requested=1)
    assert ok_feature is True
    pl.log_event(uid, "analysis_completed", {"ticker": "FPT"})
    assert int(pl.get_kpi_dashboard(uid, days=30).get("events_total") or 0) >= 1

    # Decision + trade journal
    ok_dec, _ = pl.add_decision(uid, "FPT", "BUY", 100.0, 95.0, 120.0, "smoke thesis", 30)
    assert ok_dec is True
    dec_id = int(pl.list_decisions(uid, limit=1)[0]["id"])
    ok_open, _ = pl.open_trade(uid, "FPT", 10, 100.0, decision_id=dec_id)
    assert ok_open is True
    tid = int(pl.list_trades(uid, limit=1)[0]["ID"])
    ok_close, _ = pl.close_trade(uid, tid, 110.0)
    assert ok_close is True
    assert int(pl.realized_performance(uid, days=30).get("closed_trades") or 0) >= 1

    # Alerts + forecast
    pl.add_alert(uid, "FPT", "price_above", 100.0, "smoke alert")
    fired = pl.evaluate_alerts(uid)
    assert len(fired) >= 1

    report = {
        "probabilistic_forecast": {"expected_price": 120.0, "expected_return_pct": 20.0, "horizon_days": 1},
        "valuation": {"price": 100.0},
    }
    pl.record_forecast_snapshot(uid, "FPT", report)
    with pl._conn() as c:
        c.execute("UPDATE forecast_records SET created_at='2020-01-01T00:00:00+00:00' WHERE user_id=?", (uid,))
    # Seed close đúng due date (2020-01-02) — anti look-ahead, không dùng snapshot 999.
    ohlcv_store.upsert_ohlcv(
        "FPT",
        pd.DataFrame(
            {
                "date": [pd.Timestamp("2020-01-02")],
                "open": [110.0],
                "high": [111.0],
                "low": [109.0],
                "close": [110.0],
                "volume": [1_000_000.0],
            }
        ),
        source="test",
    )
    acc = pl.get_forecast_accuracy_dashboard(uid, "FPT", lookback_days=3650)
    assert int(acc.get("records") or 0) >= 1
    assert int(acc.get("resolved") or 0) >= 1

    # Accountability exports
    out_health = Path(pl.export_forecast_health_report(uid))
    out_model = Path(pl.export_model_accountability_report(uid))
    out_md = Path(pl.export_monthly_accountability_markdown(uid))
    assert out_health.exists()
    assert out_model.exists()
    assert out_md.exists()

    # Secrets roundtrip
    pl.save_secret(uid, "smtp_user", "demo_user")
    assert pl.load_secret(uid, "smtp_user", default="") == "demo_user"
