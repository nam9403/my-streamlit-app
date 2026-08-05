from __future__ import annotations


def test_upsert_and_get_recent_cx_scores(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    pl.upsert_daily_cx_score("u1", 92, "Elite")
    pl.upsert_daily_cx_score("u1", 88, "Good")
    rows = pl.get_recent_cx_scores("u1", days=14)

    assert len(rows) == 1
    assert int(rows[0]["score"]) == 88
    assert str(rows[0]["band"]) == "Good"


def test_get_admin_cx_kpi(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    pl.upsert_daily_cx_score("u1", 90, "Elite")
    pl.upsert_daily_cx_score("u2", 70, "Good")
    out = pl.get_admin_cx_kpi(days=14)

    assert int(out["samples"]) == 2
    assert float(out["avg_score"]) >= 79.9
    assert any(str(x["band"]) == "Elite" for x in out["bands"])
