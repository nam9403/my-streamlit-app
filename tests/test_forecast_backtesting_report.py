from __future__ import annotations


def test_forecast_backtesting_report_has_win_loss(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "bt_report_user"
    with pl._conn() as c:
        for i in range(12):
            exp_ret = 8.0 if i < 10 else -4.0
            real_ret = 6.0 if i % 3 != 0 else -2.0
            direction_hit = 1 if (exp_ret >= 0 and real_ret >= 0) or (exp_ret < 0 and real_ret < 0) else 0
            c.execute(
                """
                INSERT INTO forecast_records(
                    user_id, symbol, created_at, horizon_days, base_price, expected_price, expected_return_pct,
                    realized_price, realized_return_pct, abs_error_pct, direction_hit, status
                ) VALUES (?, ?, ?, ?, 100, 108, ?, 106, ?, 3.2, ?, 'resolved')
                """,
                (
                    uid,
                    "FPT" if i < 6 else "HPG",
                    f"2026-04-{(i % 28) + 1:02d}T00:00:00+00:00",
                    90 if i % 2 == 0 else 60,
                    exp_ret,
                    real_ret,
                    direction_hit,
                ),
            )

    rep = pl.get_forecast_backtesting_report(uid, lookback_days=3650)
    assert int(rep.get("samples") or 0) >= 10
    assert int(rep.get("predicted_up_samples") or 0) >= 1
    assert rep.get("win_rate_pct") is not None
    assert isinstance(rep.get("by_horizon"), list)
