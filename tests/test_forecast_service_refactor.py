from __future__ import annotations

import pandas as pd


def test_forecast_accuracy_and_benchmark_refactor(tmp_path, monkeypatch) -> None:
    import core.ohlcv_store as ohlcv_store
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    monkeypatch.setattr(ohlcv_store, "DB_PATH", tmp_path / "ohlcv_store.db")
    monkeypatch.setattr(pl, "fetch_financial_snapshot", lambda _sym: {"price": 999.0})
    # Tránh gọi mạng khi settle backfill thiếu bar (đã seed sẵn).
    monkeypatch.setattr(
        "scrapers.portal.fetch_ohlcv_history",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no network in test")),
    )
    pl._init_db()

    uid = "forecast_user_1"
    report = {"probabilistic_forecast": {"expected_price": 120.0, "expected_return_pct": 20.0, "horizon_days": 1}, "valuation": {"price": 100.0}}
    pl.record_forecast_snapshot(uid, "FPT", report)

    with pl._conn() as c:
        c.execute("UPDATE forecast_records SET created_at='2020-01-01T00:00:00+00:00' WHERE user_id=?", (uid,))

    # Due date = 2020-01-02 — seed close lịch sử (không dùng snapshot hôm nay).
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

    bench = pl.get_forecast_benchmark_by_horizon(uid, "FPT", horizons=(1,), lookback_days=3650)
    assert len(bench) == 1
    assert int(bench[0].get("samples") or 0) >= 1


def test_forecast_drift_and_leaderboard_refactor(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "forecast_user_2"
    with pl._conn() as c:
        for i in range(35):
            c.execute(
                """
                INSERT INTO forecast_records(
                    user_id, symbol, created_at, horizon_days, base_price, expected_price, expected_return_pct,
                    realized_price, realized_return_pct, abs_error_pct, direction_hit, status
                ) VALUES (?, ?, ?, 30, 100, 110, 10, 108, 8, ?, ?, 'resolved')
                """,
                (uid, "HPG", f"2024-01-{(i % 28) + 1:02d}T00:00:00+00:00", 2.0 + (i % 3), 1 if i % 2 == 0 else 0),
            )

    lb = pl.get_forecast_leaderboard(uid, limit=10, lookback_days=3650)
    assert len(lb) >= 1

    drift = pl.get_forecast_drift_signal(uid, "HPG", recent_n=12, baseline_n=20)
    assert "status" in drift
    streak = pl.get_forecast_drift_streak(uid, "HPG", checks=3)
    assert "drift_down_streak" in streak
