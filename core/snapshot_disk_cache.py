"""
Cache snapshot tài chính trên đĩa (JSON) để lần mở app sau đọc nhanh, không gọi lại mạng từ đầu.
TTL mặc định 30 phút — đồng bộ với II_SNAPSHOT_CACHE_TTL_SEC.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _ROOT / "data" / "snapshot_disk_cache.json"
_LOCK = threading.Lock()
_VERSION = 1

# Giảm đọc JSON lặp (nhiều mã / multi-panel): giữ bản parse theo mtime + đường dẫn file.
_RAW_MEM: dict[str, Any] | None = None
_RAW_MEM_MTIME: float = -2.0
_RAW_CACHE_KEY: str | None = None


def cache_ttl_seconds() -> float:
    try:
        return float(os.environ.get("II_SNAPSHOT_CACHE_TTL_SEC", "1800").strip())
    except ValueError:
        return 1800.0


def disk_cache_enabled() -> bool:
    return os.environ.get("II_SNAPSHOT_DISK_CACHE", "1").strip().lower() not in ("0", "false", "no", "off")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _disk_cache_key() -> str:
    return str(_CACHE_PATH.resolve())


def _load_raw() -> dict[str, Any]:
    global _RAW_MEM, _RAW_MEM_MTIME, _RAW_CACHE_KEY
    ck = _disk_cache_key()
    if _RAW_CACHE_KEY != ck:
        _RAW_MEM = None
        _RAW_MEM_MTIME = -2.0
        _RAW_CACHE_KEY = ck
    try:
        mt = float(_CACHE_PATH.stat().st_mtime) if _CACHE_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    if _RAW_MEM is not None and _RAW_MEM_MTIME == mt:
        return _RAW_MEM
    if not _CACHE_PATH.exists():
        payload: dict[str, Any] = {"version": _VERSION, "symbols": {}}
        _RAW_MEM = payload
        _RAW_MEM_MTIME = -1.0
        return payload
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        payload = data if isinstance(data, dict) else {"version": _VERSION, "symbols": {}}
    except (OSError, json.JSONDecodeError):
        payload = {"version": _VERSION, "symbols": {}}
    try:
        mt = float(_CACHE_PATH.stat().st_mtime) if _CACHE_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    _RAW_MEM = payload
    _RAW_MEM_MTIME = mt
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use per-process/thread temp file to avoid cross-process collisions on Windows.
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    raw = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(raw)
    try:
        tmp.replace(path)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def get_disk_snapshot_any_age(symbol: str) -> dict[str, Any] | None:
    """
    Đọc snapshot đã lưu trên đĩa **bất kể TTL** (bồn vẫn còn nước dù đã quá hạn “uống ngay”).
    Dùng khi II_READ_STALE_DISK=1 để ưu tiên không gọi mạng cho chỉ số cơ bản.
    """
    if not disk_cache_enabled():
        return None
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    with _LOCK:
        data = _load_raw()
    block = (data.get("symbols") or {}).get(sym)
    if not isinstance(block, dict):
        return None
    snap = block.get("snapshot")
    if not isinstance(snap, dict):
        return None
    cached_at = _parse_iso(str(block.get("cached_at") or ""))
    ttl = cache_ttl_seconds()
    age = (_utc_now() - cached_at).total_seconds() if cached_at else None
    stale = ttl > 0 and cached_at is not None and age is not None and age > ttl
    out = dict(snap)
    out["_disk_cache"] = {
        "hit": True,
        "stale": bool(stale),
        "cached_at": block.get("cached_at"),
        "age_seconds": round(age, 1) if age is not None else None,
        "ttl_sec": ttl,
    }
    return out


def get_cached_snapshot(symbol: str) -> dict[str, Any] | None:
    """Trả snapshot nếu còn mới trong TTL; ngược lại None."""
    if not disk_cache_enabled():
        return None
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    ttl = cache_ttl_seconds()
    if ttl <= 0:
        return None
    with _LOCK:
        data = _load_raw()
    block = (data.get("symbols") or {}).get(sym)
    if not isinstance(block, dict):
        return None
    snap = block.get("snapshot")
    if not isinstance(snap, dict):
        return None
    cached_at = _parse_iso(str(block.get("cached_at") or ""))
    if cached_at is None:
        return None
    age = (_utc_now() - cached_at).total_seconds()
    if age > ttl:
        return None
    out = dict(snap)
    out["_disk_cache"] = {
        "hit": True,
        "cached_at": block.get("cached_at"),
        "age_seconds": round(age, 1),
        "ttl_sec": ttl,
    }
    return out


def put_snapshot(symbol: str, snapshot: dict[str, Any]) -> None:
    """Ghi đè snapshot cho mã (sau khi fetch thành công)."""
    if not disk_cache_enabled():
        return
    sym = (symbol or "").strip().upper()
    if not sym or not isinstance(snapshot, dict):
        return
    clean = {k: v for k, v in snapshot.items() if not str(k).startswith("_disk_cache")}
    now = _utc_now().isoformat()
    with _LOCK:
        data = _load_raw()
        data["version"] = _VERSION
        data["updated_at"] = now
        if "symbols" not in data or not isinstance(data["symbols"], dict):
            data["symbols"] = {}
        data["symbols"][sym] = {"snapshot": clean, "cached_at": now}
        _atomic_write(_CACHE_PATH, data)
        global _RAW_MEM, _RAW_MEM_MTIME
        try:
            mt = float(_CACHE_PATH.stat().st_mtime)
        except OSError:
            mt = -1.0
        _RAW_MEM = data
        _RAW_MEM_MTIME = mt


def get_disk_cache_cached_at(symbol: str) -> str | None:
    """ISO timestamp `cached_at` của mã trong file đĩa (không qua TTL) — dùng để phát hiện job nền đã ghi mới."""
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    with _LOCK:
        data = _load_raw()
    block = (data.get("symbols") or {}).get(sym)
    if not isinstance(block, dict):
        return None
    ca = block.get("cached_at")
    return str(ca).strip() if ca else None


def cache_meta_summary() -> dict[str, Any]:
    """Thông tin nhanh cho UI (đếm mã, thời điểm cập nhật gần nhất)."""
    with _LOCK:
        data = _load_raw()
    syms_raw = data.get("symbols")
    syms: dict[str, Any] = syms_raw if isinstance(syms_raw, dict) else {}
    latest: str | None = None
    for b in syms.values():
        if isinstance(b, dict) and b.get("cached_at"):
            ca = str(b["cached_at"])
            if latest is None or ca > latest:
                latest = ca
    return {
        "path": str(_CACHE_PATH),
        "symbol_count": len(syms),
        "last_any_update": latest,
        "ttl_sec": cache_ttl_seconds(),
        "enabled": disk_cache_enabled(),
    }


def clear_cache() -> None:
    """Xóa file cache (ví dụ khi cần reset)."""
    with _LOCK:
        if _CACHE_PATH.exists():
            try:
                _CACHE_PATH.unlink()
            except OSError:
                pass
        global _RAW_MEM, _RAW_MEM_MTIME
        _RAW_MEM = None
        _RAW_MEM_MTIME = -2.0
