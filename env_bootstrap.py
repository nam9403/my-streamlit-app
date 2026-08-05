"""
Nạp file `.env` và kiểm tra nghiêm ngặt biến môi trường bắt buộc.

Import module này ở ĐẦU mọi entrypoint (app.py, worker/background scripts),
trước khi import bất kỳ module nào của dự án — vì nhiều module trong core/*
đọc os.environ ngay lúc import:

    import env_bootstrap
    env_bootstrap.init_app_environment()

Lưu ý: KHÔNG import core/* ở đây (core/__init__.py kéo theo toàn bộ services).
Chỉ dùng stdlib + python-dotenv.
"""

from __future__ import annotations

import base64
import binascii
import os
from collections.abc import Mapping
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

_TRUTHY = ("1", "true", "yes", "on")

# Ít nhất MỘT trong các nhóm credential LLM phải tồn tại khi chạy prod
# (trừ khi II_REQUIRE_LLM_KEYS=0 — chạy chế độ fallback template, không LLM).
_LLM_KEY_ENV_NAMES = (
    "GROQ_API_KEY",
    "GROQ_API_KEYS",
    "OPENAI_API_KEY",
    "OPENAI_API_KEYS",
    "GEMINI_API_KEY",
    "GEMINI_API_KEYS",
)


class MissingEnvConfigError(RuntimeError):
    """Thiếu/sai cấu hình môi trường bắt buộc — dừng app với thông báo rõ ràng."""


def _is_truthy(env: Mapping[str, str], name: str, default: str = "0") -> bool:
    return str(env.get(name, default) or default).strip().lower() in _TRUTHY


def load_env_file(dotenv_path: str | os.PathLike[str] | None = None, *, override: bool = False) -> bool:
    """
    Nạp `.env` ở repo root (hoặc đường dẫn chỉ định) vào os.environ.

    override=False: biến đã có trong môi trường (launcher/OS/CI) luôn thắng
    giá trị trong file — an toàn, không ghi đè cấu hình hệ thống.
    Trả về True nếu file tồn tại và được nạp.
    """
    path = Path(dotenv_path) if dotenv_path is not None else _ROOT / ".env"
    if not path.is_file():
        return False
    from dotenv import load_dotenv

    # utf-8-sig: chịu được BOM khi file .env được lưu bằng Notepad/PowerShell trên Windows
    # (BOM với utf-8 thường sẽ dính vào tên biến đầu tiên → biến "biến mất" một cách im lặng).
    return bool(load_dotenv(dotenv_path=path, override=override, encoding="utf-8-sig"))


def _validate_fernet_format(value: str) -> str | None:
    """Trả về mô tả lỗi nếu key không đúng định dạng Fernet (base64url của 32 bytes)."""
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError):
        return "không phải base64url hợp lệ"
    if len(raw) != 32:
        return f"giải mã ra {len(raw)} bytes (yêu cầu đúng 32 bytes)"
    return None


def validate_required_env(env: Mapping[str, str] | None = None) -> None:
    """
    Kiểm tra nghiêm ngặt cấu hình khi chạy Production (II_ENV=prod) hoặc khi
    II_REQUIRE_APP_SECRET_KEY=1. Thiếu/sai → raise MissingEnvConfigError với
    hướng dẫn khắc phục, thay vì lỗi im lặng lúc runtime.
    """
    e: Mapping[str, str] = os.environ if env is None else env
    is_prod = str(e.get("II_ENV", "") or "").strip().lower() == "prod"
    require_secret = is_prod or _is_truthy(e, "II_REQUIRE_APP_SECRET_KEY")

    problems: list[str] = []

    if require_secret:
        secret = str(e.get("II_APP_SECRET_KEY", "") or "").strip()
        if not secret:
            problems.append(
                "- II_APP_SECRET_KEY chưa được đặt (bắt buộc ở production).\n"
                "  Tạo key: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"\n"
                "  Sau đó thêm vào file .env: II_APP_SECRET_KEY=<key>"
            )
        else:
            fmt_err = _validate_fernet_format(secret)
            if fmt_err:
                problems.append(f"- II_APP_SECRET_KEY sai định dạng Fernet: {fmt_err}.")

    if is_prod and _is_truthy(e, "II_REQUIRE_LLM_KEYS", "1"):
        has_llm = any(str(e.get(name, "") or "").strip() for name in _LLM_KEY_ENV_NAMES)
        if not has_llm:
            problems.append(
                "- Không tìm thấy API credential LLM nào "
                f"({', '.join(_LLM_KEY_ENV_NAMES)}).\n"
                "  Thêm ít nhất một key vào .env, hoặc đặt II_REQUIRE_LLM_KEYS=0 để chạy chế độ fallback không LLM."
            )

    if problems:
        raise MissingEnvConfigError(
            "Thiếu cấu hình môi trường bắt buộc (II_ENV=prod):\n"
            + "\n".join(problems)
            + "\nXem mẫu đầy đủ trong .env.example."
        )


def _configure_vnstock_credentials() -> None:
    """Nạp II_VNSTOCK_* từ .env vào vnstock trước mọi request dữ liệu."""
    try:
        from scrapers.vnstock_provider import configure_vnstock_credentials

        configure_vnstock_credentials()
    except Exception:
        # Không chặn khởi động app nếu vnstock chưa cài (pytest/offline).
        pass


def init_app_environment() -> None:
    """Nạp .env rồi kiểm tra strict — gọi một lần ở đầu mỗi entrypoint."""
    load_env_file()
    _configure_vnstock_credentials()
    validate_required_env()
