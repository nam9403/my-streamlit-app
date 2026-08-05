"""
Cào chỉ số định giá: thứ tự nguồn giá cấu hình được (mặc định VNDirect → CafeF → Vietstock).
Cache JSON cục bộ 24h để tra cứu lại cùng mã nhanh hơn.

Lưu ý: SSI iBoard (web) chủ yếu là SPA — không có HTML chứa giá; Fast Connect cần API key.
Đổi thứ tự nguồn: biến II_QUOTE_PROVIDER_ORDER (vd: vndirect,cafef,vietstock).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import requests  # type: ignore
from bs4 import BeautifulSoup

_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _ROOT / "data" / "scrape_cache.json"
_CACHE_TTL = timedelta(hours=float(os.environ.get("VALUE_INVESTOR_CACHE_HOURS", "24")))
_CACHE_DISABLED = os.environ.get("VALUE_INVESTOR_DISABLE_CACHE", "").lower() in ("1", "true", "yes")

_SCRAPE_RAW_MEM: dict[str, Any] | None = None
_SCRAPE_RAW_MTIME: float = -2.0
_SCRAPE_CACHE_PATH_KEY: str | None = None


def _invalidate_scrape_file_cache_mem() -> None:
    global _SCRAPE_RAW_MEM, _SCRAPE_RAW_MTIME
    _SCRAPE_RAW_MEM = None
    _SCRAPE_RAW_MTIME = -2.0

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
}

VNDIRECT_HEADERS = {
    **DEFAULT_HEADERS,
    "Accept": "application/json",
    "Origin": "https://www.vndirect.com.vn",
    "Referer": "https://www.vndirect.com.vn/",
}

def _request_timeout() -> float:
    try:
        from core.config import http_timeout_seconds

        return http_timeout_seconds()
    except Exception:
        return float(os.environ.get("VALUE_INVESTOR_SCRAPER_TIMEOUT", "18"))


def _cafef_timeout() -> float:
    """CafeF HTML chậm — timeout riêng ngắn hơn để fail-fast sang VNDirect/Vietstock."""
    raw = os.environ.get("II_CAFEF_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1.5, float(raw))
        except ValueError:
            pass
    return max(1.5, min(4.0, float(_request_timeout())))


def _cafef_max_boards() -> int:
    try:
        return max(1, min(3, int(os.environ.get("II_CAFEF_MAX_BOARDS", "1"))))
    except ValueError:
        return 1

# Thứ tự thử sau khi hết cache (mỗi hàm trả dict hoặc raise)
ProviderFn = Callable[[str], dict[str, Any]]


class ScraperError(Exception):
    """Lỗi chung khi cào dữ liệu."""


class TickerNotFoundError(ScraperError):
    """Không tìm thấy mã hoặc trang không có dữ liệu giá."""


class ScraperBlockedError(ScraperError):
    """Trang trả 403 / thông báo chặn bot / thiếu quyền."""


class ScraperParseError(ScraperError):
    """HTTP 200 nhưng không trích được cấu trúc mong đợi."""


def _parse_vn_number(s: str | None) -> float | None:
    if s is None or s in ("-", "", "N/A", "n/a"):
        return None
    s = str(s).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _num_from_obj(row: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        if k not in row or row[k] is None:
            continue
        v = _parse_vn_number(str(row[k]))
        if v is not None:
            return v
    return None


def _vndirect_row_sort_key(row: dict[str, Any]) -> datetime:
    """Chọn bản ghi stock_prices có ngày giao dịch mới nhất (API có thể không sort)."""
    for k in ("date", "tradingDate", "trading_date"):
        v = row.get(k)
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        try:
            if "T" in s:
                return datetime.fromisoformat(s.replace("Z", "+00:00"))
            parts = s[:10].split("-")
            if len(parts) == 3:
                y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
                return datetime(y, m, d, tzinfo=timezone.utc)
        except (ValueError, TypeError, OSError):
            continue
    return datetime.min.replace(tzinfo=timezone.utc)


def _pick_latest_vndirect_price_row(rows: list[dict[str, Any]], sym: str) -> dict[str, Any]:
    """
    VNDirect /v4/stock-prices trả list nhiều phiên; phải lấy phiên mới nhất, không phải phần tử đầu.
    """
    sy = sym.strip().upper()
    cands = [x for x in rows if str(x.get("code") or x.get("ticker") or "").strip().upper() == sy]
    if not cands:
        cands = list(rows)
    if not cands:
        raise TickerNotFoundError(f"VNDirect: không có dòng giá cho {sym}.")
    return max(cands, key=_vndirect_row_sort_key)


def _extract_json_string(html: str, key: str) -> str | None:
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', html)
    return m.group(1) if m else None


def _extract_last_price_vnd(html: str) -> float | None:
    m = re.search(
        r'"LastPrice":"(?:[^"\\]|\\.)*?\\u003e([\d,]+)\\u003c',
        html,
    )
    if m:
        return _parse_vn_number(m.group(1))
    plain = _extract_json_string(html, "LastPrice")
    if plain:
        digits = re.search(r"([\d,]+)", plain)
        if digits:
            return _parse_vn_number(digits.group(1))
    return None


def _page_looks_blocked(html: str, status_code: int) -> bool:
    if status_code in (403, 429):
        return True
    low = html.lower()
    if "just a moment" in low and "cloudflare" in low:
        return True
    if "checking your browser before accessing" in low:
        return True
    return False


def _vietstock_company_name(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if ":" in t:
            return t.split(":", 1)[0].strip()
        return t
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_industry_vietstock(html: str) -> str | None:
    """Thử đọc tên ngành / ICB từ JSON nhúng trang Vietstock (nếu có)."""
    for key in (
        "ICBName",
        "ICB4Name",
        "IndustryName",
        "Industry",
        "SectorName",
        "BranchNameL2",
        "BranchName",
    ):
        m = _extract_json_string(html, key)
        if m and len(m.strip()) > 2 and m.strip() not in ("-", "N/A"):
            return m.strip()
    return None


# --- Cache ---


def _cache_read_all() -> dict[str, Any]:
    if _CACHE_DISABLED:
        return {}
    global _SCRAPE_RAW_MEM, _SCRAPE_RAW_MTIME, _SCRAPE_CACHE_PATH_KEY
    ck = str(_CACHE_PATH.resolve())
    if _SCRAPE_CACHE_PATH_KEY != ck:
        _invalidate_scrape_file_cache_mem()
        _SCRAPE_CACHE_PATH_KEY = ck
    try:
        mt = float(_CACHE_PATH.stat().st_mtime) if _CACHE_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    if _SCRAPE_RAW_MEM is not None and _SCRAPE_RAW_MTIME == mt:
        return _SCRAPE_RAW_MEM
    if not _CACHE_PATH.exists():
        empty: dict[str, Any] = {}
        _SCRAPE_RAW_MEM = empty
        _SCRAPE_RAW_MTIME = -1.0
        return empty
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        payload = raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    try:
        mt = float(_CACHE_PATH.stat().st_mtime) if _CACHE_PATH.exists() else -1.0
    except OSError:
        mt = -1.0
    _SCRAPE_RAW_MEM = payload
    _SCRAPE_RAW_MTIME = mt
    return payload


def _cache_write_all(data: dict[str, Any]) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".json", dir=_CACHE_PATH.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _CACHE_PATH)
        global _SCRAPE_RAW_MEM, _SCRAPE_RAW_MTIME, _SCRAPE_CACHE_PATH_KEY
        try:
            mt = float(_CACHE_PATH.stat().st_mtime)
        except OSError:
            mt = -1.0
        _SCRAPE_RAW_MEM = data
        _SCRAPE_RAW_MTIME = mt
        _SCRAPE_CACHE_PATH_KEY = str(_CACHE_PATH.resolve())
    except OSError:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _strip_volatile_fields(d: dict[str, Any]) -> dict[str, Any]:
    """Không lưu các trường chỉ dùng cho một lần phản hồi."""
    out = {k: v for k, v in d.items() if k not in ("cache_hit", "cache_age_seconds")}
    return out


def _cache_get(sym: str) -> dict[str, Any] | None:
    if _CACHE_DISABLED:
        return None
    all_c = _cache_read_all()
    entry = all_c.get(sym.upper())
    if not entry or not isinstance(entry, dict):
        return None
    saved_s = entry.get("saved_at")
    payload = entry.get("data")
    if not saved_s or not isinstance(payload, dict):
        return None
    try:
        saved = datetime.fromisoformat(saved_s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if datetime.now(timezone.utc) - saved > _CACHE_TTL:
        return None
    age = (datetime.now(timezone.utc) - saved).total_seconds()
    out = dict(payload)
    out["cache_hit"] = True
    out["cache_age_seconds"] = int(age)
    out["source"] = f"cache:{out.get('source', 'unknown')}"
    return out


def _cache_set(sym: str, data: dict[str, Any]) -> None:
    if _CACHE_DISABLED:
        return
    sym_u = sym.upper()
    all_c = _cache_read_all()
    clean = _strip_volatile_fields(dict(data))
    clean["scraped_at"] = datetime.now(timezone.utc).isoformat()
    all_c[sym_u] = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "data": clean,
    }
    try:
        _cache_write_all(all_c)
    except OSError:
        pass


# --- Vietstock ---


def _fetch_vietstock(ticker: str) -> dict[str, Any]:
    sym = ticker.strip().upper()
    if not sym or not re.fullmatch(r"[A-Z0-9]{2,6}", sym):
        raise TickerNotFoundError(f"Mã không hợp lệ: {ticker!r}")

    url = f"https://finance.vietstock.vn/{quote(sym)}/tai-chinh.htm"
    try:
        r = requests.get(url, headers=DEFAULT_HEADERS, timeout=_request_timeout())
    except requests.Timeout as e:
        raise ScraperError("Hết thời gian chờ Vietstock.") from e
    except requests.RequestException as e:
        raise ScraperError(f"Lỗi mạng khi gọi Vietstock: {e}") from e

    if r.status_code == 404:
        raise TickerNotFoundError(f"Không tìm thấy trang Vietstock cho {sym}.")

    text = r.text
    if _page_looks_blocked(text, r.status_code):
        raise ScraperBlockedError(
            "Vietstock có thể đang chặn truy cập tự động (403/bot). "
            "Thử lại sau hoặc dùng mạng/IP khác."
        )

    if '"LastPrice"' not in text and '"EPS"' not in text:
        raise TickerNotFoundError(
            f"Trang Vietstock không chứa dữ liệu giá cho mã {sym} (mã sai hoặc chưa niêm yết?)."
        )

    price = _extract_last_price_vnd(text)
    eps = _parse_vn_number(_extract_json_string(text, "EPS"))
    pe = _parse_vn_number(_extract_json_string(text, "PE"))
    pb = _parse_vn_number(_extract_json_string(text, "PB"))
    bvps = _parse_vn_number(_extract_json_string(text, "BVPS"))
    mcap = _parse_vn_number(_extract_json_string(text, "MarketCapital"))

    if price is None or price <= 0:
        raise ScraperParseError("Không đọc được giá khớp lệnh (LastPrice) từ Vietstock.")

    name = _vietstock_company_name(text)
    industry_vs = _extract_industry_vietstock(text)

    shareholders_equity: float | None = None
    if bvps is not None and bvps > 0 and mcap is not None and mcap > 0:
        cap_vnd = mcap * 1e9
        shares_est = cap_vnd / price
        if shares_est > 0:
            shareholders_equity = bvps * shares_est

    return {
        "symbol": sym,
        "name": name,
        "price": float(price),
        "eps": float(eps) if eps is not None else 0.0,
        "pe_ratio": float(pe) if pe is not None else None,
        "pb_ratio": float(pb) if pb is not None else None,
        "book_value_per_share": float(bvps) if bvps is not None else 0.0,
        "shareholders_equity": float(shareholders_equity)
        if shareholders_equity is not None
        else None,
        "market_cap_billion_vnd": float(mcap) if mcap is not None else None,
        "currency": "VND",
        "growth_rate_pct": 0.0,
        "bond_yield_pct": 4.4,
        "source": "vietstock",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "piotroski": {},
        **({"industry": industry_vs} if industry_vs else {}),
    }


# --- VNDirect Finfo (nguồn B — API JSON công khai) ---


def _fetch_vndirect_finfo(ticker: str) -> dict[str, Any]:
    sym = ticker.strip().upper()
    if not sym or not re.fullmatch(r"[A-Z0-9]{2,6}", sym):
        raise TickerNotFoundError(f"Mã không hợp lệ: {ticker!r}")

    q_url = (
        "https://finfo-api.vndirect.com.vn/v4/stock-prices"
        f"?sort=code:asc&q=code:{quote(sym)}~"
    )
    try:
        r = requests.get(q_url, headers=VNDIRECT_HEADERS, timeout=_request_timeout())
    except requests.Timeout as e:
        raise ScraperError("Hết thời gian chờ VNDirect Finfo.") from e
    except requests.RequestException as e:
        raise ScraperError(f"Lỗi mạng VNDirect: {e}") from e

    if r.status_code in (403, 429):
        raise ScraperBlockedError("VNDirect Finfo từ chối hoặc giới hạn truy cập.")
    if r.status_code == 404:
        raise TickerNotFoundError(f"Không tìm thấy mã {sym} trên VNDirect.")

    try:
        js = r.json()
    except ValueError as e:
        raise ScraperParseError("VNDirect trả về không phải JSON.") from e

    rows = js.get("data") if isinstance(js, dict) else None
    if not rows or not isinstance(rows, list):
        raise TickerNotFoundError(f"VNDirect không có dữ liệu giá cho {sym}.")

    row = _pick_latest_vndirect_price_row(rows, sym)

    price = _num_from_obj(
        row,
        "lastPrice",
        "close",
        "matchPrice",
        "price",
        "last",
    )
    if price is None or price <= 0:
        raise ScraperParseError("VNDirect: không đọc được giá.")

    name = str(row.get("stockName") or row.get("name") or row.get("organName") or sym)

    pe = pb = eps = bvps = mcap_b = None
    ratio_filters = (
        f"code:eq:{sym}",
        f"ticker:eq:{sym}",
    )
    try:
        for flt in ratio_filters:
            ratio_url = (
                "https://finfo-api.vndirect.com.vn/v4/ratios/latest"
                f"?filter={quote(flt)}&order=reportType&direction=desc&size=1"
            )
            rr = requests.get(ratio_url, headers=VNDIRECT_HEADERS, timeout=_request_timeout())
            if rr.status_code != 200:
                continue
            rj = rr.json()
            rrows = rj.get("data") if isinstance(rj, dict) else None
            if not isinstance(rrows, list) or not rrows:
                continue
            r0 = rrows[0]
            pe = _num_from_obj(r0, "pe", "PE", "priceToEarning")
            pb = _num_from_obj(r0, "pb", "PB", "priceToBook")
            eps = _num_from_obj(r0, "eps", "EPS", "earningPerShare")
            bvps = _num_from_obj(r0, "bvps", "BVPS", "bookValuePerShare")
            mcap_b = _num_from_obj(
                r0,
                "marketCap",
                "marketCapitalization",
            )
            if pe is not None or pb is not None or eps is not None:
                break
    except (requests.RequestException, ValueError, TypeError):
        pass

    if eps is None:
        eps = (price / pe) if pe and pe > 0 else 0.0
    else:
        eps = float(eps)

    if bvps is None and pb and pb > 0:
        bvps = price / pb
    bvps_f = float(bvps) if bvps is not None else 0.0

    shareholders_equity: float | None = None
    if mcap_b is not None and mcap_b > 0 and bvps_f > 0:
        cap_vnd = float(mcap_b) * 1e9
        sh = cap_vnd / price if price else 0
        if sh > 0:
            shareholders_equity = bvps_f * sh
    elif mcap_b is None:
        mcap_b = _num_from_obj(row, "marketCap", "mcap")

    price_date = row.get("date") or row.get("tradingDate") or ""

    return {
        "symbol": sym,
        "name": name,
        "price": float(price),
        "price_as_of": str(price_date)[:32] if price_date else "",
        "eps": float(eps) if eps else 0.0,
        "eps_basis": "vndirect_ratios_latest",
        "eps_basis_label_vi": (
            "EPS từ VNDirect ratios/latest (LNTT/cổ theo báo cáo gần nhất; thường tương đương TTM hoặc năm tài chính gần nhất)"
        ),
        "pe_ratio": float(pe) if pe is not None else None,
        "pb_ratio": float(pb) if pb is not None else None,
        "book_value_per_share": bvps_f,
        "shareholders_equity": float(shareholders_equity) if shareholders_equity is not None else None,
        "market_cap_billion_vnd": float(mcap_b) if mcap_b is not None else None,
        "currency": "VND",
        "growth_rate_pct": 0.0,
        "bond_yield_pct": 4.4,
        "source": "vndirect_finfo",
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "piotroski": {},
    }


# --- CafeF ---


def _fetch_cafef_thong_tin_co_ban(ticker: str) -> dict[str, Any] | None:
    sym = ticker.strip().lower()
    # HOSE trước (phần lớn thanh khoản); giới hạn số board để tránh chờ 3× timeout.
    boards = ("hose", "hnx", "upcom")[: _cafef_max_boards()]
    timeout = _cafef_timeout()
    for board in boards:
        url = f"https://cafef.vn/du-lieu/{board}/{sym}-thong-tin-co-ban.chn"
        try:
            r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
        except requests.RequestException:
            continue
        if r.status_code != 200 or len(r.text) < 5000:
            continue
        if _page_looks_blocked(r.text, r.status_code):
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        text_blob = soup.get_text("\n", strip=True)
        if sym.upper() not in text_blob.upper():
            continue
        price_m = re.search(
            r"Giá\s*[:：]?\s*([\d.,]+)",
            text_blob,
            re.IGNORECASE,
        )
        price = _parse_vn_number(price_m.group(1) if price_m else None)
        if price is None or price <= 0:
            continue
        name = ""
        if soup.title and soup.title.string:
            name = soup.title.string.strip()
        return {
            "symbol": ticker.strip().upper(),
            "name": name,
            "price": float(price),
            "eps": 0.0,
            "pe_ratio": None,
            "pb_ratio": None,
            "book_value_per_share": 0.0,
            "shareholders_equity": None,
            "market_cap_billion_vnd": None,
            "currency": "VND",
            "growth_rate_pct": 0.0,
            "bond_yield_pct": 4.4,
            "source": f"cafef_{board}",
            "scraped_at": datetime.now(timezone.utc).isoformat(),
            "piotroski": {},
        }
    return None


def _fetch_cafef_thong_tin_co_ban_or_raise(ticker: str) -> dict[str, Any]:
    out = _fetch_cafef_thong_tin_co_ban(ticker)
    if out is None:
        raise TickerNotFoundError(f"CafeF: không đọc được giá thông tin cơ bản cho {ticker.strip().upper()}.")
    return out


def _quote_provider_order_tokens() -> list[str]:
    # VNDirect API thường nhanh/ổn định hơn CafeF HTML — mặc định ưu tiên API.
    raw = str(os.environ.get("II_QUOTE_PROVIDER_ORDER", "vndirect,cafef,vietstock") or "").strip().lower()
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    return parts or ["vndirect", "cafef", "vietstock"]


def _build_quote_providers() -> list[tuple[str, ProviderFn]]:
    """Thứ tự thử nguồn giá — mặc định VNDirect → CafeF → Vietstock (tối ưu latency)."""
    name_to_fn: dict[str, ProviderFn] = {
        "cafef": _fetch_cafef_thong_tin_co_ban_or_raise,
        "vndirect": _fetch_vndirect_finfo,
        "vndirect_finfo": _fetch_vndirect_finfo,
        "vietstock": _fetch_vietstock,
    }
    out: list[tuple[str, ProviderFn]] = []
    seen: set[str] = set()
    for tok in _quote_provider_order_tokens():
        key = tok.strip().lower()
        fn = name_to_fn.get(key)
        if fn is None or key in seen:
            continue
        seen.add(key)
        out.append((key, fn))
    for key, fn in (
        ("vndirect", _fetch_vndirect_finfo),
        ("cafef", _fetch_cafef_thong_tin_co_ban_or_raise),
        ("vietstock", _fetch_vietstock),
    ):
        if key not in seen:
            out.append((key, fn))
            seen.add(key)
    return out


def _try_providers(
    sym: str,
    providers: list[tuple[str, ProviderFn]],
    *,
    budget_sec: float | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    t0 = time.perf_counter()
    for label, fn in providers:
        if budget_sec is not None and (time.perf_counter() - t0) >= float(budget_sec):
            errors.append(f"budget_exhausted:{budget_sec}s")
            break
        try:
            return fn(sym)
        except (TickerNotFoundError, ScraperBlockedError, ScraperParseError) as e:
            errors.append(f"{label}: {e}")
        except ScraperError as e:
            errors.append(f"{label}: {e}")
        except requests.RequestException as e:
            errors.append(f"{label}: {e}")

    raise ScraperError(
        "Không lấy được dữ liệu từ mọi nguồn đã cấu hình (xem II_QUOTE_PROVIDER_ORDER). "
        "Chi tiết: "
        + " | ".join(errors)
    )


def get_quote_price_fast(
    ticker: str,
    *,
    budget_sec: float | None = None,
    max_providers: int | None = None,
) -> dict[str, Any] | None:
    """
    Chỉ cần giá tươi nhanh: thử providers theo thứ tự, tôn trọng budget.
    Không đọc/ghi scrape-file cache. Trả None nếu hết budget/thất bại.
    """
    sym = ticker.strip().upper()
    if not sym or not re.fullmatch(r"[A-Z0-9]{2,6}", sym):
        return None
    providers = _build_quote_providers()
    if max_providers is not None:
        providers = providers[: max(1, int(max_providers))]

    # Siết timeout HTTP trong cửa sổ budget (tránh 1 provider nuốt hết ngân sách).
    prev_http = os.environ.get("II_HTTP_TIMEOUT")
    prev_scraper = os.environ.get("VALUE_INVESTOR_SCRAPER_TIMEOUT")
    prev_cafef = os.environ.get("II_CAFEF_TIMEOUT")
    try:
        if budget_sec is not None:
            per = max(1.2, min(3.0, float(budget_sec) / max(1, len(providers))))
            os.environ["II_HTTP_TIMEOUT"] = str(per)
            os.environ["VALUE_INVESTOR_SCRAPER_TIMEOUT"] = str(per)
            os.environ["II_CAFEF_TIMEOUT"] = str(min(per, 2.5))
            try:
                from core.config import http_timeout_seconds

                if hasattr(http_timeout_seconds, "cache_clear"):
                    http_timeout_seconds.cache_clear()
            except Exception:
                pass
        return _try_providers(sym, providers, budget_sec=budget_sec)
    except ScraperError:
        return None
    finally:
        if prev_http is None:
            os.environ.pop("II_HTTP_TIMEOUT", None)
        else:
            os.environ["II_HTTP_TIMEOUT"] = prev_http
        if prev_scraper is None:
            os.environ.pop("VALUE_INVESTOR_SCRAPER_TIMEOUT", None)
        else:
            os.environ["VALUE_INVESTOR_SCRAPER_TIMEOUT"] = prev_scraper
        if prev_cafef is None:
            os.environ.pop("II_CAFEF_TIMEOUT", None)
        else:
            os.environ["II_CAFEF_TIMEOUT"] = prev_cafef
        try:
            from core.config import http_timeout_seconds

            if hasattr(http_timeout_seconds, "cache_clear"):
                http_timeout_seconds.cache_clear()
        except Exception:
            pass


def get_stock_data(ticker: str, *, use_cache: bool = True) -> dict[str, Any]:
    """
    Lấy dữ liệu: ưu tiên cache 24h; sau đó các nguồn theo II_QUOTE_PROVIDER_ORDER
    (mặc định: VNDirect → CafeF → Vietstock).

    Biến môi trường:
    - VALUE_INVESTOR_CACHE_HOURS: số giờ TTL cache (mặc định 24).
    - VALUE_INVESTOR_DISABLE_CACHE: 1/true để tắt cache.
    - II_QUOTE_PROVIDER_ORDER: danh sách nguồn, ví dụ `vndirect,cafef,vietstock`.
    - II_CAFEF_MAX_BOARDS / II_CAFEF_TIMEOUT: fail-fast CafeF HTML.

    use_cache=False: bỏ đọc/ghi cache file (dùng cho làm mới định kỳ watchlist).

    Trả thêm khi từ cache: cache_hit, cache_age_seconds; source dạng cache:vietstock, ...
    """
    sym = ticker.strip().upper()
    if not sym or not re.fullmatch(r"[A-Z0-9]{2,6}", sym):
        raise TickerNotFoundError(f"Mã không hợp lệ: {ticker!r}")

    if use_cache:
        cached = _cache_get(sym)
        if cached is not None:
            return cached

    providers = _build_quote_providers()
    budget_sec: float | None = None
    raw_budget = str(os.environ.get("II_SNAPSHOT_QUOTE_BUDGET_SEC") or "").strip()
    fail_fast = str(os.environ.get("II_PORTAL_FAIL_FAST", "0") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if raw_budget:
        try:
            budget_sec = max(2.0, float(raw_budget))
        except ValueError:
            budget_sec = None
    elif fail_fast:
        try:
            budget_sec = max(2.0, float(os.environ.get("II_PORTAL_FAIL_FAST_BUDGET_SEC", "8") or "8"))
        except ValueError:
            budget_sec = 8.0

    prev_http = os.environ.get("II_HTTP_TIMEOUT")
    prev_scraper = os.environ.get("VALUE_INVESTOR_SCRAPER_TIMEOUT")
    prev_cafef = os.environ.get("II_CAFEF_TIMEOUT")
    try:
        if budget_sec is not None:
            per = max(1.2, min(4.0, float(budget_sec) / max(1, len(providers))))
            os.environ["II_HTTP_TIMEOUT"] = str(per)
            os.environ["VALUE_INVESTOR_SCRAPER_TIMEOUT"] = str(per)
            os.environ["II_CAFEF_TIMEOUT"] = str(min(per, 2.5))
            try:
                from core.config import http_timeout_seconds

                if hasattr(http_timeout_seconds, "cache_clear"):
                    http_timeout_seconds.cache_clear()
            except Exception:
                pass
        data = _try_providers(sym, providers, budget_sec=budget_sec)
    finally:
        if budget_sec is not None:
            if prev_http is None:
                os.environ.pop("II_HTTP_TIMEOUT", None)
            else:
                os.environ["II_HTTP_TIMEOUT"] = prev_http
            if prev_scraper is None:
                os.environ.pop("VALUE_INVESTOR_SCRAPER_TIMEOUT", None)
            else:
                os.environ["VALUE_INVESTOR_SCRAPER_TIMEOUT"] = prev_scraper
            if prev_cafef is None:
                os.environ.pop("II_CAFEF_TIMEOUT", None)
            else:
                os.environ["II_CAFEF_TIMEOUT"] = prev_cafef
            try:
                from core.config import http_timeout_seconds

                if hasattr(http_timeout_seconds, "cache_clear"):
                    http_timeout_seconds.cache_clear()
            except Exception:
                pass

    data.setdefault("cache_hit", False)
    if use_cache:
        _cache_set(sym, data)
    return data


def clear_scrape_cache(symbol: str | None = None) -> None:
    """Xóa toàn bộ cache hoặc một mã (tiện cho test / admin)."""
    if _CACHE_DISABLED:
        return
    if not _CACHE_PATH.exists():
        _invalidate_scrape_file_cache_mem()
        return
    if symbol is None:
        try:
            _CACHE_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        _invalidate_scrape_file_cache_mem()
        return
    all_c = _cache_read_all()
    all_c.pop(symbol.strip().upper(), None)
    try:
        _cache_write_all(all_c)
    except OSError:
        pass
