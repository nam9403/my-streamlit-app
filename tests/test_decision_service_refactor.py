from __future__ import annotations


def test_add_list_and_scorecard_refactor(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "decision_user_1"
    ok, _ = pl.add_decision(uid, "FPT", "BUY", 100.0, 95.0, 120.0, "good setup", 30)
    assert ok is True
    rows = pl.list_decisions(uid, limit=10)
    assert len(rows) >= 1
    score = pl.decision_scorecard(uid, limit=10)
    assert "discipline_score" in score


def test_postmortem_and_monthly_value_report_refactor(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    uid = "decision_user_2"
    pl.add_decision(uid, "HPG", "BUY", 20.0, 18.0, 24.0, "swing", 7)

    # Force a matured age by backdating.
    with pl._conn() as c:
        c.execute(
            "UPDATE decisions SET created_at='2020-01-01T00:00:00+00:00' WHERE user_id=?",
            (uid,),
        )

    pm = pl.postmortem_report(uid, days=1, limit=20)
    assert isinstance(pm, list)
    assert len(pm) >= 1

    mv = pl.monthly_value_report(uid)
    assert "value_summary" in mv
