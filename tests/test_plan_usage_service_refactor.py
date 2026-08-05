from __future__ import annotations


def test_plan_usage_and_feature_gate(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "plan_usage_user"
    pl.set_user_plan(uid, "free")
    assert pl.get_user_plan(uid) == "free"

    # Free plan has analysis/day cap = 30.
    pl.record_usage(uid, "analysis", 30)
    ok, msg = pl.can_use_feature(uid, "analysis", requested=1)
    assert ok is False
    assert "Vượt giới hạn" in msg


def test_scan_and_alert_gates_by_plan(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "scan_alert_user"
    pl.set_user_plan(uid, "free")
    ok_scan, _ = pl.can_use_feature(uid, "scan", requested=25)
    assert ok_scan is False

    # Free plan allows up to 3 alerts.
    for i in range(3):
        pl.add_alert(uid, "FPT", "price_above", 100.0 + i)
    ok_alert, msg_alert = pl.can_use_feature(uid, "alert", requested=1)
    assert ok_alert is False
    assert "giới hạn cảnh báo" in msg_alert
