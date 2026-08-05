from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any, Callable

from core import auth_repository


def pin_hash(pin: str, *, prefix: str, iterations: int) -> str:
    raw = str(pin or "").strip()
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, int(iterations))
    return (
        f"{prefix}${int(iterations)}$"
        f"{base64.urlsafe_b64encode(salt).decode('ascii')}$"
        f"{base64.urlsafe_b64encode(dk).decode('ascii')}"
    )


def pin_hash_legacy(pin: str) -> str:
    raw = str(pin or "").strip()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def verify_pin_hash(stored_hash: str, pin: str, *, prefix: str) -> bool:
    val = str(stored_hash or "").strip()
    raw = str(pin or "").strip()
    if not val or not raw:
        return False
    if val.startswith(f"{prefix}$"):
        try:
            _, iter_text, salt_b64, digest_b64 = val.split("$", 3)
            rounds = max(120_000, int(iter_text))
            salt = base64.urlsafe_b64decode(salt_b64.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_b64.encode("ascii"))
        except (TypeError, ValueError):
            return False
        current = hashlib.pbkdf2_hmac("sha256", raw.encode("utf-8"), salt, rounds)
        return hmac.compare_digest(current, expected)
    return hmac.compare_digest(val, pin_hash_legacy(raw))


def register_user_pin(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    pin: str,
    prefix: str,
    iterations: int,
    referrer_code: str = "",
) -> tuple[bool, str]:
    uid = (user_id or "").strip()
    if not uid:
        return False, "Mã khách hàng rỗng."
    p = str(pin or "").strip()
    if len(p) < 6:
        return False, "PIN tối thiểu 6 ký tự."
    if auth_repository.has_auth_user(conn_factory=conn_factory, user_id=uid):
        return False, "Tài khoản đã tồn tại."
    now = utcnow_iso()
    auth_repository.insert_auth_user(
        conn_factory=conn_factory,
        user_id=uid,
        pin_hash=pin_hash(p, prefix=prefix, iterations=iterations),
        now_iso=now,
    )
    code = str(referrer_code or "").strip()
    if code:
        try:
            from core.referral_service import record_referral_signup

            record_referral_signup(
                conn_factory=conn_factory,
                utcnow_iso=utcnow_iso,
                new_user_id=uid,
                referrer_code=code,
            )
        except Exception:
            pass
    return True, "Đăng ký thành công."


def upsert_user_pin(
    *,
    conn_factory: Callable[[], Any],
    utcnow_iso: Callable[[], str],
    user_id: str,
    pin: str,
    prefix: str,
    iterations: int,
) -> tuple[bool, str]:
    uid = (user_id or "").strip()
    p = str(pin or "").strip()
    if not uid:
        return False, "Mã khách hàng rỗng."
    if len(p) < 6:
        return False, "PIN tối thiểu 6 ký tự."
    now = utcnow_iso()
    auth_repository.upsert_auth_user(
        conn_factory=conn_factory,
        user_id=uid,
        pin_hash=pin_hash(p, prefix=prefix, iterations=iterations),
        now_iso=now,
    )
    return True, "Đã cập nhật PIN."


def verify_user_pin(
    *,
    conn_factory: Callable[[], Any],
    user_id: str,
    pin: str,
    prefix: str,
    iterations: int,
    upsert_user_pin_func: Callable[[str, str], tuple[bool, str]],
) -> bool:
    uid = (user_id or "").strip()
    if not uid:
        return False
    stored = auth_repository.get_pin_hash(conn_factory=conn_factory, user_id=uid)
    if not stored:
        return False
    ok = verify_pin_hash(stored, str(pin or "").strip(), prefix=prefix)
    if not ok:
        return False
    if stored and not stored.startswith(f"{prefix}$"):
        upsert_user_pin_func(uid, str(pin or "").strip())
    return True


def has_auth_user(*, conn_factory: Callable[[], Any], user_id: str) -> bool:
    uid = (user_id or "").strip()
    if not uid:
        return False
    return auth_repository.has_auth_user(conn_factory=conn_factory, user_id=uid)
