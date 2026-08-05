"""
Authentication gate helpers for app flows.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

import streamlit as st

_F = TypeVar("_F", bound=Callable[..., Any])
_SESSION_TOKEN_MIN_LENGTH = 32


class SessionAuthorizationError(PermissionError):
    """Phiên không được phép thực hiện thao tác đọc/ghi cho user yêu cầu."""


def _normalized_user_id(user_id: object) -> str:
    return str(user_id or "").strip()


def clear_authenticated_session(session_state: Any | None = None) -> None:
    """Xóa toàn bộ identity của phiên; dùng khi logout, đổi user hoặc login lỗi."""
    state = st.session_state if session_state is None else session_state
    state["auth_ok"] = False
    state.pop("user_id", None)
    state.pop("session_token", None)


def start_authenticated_session(user_id: str, session_state: Any | None = None) -> str:
    """Gắn phiên với đúng user và token ngẫu nhiên mật mã sau khi PIN hợp lệ."""
    uid = _normalized_user_id(user_id)
    if not uid:
        raise ValueError("user_id must not be empty when starting an authenticated session.")
    state = st.session_state if session_state is None else session_state
    token = secrets.token_urlsafe(32)
    state["auth_ok"] = True
    state["user_id"] = uid
    state["session_token"] = token
    return token


def is_authenticated_session(user_id: str, session_state: Any | None = None) -> bool:
    """True chỉ khi auth flag, user_id ràng buộc và token ngẫu nhiên đều hợp lệ."""
    state = st.session_state if session_state is None else session_state
    requested_uid = _normalized_user_id(user_id)
    session_uid = _normalized_user_id(state.get("user_id"))
    token = str(state.get("session_token") or "").strip()
    return bool(
        requested_uid
        and session_uid
        and bool(state.get("auth_ok", False))
        and secrets.compare_digest(session_uid, requested_uid)
        and len(token) >= _SESSION_TOKEN_MIN_LENGTH
    )


def require_authenticated_session(user_id: str, session_state: Any | None = None) -> str:
    """Trả token hợp lệ hoặc raise trước khi logic mutation được gọi."""
    state = st.session_state if session_state is None else session_state
    if not is_authenticated_session(user_id, state):
        clear_authenticated_session(state)
        raise SessionAuthorizationError(
            "Từ chối thao tác: phiên đăng nhập không hợp lệ hoặc không thuộc user_id được yêu cầu."
        )
    return str(state["session_token"])


def authenticated_mutation(user_id: str, func: _F, session_state: Any | None = None) -> _F:
    """Bọc callback ghi dữ liệu; gate chạy trước thân hàm nên mutation không thể lọt qua."""

    @wraps(func)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        require_authenticated_session(user_id, session_state)
        return func(*args, **kwargs)

    return guarded  # type: ignore[return-value]


def authenticated_user_mutation(user_id: str, func: _F, session_state: Any | None = None) -> _F:
    """
    Bọc mutation có `user_id` là đối số đầu tiên và chống confused-deputy.

    Ngoài kiểm tra phiên, target user mà callback nhận bắt buộc phải trùng với
    identity của phiên; không thể dùng phiên u1 để gọi mutation cho u2.
    """
    expected_uid = _normalized_user_id(user_id)

    @wraps(func)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        require_authenticated_session(expected_uid, session_state)
        actual_uid = kwargs.get("user_id")
        if actual_uid is None and args:
            actual_uid = args[0]
        if not actual_uid or not secrets.compare_digest(_normalized_user_id(actual_uid), expected_uid):
            raise SessionAuthorizationError(
                "Từ chối thao tác: user_id của mutation không khớp identity trong phiên đăng nhập."
            )
        return func(*args, **kwargs)

    return guarded  # type: ignore[return-value]


def enforce_auth_gate(*, user_id: str, has_auth_user: Callable[[str], bool]) -> None:
    """Composition-root UI gate: khóa app trước khi render bất kỳ panel mutation nào."""
    if has_auth_user(user_id) and is_authenticated_session(user_id):
        return
    clear_authenticated_session()
    st.warning("🔒 Phiên chưa xác thực. Vui lòng đăng nhập bằng PIN để tiếp tục.")
    st.stop()

