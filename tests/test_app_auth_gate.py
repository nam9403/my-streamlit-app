from __future__ import annotations

import pytest

from core.app_auth_gate import (
    SessionAuthorizationError,
    authenticated_mutation,
    authenticated_user_mutation,
    clear_authenticated_session,
    is_authenticated_session,
    require_authenticated_session,
    start_authenticated_session,
)


def test_start_session_binds_user_and_random_token() -> None:
    first: dict[str, object] = {}
    second: dict[str, object] = {}

    token_1 = start_authenticated_session("user-1", first)
    token_2 = start_authenticated_session("user-1", second)

    assert first["auth_ok"] is True
    assert first["user_id"] == "user-1"
    assert first["session_token"] == token_1
    assert len(token_1) >= 32
    assert token_1 != token_2
    assert is_authenticated_session("user-1", first)


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"auth_ok": True, "user_id": "u1"},
        {"auth_ok": True, "session_token": "x" * 43},
        {"auth_ok": False, "user_id": "u1", "session_token": "x" * 43},
        {"auth_ok": True, "user_id": "u1", "session_token": "short"},
    ],
)
def test_incomplete_session_is_rejected(state: dict[str, object]) -> None:
    assert not is_authenticated_session("u1", state)
    with pytest.raises(SessionAuthorizationError, match="Từ chối thao tác"):
        require_authenticated_session("u1", state)


def test_session_is_strictly_bound_to_requested_user() -> None:
    state: dict[str, object] = {}
    start_authenticated_session("u1", state)

    assert is_authenticated_session("u1", state)
    assert not is_authenticated_session("u2", state)
    with pytest.raises(SessionAuthorizationError):
        require_authenticated_session("u2", state)


def test_authenticated_mutation_denies_before_calling_body() -> None:
    state: dict[str, object] = {}
    calls: list[str] = []

    def mutation(value: str) -> str:
        calls.append(value)
        return value

    guarded = authenticated_mutation("u1", mutation, state)
    with pytest.raises(SessionAuthorizationError):
        guarded("must-not-run")
    assert calls == []

    start_authenticated_session("u1", state)
    assert guarded("allowed") == "allowed"
    assert calls == ["allowed"]


def test_authenticated_user_mutation_rejects_cross_user_target() -> None:
    state: dict[str, object] = {}
    start_authenticated_session("u1", state)
    calls: list[str] = []

    def mutation(user_id: str) -> None:
        calls.append(user_id)

    guarded = authenticated_user_mutation("u1", mutation, state)
    guarded("u1")
    with pytest.raises(SessionAuthorizationError, match="không khớp"):
        guarded("u2")

    assert calls == ["u1"]


def test_clear_session_removes_identity_and_token() -> None:
    state: dict[str, object] = {}
    start_authenticated_session("u1", state)

    clear_authenticated_session(state)

    assert state == {"auth_ok": False}
