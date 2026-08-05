"""
Luân phiên cửa sổ quét trên danh sách mã VN đã sắp xếp — phủ dần toàn thị trường
theo thời gian mà không quét full một lúc (hiệu quả vận hành).

Tắt: II_UNIVERSE_AUTO_ROTATE=0
Kiểu offset: II_UNIVERSE_ROTATE_STYLE=sequential (mặc định) | hash
"""

from __future__ import annotations

import hashlib
import os
from datetime import date


def universe_auto_rotate_enabled() -> bool:
    return os.environ.get("II_UNIVERSE_AUTO_ROTATE", "1").strip().lower() not in ("0", "false", "no", "off")


def rotation_style() -> str:
    raw = str(os.environ.get("II_UNIVERSE_ROTATE_STYLE", "sequential") or "sequential").strip().lower()
    if raw in ("hash", "random", "sha"):
        return "hash"
    return "sequential"


def rotation_offset(*, total: int, window: int, key: str = "default", day_ordinal: int | None = None) -> int:
    """
    Offset vào danh sách mã đầy đủ (sorted). Cùng ngày + key → cùng offset (ổn định trong ngày).
    Khi total <= window, luôn 0.
    `day_ordinal`: mặc định hôm nay; truyền số cố định trong test.

    sequential (mặc định): mỗi ngày dịch cửa sổ `window` mã → phủ dần full listing.
    hash: offset pseudo-random theo ngày (ổn định trong ngày, không tuần tự).
    """
    w = max(1, int(window))
    t = max(0, int(total))
    if t <= w:
        return 0
    span = t - w + 1
    day = date.today().toordinal() if day_ordinal is None else int(day_ordinal)
    if rotation_style() == "hash":
        h = int(hashlib.sha256(f"{key}:{day}".encode()).hexdigest(), 16)
        return int(h % span)
    # sequential: day 0 → 0, day 1 → w, day 2 → 2w, ... wrap trong span
    return int((day * w) % span)


def slice_universe(symbols: list[str], *, offset: int, limit: int) -> list[str]:
    """Cắt cửa sổ `limit` mã từ `offset`; wrap về đầu list nếu gần cuối (phủ đủ window)."""
    off = max(0, int(offset))
    lim = max(0, int(limit))
    if not symbols or lim <= 0:
        return []
    n = len(symbols)
    if lim >= n:
        return list(symbols)
    off = off % n
    end = off + lim
    if end <= n:
        return symbols[off:end]
    # wrap-around
    return symbols[off:] + symbols[: end - n]
