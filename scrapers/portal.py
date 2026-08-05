"""Portal scraper: OHLCV, financial indicators, and latest news."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pandas as pd
import requests  # type: ignore
from bs4 import BeautifulSoup

from core.ohlcv_store import last_ohlcv_date, load_recent_ohlcv, upsert_ohlcv
from scrapers.financial_statements import compute_trend_metrics, fetch_vndirect_financial_statement_rows
from scrapers.vnstock_provider import (
    VnstockProviderError,
    fetch_company_profile_snapshot as _fetch_vnstock_company_profile,
    fetch_finance_ratio_snapshot as _fetch_vnstock_finance_ratio,
    fetch_finance_statements_snapshot as _fetch_vnstock_finance_statements,
    fetch_ohlcv_history as _fetch_ohlcv_vnstock,
    merge_statement_fields_into_indicators as _merge_vnstock_statements,
    parse_finance_ratio_to_indicators as _parse_vnstock_finance_ratio,
    vnstock_available as _vnstock_available,
)

from .finance_scraper import DEFAULT_HEADERS, VNDIRECT_HEADERS

logger = logging.getLogger(__name__)

_TTL_OHLCV_S = 300
_TTL_FIN_S = 900
_TTL_NEWS_S = 300
_PORTAL_TIMEOUT = float(os.environ.get("VALUE_INVESTOR_PORTAL_TIMEOUT", "8"))
_MEM_CACHE: dict[str, tuple[datetime, Any]] = {}
_ROOT = Path(__file__).resolve().parent.parent
_OHLCV_DISK_CACHE_PATH = _ROOT / "data" / "ohlcv_cache.json"
_FIN_DISK_CACHE_PATH = _ROOT / "data" / "financial_indicators_cache.json"
_NEWS_DISK_CACHE_PATH = _ROOT / "data" / "news_cache.json"
_SLA_PATH = _ROOT / "data" / "source_sla.json"
_SWR_REFRESH_LAST_TS: dict[str, float] = {}

# SLA: đọc JSON lặp + ghi đĩa mỗi lần mark là hot path khi quét nhiều mã.
_SLA_MEM: dict[str, Any] | None = None
_SLA_MEM_MTIME: float = -2.0
_SLA_CACHE_PATH_KEY: str | None = None
_SLA_DIRTY: bool = False
_SLA_IO_LOCK = threading.RLock()
_SLA_TIMER_LOCK = threading.Lock()
_SLA_FLUSH_TIMER: threading.Timer | None = None


class PortalDataError(Exception):
    """Raised when portal data cannot be fetched or parsed."""


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _financial_force_live_refresh(*, force_refresh: bool = False) -> bool:
    """True when caller or II_FINANCIAL_LIVE_REFRESH requests bypass of fin disk/mem cache."""
    return bool(force_refresh) or _bool_env("II_FINANCIAL_LIVE_REFRESH", False)


def _float_env(name: str, default: float) -> float:
    try:
        return float(str(os.environ.get(name, str(default))).strip())
    except ValueError:
        return float(default)


def _timeout_ladder() -> list[float]:
    raw = str(os.environ.get("II_PORTAL_TIMEOUT_LADDER_SEC", "") or "").strip()
    if not raw:
        # Fail-fast mode shortens probes so UI can return quickly with fallback/cache.
        if _bool_env("II_PORTAL_FAIL_FAST", False):
            return [1.2, max(1.8, min(3.0, _PORTAL_TIMEOUT))]
        # Keep first probe fast, second probe moderate.
        return [2.5, max(3.0, _PORTAL_TIMEOUT)]
    out: list[float] = []
    for x in raw.split(","):
        try:
            v = float(x.strip())
            if v > 0:
                out.append(v)
        except ValueError:
            continue
    return out or [max(1.0, _PORTAL_TIMEOUT)]


def _pick_timeout_for_probe(probe_idx: int, started: float, live_budget: float) -> float:
    ladder = _timeout_ladder()
    base = ladder[min(max(0, probe_idx), len(ladder) - 1)]
    elapsed = max(0.0, time.perf_counter() - started)
    remain = max(0.2, live_budget - elapsed)
    return max(0.6, min(base, remain))


def _is_suspicious_vn_price_scale(sym: str, df: pd.DataFrame) -> bool:
    """
    Guard against wrong-market symbols (e.g. US ETF ticker collisions like VNM ~ $19)
    entering VN OHLCV cache/store.
    """
    symbol = str(sym or "").strip().upper()
    if not symbol or len(symbol) > 5 or not symbol.isalnum():
        return False
    d = df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if d.empty or "close" not in d.columns:
        return False
    closes = pd.to_numeric(d["close"], errors="coerce").dropna()
    if closes.empty:
        return False
    median_close = float(closes.median())
    last_close = float(closes.iloc[-1])
    # VN stocks are quoted in VND and should not be around double-digit prices.
    if median_close < 200.0:
        return True
    # Detect wrong-market tail records mixed into otherwise valid VN history.
    if median_close > 0 and (last_close / median_close) < 0.2:
        return True
    return False


def _live_budget_seconds(default_budget: float) -> float:
    base_budget = max(1.0, _float_env("II_PORTAL_LIVE_BUDGET_SEC", default_budget))
    if not _bool_env("II_PORTAL_FAIL_FAST", False):
        return base_budget
    fail_fast_budget = max(1.0, _float_env("II_PORTAL_FAIL_FAST_BUDGET_SEC", 4.0))
    return min(base_budget, fail_fast_budget)


def _financial_swr_enabled() -> bool:
    return _bool_env("II_FINANCIAL_STALE_WHILE_REVALIDATE", False)


def _strict_real_financial_data() -> bool:
    return _bool_env("II_STRICT_REAL_FINANCIAL_DATA", False)


def _is_real_financial_source(payload: dict[str, Any] | None) -> bool:
    src = str((payload or {}).get("source") or "").strip().lower()
    if not src:
        return False
    # Reject synthetic/derived payloads when strict mode is enabled.
    if "snapshot_derived" in src or "derived" in src:
        return False
    if "unavailable" in src or "mock" in src:
        return False
    return True


def _financial_swr_max_age_seconds(default_age: float) -> float:
    return max(300.0, _float_env("II_FINANCIAL_SWR_MAX_AGE_SEC", max(default_age * 3.0, 21600.0)))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_seconds_from_iso(ts_raw: str) -> float | None:
    ts = str(ts_raw or "").strip()
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _attach_ohlcv_data_trust(
    df: pd.DataFrame,
    *,
    source: str,
    saved_at: str = "",
    stale_max_age_s: float | None = None,
    fallback_chain: list[str] | None = None,
) -> pd.DataFrame:
    out = df.copy()
    effective_saved_at = str(saved_at or out.attrs.get("saved_at") or _now_iso())
    age_sec = _age_seconds_from_iso(effective_saved_at)
    max_age_s = float(stale_max_age_s) if stale_max_age_s is not None else max(60.0, _float_env("II_OHLCV_DISK_MAX_AGE_SEC", 7200.0))
    is_stale = bool(age_sec is not None and age_sec > max_age_s)
    chain = list(fallback_chain or [])
    trust = {
        "source": str(source or "unknown"),
        "saved_at": effective_saved_at,
        "age_sec": None if age_sec is None else round(float(age_sec), 2),
        "stale_max_age_sec": round(float(max_age_s), 2),
        "is_stale": is_stale,
        "fallback_chain": chain,
    }
    out.attrs["source"] = str(source or "unknown")
    out.attrs["saved_at"] = effective_saved_at
    out.attrs["age_sec"] = trust["age_sec"]
    out.attrs["is_stale"] = bool(trust["is_stale"])
    out.attrs["fallback_chain"] = chain
    out.attrs["data_trust"] = trust
    return out


def _attach_financial_data_trust(
    payload: dict[str, Any],
    *,
    source: str,
    saved_at: str = "",
    stale_max_age_s: float | None = None,
    fallback_chain: list[str] | None = None,
) -> dict[str, Any]:
    out = dict(payload or {})
    effective_saved_at = str(saved_at or out.get("saved_at") or _now_iso())
    age_sec = _age_seconds_from_iso(effective_saved_at)
    max_age_s = float(stale_max_age_s) if stale_max_age_s is not None else max(120.0, _float_env("II_FINANCIAL_DISK_MAX_AGE_SEC", 21600.0))
    is_stale = bool(age_sec is not None and age_sec > max_age_s)
    chain = list(fallback_chain or [])
    trust = {
        "source": str(source or "unknown"),
        "saved_at": effective_saved_at,
        "age_sec": None if age_sec is None else round(float(age_sec), 2),
        "stale_max_age_sec": round(float(max_age_s), 2),
        "is_stale": is_stale,
        "fallback_chain": chain,
    }
    out["source"] = str(source or "unknown")
    out["saved_at"] = effective_saved_at
    out["data_trust"] = trust
    return out


def _launch_financial_refresh(sym: str, max_probes: int) -> None:
    # Không cào BCTC nền trong phiên trừ khi bật explicit live refresh.
    if not _bool_env("II_FINANCIAL_LIVE_REFRESH", False):
        return
    now = time.time()
    key = f"fin_refresh:{str(sym or '').strip().upper()}"
    min_gap = max(20.0, _float_env("II_FINANCIAL_SWR_MIN_REFRESH_SEC", 120.0))
    last = float(_SWR_REFRESH_LAST_TS.get(key, 0.0))
    if (now - last) < min_gap:
        return
    _SWR_REFRESH_LAST_TS[key] = now

    def _refresh() -> None:
        try:
            try:
                out_live = _fetch_financial_indicators_from_vnstock(sym)
            except PortalDataError:
                out_live = _fetch_financial_indicators_uncached(sym, max_probes=max_probes)
            _write_fin_disk_cache(sym, out_live)
            _cache_set(f"fin:{sym}", dict(out_live))
            _sla_mark("financial_swr_refresh", True)
        except Exception:
            _sla_mark("financial_swr_refresh", False)
            return

    t = threading.Thread(target=_refresh, name=f"financial_swr_refresh_{sym}", daemon=True)
    t.start()


def _sla_flush_debounce_sec() -> float:
    return max(0.05, _float_env("II_SLA_FLUSH_DEBOUNCE_SEC", 0.5))


def _invalidate_sla_memory_cache() -> None:
    global _SLA_MEM, _SLA_MEM_MTIME, _SLA_DIRTY
    _SLA_MEM = None
    _SLA_MEM_MTIME = -2.0
    _SLA_DIRTY = False


def _cancel_sla_flush_timer() -> None:
    global _SLA_FLUSH_TIMER
    with _SLA_TIMER_LOCK:
        if _SLA_FLUSH_TIMER is not None:
            _SLA_FLUSH_TIMER.cancel()
            _SLA_FLUSH_TIMER = None


def _flush_sla_to_disk() -> None:
    global _SLA_MEM, _SLA_MEM_MTIME, _SLA_DIRTY
    with _SLA_IO_LOCK:
        if not _SLA_DIRTY or _SLA_MEM is None:
            return
        _SLA_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(_SLA_PATH, "w", encoding="utf-8") as f:
                json.dump(_SLA_MEM, f, ensure_ascii=False, indent=2)
        except OSError:
            return
        _SLA_DIRTY = False
        try:
            mt = float(_SLA_PATH.stat().st_mtime) if _SLA_PATH.exists() else -1.0
        except OSError:
            mt = -1.0
        _SLA_MEM_MTIME = mt


def _schedule_sla_flush() -> None:
    global _SLA_FLUSH_TIMER
    delay = _sla_flush_debounce_sec()

    def _fire() -> None:
        _flush_sla_to_disk()

    with _SLA_TIMER_LOCK:
        if _SLA_FLUSH_TIMER is not None:
            _SLA_FLUSH_TIMER.cancel()
            _SLA_FLUSH_TIMER = None
        t = threading.Timer(delay, _fire)
        t.daemon = True
        _SLA_FLUSH_TIMER = t
        t.start()


def flush_sla_pending_sync() -> None:
    """Ghi ngay SLA ra đĩa (test / shutdown); bình thường dùng debounce."""
    _cancel_sla_flush_timer()
    _flush_sla_to_disk()


def _load_sla_unlocked() -> dict[str, Any]:
    global _SLA_MEM, _SLA_MEM_MTIME, _SLA_CACHE_PATH_KEY
    ck = str(_SLA_PATH.resolve())
    if _SLA_CACHE_PATH_KEY != ck:
        _cancel_sla_flush_timer()
        _invalidate_sla_memory_cache()
        _SLA_CACHE_PATH_KEY = ck

    if _SLA_DIRTY and _SLA_MEM is not None:
        return _SLA_MEM

    try:
        mt = float(_SLA_PATH.stat().st_mtime) if _SLA_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    if _SLA_MEM is not None and _SLA_MEM_MTIME == mt:
        return _SLA_MEM

    if not _SLA_PATH.exists():
        payload: dict[str, Any] = {}
        _SLA_MEM = payload
        _SLA_MEM_MTIME = -1.0
        return payload
    try:
        with open(_SLA_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        payload = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        payload = {}
    try:
        mt = float(_SLA_PATH.stat().st_mtime) if _SLA_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    _SLA_MEM = payload
    _SLA_MEM_MTIME = mt
    return payload


def _load_sla() -> dict[str, Any]:
    with _SLA_IO_LOCK:
        return _load_sla_unlocked()


def _save_sla(payload: dict[str, Any]) -> None:
    """Ghi đồng bộ toàn bộ payload (ít dùng); cập nhật cache trong RAM."""
    global _SLA_MEM, _SLA_MEM_MTIME, _SLA_DIRTY
    _cancel_sla_flush_timer()
    with _SLA_IO_LOCK:
        _SLA_MEM = dict(payload)
        _SLA_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(_SLA_PATH, "w", encoding="utf-8") as f:
                json.dump(_SLA_MEM, f, ensure_ascii=False, indent=2)
        except OSError:
            return
        _SLA_DIRTY = False
        try:
            mt = float(_SLA_PATH.stat().st_mtime) if _SLA_PATH.exists() else -1.0
        except OSError:
            mt = -1.0
        _SLA_MEM_MTIME = mt


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tag_attr_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return " ".join(str(x).strip() for x in value if str(x).strip()).strip()
    return str(value or "").strip()


def _sla_mark(source: str, success: bool) -> None:
    global _SLA_DIRTY
    with _SLA_IO_LOCK:
        data = _load_sla_unlocked()
        key = (source or "unknown").strip().lower()
        block = _as_dict(data.get(key))
        ok = int(block.get("ok") or 0)
        fail = int(block.get("fail") or 0)
        block["ok"] = ok + (1 if success else 0)
        block["fail"] = fail + (0 if success else 1)
        total = block["ok"] + block["fail"]
        block["success_rate_pct"] = round((block["ok"] / total * 100.0), 2) if total > 0 else 0.0
        block["last_status"] = "ok" if success else "fail"
        block["updated_at"] = datetime.now(timezone.utc).isoformat()
        data[key] = block
        _SLA_DIRTY = True
    _schedule_sla_flush()


def get_source_sla_report() -> list[dict[str, Any]]:
    with _SLA_IO_LOCK:
        data = dict(_load_sla_unlocked())
    rows: list[dict[str, Any]] = []
    for k, v in data.items():
        if not isinstance(v, dict):
            continue
        rows.append(
            {
                "source": k,
                "ok": int(v.get("ok") or 0),
                "fail": int(v.get("fail") or 0),
                "success_rate_pct": float(v.get("success_rate_pct") or 0.0),
                "last_status": str(v.get("last_status") or "unknown"),
                "updated_at": str(v.get("updated_at") or ""),
            }
        )
    rows.sort(key=lambda x: (x["success_rate_pct"], x["ok"]), reverse=True)
    return rows


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _norm_ticker(ticker: str) -> str:
    sym = (ticker or "").strip().upper()
    if not sym:
        raise PortalDataError("Ticker rỗng.")
    return sym


def _cache_get(key: str, ttl_seconds: int) -> Any | None:
    item = _MEM_CACHE.get(key)
    if not item:
        return None
    saved_at, payload = item
    if datetime.now(timezone.utc) - saved_at > timedelta(seconds=ttl_seconds):
        _MEM_CACHE.pop(key, None)
        return None
    return payload


def _cache_set(key: str, payload: Any) -> None:
    _MEM_CACHE[key] = (datetime.now(timezone.utc), payload)


def _read_ohlcv_disk_cache(sym: str) -> pd.DataFrame | None:
    if not _OHLCV_DISK_CACHE_PATH.exists():
        return None
    try:
        with open(_OHLCV_DISK_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    block = raw.get(sym)
    if not isinstance(block, dict):
        return None
    rows = block.get("rows")
    if not isinstance(rows, list) or len(rows) < 50:
        return None
    df = pd.DataFrame(rows)
    needed = {"date", "open", "high", "low", "close", "volume"}
    if not needed.issubset(set(df.columns)):
        return None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close", "volume"]).sort_values("date")
    if len(df) < 50:
        return None
    df.attrs["source"] = "disk_cache"
    df.attrs["saved_at"] = block.get("saved_at")
    return df.reset_index(drop=True)


def _ohlcv_disk_cache_age_seconds(df: pd.DataFrame) -> float | None:
    saved_at = str(df.attrs.get("saved_at") or "").strip()
    if not saved_at:
        return None
    try:
        ts = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def _write_ohlcv_disk_cache(sym: str, df: pd.DataFrame) -> None:
    payload: dict[str, Any] = {}
    if _OHLCV_DISK_CACHE_PATH.exists():
        try:
            with open(_OHLCV_DISK_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    payload = raw
        except (OSError, ValueError):
            payload = {}

    # Keep enough rows for long-horizon chart rendering (3Y/5Y).
    out_df = df.tail(2200).copy()
    out_df["date"] = out_df["date"].dt.strftime("%Y-%m-%d")
    payload[sym] = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "rows": out_df.to_dict(orient="records"),
    }
    _OHLCV_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_OHLCV_DISK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        return


def _read_fin_disk_cache(sym: str) -> dict[str, Any] | None:
    if not _FIN_DISK_CACHE_PATH.exists():
        return None
    try:
        with open(_FIN_DISK_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    block = raw.get(sym)
    if not isinstance(block, dict):
        return None
    payload = block.get("payload")
    if not isinstance(payload, dict):
        return None
    out = dict(payload)
    out["source"] = f"{out.get('source', 'unknown')}:disk_cache"
    out["saved_at"] = block.get("saved_at")
    return out


def _fin_disk_cache_age_seconds(payload: dict[str, Any]) -> float | None:
    saved_at = str(payload.get("saved_at") or "").strip()
    if not saved_at:
        return None
    try:
        ts = datetime.fromisoformat(saved_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def _write_fin_disk_cache(sym: str, payload: dict[str, Any]) -> None:
    data: dict[str, Any] = {}
    if _FIN_DISK_CACHE_PATH.exists():
        try:
            with open(_FIN_DISK_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except (OSError, ValueError):
            data = {}
    clean = dict(payload)
    clean.pop("saved_at", None)
    data[sym] = {"saved_at": datetime.now(timezone.utc).isoformat(), "payload": clean}
    _FIN_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_FIN_DISK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        return


def _news_disk_cache_ttl_seconds() -> float:
    return max(30.0, _float_env("II_NEWS_DISK_CACHE_TTL_SEC", 180.0))


def _news_disk_stale_fallback_seconds() -> float:
    return max(_news_disk_cache_ttl_seconds(), _float_env("II_NEWS_DISK_STALE_MAX_AGE_SEC", 900.0))


def _read_news_disk_cache(sym: str) -> tuple[list[dict[str, str]], str | None] | None:
    if not _NEWS_DISK_CACHE_PATH.exists():
        return None
    try:
        with open(_NEWS_DISK_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    block = raw.get(sym)
    if not isinstance(block, dict):
        return None
    items = block.get("items")
    if not isinstance(items, list):
        return None
    out: list[dict[str, str]] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title") or "").strip()
        url = str(x.get("url") or "").strip()
        source = str(x.get("source") or "unknown").strip()
        if not title or not url:
            continue
        out.append({"title": title, "url": url, "source": source})
    if not out:
        return None
    saved_at = str(block.get("saved_at") or "").strip() or None
    return out, saved_at


def _news_disk_age_seconds(saved_at: str | None) -> float | None:
    if not saved_at:
        return None
    try:
        ts = datetime.fromisoformat(str(saved_at).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def _write_news_disk_cache(sym: str, items: list[dict[str, str]]) -> None:
    data: dict[str, Any] = {}
    if _NEWS_DISK_CACHE_PATH.exists():
        try:
            with open(_NEWS_DISK_CACHE_PATH, encoding="utf-8") as f:
                raw = json.load(f)
                if isinstance(raw, dict):
                    data = raw
        except (OSError, ValueError):
            data = {}
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for x in items:
        title = str(x.get("title") or "").strip()
        url = str(x.get("url") or "").strip()
        source = str(x.get("source") or "unknown").strip()
        if not title or not url:
            continue
        k = f"{title}|{url}"
        if k in seen:
            continue
        seen.add(k)
        clean.append({"title": title, "url": url, "source": source})
        if len(clean) >= 30:
            break
    if not clean:
        return
    data[sym] = {"saved_at": datetime.now(timezone.utc).isoformat(), "items": clean}
    _NEWS_DISK_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_NEWS_DISK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        return


def _fetch_ohlcv_history_uncached(ticker: str, sessions: int = 80, since_date: str | None = None) -> pd.DataFrame:
    """
    Fetch historical OHLCV for at least 50 recent sessions.

    Returns columns: date, open, high, low, close, volume.
    """
    sym = _norm_ticker(ticker)
    size = max(80, sessions)
    if since_date:
        since = str(since_date).strip()[:10]
    else:
        now = datetime.now(timezone.utc).date()
        # Estimate calendar span from requested trading sessions.
        # ~260 trading sessions/year => ~365 calendar days/year.
        lookback_days = max(220, int(size * 1.6))
        since = (now - timedelta(days=lookback_days)).isoformat()
    urls = [
        (
            "https://finfo-api.vndirect.com.vn/v4/stock_prices"
            f"?sort=date&size={size}&q=code:{quote(sym)}~date:gte:{since}"
        ),
        (
            "https://finfo-api.vndirect.com.vn/v4/stock-prices"
            f"?sort=date&size={size}&q=code:{quote(sym)}~date:gte:{since}"
        ),
    ]
    rows: list[dict[str, Any]] | None = None
    errors: list[str] = []
    started = time.perf_counter()
    live_budget = _live_budget_seconds(12.0)
    for i, url in enumerate(urls):
        if time.perf_counter() - started > live_budget:
            errors.append("live_budget_exceeded")
            break
        try:
            req_timeout = _pick_timeout_for_probe(i, started, live_budget)
            r = requests.get(url, headers=VNDIRECT_HEADERS, timeout=req_timeout)
            r.raise_for_status()
            js = r.json()
            data = js.get("data") if isinstance(js, dict) else None
            if isinstance(data, list) and data:
                rows = data
                break
            errors.append(f"empty:{url}")
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{url} => {e}")
    if not rows:
        raise PortalDataError(f"Không có dữ liệu OHLCV cho {sym}. Chi tiết: {' | '.join(errors)}")

    parsed: list[dict[str, Any]] = []
    for row in rows:
        o = _to_float(row.get("open"))
        h = _to_float(row.get("high"))
        low = _to_float(row.get("low"))
        c = _to_float(row.get("close") or row.get("lastPrice"))
        v = _to_float(row.get("nmVolume") or row.get("volume"))
        d = row.get("date") or row.get("tradingDate")
        if o is None or h is None or low is None or c is None or v is None or not d:
            continue
        parsed.append({"date": str(d), "open": o, "high": h, "low": low, "close": c, "volume": v})

    if len(parsed) < 50:
        raise PortalDataError(f"Dữ liệu OHLCV {sym} chưa đủ 50 phiên (hiện {len(parsed)}).")

    df = pd.DataFrame(parsed)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = (
        df.dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .tail(max(50, sessions))
        .reset_index(drop=True)
    )
    return df


def _fetch_ohlcv_yahoo_uncached(ticker: str, sessions: int = 80) -> pd.DataFrame:
    """
    Fallback OHLCV provider via Yahoo chart API.

    Tries Vietnam suffixes and returns DataFrame with:
    date, open, high, low, close, volume
    """
    sym = _norm_ticker(ticker)
    # HOSE: .VN — HNX: .HN — tránh ưu tiên .HM (dễ nhầm mã / sàn)
    suffixes = (".VN", ".HN", ".HM")
    errors: list[str] = []
    target = max(80, sessions)
    if target <= 260:
        y_range = "1y"
    elif target <= 520:
        y_range = "2y"
    elif target <= 1300:
        y_range = "5y"
    elif target <= 2600:
        y_range = "10y"
    else:
        y_range = "max"
    range_candidates = [y_range]
    # Some VN tickers return truncated history for 5y/10y but become fuller on max.
    if y_range != "max":
        range_candidates.append("max")
    started = time.perf_counter()
    live_budget = _live_budget_seconds(12.0)

    best_df: pd.DataFrame | None = None
    best_len = 0
    best_suffix = ""
    probe_idx = 0
    for sx in suffixes:
        if time.perf_counter() - started > live_budget:
            errors.append("live_budget_exceeded")
            break
        for rg in range_candidates:
            yahoo_sym = f"{sym}{sx}"
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(yahoo_sym)}?interval=1d&range={rg}"
            try:
                req_timeout = _pick_timeout_for_probe(probe_idx, started, live_budget)
                probe_idx += 1
                r = requests.get(url, headers=DEFAULT_HEADERS, timeout=req_timeout)
                if r.status_code != 200:
                    errors.append(f"{yahoo_sym}:{rg}:HTTP {r.status_code}")
                    continue
                js = r.json()
                result = (((js.get("chart") or {}).get("result") or [None])[0]) or {}
                timestamps = result.get("timestamp") or []
                quote_arr = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
                opens = quote_arr.get("open") or []
                highs = quote_arr.get("high") or []
                lows = quote_arr.get("low") or []
                closes = quote_arr.get("close") or []
                vols = quote_arr.get("volume") or []
                n = min(len(timestamps), len(opens), len(highs), len(lows), len(closes), len(vols))
                if n < 50:
                    errors.append(f"{yahoo_sym}:{rg}:insufficient {n}")
                    continue
                rows: list[dict[str, Any]] = []
                for i in range(n):
                    o = _to_float(opens[i])
                    h = _to_float(highs[i])
                    low = _to_float(lows[i])
                    c = _to_float(closes[i])
                    v = _to_float(vols[i])
                    if o is None or h is None or low is None or c is None or v is None:
                        continue
                    rows.append(
                        {
                            "date": datetime.fromtimestamp(int(timestamps[i]), tz=timezone.utc).date().isoformat(),
                            "open": o,
                            "high": h,
                            "low": low,
                            "close": c,
                            "volume": v,
                        }
                    )
                if len(rows) < 50:
                    errors.append(f"{yahoo_sym}:{rg}:valid_rows {len(rows)}")
                    continue
                df = pd.DataFrame(rows)
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = (
                    df.dropna(subset=["date"])
                    .sort_values("date")
                    .tail(target)
                    .reset_index(drop=True)
                )
                cur_len = int(len(df))
                if cur_len > best_len:
                    best_df = df
                    best_len = cur_len
                    best_suffix = sx
                # Early return only when coverage is already good enough.
                if cur_len >= target:
                    df.attrs["source"] = f"yahoo{sx}:{rg}"
                    return df
            except (requests.RequestException, ValueError, TypeError) as e:
                errors.append(f"{yahoo_sym}:{rg}:{e}")
    if best_df is not None and best_len >= 50:
        best_df.attrs["source"] = f"yahoo{best_suffix}:partial"
        return best_df
    raise PortalDataError(f"Yahoo OHLCV không khả dụng cho {sym}. Chi tiết: {' | '.join(errors)}")


def _fetch_ohlcv_yfinance_uncached(ticker: str, sessions: int = 80) -> pd.DataFrame:
    """
    Secondary fallback for symbols where Yahoo chart endpoint returns truncated history.
    """
    try:
        import yfinance as yf  # type: ignore
    except Exception as e:  # pragma: no cover - optional dependency
        raise PortalDataError(f"yfinance unavailable: {e}") from e

    sym = _norm_ticker(ticker)
    target = max(80, sessions)
    period = "max" if target > 1300 else "5y"
    # Không thử ticker trần (vd. "VNM") — trùng mã ETF/cổ phiếu US (~18 USD) gây giá sai so với VNM.VN (~60k VND).
    candidates = (f"{sym}.VN", f"{sym}.HN", f"{sym}.HM")
    best_df: pd.DataFrame | None = None
    best_len = 0
    errors: list[str] = []
    for csym in candidates:
        try:
            hist = yf.Ticker(csym).history(period=period, interval="1d")
            if hist is None or hist.empty:
                errors.append(f"{csym}:empty")
                continue
            out = hist.reset_index().rename(
                columns={
                    "Date": "date",
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            needed = {"date", "open", "high", "low", "close", "volume"}
            if not needed.issubset(set(out.columns)):
                errors.append(f"{csym}:bad_columns")
                continue
            out = out[["date", "open", "high", "low", "close", "volume"]].copy()
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
            for c in ("open", "high", "low", "close", "volume"):
                out[c] = pd.to_numeric(out[c], errors="coerce")
            out = out.dropna(subset=["date", "open", "high", "low", "close", "volume"]).sort_values("date")
            if len(out) < 50:
                errors.append(f"{csym}:insufficient {len(out)}")
                continue
            out = out.tail(target).reset_index(drop=True)
            cur_len = int(len(out))
            if cur_len > best_len:
                best_df = out
                best_len = cur_len
            if cur_len >= target:
                out.attrs["source"] = f"yfinance:{csym}"
                return out
        except Exception as e:  # pragma: no cover - network/provider variability
            errors.append(f"{csym}:{e}")
    if best_df is not None and best_len >= 50:
        best_df.attrs["source"] = "yfinance:partial"
        return best_df
    raise PortalDataError(f"yfinance OHLCV không khả dụng cho {sym}. Chi tiết: {' | '.join(errors)}")


def _fetch_ohlcv_fireant_uncached(ticker: str, sessions: int = 80) -> pd.DataFrame:
    """Fallback OHLCV provider via FireAnt historical quotes API."""
    sym = _norm_ticker(ticker)
    target = max(80, sessions)
    lookback_days = max(365, int(target * 1.8))
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=lookback_days)
    url = (
        "https://www.fireant.vn/api/Data/Markets/HistoricalQuotes"
        f"?symbol={quote(sym)}&startDate={start.isoformat()}&endDate={end.isoformat()}"
    )
    try:
        r = requests.get(url, timeout=max(4.0, _float_env("II_FIREANT_TIMEOUT_SEC", 12.0)))
        if r.status_code != 200:
            raise PortalDataError(f"fireant_ohlcv:HTTP {r.status_code}")
        js = r.json()
    except (requests.RequestException, ValueError) as e:
        raise PortalDataError(f"fireant_ohlcv:{e}") from e
    if not isinstance(js, list) or not js:
        raise PortalDataError("fireant_ohlcv:empty")
    rows: list[dict[str, Any]] = []
    for x in js:
        if not isinstance(x, dict):
            continue
        d = x.get("Date")
        o = _to_float(x.get("Open"))
        h = _to_float(x.get("High"))
        low = _to_float(x.get("Low"))
        c = _to_float(x.get("Close"))
        v = _to_float(x.get("Volume"))
        if not d or o is None or h is None or low is None or c is None or v is None:
            continue
        rows.append({"date": str(d), "open": o, "high": h, "low": low, "close": c, "volume": v})
    if len(rows) < 50:
        raise PortalDataError(f"fireant_ohlcv:insufficient {len(rows)}")
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out = (
        out.dropna(subset=["date"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .tail(target)
        .reset_index(drop=True)
    )
    if len(out) < 50:
        raise PortalDataError(f"fireant_ohlcv:valid_rows {len(out)}")
    out.attrs["source"] = "fireant_ohlcv"
    return out


def fetch_ohlcv_history(ticker: str, sessions: int = 80) -> pd.DataFrame:
    """Cached OHLCV history fetch."""
    sym = _norm_ticker(ticker)
    if _bool_env("II_VN_SYMBOL_GUARD", True):
        try:
            from scrapers.vn_listing import is_tradable_vn_symbol

            if not is_tradable_vn_symbol(sym):
                return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        except Exception:
            pass
    key = f"ohlcv:{sym}:{max(80, sessions)}"
    required_rows = max(50, int(sessions))
    hit = _cache_get(key, _TTL_OHLCV_S)
    if hit is not None:
        _sla_mark("ohlcv_mem_cache", True)
        return hit.copy()
    store_enabled = _bool_env("II_OHLCV_STORE_ENABLED", True)
    if store_enabled:
        try:
            store_df = load_recent_ohlcv(sym, sessions=required_rows)
        except Exception:
            store_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        if len(store_df) >= required_rows:
            out_store = store_df.tail(required_rows).reset_index(drop=True)
            suspicious_scale = _is_suspicious_vn_price_scale(sym, out_store)
            # Calendar freshness: always reject store fastpath when last bar is too old.
            # II_OHLCV_STORE_REQUIRE_FRESH=1 tightens the allowed gap (default 5 days).
            require_fresh_store = _bool_env("II_OHLCV_STORE_REQUIRE_FRESH", False)
            max_stale_days = int(max(3.0, _float_env("II_OHLCV_STORE_MAX_STALE_DAYS", 21.0)))
            if require_fresh_store:
                max_stale_days = min(max_stale_days, int(max(2.0, _float_env("II_OHLCV_STORE_FRESH_DAYS", 5.0))))
            latest = pd.to_datetime(out_store["date"], errors="coerce").max()
            days_behind = (
                (datetime.now(timezone.utc).date() - latest.date()).days
                if pd.notna(latest)
                else 10**9
            )
            stale_store = bool(days_behind > max_stale_days)
            enough_recent_depth = True
            if required_rows >= 1000:
                dt = pd.to_datetime(out_store["date"], errors="coerce")
                dt = dt.dropna().sort_values()
                if not dt.empty:
                    end = dt.max()
                    rows_3y = int((dt >= (end - pd.Timedelta(days=1096))).sum())
                    enough_recent_depth = rows_3y >= 700
            if (not stale_store) and enough_recent_depth and (not suspicious_scale):
                out_store = _attach_ohlcv_data_trust(
                    out_store,
                    source="ohlcv_store_fastpath",
                    fallback_chain=["ohlcv_store_fastpath"],
                )
                _cache_set(key, out_store.copy())
                _sla_mark("ohlcv_store_fastpath", True)
                return out_store
            if suspicious_scale:
                _sla_mark("ohlcv_store_fastpath_scale_mismatch", False)
            else:
                _sla_mark("ohlcv_store_fastpath_stale", False)
        if not store_df.empty:
            try:
                last_date = last_ohlcv_date(sym)
            except Exception:
                last_date = None
            if last_date:
                try:
                    # Incremental refresh: only fetch recent delta from provider.
                    delta = _fetch_ohlcv_history_uncached(sym, sessions=max(160, required_rows), since_date=last_date)
                    if not delta.empty:
                        upsert_ohlcv(sym, delta, source=str(delta.attrs.get("source") or "live_delta"))
                        combined = (
                            pd.concat([store_df, delta], ignore_index=True)
                            .drop_duplicates(subset=["date"], keep="last")
                            .sort_values("date")
                            .tail(required_rows)
                            .reset_index(drop=True)
                        )
                        if len(combined) >= required_rows:
                            combined = _attach_ohlcv_data_trust(
                                combined,
                                source="ohlcv_store+live_delta",
                                fallback_chain=["ohlcv_store", "vndirect_live_delta"],
                            )
                            _cache_set(key, combined.copy())
                            _sla_mark("ohlcv_store_delta", True)
                            return combined
                except Exception:
                    _sla_mark("ohlcv_store_delta", False)
    prefer_disk_first = _bool_env("II_OHLCV_DISK_FIRST", False)
    # Mặc định: không dùng đóng cửa cũ từ disk khi mọi live source lỗi (tránh sai MOS/F-Score).
    # Chỉ bật lại qua II_OHLCV_ALLOW_STALE_DISK_FALLBACK=1 (dev/offline).
    allow_stale_disk_fallback = _bool_env("II_OHLCV_ALLOW_STALE_DISK_FALLBACK", False)
    allow_stale_disk = _bool_env("II_READ_STALE_DISK", True)
    max_age_s = max(60.0, _float_env("II_OHLCV_DISK_MAX_AGE_SEC", 7200.0))
    disk_first = _read_ohlcv_disk_cache(sym) if prefer_disk_first else None
    if disk_first is not None:
        age_s = _ohlcv_disk_cache_age_seconds(disk_first)
        fresh_enough = age_s is not None and age_s <= max_age_s
        has_depth = len(disk_first) >= required_rows
        # Important: do not short-circuit to disk fastpath when user asks for a
        # long lookback (e.g. 3Y/5Y) but disk currently stores only short history.
        # In that case we must continue to live/fallback fetch to expand coverage.
        if (fresh_enough or allow_stale_disk) and has_depth:
            out = disk_first.tail(max(50, sessions)).reset_index(drop=True)
            out = _attach_ohlcv_data_trust(
                out,
                source="disk_cache_fastpath",
                saved_at=str(disk_first.attrs.get("saved_at") or ""),
                stale_max_age_s=max_age_s,
                fallback_chain=["disk_cache_fastpath"],
            )
            _cache_set(key, out.copy())
            _sla_mark("ohlcv_disk_cache_fastpath", True)
            return out
    live_errors: list[str] = []
    # Primary: vnstock → FireAnt → Yahoo/yfinance. Không fallback disk stale cho tín hiệu mới.
    try:
        out = _fetch_ohlcv_vnstock(sym, sessions=sessions)
        out = _attach_ohlcv_data_trust(
            out,
            source=str(out.attrs.get("source") or "vnstock"),
            fallback_chain=["vnstock"],
        )
        _write_ohlcv_disk_cache(sym, out)
        _sla_mark("ohlcv_vnstock", True)
    except (VnstockProviderError, Exception) as e_vn:
        _sla_mark("ohlcv_vnstock", False)
        live_errors.append(f"vnstock:{e_vn}")
        try:
            out = _fetch_ohlcv_fireant_uncached(sym, sessions=sessions)
            out = _attach_ohlcv_data_trust(
                out,
                source="fireant_fallback",
                fallback_chain=["vnstock", "fireant_fallback"],
            )
            _write_ohlcv_disk_cache(sym, out)
            _sla_mark("ohlcv_fireant", True)
        except PortalDataError as e_fa:
            _sla_mark("ohlcv_fireant", False)
            live_errors.append(f"fireant:{e_fa}")
            try:
                out = _fetch_ohlcv_yahoo_uncached(sym, sessions=sessions)
                out = _attach_ohlcv_data_trust(
                    out,
                    source="yahoo_fallback",
                    fallback_chain=["vnstock", "fireant_fallback", "yahoo_fallback"],
                )
                required_rows = max(50, int(sessions))
                if len(out) < required_rows:
                    try:
                        yfo = _fetch_ohlcv_yfinance_uncached(sym, sessions=sessions)
                        if len(yfo) > len(out):
                            out = _attach_ohlcv_data_trust(
                                yfo,
                                source="yfinance_fallback",
                                fallback_chain=["vnstock", "fireant_fallback", "yahoo_fallback", "yfinance_fallback"],
                            )
                            _sla_mark("ohlcv_yfinance", True)
                    except PortalDataError as e_yf:
                        _sla_mark("ohlcv_yfinance", False)
                        live_errors.append(f"yfinance:{e_yf}")
                _write_ohlcv_disk_cache(sym, out)
                _sla_mark("ohlcv_yahoo", True)
            except PortalDataError as e_yh:
                _sla_mark("ohlcv_yahoo", False)
                live_errors.append(f"yahoo:{e_yh}")
                # Legacy VNDirect vẫn thử (tùy chọn) trước khi báo lỗi — không dùng disk stale.
                try:
                    out = _fetch_ohlcv_history_uncached(sym, sessions=sessions)
                    out = _attach_ohlcv_data_trust(
                        out,
                        source="vndirect_live",
                        fallback_chain=["vnstock", "fireant_fallback", "yahoo_fallback", "vndirect_live"],
                    )
                    _write_ohlcv_disk_cache(sym, out)
                    _sla_mark("ohlcv_vndirect", True)
                except PortalDataError as e_vd:
                    _sla_mark("ohlcv_vndirect", False)
                    live_errors.append(f"vndirect:{e_vd}")
                    if allow_stale_disk_fallback:
                        cached = _read_ohlcv_disk_cache(sym)
                        if cached is not None:
                            out = cached.tail(max(50, sessions)).reset_index(drop=True)
                            out = _attach_ohlcv_data_trust(
                                out,
                                source="disk_cache",
                                saved_at=str(cached.attrs.get("saved_at") or ""),
                                stale_max_age_s=max_age_s,
                                fallback_chain=["vnstock", "fireant_fallback", "yahoo_fallback", "disk_cache"],
                            )
                            _sla_mark("ohlcv_disk_cache", True)
                        else:
                            raise PortalDataError(
                                f"OHLCV không khả dụng cho {sym} (mọi nguồn live lỗi). "
                                f"Chi tiết: {' | '.join(live_errors)}"
                            ) from e_vd
                    else:
                        raise PortalDataError(
                            f"OHLCV không khả dụng cho {sym} (mọi nguồn live lỗi; "
                            f"không dùng đóng cửa cũ để tính tín hiệu mới). "
                            f"Chi tiết: {' | '.join(live_errors)}"
                        ) from e_vd
    if "data_trust" not in out.attrs:
        out = _attach_ohlcv_data_trust(out, source=str(out.attrs.get("source") or "unknown"))
    _cache_set(key, out.copy())
    if store_enabled and not out.empty:
        try:
            upsert_ohlcv(sym, out, source=str(out.attrs.get("source") or ""))
        except Exception:
            pass
    return out


def fetch_ohlcv_history_batch(
    tickers: list[str] | tuple[str, ...],
    sessions: int = 80,
    max_concurrency: int = 4,
) -> dict[str, pd.DataFrame]:
    """
    Backward-compatible batch OHLCV fetch helper.
    Returns mapping {SYMBOL: dataframe}. Any failed symbol is skipped.
    """
    _ = max_concurrency  # keep signature compatible; current implementation is sequential.
    syms = [str(t or "").strip().upper() for t in (tickers or []) if str(t or "").strip()]
    if not syms:
        return {}
    out: dict[str, pd.DataFrame] = {}
    for sym in syms:
        try:
            out[sym] = fetch_ohlcv_history(sym, sessions=sessions)
        except Exception:
            continue
    return out


def _maybe_backfill_cfo(out: dict[str, Any], sym: str) -> dict[str, Any]:
    """
    When disk/FireAnt cache lacks CFO, try vnstock cash_flow once (opt-in).
    Does not replace a full live refresh — only fills missing CFO/NI.
    """
    if not isinstance(out, dict):
        return out
    if out.get("operating_cash_flow") is not None:
        return out
    if not _bool_env("II_CFO_BACKFILL", True):
        return out
    if not _vnstock_available():
        return out
    allow_statements = str(os.environ.get("II_VNSTOCK_FETCH_STATEMENTS", "1")).strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    if not allow_statements:
        return out
    try:
        stmts = _fetch_vnstock_finance_statements(sym, force_refresh=False)
        merged = _merge_vnstock_statements(dict(out), stmts)
        if merged.get("operating_cash_flow") is not None or merged.get("net_income") is not None:
            notes = list(merged.get("notes_vi") or [])
            notes.append("CFO/NI backfill từ vnstock cash_flow/income (disk-cache miss).")
            merged["notes_vi"] = list(dict.fromkeys(notes))
            src = str(merged.get("source") or "unknown")
            if "cfo_backfill" not in src:
                merged["source"] = f"{src}+cfo_backfill"
            try:
                _write_fin_disk_cache(sym, merged)
            except Exception:
                pass
            _sla_mark("financial_cfo_backfill", True)
            return merged
    except Exception as exc:
        logger.warning("cfo_backfill_skipped symbol=%s err=%s", sym, exc.__class__.__name__)
        _sla_mark("financial_cfo_backfill", False)
    return out


def _fetch_financial_indicators_from_vnstock(ticker: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Fetch valuation ratios from vnstock Finance.ratio (Community API, disk-cached by caller)."""
    sym = _norm_ticker(ticker)
    if not _vnstock_available():
        raise PortalDataError("vnstock_finance_unavailable")
    try:
        snap = _fetch_vnstock_finance_ratio(sym, force_refresh=force_refresh)
        out = _parse_vnstock_finance_ratio(snap.get("ratio_frame"), symbol=sym)
        out["source"] = str(snap.get("source") or "vnstock_finance:vci")
        out["fetched_at"] = snap.get("fetched_at")
        # CFO/NI: chỉ khi thiếu hoặc force_refresh — tránh nhân HTTP trên mọi lần đọc cache.
        need_statements = force_refresh or (
            out.get("operating_cash_flow") is None or out.get("net_income") is None
        )
        allow_statements = str(os.environ.get("II_VNSTOCK_FETCH_STATEMENTS", "1")).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        if need_statements and allow_statements:
            try:
                stmts = _fetch_vnstock_finance_statements(sym, force_refresh=force_refresh)
                out = _merge_vnstock_statements(out, stmts)
            except VnstockProviderError as exc:
                logger.warning("vnstock_statements_skipped symbol=%s err=%s", sym, exc)
        try:
            company = _fetch_vnstock_company_profile(sym, force_refresh=force_refresh)
            for key in (
                "icb_sector",
                "free_float_pct",
                "outstanding_shares",
                "foreign_ownership_pct",
                "company_profile",
                "dividend_paid_years",
                "dividend_events_count",
                "dividend_years_list",
                "latest_dividend_value",
            ):
                if company.get(key) is not None:
                    out[key] = company[key]
            if company.get("dividend_paid_years") is not None:
                out["data_quality_score"] = int(out.get("data_quality_score") or 0) + 1
        except VnstockProviderError:
            pass
        if int(out.get("data_quality_score") or 0) < 2:
            raise PortalDataError(f"vnstock_finance:insufficient_metrics:{sym}")
        if force_refresh:
            out["source"] = "vnstock:live"
        return out
    except (VnstockProviderError,) as e:
        raise PortalDataError(f"vnstock_finance:{sym}:{e}") from e


def _fetch_financial_indicators_uncached(ticker: str, max_probes: int | None = None) -> dict[str, Any]:
    """
    Fetch core financial indicators from VNDirect ratios endpoint.

    Output keys:
    - debt_to_equity
    - gross_margin
    - revenue_growth_yoy, revenue_growth_qoq
    - profit_growth_yoy, profit_growth_qoq
    """
    sym = _norm_ticker(ticker)
    filters = (f"code:eq:{sym}", f"ticker:eq:{sym}", f"code:{sym}~", f"ticker:{sym}~")
    errors: list[str] = []

    def _extract_ratio_row(x: dict[str, Any], src: str) -> dict[str, Any]:
        out = {
            "symbol": sym,
            "debt_to_equity": _to_float(
                x.get("debtToEquity")
                or x.get("debt_equity")
                or x.get("debt/equity")
                or x.get("d/e")
            ),
            "gross_margin": _to_float(
                x.get("grossMargin")
                or x.get("grossProfitMargin")
                or x.get("gross_margin")
            ),
            "revenue_growth_yoy": _to_float(
                x.get("revenueGrowthYoy")
                or x.get("revenueGrowthYoY")
                or x.get("revenue_growth_yoy")
            ),
            "revenue_growth_qoq": _to_float(
                x.get("revenueGrowthQoq")
                or x.get("revenueGrowthQoQ")
                or x.get("revenue_growth_qoq")
            ),
            "profit_growth_yoy": _to_float(
                x.get("netIncomeGrowthYoy")
                or x.get("profitGrowthYoy")
                or x.get("profitGrowthYoY")
                or x.get("profit_growth_yoy")
            ),
            "profit_growth_qoq": _to_float(
                x.get("netIncomeGrowthQoq")
                or x.get("profitGrowthQoq")
                or x.get("profitGrowthQoQ")
                or x.get("profit_growth_qoq")
            ),
            "source": src,
            "raw": x,
        }
        quality = sum(
            out[k] is not None
            for k in (
                "debt_to_equity",
                "gross_margin",
                "revenue_growth_yoy",
                "revenue_growth_qoq",
                "profit_growth_yoy",
                "profit_growth_qoq",
            )
        )
        out["data_quality_score"] = quality
        return out

    urls: list[tuple[str, str]] = []
    for flt in filters:
        if "eq:" in flt:
            urls.append(
                (
                    "vndirect_v4_ratios_latest_filter",
                    "https://finfo-api.vndirect.com.vn/v4/ratios/latest"
                    f"?filter={quote(flt)}&order=reportType&direction=desc&size=1",
                )
            )
        else:
            urls.append(
                (
                    "vndirect_v4_ratios_latest_q",
                    "https://finfo-api.vndirect.com.vn/v4/ratios/latest"
                    f"?sort=code:asc&size=1&q={quote(flt)}",
                )
            )

    best: dict[str, Any] | None = None
    started = time.perf_counter()
    live_budget = _live_budget_seconds(12.0)
    for i, (src, url) in enumerate(urls):
        if max_probes is not None and i >= max_probes:
            break
        if time.perf_counter() - started > live_budget:
            errors.append("live_budget_exceeded")
            break
        try:
            req_timeout = _pick_timeout_for_probe(i, started, live_budget)
            r = requests.get(url, headers=VNDIRECT_HEADERS, timeout=req_timeout)
            if r.status_code != 200:
                errors.append(f"{src}:HTTP {r.status_code}")
                continue
            js = r.json()
            rows = js.get("data") if isinstance(js, dict) else None
            if not isinstance(rows, list) or not rows:
                errors.append(f"{src}:empty")
                continue
            cand = _extract_ratio_row(rows[0], src)
            if best is None or int(cand.get("data_quality_score") or 0) > int(best.get("data_quality_score") or 0):
                best = cand
            if int(cand.get("data_quality_score") or 0) >= 4:
                return cand
        except (requests.RequestException, ValueError) as e:
            errors.append(f"{src}:{e}")

    if best is not None:
        return best
    raise PortalDataError(f"Không lấy được chỉ số tài chính cho {sym}. Chi tiết: {' | '.join(errors)}")


def _fetch_financial_indicators_from_statements(ticker: str) -> dict[str, Any]:
    sym = _norm_ticker(ticker)
    rows, src = fetch_vndirect_financial_statement_rows(sym, size=12)
    if not rows:
        raise PortalDataError(f"Không có financial statements cho {sym}. Chi tiết: {src}")
    trend = compute_trend_metrics(rows)
    out = {
        "symbol": sym,
        "debt_to_equity": None,
        "gross_margin": None,
        "revenue_growth_yoy": trend.get("revenue_yoy_pct"),
        "revenue_growth_qoq": None,
        "profit_growth_yoy": trend.get("profit_yoy_pct"),
        "profit_growth_qoq": None,
        "data_quality_score": 0,
        "source": f"vndirect_financial_statements:{src}",
        "statement_periods": int(trend.get("periods") or 0),
        "trend_label": str(trend.get("trend_label") or ""),
        "yoy_compare_label_vi": str(trend.get("yoy_compare_label_vi") or ""),
    }
    out["data_quality_score"] = sum(
        out.get(k) is not None
        for k in (
            "debt_to_equity",
            "gross_margin",
            "revenue_growth_yoy",
            "profit_growth_yoy",
        )
    )
    return out


def _fetch_financial_indicators_from_fireant(ticker: str) -> dict[str, Any]:
    sym = _norm_ticker(ticker)
    base = "https://www.fireant.vn/api/Data/Finance"
    timeout = max(2.0, _float_env("II_FIREANT_TIMEOUT_SEC", 10.0))
    latest_url = f"{base}/LastestFinancialInfo?symbol={quote(sym)}"
    quarterly_url = (
        f"{base}/QuarterlyFinancialInfo?symbol={quote(sym)}"
        "&fromYear=2022&fromQuarter=1&toYear=2030&toQuarter=4"
    )
    latest: dict[str, Any] | None = None
    q_rows: list[dict[str, Any]] | None = None
    last_err = ""
    for _ in range(2):
        try:
            r_latest = requests.get(latest_url, timeout=timeout)
            if r_latest.status_code != 200:
                last_err = f"fireant_latest:HTTP {r_latest.status_code}"
                continue
            latest_js = r_latest.json()
            if not isinstance(latest_js, dict) or not latest_js:
                last_err = "fireant_latest:empty"
                continue
            r_q = requests.get(quarterly_url, timeout=timeout)
            if r_q.status_code != 200:
                last_err = f"fireant_quarterly:HTTP {r_q.status_code}"
                continue
            q_js = r_q.json()
            if not isinstance(q_js, list) or not q_js:
                last_err = "fireant_quarterly:empty"
                continue
            latest = latest_js
            q_rows = [x for x in q_js if isinstance(x, dict)]
            if q_rows:
                break
            last_err = "fireant_quarterly:invalid_rows"
        except (requests.RequestException, ValueError) as e:
            last_err = f"fireant:{e}"
            continue
    if latest is None or not q_rows:
        raise PortalDataError(last_err or "fireant:no_data")

    last_q = q_rows[-1]
    if not isinstance(last_q, dict):
        raise PortalDataError("fireant_quarterly:invalid_row")
    rev_yoy = _to_float(last_q.get("SalesGrowth_MRQ"))
    ni_yoy = _to_float(last_q.get("ProfitGrowth_MRQ"))
    gross_margin = _to_float(last_q.get("GrossMargin_TTM"))
    if gross_margin is None:
        gross_margin = _to_float(latest.get("GrossMargin"))
    dte = _to_float(last_q.get("TotalDebtToEquity_MRQ"))
    if dte is None:
        dte = _to_float(latest.get("TotalDebtOverEquity"))
    current_ratio = _to_float(last_q.get("CurrentRatio_MRQ"))
    if current_ratio is None:
        current_ratio = _to_float(latest.get("CurrentRatio"))
    ca = _to_float(last_q.get("CurrentAssets_MRQ"))
    if ca is None:
        ca = _to_float(latest.get("TotalCurrentAssets"))
    cl = _to_float(last_q.get("CurrentLiabilities_MRQ"))
    if cl is None:
        cl = _to_float(latest.get("TotalShortTermLiabilities"))
    if current_ratio is None and ca is not None and cl is not None and cl > 0:
        current_ratio = ca / cl
    net_income = _to_float(last_q.get("ProfitAfterTax_MRQ"))
    if net_income is None:
        net_income = _to_float(latest.get("ProfitAfterIncomeTaxes"))

    out = {
        "symbol": sym,
        "debt_to_equity": dte,
        "gross_margin": gross_margin,
        "revenue_growth_yoy": (rev_yoy * 100.0) if rev_yoy is not None and abs(rev_yoy) <= 3.0 else rev_yoy,
        "revenue_growth_qoq": None,
        "profit_growth_yoy": (ni_yoy * 100.0) if ni_yoy is not None and abs(ni_yoy) <= 3.0 else ni_yoy,
        "profit_growth_qoq": None,
        "current_ratio": current_ratio,
        "current_assets": ca,
        "current_liabilities": cl,
        "net_income": net_income,
        "data_quality_score": 0,
        "source": "fireant_finance_api",
        "statement_periods": len(q_rows),
        "yoy_compare_label_vi": f"Q{int(last_q.get('Quarter') or 0)}/{int(last_q.get('Year') or 0)} so với cùng kỳ",
    }
    out["data_quality_score"] = sum(
        out.get(k) is not None
        for k in (
            "debt_to_equity",
            "gross_margin",
            "revenue_growth_yoy",
            "profit_growth_yoy",
            "current_ratio",
            "net_income",
        )
    )
    if int(out["data_quality_score"] or 0) <= 0:
        raise PortalDataError("fireant:no_core_metrics")
    return out


def fetch_financial_indicators(
    ticker: str,
    *,
    fast_mode: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Cached financial indicators fetch."""
    sym = _norm_ticker(ticker)
    key = f"fin:{sym}"
    strict_real = _strict_real_financial_data()
    force_live = _financial_force_live_refresh(force_refresh=force_refresh)
    if not force_live:
        hit = _cache_get(key, _TTL_FIN_S)
        if hit is not None and (not strict_real or _is_real_financial_source(hit)):
            _sla_mark("financial_mem_cache", True)
            out_hit = dict(hit)
            if "data_trust" not in out_hit:
                out_hit = _attach_financial_data_trust(
                    out_hit,
                    source=str(out_hit.get("source") or "unknown"),
                    saved_at=str(out_hit.get("saved_at") or ""),
                    fallback_chain=["financial_mem_cache"],
                )
            return out_hit
    prefer_disk_first = _bool_env("II_FINANCIAL_DISK_FIRST", True) and not force_live
    # Trong phiên giao dịch: mặc định không cào BCTC realtime — chỉ dùng cache đĩa/DB.
    # Bật II_FINANCIAL_LIVE_REFRESH=1 hoặc force_refresh=True để bỏ qua cache và gọi vnstock live.
    allow_live_financial_refresh = force_live
    allow_stale_disk = _bool_env("II_READ_STALE_DISK", True)
    max_age_s = max(120.0, _float_env("II_FINANCIAL_DISK_MAX_AGE_SEC", 21600.0))
    cached = None if force_live else _read_fin_disk_cache(sym)
    max_probes_env = int(max(1, _float_env("II_FINANCIAL_MAX_PROBES", 4.0)))
    if cached is not None and (not strict_real or _is_real_financial_source(cached)) and _financial_swr_enabled():
        age_s = _fin_disk_cache_age_seconds(cached)
        swr_age_limit = _financial_swr_max_age_seconds(max_age_s)
        if age_s is None or age_s <= swr_age_limit:
            out_swr = _attach_financial_data_trust(
                dict(cached),
                source=f"{dict(cached).get('source', 'unknown')}:swr",
                saved_at=str(dict(cached).get("saved_at") or ""),
                stale_max_age_s=swr_age_limit,
                fallback_chain=["financial_disk_cache", "financial_swr"],
            )
            out_swr = _maybe_backfill_cfo(out_swr, sym)
            _cache_set(key, dict(out_swr))
            _sla_mark("financial_swr_served", True)
            _launch_financial_refresh(sym, max_probes=max_probes_env)
            return out_swr
    if cached is not None and (not strict_real or _is_real_financial_source(cached)) and prefer_disk_first:
        age_s = _fin_disk_cache_age_seconds(cached)
        fresh_enough = age_s is not None and age_s <= max_age_s
        if fresh_enough or allow_stale_disk:
            out_fast = _attach_financial_data_trust(
                dict(cached),
                source=f"{dict(cached).get('source', 'unknown')}:fastpath",
                saved_at=str(dict(cached).get("saved_at") or ""),
                stale_max_age_s=max_age_s,
                fallback_chain=["financial_disk_cache_fastpath"],
            )
            out_fast = _maybe_backfill_cfo(out_fast, sym)
            _sla_mark("financial_disk_cache_fastpath", True)
            _cache_set(key, dict(out_fast))
            return out_fast
    if cached is not None and (not strict_real or _is_real_financial_source(cached)) and not prefer_disk_first:
        _sla_mark("financial_disk_cache", True)
        out_cached = _attach_financial_data_trust(
            dict(cached),
            source=str(dict(cached).get("source") or "unknown"),
            saved_at=str(dict(cached).get("saved_at") or ""),
            stale_max_age_s=max_age_s,
            fallback_chain=["financial_disk_cache"],
        )
        out_cached = _maybe_backfill_cfo(out_cached, sym)
        _cache_set(key, dict(out_cached))
        return out_cached
    if fast_mode:
        # Fail-soft: không raise — caller (story/engine) dùng {} và derive từ snapshot.
        _sla_mark("financial_fast_mode_skip", False)
        return {
            "symbol": sym,
            "source": "unavailable_fast_mode",
            "notes_vi": [f"Fast mode: chưa có financial cache cho {sym}."],
        }
    if not allow_live_financial_refresh:
        if cached is not None and (not strict_real or _is_real_financial_source(cached)):
            out_cached = _attach_financial_data_trust(
                dict(cached),
                source=f"{dict(cached).get('source', 'unknown')}:session_cache",
                saved_at=str(dict(cached).get("saved_at") or ""),
                stale_max_age_s=max_age_s,
                fallback_chain=["financial_disk_cache", "session_no_live_scrape"],
            )
            _cache_set(key, dict(out_cached))
            _sla_mark("financial_session_cache_only", True)
            return out_cached
        raise PortalDataError(
            f"Financial indicators chưa có trong cache cho {sym}. "
            "Chạy refresh định kỳ (đêm/cuối tuần) hoặc đặt II_FINANCIAL_LIVE_REFRESH=1."
        )
    try:
        try:
            out = _fetch_financial_indicators_from_vnstock(sym, force_refresh=force_live)
            live_source = "vnstock:live" if force_live else str(out.get("source") or "unknown")
            out = _attach_financial_data_trust(
                out,
                source=live_source,
                fallback_chain=["financial_vnstock_live"],
            )
            _write_fin_disk_cache(sym, out)
            _sla_mark("financial_vnstock_live", True)
        except PortalDataError:
            _sla_mark("financial_vnstock_live", False)
            out = _fetch_financial_indicators_uncached(sym, max_probes=max_probes_env)
            out = _attach_financial_data_trust(
                out,
                source=str(out.get("source") or "unknown"),
                fallback_chain=["financial_vnstock_live", "financial_vndirect_live"],
            )
            _write_fin_disk_cache(sym, out)
            _sla_mark("financial_vndirect_live", True)
    except PortalDataError:
        _sla_mark("financial_vndirect_live", False)
        try:
            out = _fetch_financial_indicators_from_statements(sym)
            out = _attach_financial_data_trust(
                out,
                source=str(out.get("source") or "unknown"),
                fallback_chain=["financial_vndirect_live", "financial_statement_fallback"],
            )
            _write_fin_disk_cache(sym, out)
            _sla_mark("financial_statement_fallback", True)
        except PortalDataError:
            _sla_mark("financial_statement_fallback", False)
            try:
                out = _fetch_financial_indicators_from_fireant(sym)
                out = _attach_financial_data_trust(
                    out,
                    source=str(out.get("source") or "unknown"),
                    fallback_chain=["financial_vndirect_live", "financial_statement_fallback", "financial_fireant_fallback"],
                )
                _write_fin_disk_cache(sym, out)
                _sla_mark("financial_fireant_fallback", True)
            except PortalDataError:
                _sla_mark("financial_fireant_fallback", False)
                if force_live:
                    raise
                cached2 = _read_fin_disk_cache(sym)
                if cached2 is None or (strict_real and not _is_real_financial_source(cached2)):
                    raise
                out = _attach_financial_data_trust(
                    dict(cached2),
                    source=str(dict(cached2).get("source") or "unknown"),
                    saved_at=str(dict(cached2).get("saved_at") or ""),
                    stale_max_age_s=max_age_s,
                    fallback_chain=[
                        "financial_vndirect_live",
                        "financial_statement_fallback",
                        "financial_fireant_fallback",
                        "financial_disk_cache",
                    ],
                )
                _sla_mark("financial_disk_cache", True)
    if "data_trust" not in out:
        out = _attach_financial_data_trust(out, source=str(out.get("source") or "unknown"))
    _cache_set(key, dict(out))
    return out


def _normalize_news_item(title: str, link: str, source: str) -> dict[str, str]:
    return {"title": title.strip(), "url": link.strip(), "source": source}


def _fetch_cafef_news(ticker: str, limit: int = 10) -> list[dict[str, str]]:
    sym = _norm_ticker(ticker)
    url = f"https://cafef.vn/tim-kiem.chn?keywords={quote(sym)}"
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=_PORTAL_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        raise PortalDataError(f"CafeF news lỗi mạng: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    for a in soup.select("a"):
        title = _tag_attr_text(a.get("title")) or _tag_attr_text(a.get_text(" ", strip=True))
        href = _tag_attr_text(a.get("href"))
        if len(title) < 20 or sym not in title.upper():
            continue
        if not href:
            continue
        if href.startswith("/"):
            href = "https://cafef.vn" + href
        if "cafef.vn" not in href:
            continue
        key = f"{title}|{href}"
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalize_news_item(title, href, "cafef"))
        if len(out) >= limit:
            break
    return out


def _fetch_vietstock_news(ticker: str, limit: int = 10) -> list[dict[str, str]]:
    sym = _norm_ticker(ticker)
    url = f"https://vietstock.vn/tim-kiem.htm?keyword={quote(sym)}"
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=_PORTAL_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        raise PortalDataError(f"Vietstock news lỗi mạng: {e}") from e

    soup = BeautifulSoup(r.text, "html.parser")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for a in soup.select("a"):
        title = _tag_attr_text(a.get("title")) or _tag_attr_text(a.get_text(" ", strip=True))
        href = _tag_attr_text(a.get("href"))
        if len(title) < 20 or sym not in title.upper():
            continue
        if not href:
            continue
        if href.startswith("/"):
            href = "https://vietstock.vn" + href
        if "vietstock.vn" not in href:
            continue
        key = f"{title}|{href}"
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalize_news_item(title, href, "vietstock"))
        if len(out) >= limit:
            break
    return out


def _fetch_latest_news_uncached(ticker: str, limit: int = 10) -> list[dict[str, str]]:
    """Fetch latest headlines from CafeF/Vietstock, merged and deduplicated."""
    lim = max(1, min(limit, 30))
    items: list[dict[str, str]] = []
    errors: list[str] = []
    providers = (_fetch_cafef_news, _fetch_vietstock_news)
    budget = max(1.0, _live_budget_seconds(default_budget=6.0))

    # Fetch parallel from CafeF/Vietstock to cut end-to-end latency.
    try:
        with ThreadPoolExecutor(max_workers=len(providers)) as ex:
            futs = {ex.submit(fn, ticker, lim): fn.__name__ for fn in providers}
            for fut in as_completed(futs, timeout=budget):
                label = futs[fut]
                try:
                    got = fut.result()
                    if isinstance(got, list):
                        items.extend(got)
                except PortalDataError as e:
                    errors.append(f"{label}:{e}")
                except Exception as e:
                    errors.append(f"{label}:{e.__class__.__name__}:{e}")
    except TimeoutError:
        # Keep graceful behavior: return whatever source finished in budget.
        pass

    dedup: list[dict[str, str]] = []
    seen: set[str] = set()
    for x in items:
        key = f"{x.get('title')}|{x.get('url')}"
        if key in seen:
            continue
        seen.add(key)
        dedup.append(x)
        if len(dedup) >= lim:
            break

    if not dedup:
        raise PortalDataError(f"Không lấy được tin tức cho {ticker}. Chi tiết: {' | '.join(errors)}")
    return dedup


def fetch_latest_news(ticker: str, limit: int = 10) -> list[dict[str, str]]:
    """Cached latest headlines fetch."""
    sym = _norm_ticker(ticker)
    lim = max(1, min(limit, 30))
    key = f"news:{sym}:{lim}"
    hit = _cache_get(key, _TTL_NEWS_S)
    if hit is not None:
        _sla_mark("news_mem_cache", True)
        return [dict(x) for x in hit]
    disk_cached = _read_news_disk_cache(sym)
    if disk_cached is not None:
        cached_items, saved_at = disk_cached
        age_s = _news_disk_age_seconds(saved_at)
        if age_s is not None and age_s <= _news_disk_cache_ttl_seconds():
            out_cached = [dict(x) for x in cached_items[:lim]]
            _cache_set(key, out_cached)
            _sla_mark("news_disk_cache_fastpath", True)
            return out_cached
    try:
        out = _fetch_latest_news_uncached(sym, lim)
        _sla_mark("news_live", True)
    except PortalDataError:
        _sla_mark("news_live", False)
        if disk_cached is not None:
            cached_items, saved_at = disk_cached
            age_s = _news_disk_age_seconds(saved_at)
            if age_s is not None and age_s <= _news_disk_stale_fallback_seconds():
                out_cached = [dict(x) for x in cached_items[:lim]]
                _cache_set(key, out_cached)
                _sla_mark("news_disk_cache", True)
                return out_cached
        raise
    _cache_set(key, [dict(x) for x in out])
    _write_news_disk_cache(sym, [dict(x) for x in out])
    return out
