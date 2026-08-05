"""
Primary Vietnam market data provider via `vnstock` (unified Quote / Finance API).

Giá từ nguồn VCI thường tính bằng nghìn đồng → nhân 1000 để khớp thang VND
dùng trong portal / valuation (MOS, P/E, ...).

Credentials (env):
  II_VNSTOCK_TOKEN or II_VNSTOCK_API_KEY → vnstock Community tier (60 req/min)
  II_VNSTOCK_USER / II_VNSTOCK_PASSWORD   → optional; exported for tooling that reads them
  VNSTOCK_API_KEY                        → also honored by vnai if already set
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_SOURCE = "VCI"
_CREDENTIALS_CONFIGURED = False

_RETRYABLE_MARKERS = (
    "429",
    "rate limit",
    "rate_limit",
    "guest limit",
    "giới hạn api",
    "read timed out",
    "timed out",
    "timeout",
    "connection reset",
    "connection aborted",
    "temporarily unavailable",
    "503",
    "502",
    "vietcap.com.vn",
)

T = TypeVar("T")


class VnstockProviderError(Exception):
    """Không lấy được dữ liệu từ vnstock."""


def _source() -> str:
    return str(os.environ.get("II_VNSTOCK_SOURCE", _DEFAULT_SOURCE) or _DEFAULT_SOURCE).strip().upper() or _DEFAULT_SOURCE


def _price_scale() -> float:
    """
    Hệ số nhân giá OHLCV từ vnstock → VND đầy đủ.
    Mặc định 1000 (VCI trả ~67.0 cho FPT ~67_000). Đặt II_VNSTOCK_PRICE_SCALE=1 nếu nguồn đã là VND.
    """
    try:
        return max(1.0, float(os.environ.get("II_VNSTOCK_PRICE_SCALE", "1000") or "1000"))
    except ValueError:
        return 1000.0


def _retry_max_attempts() -> int:
    # Fail-fast portal: không retry timeout 30s × 3.
    if str(os.environ.get("II_PORTAL_FAIL_FAST", "0") or "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            return max(1, int(os.environ.get("II_VNSTOCK_RETRY_MAX", "1") or "1"))
        except ValueError:
            return 1
    try:
        return max(1, int(os.environ.get("II_VNSTOCK_RETRY_MAX", "3") or "3"))
    except ValueError:
        return 3


def _retry_base_sec() -> float:
    if str(os.environ.get("II_PORTAL_FAIL_FAST", "0") or "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            return max(0.2, float(os.environ.get("II_VNSTOCK_RETRY_BASE_SEC", "0.5") or "0.5"))
        except ValueError:
            return 0.5
    try:
        return max(0.5, float(os.environ.get("II_VNSTOCK_RETRY_BASE_SEC", "2") or "2"))
    except ValueError:
        return 2.0


def _vnstock_call_timeout_sec() -> float:
    """
    Timeout cứng quanh gọi vnstock (Vietcap client mặc định ~30s — dễ treo Autopilot).
    Ưu tiên II_VNSTOCK_TIMEOUT_SEC; khi fail-fast dùng budget portal.
    """
    raw = str(os.environ.get("II_VNSTOCK_TIMEOUT_SEC", "") or "").strip()
    if raw:
        try:
            return max(1.5, min(30.0, float(raw)))
        except ValueError:
            pass
    if str(os.environ.get("II_PORTAL_FAIL_FAST", "0") or "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            return max(1.5, min(12.0, float(os.environ.get("II_PORTAL_FAIL_FAST_BUDGET_SEC", "3.5") or "3.5")))
        except ValueError:
            return 3.5
    try:
        return max(3.0, min(20.0, float(os.environ.get("II_HTTP_TIMEOUT", "8") or "8")))
    except ValueError:
        return 8.0


def _resolve_api_token() -> str:
    for key in ("II_VNSTOCK_TOKEN", "II_VNSTOCK_API_KEY", "VNSTOCK_API_KEY"):
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val
    return ""


def _persist_api_key_file(api_key: str) -> None:
    """Write ~/.vnstock/api_key.json without interactive vnstock prompts."""
    try:
        vn_dir = Path.home() / ".vnstock"
        vn_dir.mkdir(parents=True, exist_ok=True)
        key_path = vn_dir / "api_key.json"
        payload = {"api_key": api_key.strip()}
        key_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("vnstock_api_key_persist_failed", exc_info=True)


def configure_vnstock_credentials(*, force: bool = False) -> bool:
    """
    Apply II_VNSTOCK_* env credentials once per process.

    Returns True when an API token was applied (Community tier vs Guest).
    """
    global _CREDENTIALS_CONFIGURED
    if _CREDENTIALS_CONFIGURED and not force:
        return bool(_resolve_api_token())

    token = _resolve_api_token()
    user = str(os.environ.get("II_VNSTOCK_USER") or "").strip()
    password = str(os.environ.get("II_VNSTOCK_PASSWORD") or "").strip()

    if user:
        os.environ.setdefault("VNSTOCK_USER", user)
    if password:
        os.environ.setdefault("VNSTOCK_PASSWORD", password)

    if token:
        os.environ["VNSTOCK_API_KEY"] = token
        _persist_api_key_file(token)
        logger.info("vnstock_credentials_configured tier=community source=env_token")
        _CREDENTIALS_CONFIGURED = True
        return True

    if user and password:
        logger.info(
            "vnstock_user_password_set; set II_VNSTOCK_TOKEN for higher rate limits (Guest=20/min)"
        )
    else:
        logger.debug("vnstock_guest_mode_no_token_configured")

    _CREDENTIALS_CONFIGURED = True
    return False


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(marker in msg for marker in _RETRYABLE_MARKERS):
        return True
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return True
    try:
        import requests

        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
    except ImportError:
        pass
    return False


def _call_with_retry(
    label: str,
    fn: Callable[..., T],
    /,
    *args: Any,
    max_attempts: int | None = None,
    **kwargs: Any,
) -> T:
    """Exponential backoff for rate-limit / timeout errors (default 2s → 4s → 8s, max 3 tries)."""
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FuturesTimeout

    configure_vnstock_credentials()
    attempts = int(max_attempts) if max_attempts is not None else _retry_max_attempts()
    attempts = max(1, min(5, attempts))
    call_timeout = _vnstock_call_timeout_sec()
    last_err: Exception | None = None
    for attempt in range(attempts):
        pool: ThreadPoolExecutor | None = None
        try:
            pool = ThreadPoolExecutor(max_workers=1)
            fut = pool.submit(fn, *args, **kwargs)
            try:
                return fut.result(timeout=call_timeout)
            except FuturesTimeout as te:
                raise TimeoutError(
                    f"{label}: vnstock call exceeded {call_timeout:.1f}s "
                    f"(set II_VNSTOCK_TIMEOUT_SEC / II_PORTAL_FAIL_FAST)"
                ) from te
        except Exception as e:
            last_err = e
            if attempt >= attempts - 1 or not _is_retryable(e):
                break
            delay = _retry_base_sec() * (2**attempt)
            logger.warning(
                "vnstock_retry label=%s attempt=%s/%s sleep_sec=%.1f err=%r",
                label,
                attempt + 1,
                attempts,
                delay,
                e,
                exc_info=True,
            )
            time.sleep(delay)
        finally:
            if pool is not None:
                # Không chờ request Vietcap 30s còn treo sau khi đã timeout.
                try:
                    pool.shutdown(wait=False, cancel_futures=True)
                except TypeError:
                    pool.shutdown(wait=False)
    assert last_err is not None
    raise VnstockProviderError(f"{label}: {last_err}") from last_err


def vnstock_available() -> bool:
    try:
        from vnstock.api.quote import Quote  # noqa: F401

        return True
    except Exception:
        return False


def _normalize_ohlcv_frame(raw: pd.DataFrame, *, symbol: str, source_tag: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise VnstockProviderError(f"vnstock_ohlcv:empty:{symbol}")
    df = raw.copy()
    time_col = None
    for c in ("time", "date", "Date", "TradingDate", "ngay"):
        if c in df.columns:
            time_col = c
            break
    if time_col is None:
        raise VnstockProviderError(f"vnstock_ohlcv:no_date:{symbol}")
    rename = {time_col: "date"}
    for src, dst in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close"), ("Volume", "volume")):
        if src in df.columns and dst not in df.columns:
            rename[src] = dst
    df = df.rename(columns=rename)
    need = ["date", "open", "high", "low", "close", "volume"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise VnstockProviderError(f"vnstock_ohlcv:missing_cols:{missing}")
    scale = _price_scale()
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"], errors="coerce"),
            "open": pd.to_numeric(df["open"], errors="coerce") * scale,
            "high": pd.to_numeric(df["high"], errors="coerce") * scale,
            "low": pd.to_numeric(df["low"], errors="coerce") * scale,
            "close": pd.to_numeric(df["close"], errors="coerce") * scale,
            "volume": pd.to_numeric(df["volume"], errors="coerce").fillna(0.0),
        }
    )
    out = out.dropna(subset=["date", "close"]).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    out = out.reset_index(drop=True)
    if out.empty:
        raise VnstockProviderError(f"vnstock_ohlcv:no_valid_rows:{symbol}")
    out.attrs["source"] = source_tag
    out.attrs["symbol"] = str(symbol).upper()
    return out


def _fetch_quote_history_raw(sym: str, start: date, end: date, src: str) -> pd.DataFrame:
    from vnstock.api.quote import Quote

    q = Quote(symbol=sym, source=src)
    return q.history(start=str(start), end=str(end), interval="1D")


def _fetch_finance_ratio_raw(sym: str, src: str) -> Any:
    from vnstock.api.financial import Finance

    fin = Finance(symbol=sym, source=src, period="year")
    return fin.ratio()


def fetch_ohlcv_history(symbol: str, sessions: int = 80, *, since_date: str | None = None) -> pd.DataFrame:
    """
    Lấy OHLCV daily từ vnstock Quote.history.
    `sessions`: số phiên gần nhất cần giữ lại.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        raise VnstockProviderError("vnstock_ohlcv:empty_symbol")
    if not vnstock_available():
        raise VnstockProviderError("vnstock_unavailable")

    end = date.today() + timedelta(days=1)
    if since_date:
        try:
            start = datetime.fromisoformat(str(since_date)[:10]).date() - timedelta(days=5)
        except ValueError:
            start = end - timedelta(days=max(120, int(sessions) * 2))
    else:
        start = end - timedelta(days=max(120, int(sessions) * 2 + 30))

    src = _source()
    raw = _call_with_retry(
        f"vnstock_ohlcv:{sym}",
        _fetch_quote_history_raw,
        sym,
        start,
        end,
        src,
    )
    out = _normalize_ohlcv_frame(raw, symbol=sym, source_tag=f"vnstock:{src.lower()}")
    need = max(50, int(sessions))
    if len(out) > need:
        out = out.tail(need).reset_index(drop=True)
        out.attrs["source"] = f"vnstock:{src.lower()}"
        out.attrs["symbol"] = sym
    return out


def fetch_latest_quote_price(symbol: str) -> dict[str, Any]:
    """Snapshot giá gần nhất từ OHLCV vnstock (1 phiên cuối)."""
    df = fetch_ohlcv_history(symbol, sessions=5)
    last = df.iloc[-1]
    px = float(last["close"] or 0.0)
    if px <= 0:
        raise VnstockProviderError(f"vnstock_quote:no_price:{symbol}")
    as_of = pd.Timestamp(last["date"])
    return {
        "symbol": str(symbol).strip().upper(),
        "price": px,
        "price_as_of": str(as_of.date()) if pd.notna(as_of) else None,
        "source": str(df.attrs.get("source") or "vnstock"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def _finance_frame_latest_prior(frame: Any) -> tuple[pd.Series, pd.Series]:
    """
    Từ DataFrame Finance.* (cột năm + item_id) → Series latest / prior theo item_id.
    """
    if frame is None or (hasattr(frame, "empty") and frame.empty):
        raise VnstockProviderError("vnstock_finance:empty_frame")
    df = frame.copy() if hasattr(frame, "copy") else pd.DataFrame(frame)
    if "item_id" not in df.columns:
        raise VnstockProviderError("vnstock_finance:missing_item_id")

    meta_cols = {
        "item",
        "item_en",
        "item_id",
        "year",
        "quarter",
        "period",
        "ratiottmid",
        "ratiotype",
        "report_type",
    }
    meta_idx = {i for i, c in enumerate(df.columns) if str(c).lower() in meta_cols}
    if not meta_idx:
        meta_idx = set(range(min(3, len(df.columns))))
    value_cols = [i for i in range(len(df.columns)) if i not in meta_idx]
    if not value_cols:
        raise VnstockProviderError("vnstock_finance:no_value_columns")

    numeric = df.iloc[:, value_cols].apply(pd.to_numeric, errors="coerce")
    latest = numeric.apply(lambda row: row.dropna().iloc[-1] if row.notna().any() else pd.NA, axis=1)
    prior = numeric.apply(
        lambda row: row.dropna().iloc[-2] if int(row.notna().sum()) >= 2 else pd.NA,
        axis=1,
    )
    idx = df["item_id"].astype(str).str.lower().values
    return (
        pd.Series(latest.values, index=idx),
        pd.Series(prior.values, index=idx),
    )


def _pick_item(lookup: pd.Series, *keys: str) -> float | None:
    for key in keys:
        if key in lookup.index:
            val = lookup.loc[key]
            if pd.notna(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
    return None


def parse_finance_ratio_to_indicators(ratio_frame: Any, *, symbol: str = "") -> dict[str, Any]:
    """
    Map vnstock Finance.ratio() DataFrame → schema financial indicators của portal.

    Vectorized: xử lý cột năm trùng tên (VCI trả nhiều cột ``2018``) bằng iloc positional.
    """
    sym = str(symbol or "").strip().upper()
    latest, _prior = _finance_frame_latest_prior(ratio_frame)

    pe = _pick_item(latest, "pe_ratio")
    pb = _pick_item(latest, "pb_ratio")
    roe = _pick_item(latest, "roe")
    roa = _pick_item(latest, "roa")
    de = _pick_item(latest, "debt_to_equity", "debtperequity")
    gross_margin = _pick_item(latest, "gross_margin", "gross_profit_margin")
    dividend_yield = _pick_item(latest, "dividend_yield")
    eps_growth = _pick_item(latest, "eps_growth")
    revenue_growth = _pick_item(latest, "revenue_growth")
    current_ratio = _pick_item(latest, "current_ratio")
    quick_ratio = _pick_item(latest, "quick_ratio")

    out: dict[str, Any] = {
        "symbol": sym,
        "pe_ratio": pe,
        "pb_ratio": pb,
        "roe": roe,
        "roa": roa,
        "debt_to_equity": de,
        "gross_margin": gross_margin,
        "dividend_yield_pct": dividend_yield,
        "eps_growth_yoy": eps_growth,
        "revenue_growth_yoy": revenue_growth,
        "profit_growth_yoy": eps_growth,
        "current_ratio": current_ratio,
        "quick_ratio": quick_ratio,
    }
    out["data_quality_score"] = sum(
        out.get(k) is not None
        for k in (
            "pe_ratio",
            "pb_ratio",
            "roe",
            "roa",
            "debt_to_equity",
            "gross_margin",
            "dividend_yield_pct",
            "revenue_growth_yoy",
            "current_ratio",
        )
    )
    return out


def parse_finance_statements_to_indicators(cash_flow: Any, income: Any, *, symbol: str = "") -> dict[str, Any]:
    """Map Finance.cash_flow + income_statement → CFO / NI (+ prior) cho enrichment."""
    sym = str(symbol or "").strip().upper()
    out: dict[str, Any] = {"symbol": sym}
    try:
        cf_latest, cf_prior = _finance_frame_latest_prior(cash_flow)
        cfo = _pick_item(
            cf_latest,
            "net_cash_inflows_outflows_from_operating_activities",
            "net_cash_from_operating_activities",
            "operating_cash_flow",
        )
        cfo_p = _pick_item(
            cf_prior,
            "net_cash_inflows_outflows_from_operating_activities",
            "net_cash_from_operating_activities",
            "operating_cash_flow",
        )
        if cfo is not None:
            out["operating_cash_flow"] = cfo
        if cfo_p is not None:
            out["operating_cash_flow_prior"] = cfo_p
    except VnstockProviderError:
        pass
    try:
        ni_latest, ni_prior = _finance_frame_latest_prior(income)
        ni = _pick_item(
            ni_latest,
            "net_profit_loss_after_tax",
            "attributable_to_parent_company",
            "net_income",
            "profit_after_tax",
        )
        ni_p = _pick_item(
            ni_prior,
            "net_profit_loss_after_tax",
            "attributable_to_parent_company",
            "net_income",
            "profit_after_tax",
        )
        if ni is not None:
            out["net_income"] = ni
        if ni_p is not None:
            out["net_income_prior"] = ni_p
    except VnstockProviderError:
        pass
    return out


def _fetch_finance_cash_flow_raw(sym: str, src: str) -> Any:
    from vnstock.api.financial import Finance

    fin = Finance(symbol=sym, source=src, period="year")
    return fin.cash_flow()


def _fetch_finance_income_raw(sym: str, src: str) -> Any:
    from vnstock.api.financial import Finance

    fin = Finance(symbol=sym, source=src, period="year")
    return fin.income_statement()


def fetch_finance_statements_snapshot(symbol: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """
    CFO + NI từ vnstock cash_flow / income_statement.
    Fail-soft từng nhánh: thiếu một bảng vẫn trả phần còn lại.
    """
    sym = str(symbol or "").strip().upper()
    try:
        from vnstock.api.financial import Finance  # noqa: F401
    except Exception as e:
        raise VnstockProviderError(f"vnstock_finance_unavailable:{e}") from e
    src = _source()
    cash_flow = None
    income = None
    try:
        cash_flow = _call_with_retry(
            f"vnstock_cash_flow:{sym}",
            _fetch_finance_cash_flow_raw,
            sym,
            src,
            max_attempts=1,
        )
    except VnstockProviderError as exc:
        logger.warning("vnstock_cash_flow_failed symbol=%s err=%s", sym, exc)
    try:
        income = _call_with_retry(
            f"vnstock_income:{sym}",
            _fetch_finance_income_raw,
            sym,
            src,
            max_attempts=1,
        )
    except VnstockProviderError as exc:
        logger.warning("vnstock_income_failed symbol=%s err=%s", sym, exc)
    parsed = parse_finance_statements_to_indicators(cash_flow, income, symbol=sym)
    if parsed.get("operating_cash_flow") is None and parsed.get("net_income") is None:
        raise VnstockProviderError(f"vnstock_statements:empty:{sym}")
    parsed["source"] = "vnstock:live" if force_refresh else f"vnstock_statements:{src.lower()}"
    parsed["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return parsed


def merge_statement_fields_into_indicators(indicators: dict[str, Any], statements: dict[str, Any]) -> dict[str, Any]:
    """Gộp CFO/NI vào dict indicators (không ghi đè giá trị đã có)."""
    out = dict(indicators or {})
    for key in (
        "operating_cash_flow",
        "operating_cash_flow_prior",
        "net_income",
        "net_income_prior",
    ):
        if out.get(key) is None and statements.get(key) is not None:
            out[key] = statements.get(key)
    bonus = sum(
        1
        for k in ("operating_cash_flow", "net_income", "current_ratio")
        if out.get(k) is not None
    )
    out["data_quality_score"] = int(out.get("data_quality_score") or 0) + min(3, bonus)
    return out


def _fetch_company_info_raw(sym: str, src: str) -> Any:
    from vnstock.api.company import Company

    company = Company(symbol=sym, source=src)
    return company.info()


def _fetch_company_events_raw(sym: str, src: str) -> Any:
    from vnstock.api.company import Company

    company = Company(symbol=sym, source=src)
    return company.events()


def parse_company_info(info: Any) -> dict[str, Any]:
    """Extract ICB sector, free float, outstanding shares from Company.info()."""
    if info is None:
        return {}
    if isinstance(info, pd.DataFrame):
        if info.empty:
            return {}
        row = info.iloc[0]
        payload = row.to_dict()
    elif isinstance(info, dict):
        payload = info
    else:
        return {}

    def _first(*keys: str) -> Any:
        for k in keys:
            if k in payload and payload[k] not in (None, ""):
                return payload[k]
        return None

    icb = _first("icb_code_lv2", "icb_code_lv3", "icb_code", "icb_name", "sector")
    free_float = _first("free_float", "free_float_rate", "free_float_percentage")
    outstanding = _first("outstanding_shares", "outstanding_share", "shares_outstanding")
    foreign_pct = _first("foreigner_percentage", "foreign_ownership_pct")
    profile = _first("company_profile", "organ_name", "company_name")

    out: dict[str, Any] = {}
    if icb is not None:
        out["icb_sector"] = str(icb)
    if free_float is not None:
        try:
            out["free_float_pct"] = float(free_float)
        except (TypeError, ValueError):
            pass
    if outstanding is not None:
        try:
            out["outstanding_shares"] = float(outstanding)
        except (TypeError, ValueError):
            pass
    if foreign_pct is not None:
        try:
            out["foreign_ownership_pct"] = float(foreign_pct)
        except (TypeError, ValueError):
            pass
    if profile is not None:
        out["company_profile"] = str(profile)
    return out


def parse_company_events_dividends(events: Any, *, lookback_years: int = 10) -> dict[str, Any]:
    """Count dividend events for Graham guardrails (dividend_paid_years proxy)."""
    if events is None:
        return {}
    if isinstance(events, pd.DataFrame):
        if events.empty:
            return {"dividend_paid_years": 0, "dividend_events_count": 0}
        df = events.copy()
    elif isinstance(events, list):
        df = pd.DataFrame(events)
        if df.empty:
            return {"dividend_paid_years": 0, "dividend_events_count": 0}
    else:
        return {}

    cols = {str(c).lower(): c for c in df.columns}
    type_col = next((cols[k] for k in cols if k in ("event_type", "type", "category", "item")), None)
    date_col = next((cols[k] for k in cols if k in ("payout_date", "ex_date", "record_date", "date", "time")), None)
    value_col = next((cols[k] for k in cols if "value" in k or "dividend" in k), None)

    if type_col is not None:
        mask = df[type_col].astype(str).str.lower().str.contains("dividend|cash|cổ tức|cotuc", regex=True, na=False)
        div_df = df.loc[mask]
    else:
        div_df = df

    years: set[int] = set()
    if date_col is not None:
        dates = pd.to_datetime(div_df[date_col], errors="coerce")
        cutoff = pd.Timestamp.now().year - max(1, lookback_years)
        for ts in dates.dropna():
            if int(ts.year) >= cutoff:
                years.add(int(ts.year))

    latest_yield: float | None = None
    if value_col is not None and not div_df.empty:
        try:
            latest_yield = float(pd.to_numeric(div_df[value_col], errors="coerce").dropna().iloc[-1])
        except (IndexError, ValueError, TypeError):
            latest_yield = None

    return {
        "dividend_paid_years": len(years),
        "dividend_events_count": int(len(div_df)),
        "dividend_years_list": sorted(years),
        "latest_dividend_value": latest_yield,
    }


def fetch_company_profile_snapshot(symbol: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """Company.info() + events() merged snapshot (disk-cached by portal caller)."""
    sym = str(symbol or "").strip().upper()
    try:
        from vnstock.api.company import Company  # noqa: F401
    except Exception as e:
        raise VnstockProviderError(f"vnstock_company_unavailable:{e}") from e
    src = _source()
    info_raw = _call_with_retry(f"vnstock_company_info:{sym}", _fetch_company_info_raw, sym, src)
    events_raw = _call_with_retry(f"vnstock_company_events:{sym}", _fetch_company_events_raw, sym, src)
    out = parse_company_info(info_raw)
    out.update(parse_company_events_dividends(events_raw))
    out["symbol"] = sym
    out["source"] = "vnstock:live" if force_refresh else f"vnstock_company:{src.lower()}"
    out["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return out


def fetch_finance_ratio_snapshot(symbol: str, *, force_refresh: bool = False) -> dict[str, Any]:
    """
    Chỉ số tài chính thô từ vnstock Finance.ratio (dùng cho refresh định kỳ, không realtime).
    Trả dict tối giản; caller map sang schema financial_indicators của app.
    """
    sym = str(symbol or "").strip().upper()
    try:
        from vnstock.api.financial import Finance  # noqa: F401
    except Exception as e:
        raise VnstockProviderError(f"vnstock_finance_unavailable:{e}") from e
    src = _source()
    ratio = _call_with_retry(
        f"vnstock_finance:{sym}",
        _fetch_finance_ratio_raw,
        sym,
        src,
    )
    if ratio is None or (hasattr(ratio, "empty") and ratio.empty):
        raise VnstockProviderError(f"vnstock_finance:empty:{sym}")
    return {
        "symbol": sym,
        "source": "vnstock:live" if force_refresh else f"vnstock_finance:{src.lower()}",
        "ratio_frame": ratio,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


_EXCHANGE_ALIASES = {
    "HSX": "HOSE",
    "HOSE": "HOSE",
    "HNX": "HNX",
    "UPCOM": "UPCOM",
}


def _fetch_listing_symbols_raw(src: str) -> pd.DataFrame:
    from vnstock.api.listing import Listing

    listing = Listing(source=src)
    return listing.symbols_by_exchange(exchange="HOSE")


def normalize_listing_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Filter STOCK on HOSE/HNX/UPCOM; normalize exchange + industry columns."""
    if raw is None or raw.empty:
        raise VnstockProviderError("vnstock_listing:empty")
    df = raw.copy()
    if "symbol" not in df.columns:
        raise VnstockProviderError("vnstock_listing:missing_symbol")
    df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
    if "type" in df.columns:
        df = df.loc[df["type"].astype(str).str.upper().eq("STOCK")]
    if "exchange" in df.columns:
        ex = df["exchange"].astype(str).str.upper().str.strip()
        df = df.loc[ex.isin({"HSX", "HOSE", "HNX", "UPCOM"})]
        df["exchange_norm"] = ex.map(lambda x: _EXCHANGE_ALIASES.get(x, x))
    else:
        df["exchange_norm"] = "UNKNOWN"
    icb_col = next((c for c in df.columns if str(c).lower().startswith("icb_code")), None)
    if icb_col:
        df["icb_code"] = df[icb_col].astype(str).str.strip()
    df = df.drop_duplicates(subset=["symbol"], keep="last")
    return df.reset_index(drop=True)


def fetch_listing_snapshot(
    *,
    exchange: str | None = None,
    icb_code: str | None = None,
) -> dict[str, Any]:
    """
    Listing universe via vnstock ``symbols_by_exchange`` (Community API, disk-cached by caller).

    Optional filters: ``exchange`` in HOSE/HNX/UPCOM; ``icb_code`` prefix match on icb_code2.
    """
    if not vnstock_available():
        raise VnstockProviderError("vnstock_listing_unavailable")
    src = _source()
    raw = _call_with_retry("vnstock_listing:all", _fetch_listing_symbols_raw, src)
    df = normalize_listing_frame(raw)
    if exchange:
        ex_want = _EXCHANGE_ALIASES.get(str(exchange).strip().upper(), str(exchange).strip().upper())
        df = df.loc[df["exchange_norm"].astype(str).str.upper() == ex_want]
    if icb_code:
        code = str(icb_code).strip()
        if "icb_code" in df.columns:
            df = df.loc[df["icb_code"].astype(str).str.startswith(code)]
    symbols = sorted({str(s) for s in df["symbol"].tolist() if str(s).strip()})
    if not symbols:
        raise VnstockProviderError("vnstock_listing:no_symbols_after_filter")
    records = df.to_dict(orient="records")
    return {
        "symbols": symbols,
        "records": records,
        "count": len(symbols),
        "source": f"vnstock_listing:{src.lower()}",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
