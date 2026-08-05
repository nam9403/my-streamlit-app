from __future__ import annotations


def test_open_close_and_realized_performance(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "trade_user_1"
    ok_open, _ = pl.open_trade(uid, "FPT", 10, 100.0, entry_fee=1.0)
    assert ok_open is True
    trades = pl.list_trades(uid, limit=20)
    assert len(trades) >= 1
    tid = int(trades[0]["ID"])

    ok_close, _ = pl.close_trade(uid, tid, 110.0, exit_fee=1.0)
    assert ok_close is True

    perf = pl.realized_performance(uid, days=30)
    assert int(perf.get("closed_trades") or 0) >= 1
    assert float(perf.get("realized_pnl_total") or 0.0) > 0.0


def test_execution_vs_plan_report_with_decision_link(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "trade_user_2"
    ok_dec, _ = pl.add_decision(uid, "HPG", "BUY", 20.0, 18.0, 26.0, "thesis")
    assert ok_dec is True
    dec_id = int(pl.list_decisions(uid, limit=5)[0]["id"])
    ok_open, _ = pl.open_trade(uid, "HPG", 100, 20.0, decision_id=dec_id)
    assert ok_open is True
    trow = pl.list_trades(uid, limit=5)[0]
    ok_close, _ = pl.close_trade(uid, int(trow["ID"]), 25.0)
    assert ok_close is True

    rep = pl.execution_vs_plan_report(uid, limit=20)
    assert len(rep) >= 1
    assert "Entry Slippage %" in rep[0]
