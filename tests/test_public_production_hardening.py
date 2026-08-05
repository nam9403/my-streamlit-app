from __future__ import annotations

from pathlib import Path

import pytest


def test_initialize_database_connection_is_explicit(tmp_path: Path, monkeypatch) -> None:
    """DB files must only appear after explicit initialize_database_connection()."""
    import core.product_layer as pl

    db_path = tmp_path / "explicit_bootstrap.db"
    monkeypatch.setattr(pl, "DB_PATH", db_path)
    pl._DB_INITIALIZED = False

    assert not db_path.exists()
    assert pl._DB_INITIALIZED is False

    pl.initialize_database_connection()
    assert pl._DB_INITIALIZED is True
    assert db_path.exists()


def test_init_sentry_noop_without_dsn(monkeypatch) -> None:
    from core import observability as obs

    monkeypatch.delenv("II_SENTRY_DSN", raising=False)
    obs._SENTRY_INITIALIZED = False
    assert obs.init_sentry("test") is False
    assert obs._SENTRY_INITIALIZED is False


def test_require_feature_raises_insufficient_quota(tmp_path: Path, monkeypatch) -> None:
    import core.product_layer as pl
    from core.exceptions import InsufficientQuotaError

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "quota.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(pl, "APP_SECRET_PATH", tmp_path / ".app_secret.key")
    pl._DB_INITIALIZED = False
    pl.initialize_database_connection(force=True)

    uid = "quota_user"
    pl.set_user_plan(uid, "free")
    pl.record_usage(uid, "analysis", 30)

    with pytest.raises(InsufficientQuotaError, match="Vượt giới hạn"):
        pl.require_feature(uid, "analysis", requested=1)


def test_alembic_baseline_revision_file_exists() -> None:
    root = Path(__file__).resolve().parents[1]
    baseline = root / "alembic" / "versions" / "0001_baseline_postgres.py"
    assert baseline.is_file()
    text = baseline.read_text(encoding="utf-8")
    assert 'revision: str = "0001_baseline"' in text
    assert "ii_async_jobs" in text
