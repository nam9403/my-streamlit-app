from __future__ import annotations

import base64

import pytest


def test_require_app_secret_key_blocks_local_fallback(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    monkeypatch.delenv("II_APP_SECRET_KEY", raising=False)
    monkeypatch.setenv("II_REQUIRE_APP_SECRET_KEY", "1")

    with pytest.raises(RuntimeError, match="II_APP_SECRET_KEY is required"):
        pl.save_secret("u1", "telegram_token", "abc")


def test_strict_mode_disables_legacy_secret_decrypt(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    monkeypatch.setenv("II_REQUIRE_APP_SECRET_KEY", "1")
    monkeypatch.setenv("II_APP_SECRET_KEY", "vBUjKIQm9RWv6fbf_6A6uDPDVXnTUu18rqzSaP6L5qs=")

    uid = "legacy_user"
    name = "api_token"
    plain = "legacy-secret"
    encoded = base64.b64encode(pl._xor_crypt(plain.encode("utf-8"), pl._secret_key(uid))).decode("ascii")
    pl._save_secrets({uid: {name: encoded}})

    assert pl.load_secret(uid, name, default="fallback") == "fallback"
