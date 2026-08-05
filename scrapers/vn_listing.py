"""
Danh sách mã giao dịch (VN) — ưu tiên API công khai, dự phòng metadata dự án.
Kết quả được cache file để không gọi API mỗi lần chạy.
"""

from __future__ import annotations

import functools
import json
import os
import string
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests  # type: ignore[import-untyped]

from scrapers.finance_scraper import VNDIRECT_HEADERS

_ROOT = Path(__file__).resolve().parent.parent
_LISTING_CACHE_PATH = _ROOT / "data" / "vn_listing_symbols.json"
_EXTRA_PATH = _ROOT / "data" / "vn_universe_extra.txt"
_META_PATH = _ROOT / "data" / "stock_metadata.json"


def _http_timeout() -> float:
    try:
        from core.config import http_timeout_seconds

        return http_timeout_seconds()
    except Exception:
        return 18.0


def _load_metadata_symbols() -> list[str]:
    if not _META_PATH.exists():
        return []
    try:
        with open(_META_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return []
        return sorted({str(k).strip().upper() for k in data if str(k).strip()})
    except (OSError, json.JSONDecodeError):
        return []


def _load_extra_txt() -> list[str]:
    if not _EXTRA_PATH.exists():
        return []
    out: list[str] = []
    try:
        text = _EXTRA_PATH.read_text(encoding="utf-8")
        for line in text.splitlines():
            sym = line.strip().upper().split("#")[0].strip()
            if sym and sym.isalnum():
                out.append(sym)
    except OSError:
        return []
    return out


def fetch_vnstock_listing_codes(
    *,
    exchange: str | None = None,
    icb_code: str | None = None,
) -> tuple[list[str], str, list[dict[str, Any]]]:
    """Primary listing source via vnstock Listing API."""
    try:
        from scrapers.vnstock_provider import fetch_listing_snapshot

        snap = fetch_listing_snapshot(exchange=exchange, icb_code=icb_code)
        codes = [str(x).upper() for x in snap.get("symbols") or []]
        records = list(snap.get("records") or [])
        detail = f"vnstock_listing:{snap.get('source', 'vci')}:count={len(codes)}"
        return codes, detail, records
    except Exception as e:
        return [], f"vnstock_listing_fail:{e}", []


def fetch_vndirect_stock_codes(*, size: int = 4000) -> tuple[list[str], str]:
    """
    Thử lấy danh sách mã từ Finfo v4/stocks. Trả (codes, detail).
    """
    url = f"https://finfo-api.vndirect.com.vn/v4/stocks?size={size}&sort=code:asc"
    try:
        r = requests.get(url, headers=VNDIRECT_HEADERS, timeout=_http_timeout())
        if r.status_code != 200:
            return [], f"HTTP{r.status_code}"
        js = r.json()
        rows = js.get("data") if isinstance(js, dict) else None
        if not isinstance(rows, list):
            return [], "no_data"
        codes: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            c = row.get("code") or row.get("ticker") or row.get("symbol")
            if c:
                s = str(c).strip().upper()
                if 2 <= len(s) <= 6 and s.replace("&", "").isalnum():
                    codes.append(s)
        return sorted(set(codes)), "ok"
    except requests.RequestException as e:
        return [], str(e)


def fetch_fireant_stock_codes(*, max_depth: int = 2, max_requests: int = 700) -> tuple[list[str], str]:
    """
    Fallback listing discovery via FireAnt symbol search.
    Breadth-first prefix crawl (A..Z,0..9) to bypass 10-row autocomplete cap.
    """
    base = "https://www.fireant.vn/api/Data/Markets/SearchSymbol?symbol="
    allowed_exchanges = {"HOSTC", "HASTC", "UPCOM"}
    alphabet = string.ascii_uppercase + string.digits
    queue: list[tuple[str, int]] = [(ch, 1) for ch in alphabet]
    seen_prefix: set[str] = set()
    codes: set[str] = set()
    req_n = 0
    timeout = max(4.0, _http_timeout())
    while queue and req_n < max_requests:
        prefix, depth = queue.pop(0)
        if prefix in seen_prefix:
            continue
        seen_prefix.add(prefix)
        try:
            r = requests.get(base + prefix, timeout=timeout)
            req_n += 1
            if r.status_code != 200:
                continue
            js = r.json()
            items = js.get("Items") if isinstance(js, dict) else None
            if not isinstance(items, list):
                continue
            for it in items:
                if not isinstance(it, dict):
                    continue
                ex = str(it.get("Exchange") or "").strip().upper()
                sym = str(it.get("Symbol") or "").strip().upper()
                if ex in allowed_exchanges and 2 <= len(sym) <= 6 and sym.isalnum():
                    codes.add(sym)
            if len(items) >= 10 and depth < max_depth:
                for ch in alphabet:
                    queue.append((prefix + ch, depth + 1))
        except (requests.RequestException, ValueError):
            continue
    if not codes:
        return [], f"fireant_empty:req={req_n}"
    return sorted(codes), f"fireant_ok:req={req_n}"


def read_listing_cache_codes(*, ignore_age: bool = True, max_age_hours: float = 24.0) -> list[str]:
    """
    Đọc mã từ data/vn_listing_symbols.json (không gọi mạng).
    ignore_age=True: dùng cache dù cũ — phù hợp Autopilot disk-first.
    """
    if not _LISTING_CACHE_PATH.exists():
        return []
    try:
        with open(_LISTING_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return []
        codes = raw.get("codes")
        if not isinstance(codes, list):
            return []
        if not ignore_age:
            ts = raw.get("fetched_at")
            if not ts:
                return []
            try:
                fetched = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age_h = (datetime.now(timezone.utc) - fetched).total_seconds() / 3600.0
                if age_h >= max_age_hours:
                    return []
            except ValueError:
                return []
        return [str(x).upper() for x in codes if x]
    except (OSError, json.JSONDecodeError):
        return []


def load_or_refresh_listing_cache(*, max_age_hours: float = 24.0) -> tuple[list[str], str]:
    """
    Đọc cache file nếu còn mới; nếu không thì gọi API và ghi cache.
    """
    now = datetime.now(timezone.utc)
    fresh = read_listing_cache_codes(ignore_age=False, max_age_hours=max_age_hours)
    if fresh:
        return fresh, "disk_fresh"

    codes, detail, records = fetch_vnstock_listing_codes()
    source = "vnstock_listing_symbols_by_exchange"
    if not codes:
        codes, detail = fetch_vndirect_stock_codes()
        source = "vndirect_finfo_v4_stocks"
        records = []
    if not codes:
        fa_codes, fa_detail = fetch_fireant_stock_codes()
        if fa_codes:
            codes = fa_codes
            detail = fa_detail
            source = "fireant_searchsymbol_crawl"
            records = []
        else:
            merged = sorted(set(_load_metadata_symbols()) | set(_load_extra_txt()))
            return merged, f"api_fail:{detail}|{fa_detail}"

    payload = {
        "fetched_at": now.isoformat(),
        "source": source,
        "detail": detail,
        "codes": codes,
        "records": records,
    }
    _LISTING_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_LISTING_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError:
        pass
    return codes, detail


def _vn_listing_mem_ttl_sec() -> float:
    try:
        return max(15.0, float(os.environ.get("II_VN_LISTING_MEM_TTL_SEC", "300")))
    except ValueError:
        return 300.0


# Cache in-process list (Auto Pilot + scan gọi list nhiều lần/giây sau khi có luân phiên universe).
_ltv_mem_ts: float = 0.0
_ltv_mem_data: list[str] | None = None
_ltv_mem_use_api: bool | None = None


def list_symbols_by_exchange(exchange: str, *, use_api: bool = True) -> list[str]:
    """Return tradable symbols filtered by exchange (HOSE/HNX/UPCOM)."""
    ex = str(exchange or "").strip().upper()
    if not ex:
        return []
    if use_api and os.environ.get("II_VN_LISTING_API", "1").strip().lower() not in ("0", "false", "no"):
        codes, _, _ = fetch_vnstock_listing_codes(exchange=ex)
        if codes:
            return sorted(set(codes) | set(_load_metadata_symbols()) | set(_load_extra_txt()))
    all_codes = list_tradable_vn_symbols(use_api=use_api)
    if not _LISTING_CACHE_PATH.exists():
        return [c for c in all_codes if c]
    try:
        with open(_LISTING_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        records = raw.get("records") if isinstance(raw, dict) else None
        if isinstance(records, list) and records:
            ex_norm = {"HOSE": "HOSE", "HSX": "HOSE"}.get(ex, ex)
            out = {
                str(r.get("symbol", "")).upper()
                for r in records
                if isinstance(r, dict)
                and str(r.get("exchange_norm") or r.get("exchange") or "").upper() in {ex, ex_norm, "HSX"}
            }
            return sorted(out & set(all_codes)) if out else all_codes
    except (OSError, json.JSONDecodeError):
        pass
    return all_codes


def symbol_industry_map(*, use_api: bool = True) -> dict[str, str]:
    """Map symbol → ICB code from vnstock listing cache."""
    if not _LISTING_CACHE_PATH.exists():
        return {}
    try:
        with open(_LISTING_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        records = raw.get("records") if isinstance(raw, dict) else None
        if not isinstance(records, list):
            return {}
        out: dict[str, str] = {}
        for row in records:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip().upper()
            icb = str(row.get("icb_code") or row.get("icb_code2") or "").strip()
            if sym and icb:
                out[sym] = icb
        return out
    except (OSError, json.JSONDecodeError):
        return {}


def list_tradable_vn_symbols(*, use_api: bool = True) -> list[str]:
    """
    Hợp nhất: API listing (nếu bật) + stock_metadata.json + vn_universe_extra.txt.
    Kết quả được giữ trong RAM một khoảng (II_VN_LISTING_MEM_TTL_SEC) để giảm đọc lặp.
    """
    global _ltv_mem_ts, _ltv_mem_data, _ltv_mem_use_api
    now = time.time()
    if (
        _ltv_mem_data is not None
        and _ltv_mem_use_api == use_api
        and (now - _ltv_mem_ts) < _vn_listing_mem_ttl_sec()
    ):
        return list(_ltv_mem_data)
    api_codes: list[str] = []
    note = ""
    if use_api and os.environ.get("II_VN_LISTING_API", "1").strip().lower() not in ("0", "false", "no"):
        api_codes, note = load_or_refresh_listing_cache()
    else:
        # Disk-first: vẫn lấy full listing từ file cache, không gọi mạng.
        api_codes = read_listing_cache_codes(ignore_age=True)
        note = "disk_only" if api_codes else "disk_empty"
    meta = _load_metadata_symbols()
    extra = _load_extra_txt()
    merged = sorted(set(api_codes) | set(meta) | set(extra))
    _ltv_mem_ts = now
    _ltv_mem_data = merged
    _ltv_mem_use_api = use_api
    return list(merged)


def tradable_vn_symbol_count(*, use_api: bool = True) -> int:
    """
    Số lượng mã niêm yết VN (API + metadata + extra).
    Khi cache RAM còn TTL: không tạo list đầy đủ — chỉ đếm (sidebar / tổng universe).
    """
    global _ltv_mem_ts, _ltv_mem_data, _ltv_mem_use_api
    now = time.time()
    if (
        _ltv_mem_data is not None
        and _ltv_mem_use_api == use_api
        and (now - _ltv_mem_ts) < _vn_listing_mem_ttl_sec()
    ):
        return len(_ltv_mem_data)
    return len(list_tradable_vn_symbols(use_api=use_api))


def tradable_vn_symbol_count_fast() -> int:
    """
    Đếm mã cho UI (sidebar) — chỉ đọc cache đĩa + metadata, không gọi API.
    Tránh kẹt Streamlit khi VNDirect/FireAnt chậm hoặc timeout lần đầu.
    """
    api_codes = read_listing_cache_codes(ignore_age=True)
    return len(sorted(set(api_codes) | set(_load_metadata_symbols()) | set(_load_extra_txt())))


def _vn_symbol_guard_enabled() -> bool:
    return os.environ.get("II_VN_SYMBOL_GUARD", "1").strip().lower() not in ("0", "false", "no", "off")


@functools.lru_cache(maxsize=1)
def _tradable_vn_symbol_frozen() -> frozenset[str]:
    return frozenset(list_tradable_vn_symbols(use_api=True))


def clear_tradable_vn_symbol_cache() -> None:
    """Gọi sau khi monkeypatch listing trong test hoặc khi làm mới cache thủ công."""
    global _ltv_mem_data, _ltv_mem_use_api
    _tradable_vn_symbol_frozen.cache_clear()
    _ltv_mem_data = None
    _ltv_mem_use_api = None


def is_tradable_vn_symbol(sym: str) -> bool:
    """
    True nếu mã thuộc listing cổ phiếu VN (HOSE/HNX/UPCOM + metadata/extra).
    Khi listing chưa tải đủ (<50 mã, thường là API lỗi/offline), không chặn để dev vẫn chạy.
    Tắt kiểm: II_VN_SYMBOL_GUARD=0.
    """
    if not _vn_symbol_guard_enabled():
        return True
    u = (sym or "").strip().upper()
    if not u or not (2 <= len(u) <= 6 and u.isalnum()):
        return False
    bag = _tradable_vn_symbol_frozen()
    if len(bag) < 50:
        return True
    return u in bag


def listing_cache_info() -> dict[str, Any]:
    if not _LISTING_CACHE_PATH.exists():
        return {"path": str(_LISTING_CACHE_PATH), "exists": False}
    try:
        with open(_LISTING_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        return {
            "path": str(_LISTING_CACHE_PATH),
            "exists": True,
            "fetched_at": raw.get("fetched_at") if isinstance(raw, dict) else None,
            "count": len(raw.get("codes") or []) if isinstance(raw, dict) else 0,
        }
    except (OSError, json.JSONDecodeError):
        return {"path": str(_LISTING_CACHE_PATH), "exists": True, "error": True}
