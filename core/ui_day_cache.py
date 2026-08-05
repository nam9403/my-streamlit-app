"""
Disk cache keyed by Vietnam (ICT) calendar day for heavy UI results.

Used so a second request the same day can skip recomputation until the next ICT date.
"""

from __future__ import annotations

import hashlib
import json
import pickle
from pathlib import Path
from typing import Any

_ICT_OFFSET_SEC = 7 * 3600

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_ROOT = _ROOT / "data" / "runtime" / "ui_day_cache"


def ict_calendar_date_str() -> str:
    """YYYY-MM-DD in ICT (UTC+7), consistent for 'within the same day' in VN."""
    from datetime import datetime, timedelta, timezone

    utc = datetime.now(timezone.utc)
    ict = utc + timedelta(seconds=_ICT_OFFSET_SEC)
    return ict.strftime("%Y-%m-%d")


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)


def cache_key_hash(namespace: str, parts: tuple[Any, ...]) -> str:
    raw = f"{namespace}|{_stable_json(parts)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def day_cache_dir() -> Path:
    d = _CACHE_ROOT / ict_calendar_date_str()
    d.mkdir(parents=True, exist_ok=True)
    return d


def day_cache_path(namespace: str, parts: tuple[Any, ...]) -> Path:
    h = cache_key_hash(namespace, parts)
    return day_cache_dir() / f"{namespace}_{h}.pkl"


def day_cache_load(namespace: str, parts: tuple[Any, ...]) -> Any | None:
    path = day_cache_path(namespace, parts)
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (OSError, EOFError, pickle.UnpicklingError):
        return None


def day_cache_save(namespace: str, parts: tuple[Any, ...], payload: Any) -> None:
    path = day_cache_path(namespace, parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
