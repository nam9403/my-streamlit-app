from __future__ import annotations


def test_register_verify_and_has_auth_user(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    ok_reg, _ = pl.register_user_pin("u_auth_1", "123456")
    assert ok_reg is True
    assert pl.has_auth_user("u_auth_1") is True
    assert pl.verify_user_pin("u_auth_1", "123456") is True
    assert pl.verify_user_pin("u_auth_1", "000000") is False


def test_legacy_hash_upgrade_on_successful_verify(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "app_state.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._init_db()

    legacy_hash = pl._pin_hash_legacy("654321")
    with pl._conn() as c:
        now = pl._utcnow_iso()
        c.execute(
            "INSERT INTO auth_users(user_id, pin_hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
            ("u_auth_legacy", legacy_hash, now, now),
        )
    assert pl.verify_user_pin("u_auth_legacy", "654321") is True

    with pl._conn() as c:
        row = c.execute("SELECT pin_hash FROM auth_users WHERE user_id=?", ("u_auth_legacy",)).fetchone()
    assert str(row["pin_hash"]).startswith(f"{pl.PIN_HASH_PREFIX}$")
