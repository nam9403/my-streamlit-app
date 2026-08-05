from __future__ import annotations

from types import SimpleNamespace

from core.app_account_helpers import is_auth_ready, normalize_notify_channels, resolve_plan_index


def test_is_auth_ready_rejects_guest_without_auth_account() -> None:
    assert not is_auth_ready(has_auth_user=False, auth_ok_in_session=False)


def test_is_auth_ready_for_existing_user_requires_session_auth() -> None:
    assert not is_auth_ready(has_auth_user=True, auth_ok_in_session=False)
    assert is_auth_ready(has_auth_user=True, auth_ok_in_session=True)


def test_resolve_plan_index_falls_back_for_unknown_plan() -> None:
    options = ["Free", "Pro", "Expert"]
    assert resolve_plan_index("pro", options) == 1
    assert resolve_plan_index("unknown", options) == 0


def test_normalize_notify_channels_defaults_smtp_port() -> None:
    cfg = SimpleNamespace(tg_bot="bot", smtp_port=None, smtp_user="user@example.com")
    channels = normalize_notify_channels(cfg)
    assert channels["tg_bot"] == "bot"
    assert channels["smtp_port"] == 587
    assert channels["smtp_user"] == "user@example.com"

