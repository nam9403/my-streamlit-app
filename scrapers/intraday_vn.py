"""Intraday OHLCV scraper cho TTCK Việt Nam — chỉ dùng nguồn miễn phí.

Mục tiêu: cung cấp dữ liệu nến 1m/5m/15m theo cùng schema với
``scrapers.portal.fetch_ohlcv_history`` để Tier 1 ``analyze_flow`` có thể
"plug-and-play" mà không phải sửa logic.

Nguồn (theo thứ tự fallback chain):
1. VNDirect dchart-api  (TradingView UDF format, public, không cần token)
2. TCBS apipubaws       (stock-insight v2 bars-long-term, public)

Cả hai đều public/free. Không gọi REST/WebSocket trả phí.

Thiết kế:
- Trả về ``pd.DataFrame`` với cột ``date, open, high, low, close, volume``
  (giống ``fetch_ohlcv_history``).
- Gắn metadata ``.attrs["source"]`` + ``.attrs["data_trust"]`` để
  ``data_quality`` panel có thể audit nguồn.
- Có HTTP session injectable cho unit test (không cần monkeypatch ``requests``).
- Cache in-memory TTL 30s — intraday biến động nhanh, cache lâu không có ý nghĩa.
- Có ``is_vn_market_open()`` để caller skip lúc ngoài giờ giao dịch.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Iterable

import pandas as pd
import requests  # type: ignore

logger = logging.getLogger(__name__)

# -- Constants ---------------------------------------------------------------

VN_TZ = timezone(timedelta(hours=7), name="Asia/Ho_Chi_Minh")

_ALLOWED_RESOLUTIONS = ("1", "3", "5", "15", "30", "60")

_VNDIRECT_DCHART_URL = "https://dchart-api.vndirect.com.vn/dchart/history"
_TCBS_BARS_URL = "https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/bars-long-term"

_DEFAULT_TIMEOUT = float(os.environ.get("II_INTRADAY_TIMEOUT_SEC", "6") or "6")
_DEFAULT_CACHE_TTL = float(os.environ.get("II_INTRADAY_CACHE_TTL_SEC", "30") or "30")

_DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.7",
}

_CACHE_LOCK = threading.RLock()
_MEM_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}

# Circuit-breaker: per-source state. ``open_until_ts`` = nếu time.time() <
# value thì source bị skip tạm; ``consecutive_failures`` để tính backoff.
_BREAKER_LOCK = threading.RLock()
_BREAKER_STATE: dict[str, dict[str, float]] = {}
_BREAKER_FAILURE_THRESHOLD = int(
    os.environ.get("II_INTRADAY_BREAKER_FAILURES") or "3"
)
_BREAKER_COOLDOWN_SEC = float(
    os.environ.get("II_INTRADAY_BREAKER_COOLDOWN_SEC") or "180"
)
_RETRY_MAX_ATTEMPTS = int(os.environ.get("II_INTRADAY_RETRY_ATTEMPTS") or "2")
_RETRY_BASE_BACKOFF_SEC = float(
    os.environ.get("II_INTRADAY_RETRY_BACKOFF_SEC") or "0.5"
)


class IntradayDataError(Exception):
    """Raised khi không thể fetch/parse dữ liệu intraday từ mọi nguồn miễn phí."""


class IntradayRateLimitError(IntradayDataError):
    """Raised khi nguồn trả 429/503 — caller có thể retry với backoff."""


# -- Market hours ------------------------------------------------------------

_MORNING_OPEN = dtime(hour=9, minute=0)
_MORNING_CLOSE = dtime(hour=11, minute=30)
_AFTERNOON_OPEN = dtime(hour=13, minute=0)
_AFTERNOON_CLOSE = dtime(hour=14, minute=45)


def is_vn_market_open(now: datetime | None = None) -> bool:
    """Trả về True nếu ``now`` (mặc định: hiện tại) nằm trong khung 09:00-11:30
    hoặc 13:00-14:45 theo giờ VN (UTC+7) và là ngày thứ 2-6.

    Hàm này dùng để background scheduler skip nhanh khi sàn đóng cửa, tiết kiệm
    băng thông tới API miễn phí và tránh nhiễu log.
    """
    ts = now or datetime.now(VN_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=VN_TZ)
    else:
        ts = ts.astimezone(VN_TZ)
    if ts.weekday() >= 5:
        return False
    t = ts.time()
    if _MORNING_OPEN <= t <= _MORNING_CLOSE:
        return True
    if _AFTERNOON_OPEN <= t <= _AFTERNOON_CLOSE:
        return True
    return False


def next_vn_market_open(now: datetime | None = None) -> datetime:
    """Tính thời điểm mở cửa kế tiếp (giờ VN). Hữu ích cho scheduler sleep."""
    ts = now or datetime.now(VN_TZ)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=VN_TZ)
    else:
        ts = ts.astimezone(VN_TZ)
    candidate = ts.replace(hour=9, minute=0, second=0, microsecond=0)
    if ts.time() < _MORNING_OPEN and ts.weekday() < 5:
        return candidate
    if _MORNING_CLOSE < ts.time() < _AFTERNOON_OPEN and ts.weekday() < 5:
        return ts.replace(hour=13, minute=0, second=0, microsecond=0)
    nxt = candidate
    for _ in range(7):
        nxt = nxt + timedelta(days=1)
        if nxt.weekday() < 5:
            return nxt
    return nxt


# -- Public dataclass --------------------------------------------------------

@dataclass(frozen=True)
class IntradayFetchConfig:
    """Tham số fetch intraday — readonly để dễ propagate xuyên thread."""

    resolution: str = "5"
    lookback_bars: int = 400
    timeout_sec: float = _DEFAULT_TIMEOUT
    cache_ttl_sec: float = _DEFAULT_CACHE_TTL
    primary_source: str = "vndirect"  # vndirect | tcbs

    def normalize(self) -> IntradayFetchConfig:
        res = str(self.resolution or "5").strip().upper()
        if res in ("1D", "D", "DAILY"):
            raise IntradayDataError(
                "Daily resolution không thuộc intraday scraper — dùng "
                "scrapers.portal.fetch_ohlcv_history thay vì module này."
            )
        if res not in _ALLOWED_RESOLUTIONS:
            res = "5"
        lookback = max(50, min(5000, int(self.lookback_bars or 400)))
        timeout = max(1.0, min(30.0, float(self.timeout_sec or _DEFAULT_TIMEOUT)))
        # Note: explicit None-check để cho phép cache_ttl_sec=0 (tắt cache) —
        # ``or`` xử lý 0.0 là falsy nên không dùng được.
        ttl_raw = self.cache_ttl_sec
        ttl = max(
            0.0,
            min(600.0, float(_DEFAULT_CACHE_TTL if ttl_raw is None else ttl_raw)),
        )
        primary = str(self.primary_source or "vndirect").lower()
        if primary not in ("vndirect", "tcbs"):
            primary = "vndirect"
        return IntradayFetchConfig(
            resolution=res,
            lookback_bars=lookback,
            timeout_sec=timeout,
            cache_ttl_sec=ttl,
            primary_source=primary,
        )


# -- Helpers ----------------------------------------------------------------

def _cache_key(symbol: str, cfg: IntradayFetchConfig) -> str:
    return f"intraday::{symbol}::{cfg.resolution}::{cfg.lookback_bars}::{cfg.primary_source}"


def _cache_get(key: str, ttl_sec: float) -> pd.DataFrame | None:
    if ttl_sec <= 0:
        return None
    with _CACHE_LOCK:
        item = _MEM_CACHE.get(key)
        if not item:
            return None
        saved_at, payload = item
        if (time.time() - saved_at) > ttl_sec:
            _MEM_CACHE.pop(key, None)
            return None
        return payload.copy(deep=True)


def _cache_set(key: str, df: pd.DataFrame) -> None:
    with _CACHE_LOCK:
        _MEM_CACHE[key] = (time.time(), df.copy(deep=True))


def _norm_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if not s:
        raise IntradayDataError("Symbol rỗng.")
    if not s.isalnum() or len(s) > 8:
        raise IntradayDataError(f"Symbol không hợp lệ: {symbol!r}")
    return s


def _vnd_resolution(resolution: str) -> str:
    return str(resolution or "5")


def _tcbs_resolution(resolution: str) -> str:
    if str(resolution or "5") == "60":
        return "60"
    return str(resolution or "5")


def _from_ts_for_lookback(resolution: str, lookback_bars: int) -> int:
    minutes_per_bar = {"1": 1, "3": 3, "5": 5, "15": 15, "30": 30, "60": 60}.get(
        str(resolution), 5
    )
    minutes_total = minutes_per_bar * lookback_bars
    days_back = max(2, int(minutes_total / (60 * 5)) + 1)
    return int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp())


def _breaker_is_open(source: str, *, now: float | None = None) -> bool:
    """Return True nếu source đang trong cooldown của circuit breaker."""
    ts = float(now) if now is not None else time.time()
    with _BREAKER_LOCK:
        state = _BREAKER_STATE.get(source)
        if not state:
            return False
        return float(state.get("open_until_ts") or 0.0) > ts


def _breaker_record_success(source: str) -> None:
    """Reset breaker khi source success — không giữ failure count cũ."""
    with _BREAKER_LOCK:
        _BREAKER_STATE.pop(source, None)


def _breaker_record_failure(source: str, *, now: float | None = None) -> None:
    """Tăng failure count; mở breaker nếu vượt ngưỡng."""
    ts = float(now) if now is not None else time.time()
    with _BREAKER_LOCK:
        state = _BREAKER_STATE.setdefault(source, {})
        fails = float(state.get("consecutive_failures") or 0.0) + 1.0
        state["consecutive_failures"] = fails
        state["last_failure_ts"] = ts
        if fails >= float(_BREAKER_FAILURE_THRESHOLD):
            state["open_until_ts"] = ts + float(_BREAKER_COOLDOWN_SEC)


def reset_intraday_breaker(source: str | None = None) -> None:
    """API public để clear breaker state — chủ yếu cho test hoặc ops manual reset."""
    with _BREAKER_LOCK:
        if source is None:
            _BREAKER_STATE.clear()
        else:
            _BREAKER_STATE.pop(source, None)


def get_intraday_breaker_state() -> dict[str, dict[str, float]]:
    """Snapshot trạng thái breaker — cho health endpoint / dashboard."""
    with _BREAKER_LOCK:
        return {k: dict(v) for k, v in _BREAKER_STATE.items()}


def _is_rate_limit_status(status_code: int) -> bool:
    return status_code in (429, 503)


def _attach_attrs(df: pd.DataFrame, *, source: str, fallback_chain: list[str]) -> pd.DataFrame:
    df.attrs["source"] = source
    df.attrs["data_trust"] = {
        "source": source,
        "fallback_chain": list(fallback_chain),
        "is_stale": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return df


def _empty_intraday_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])


# -- VNDirect dchart-api ----------------------------------------------------

def _parse_vndirect_payload(payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise IntradayDataError("VNDirect: payload không phải dict.")
    status = str(payload.get("s") or "").lower()
    if status != "ok":
        raise IntradayDataError(f"VNDirect: status={status!r}")
    ts = payload.get("t") or []
    opens = payload.get("o") or []
    highs = payload.get("h") or []
    lows = payload.get("l") or []
    closes = payload.get("c") or []
    vols = payload.get("v") or []
    n = min(len(ts), len(opens), len(highs), len(lows), len(closes), len(vols))
    if n == 0:
        raise IntradayDataError("VNDirect: payload rỗng.")
    df = pd.DataFrame(
        {
            "date": [pd.Timestamp(int(t), unit="s", tz="UTC").tz_convert(VN_TZ) for t in ts[:n]],
            "open": [float(x) for x in opens[:n]],
            "high": [float(x) for x in highs[:n]],
            "low": [float(x) for x in lows[:n]],
            "close": [float(x) for x in closes[:n]],
            "volume": [float(x) for x in vols[:n]],
        }
    )
    df = df.sort_values("date").reset_index(drop=True)
    return df


def _fetch_vndirect(
    symbol: str,
    cfg: IntradayFetchConfig,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    to_ts = int(datetime.now(timezone.utc).timestamp())
    from_ts = _from_ts_for_lookback(cfg.resolution, cfg.lookback_bars)
    params = {
        "symbol": symbol,
        "resolution": _vnd_resolution(cfg.resolution),
        "from": from_ts,
        "to": to_ts,
    }
    sess = session or requests
    resp = sess.get(_VNDIRECT_DCHART_URL, params=params, headers=_DEFAULT_HEADERS, timeout=cfg.timeout_sec)
    status = int(getattr(resp, "status_code", 200))
    if _is_rate_limit_status(status):
        raise IntradayRateLimitError(f"VNDirect HTTP {status}")
    if status >= 400:
        raise IntradayDataError(f"VNDirect HTTP {status}")
    try:
        payload = resp.json()
    except (ValueError, AttributeError) as exc:
        raise IntradayDataError(f"VNDirect: lỗi parse JSON: {exc}") from exc
    return _parse_vndirect_payload(payload)


# -- TCBS apipubaws ----------------------------------------------------------

def _parse_tcbs_payload(payload: Any) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise IntradayDataError("TCBS: payload không phải dict.")
    rows = payload.get("data") or []
    if not isinstance(rows, list) or not rows:
        raise IntradayDataError("TCBS: data rỗng.")
    dates: list[pd.Timestamp] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    vols: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        td = r.get("tradingDate") or r.get("date")
        if td is None:
            continue
        try:
            ts = pd.Timestamp(td)
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC").tz_convert(VN_TZ)
            else:
                ts = ts.tz_convert(VN_TZ)
            dates.append(ts)
            opens.append(float(r.get("open") or 0.0))
            highs.append(float(r.get("high") or 0.0))
            lows.append(float(r.get("low") or 0.0))
            closes.append(float(r.get("close") or 0.0))
            vols.append(float(r.get("volume") or 0.0))
        except (ValueError, TypeError):
            continue
    if not dates:
        raise IntradayDataError("TCBS: không parse được bar nào.")
    df = pd.DataFrame(
        {
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        }
    ).sort_values("date").reset_index(drop=True)
    return df


def _fetch_tcbs(
    symbol: str,
    cfg: IntradayFetchConfig,
    *,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    to_ts = int(datetime.now(timezone.utc).timestamp())
    params = {
        "ticker": symbol,
        "type": "stock",
        "resolution": _tcbs_resolution(cfg.resolution),
        "to": to_ts,
        "countBack": int(cfg.lookback_bars),
    }
    sess = session or requests
    resp = sess.get(_TCBS_BARS_URL, params=params, headers=_DEFAULT_HEADERS, timeout=cfg.timeout_sec)
    status = int(getattr(resp, "status_code", 200))
    if _is_rate_limit_status(status):
        raise IntradayRateLimitError(f"TCBS HTTP {status}")
    if status >= 400:
        raise IntradayDataError(f"TCBS HTTP {status}")
    try:
        payload = resp.json()
    except (ValueError, AttributeError) as exc:
        raise IntradayDataError(f"TCBS: lỗi parse JSON: {exc}") from exc
    return _parse_tcbs_payload(payload)


# -- Public API --------------------------------------------------------------

_SOURCE_FETCHERS: dict[str, Callable[..., pd.DataFrame]] = {
    "vndirect": _fetch_vndirect,
    "tcbs": _fetch_tcbs,
}

_BUILTIN_SOURCES = frozenset(_SOURCE_FETCHERS.keys())


def register_intraday_source(
    name: str,
    fetcher: Callable[..., pd.DataFrame],
    *,
    overwrite: bool = False,
) -> None:
    """Đăng ký source intraday tuỳ biến (vd. SSI iboard, DNSE Entrade).

    Signature của ``fetcher`` phải khớp:
    ``def f(symbol: str, cfg: IntradayFetchConfig, *, session=None) -> pd.DataFrame``

    Nếu fetcher gặp rate-limit, nên raise ``IntradayRateLimitError`` để hệ
    thống retry & ghi nhận circuit-breaker. Mọi lỗi khác raise
    ``IntradayDataError``.

    Args:
        name: định danh ngắn (e.g. ``"dnse"``). Không trùng builtin nếu
            ``overwrite=False``.
        fetcher: callable thực hiện fetch.
        overwrite: cho phép ghi đè builtin (chỉ dùng ở ops emergency).
    """
    key = str(name or "").strip().lower()
    if not key:
        raise ValueError("Source name không được rỗng.")
    if not overwrite and key in _BUILTIN_SOURCES:
        raise ValueError(
            f"Source {key!r} là builtin. Đặt overwrite=True nếu thực sự muốn thay."
        )
    _SOURCE_FETCHERS[key] = fetcher


def list_intraday_sources() -> list[str]:
    """Liệt kê các source intraday hiện đăng ký (builtin + custom)."""
    return sorted(_SOURCE_FETCHERS.keys())


def _resolve_chain(primary: str) -> list[str]:
    extras_env = (os.environ.get("II_INTRADAY_EXTRA_SOURCES") or "").strip()
    extras: list[str] = []
    if extras_env:
        for tok in extras_env.split(","):
            tok = tok.strip().lower()
            if tok and tok in _SOURCE_FETCHERS and tok not in extras:
                extras.append(tok)
    base = ["tcbs", "vndirect"] if primary == "tcbs" else ["vndirect", "tcbs"]
    chain = list(dict.fromkeys(base + extras))
    return chain


def _retry_fetch(
    fetcher: Callable[..., pd.DataFrame],
    *,
    sym: str,
    cfg: IntradayFetchConfig,
    session: Any,
    source: str,
    max_attempts: int,
    base_backoff: float,
) -> pd.DataFrame:
    """Wrap fetch với retry-on-rate-limit (exponential backoff).

    Mỗi rate-limit error chờ ``base_backoff * 2**(attempt-1)`` rồi thử lại.
    ``IntradayDataError`` thường (không phải rate-limit) raise ngay.
    """
    last_exc: Exception | None = None
    attempts = max(1, int(max_attempts))
    for attempt in range(1, attempts + 1):
        try:
            return fetcher(sym, cfg, session=session)
        except IntradayRateLimitError as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            sleep_sec = float(base_backoff) * (2 ** (attempt - 1))
            logger.info(
                "intraday_%s_rate_limited symbol=%s attempt=%d sleep=%.2fs",
                source,
                sym,
                attempt,
                sleep_sec,
            )
            time.sleep(sleep_sec)
            continue
    raise last_exc if last_exc else IntradayDataError(
        f"{source}: hết lượt retry không xác định"
    )


def fetch_intraday_ohlcv(
    symbol: str,
    *,
    resolution: str = "5",
    lookback_bars: int = 400,
    timeout_sec: float | None = None,
    cache_ttl_sec: float | None = None,
    primary_source: str = "vndirect",
    session: requests.Session | None = None,
    sla_recorder: Callable[[str, bool], None] | None = None,
) -> pd.DataFrame:
    """Lấy OHLCV intraday từ nguồn miễn phí với fallback chain.

    Args:
        symbol: Mã chứng khoán VN (vd ``"FPT"``).
        resolution: Một trong ``"1"``, ``"3"``, ``"5"``, ``"15"``, ``"30"``, ``"60"``.
        lookback_bars: Số nến tối đa muốn nhận (sẽ giới hạn 50..5000).
        timeout_sec: Override timeout (default từ env ``II_INTRADAY_TIMEOUT_SEC``).
        cache_ttl_sec: Override TTL cache (default từ env ``II_INTRADAY_CACHE_TTL_SEC``).
        primary_source: ``"vndirect"`` (default) hoặc ``"tcbs"``.
        session: HTTP session inject cho test (không bắt buộc).
        sla_recorder: callback ``(source, success)`` để mark SLA — tránh import vòng.

    Returns:
        DataFrame columns ``date, open, high, low, close, volume`` đã sort tăng dần.
        ``df.attrs["source"]`` ghi nhận nguồn thực tế đã trả dữ liệu.
        ``df.attrs["data_trust"]`` chứa ``fallback_chain`` thực sự dùng.

    Raises:
        IntradayDataError: khi mọi nguồn trong chain đều fail (không có dữ liệu).
    """
    sym = _norm_symbol(symbol)
    cfg = IntradayFetchConfig(
        resolution=str(resolution),
        lookback_bars=int(lookback_bars),
        timeout_sec=float(timeout_sec) if timeout_sec is not None else _DEFAULT_TIMEOUT,
        cache_ttl_sec=float(cache_ttl_sec) if cache_ttl_sec is not None else _DEFAULT_CACHE_TTL,
        primary_source=str(primary_source),
    ).normalize()

    key = _cache_key(sym, cfg)
    hit = _cache_get(key, cfg.cache_ttl_sec)
    if hit is not None and not hit.empty:
        return hit

    chain = _resolve_chain(cfg.primary_source)
    last_error: Exception | None = None
    used_chain: list[str] = []
    skipped_breaker: list[str] = []
    for src in chain:
        fetcher = _SOURCE_FETCHERS.get(src)
        if fetcher is None:
            continue
        if _breaker_is_open(src):
            skipped_breaker.append(src)
            logger.info("intraday_%s_skipped_breaker_open symbol=%s", src, sym)
            continue
        used_chain.append(src)

        def _record_sla(success: bool) -> None:
            if sla_recorder is None:
                return
            try:
                sla_recorder(f"intraday_{src}", success)
            except Exception:  # noqa: BLE001
                pass

        try:
            df = _retry_fetch(
                fetcher,
                sym=sym,
                cfg=cfg,
                session=session,
                source=src,
                max_attempts=_RETRY_MAX_ATTEMPTS,
                base_backoff=_RETRY_BASE_BACKOFF_SEC,
            )
            if df is None or df.empty:
                _record_sla(False)
                _breaker_record_failure(src)
                continue
            df = _attach_attrs(df, source=f"intraday_{src}", fallback_chain=used_chain)
            _cache_set(key, df)
            _record_sla(True)
            _breaker_record_success(src)
            return df
        except IntradayRateLimitError as exc:
            last_error = exc
            _record_sla(False)
            _breaker_record_failure(src)
            logger.info(
                "intraday_%s_rate_limited_exhausted symbol=%s reason=%s",
                src,
                sym,
                exc,
            )
            continue
        except IntradayDataError as exc:
            last_error = exc
            _record_sla(False)
            _breaker_record_failure(src)
            logger.info("intraday_%s_failed symbol=%s reason=%s", src, sym, exc)
            continue
        except (requests.RequestException, ValueError, TypeError) as exc:
            last_error = exc
            _record_sla(False)
            _breaker_record_failure(src)
            logger.info(
                "intraday_%s_network_failed symbol=%s error=%s",
                src,
                sym,
                exc.__class__.__name__,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _record_sla(False)
            _breaker_record_failure(src)
            logger.warning(
                "intraday_%s_unexpected symbol=%s error=%s",
                src,
                sym,
                exc.__class__.__name__,
            )
            continue
    raise IntradayDataError(
        f"Không lấy được intraday OHLCV cho {sym} từ chain {chain} "
        f"(skipped do breaker: {skipped_breaker}): {last_error}"
    )


def batch_fetch_intraday(
    symbols: Iterable[str],
    *,
    resolution: str = "5",
    lookback_bars: int = 400,
    primary_source: str = "vndirect",
    timeout_sec: float | None = None,
    sla_recorder: Callable[[str, bool], None] | None = None,
) -> dict[str, pd.DataFrame]:
    """Fetch tuần tự (single-thread) cho danh sách mã.

    Cố ý tuần tự để tôn trọng rate-limit của API miễn phí (~30 req/phút mỗi
    nguồn). Caller nếu cần song song có thể tự gọi từ ThreadPoolExecutor với
    ``max_workers <= 4``.
    """
    out: dict[str, pd.DataFrame] = {}
    for sym in symbols:
        s = (sym or "").strip().upper()
        if not s:
            continue
        try:
            out[s] = fetch_intraday_ohlcv(
                s,
                resolution=resolution,
                lookback_bars=lookback_bars,
                primary_source=primary_source,
                timeout_sec=timeout_sec,
                sla_recorder=sla_recorder,
            )
        except IntradayDataError:
            continue
    return out


__all__ = [
    "VN_TZ",
    "IntradayDataError",
    "IntradayFetchConfig",
    "IntradayRateLimitError",
    "batch_fetch_intraday",
    "fetch_intraday_ohlcv",
    "get_intraday_breaker_state",
    "is_vn_market_open",
    "list_intraday_sources",
    "next_vn_market_open",
    "register_intraday_source",
    "reset_intraday_breaker",
]
