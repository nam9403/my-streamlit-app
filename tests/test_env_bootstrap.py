"""env_bootstrap: nạp .env + strict validation cho production."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import env_bootstrap

_VALID_FERNET_KEY = "vBUjKIQm9RWv6fbf_6A6uDPDVXnTUu18rqzSaP6L5qs="


def test_dev_mode_without_secret_does_not_raise() -> None:
    env = {"II_ENV": "dev"}
    env_bootstrap.validate_required_env(env)


def test_prod_missing_secret_raises_clear_error() -> None:
    env = {"II_ENV": "prod", "GROQ_API_KEYS": "gsk_x"}
    with pytest.raises(env_bootstrap.MissingEnvConfigError, match="II_APP_SECRET_KEY"):
        env_bootstrap.validate_required_env(env)


def test_prod_invalid_fernet_format_raises() -> None:
    env = {"II_ENV": "prod", "II_APP_SECRET_KEY": "khong-phai-fernet", "GROQ_API_KEYS": "gsk_x"}
    with pytest.raises(env_bootstrap.MissingEnvConfigError, match="Fernet"):
        env_bootstrap.validate_required_env(env)


def test_prod_missing_all_llm_keys_raises() -> None:
    env = {"II_ENV": "prod", "II_APP_SECRET_KEY": _VALID_FERNET_KEY}
    with pytest.raises(env_bootstrap.MissingEnvConfigError, match="LLM"):
        env_bootstrap.validate_required_env(env)


def test_prod_llm_requirement_can_be_opted_out() -> None:
    env = {
        "II_ENV": "prod",
        "II_APP_SECRET_KEY": _VALID_FERNET_KEY,
        "II_REQUIRE_LLM_KEYS": "0",
    }
    env_bootstrap.validate_required_env(env)


def test_prod_with_secret_and_one_llm_key_passes() -> None:
    env = {
        "II_ENV": "prod",
        "II_APP_SECRET_KEY": _VALID_FERNET_KEY,
        "OPENAI_API_KEY": "sk-test",
    }
    env_bootstrap.validate_required_env(env)


def test_require_flag_outside_prod_also_enforces_secret() -> None:
    env = {"II_ENV": "dev", "II_REQUIRE_APP_SECRET_KEY": "1"}
    with pytest.raises(env_bootstrap.MissingEnvConfigError, match="II_APP_SECRET_KEY"):
        env_bootstrap.validate_required_env(env)


def test_load_env_file_sets_new_vars_but_never_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "II_TEST_DOTENV_NEW=from_file\nII_TEST_DOTENV_EXISTING=from_file\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("II_TEST_DOTENV_NEW", raising=False)
    monkeypatch.setenv("II_TEST_DOTENV_EXISTING", "from_process")

    assert env_bootstrap.load_env_file(dotenv) is True
    try:
        assert os.environ.get("II_TEST_DOTENV_NEW") == "from_file"
        assert os.environ.get("II_TEST_DOTENV_EXISTING") == "from_process"
    finally:
        os.environ.pop("II_TEST_DOTENV_NEW", None)


def test_load_env_file_missing_file_returns_false(tmp_path: Path) -> None:
    assert env_bootstrap.load_env_file(tmp_path / "khong_ton_tai.env") is False
