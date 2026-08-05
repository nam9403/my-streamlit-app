from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from typing import Callable

from cryptography.fernet import Fernet, InvalidToken

from core import secret_repository


def _as_secret_map(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in value.items():
        out[str(k)] = str(v)
    return out


def secret_key(user_id: str) -> bytes:
    seed = f"{user_id}|value-investor-local".encode()
    return hashlib.sha256(seed).digest()


def xor_crypt(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def is_truthy_env(env_get: Callable[[str, str], str], name: str, default: str = "0") -> bool:
    return str(env_get(name, default)).strip().lower() in ("1", "true", "yes", "on")


def require_env_secret_key(env_get: Callable[[str, str], str]) -> bool:
    return is_truthy_env(env_get, "II_REQUIRE_APP_SECRET_KEY", "0")


def allow_legacy_secret_decrypt(env_get: Callable[[str, str], str]) -> bool:
    if require_env_secret_key(env_get):
        return False
    return is_truthy_env(env_get, "II_ALLOW_LEGACY_SECRET_DECRYPT", "1")


def get_fernet(
    *,
    env_get: Callable[[str, str], str],
    app_secret_path: Path,
) -> Fernet:
    env_key = str(env_get("II_APP_SECRET_KEY", "") or "").strip()
    if env_key:
        try:
            return Fernet(env_key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            raise RuntimeError("II_APP_SECRET_KEY is set but invalid Fernet key format.") from exc
    if require_env_secret_key(env_get):
        raise RuntimeError("II_APP_SECRET_KEY is required when II_REQUIRE_APP_SECRET_KEY=1.")
    if app_secret_path.exists():
        key = app_secret_path.read_text(encoding="utf-8").strip()
        if key:
            return Fernet(key.encode("ascii"))
    app_secret_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key().decode("ascii")
    app_secret_path.write_text(key, encoding="utf-8")
    return Fernet(key.encode("ascii"))


def save_secret(
    *,
    env_get: Callable[[str, str], str],
    app_secret_path: Path,
    secrets_path: Path,
    user_id: str,
    name: str,
    value: str,
) -> None:
    uid = (user_id or "").strip()
    nm = (name or "").strip()
    if not uid or not nm:
        return
    raw = (value or "").encode("utf-8")
    token = get_fernet(env_get=env_get, app_secret_path=app_secret_path).encrypt(raw).decode("ascii")
    payload = secret_repository.load_secrets(secrets_path)
    user_block = _as_secret_map(payload.get(uid))
    user_block[nm] = f"v2:{token}"
    payload[uid] = user_block
    secret_repository.save_secrets(secrets_path, payload)


def load_secret(
    *,
    env_get: Callable[[str, str], str],
    app_secret_path: Path,
    secrets_path: Path,
    save_secret_func: Callable[[str, str, str], None],
    user_id: str,
    name: str,
    default: str = "",
) -> str:
    uid = (user_id or "").strip()
    nm = (name or "").strip()
    payload = secret_repository.load_secrets(secrets_path)
    block = _as_secret_map(payload.get(uid))
    b64 = str(block.get(nm) or "")
    if not b64:
        return default
    try:
        if b64.startswith("v2:"):
            raw = get_fernet(env_get=env_get, app_secret_path=app_secret_path).decrypt(b64[3:].encode("ascii"))
            return raw.decode("utf-8")
        if not allow_legacy_secret_decrypt(env_get):
            return default
        enc = base64.b64decode(b64.encode("ascii"))
        dec = xor_crypt(enc, secret_key(uid))
        value = dec.decode("utf-8")
        if value:
            save_secret_func(uid, nm, value)
        return value or default
    except (InvalidToken, ValueError, OSError):
        return default
