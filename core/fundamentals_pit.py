"""
Point-in-time fundamentals from multi-period BCTC (VNDirect).

Not a full SEC-style PIT warehouse: uses structured quarterly/annual rows and a
conservative publish lag so backtests never see a period before it could exist.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from scrapers.financial_statements import compute_trend_metrics, fetch_vndirect_financial_statement_rows

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "runtime" / "statements_cache"
DEFAULT_PUBLISH_LAG_DAYS = 45


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    try:
        ts = str(v).replace("Z", "+00:00")
        if "T" in ts:
            return datetime.fromisoformat(ts).date()
        return datetime.strptime(ts[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def period_end_date(year: int, quarter: int) -> date | None:
    y = int(year or 0)
    q = int(quarter or 0)
    if y < 1990:
        return None
    if q <= 0:
        return date(y, 12, 31)
    ends = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    m, d = ends.get(q, (12, 31))
    try:
        return date(y, m, d)
    except ValueError:
        return None


def period_available_on(
    year: int,
    quarter: int,
    *,
    publish_lag_days: int = DEFAULT_PUBLISH_LAG_DAYS,
) -> date | None:
    """Earliest date the period is assumed public (period end + lag)."""
    end = period_end_date(year, quarter)
    if end is None:
        return None
    return end + timedelta(days=max(0, int(publish_lag_days)))


def filter_rows_as_of(
    rows: list[dict[str, Any]],
    as_of: date | str | datetime,
    *,
    publish_lag_days: int = DEFAULT_PUBLISH_LAG_DAYS,
) -> list[dict[str, Any]]:
    """Keep only statement periods that would be available on/before as_of."""
    cut = _to_date(as_of)
    if cut is None:
        return []
    kept: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        avail = period_available_on(
            int(r.get("year") or 0),
            int(r.get("quarter") or 0),
            publish_lag_days=publish_lag_days,
        )
        if avail is None or avail > cut:
            continue
        kept.append(r)
    kept.sort(
        key=lambda x: (int(x.get("year") or 0), int(x.get("quarter") or 0)),
        reverse=True,
    )
    return kept


def _cache_path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol.strip().upper()}.json"


def fetch_fireant_quarterly_rows(ticker: str) -> tuple[list[dict[str, Any]], str]:
    """Fireant quarterly financial info → normalized rows for PIT."""
    sym = str(ticker or "").strip().upper()
    if not sym:
        return [], "empty"
    try:
        import requests
        from urllib.parse import quote

        url = (
            "https://www.fireant.vn/api/Data/Finance/QuarterlyFinancialInfo"
            f"?symbol={quote(sym)}&fromYear=2018&fromQuarter=1&toYear=2030&toQuarter=4"
        )
        timeout = float(__import__("os").environ.get("II_FIREANT_TIMEOUT_SEC", "12") or 12)
        r = requests.get(url, timeout=max(3.0, timeout))
        if r.status_code != 200:
            return [], f"http_{r.status_code}"
        js = r.json()
        if not isinstance(js, list) or not js:
            return [], "empty"
        out: list[dict[str, Any]] = []
        for raw in js:
            if not isinstance(raw, dict):
                continue
            try:
                year = int(raw.get("Year") or 0)
                quarter = int(raw.get("Quarter") or 0)
            except (TypeError, ValueError):
                continue
            if year < 1990:
                continue
            # Fireant growth often as ratio 0.18 → convert to %
            def _pct(v: Any) -> float | None:
                try:
                    x = float(v)
                except (TypeError, ValueError):
                    return None
                if abs(x) <= 3.5:
                    x *= 100.0
                return round(x, 4)

            sales = _pct(raw.get("SalesGrowth_TTM") if raw.get("SalesGrowth_TTM") is not None else raw.get("SalesGrowth_MRQ"))
            profit = _pct(raw.get("ProfitGrowth_TTM") if raw.get("ProfitGrowth_TTM") is not None else raw.get("ProfitGrowth_MRQ"))
            roe = None
            for k in ("ROE_TTM", "ROE", "ReturnOnEquity_TTM", "ROA_TTM"):
                if raw.get(k) is not None:
                    roe = _pct(raw.get(k))
                    break
            out.append(
                {
                    "year": year,
                    "quarter": quarter,
                    "revenue": None,
                    "net_income": None,
                    "total_assets": None,
                    "equity": None,
                    "sales_growth_ttm_pct": sales,
                    "profit_growth_ttm_pct": profit,
                    "roe_ttm_pct": roe,
                    "eps_ttm": raw.get("BasicEPS_TTM") or raw.get("DilutedEPS_TTM"),
                    "_provider": "fireant",
                }
            )
        out.sort(key=lambda x: (x["year"], x["quarter"]), reverse=True)
        return out, "fireant_quarterly"
    except Exception as exc:
        return [], f"fireant_err:{exc.__class__.__name__}"


def load_statement_rows_cached(
    symbol: str,
    *,
    size: int = 20,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """
    Load multi-period BCTC rows with disk cache (avoid re-hitting API per bar).
    Prefer Fireant (stable) then VNDirect statements.
    """
    sym = str(symbol or "").strip().upper()
    if not sym:
        return [], "empty"
    path = _cache_path(sym)
    if path.exists() and not force_refresh:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rows = raw.get("rows") if isinstance(raw, dict) else None
            if isinstance(rows, list) and rows:
                return rows, str(raw.get("source") or "disk_cache")
        except Exception:
            pass

    rows, src = fetch_fireant_quarterly_rows(sym)
    if not rows:
        rows, src = fetch_vndirect_financial_statement_rows(sym, size=max(8, int(size)))
        slim = []
        for r in rows:
            slim.append(
                {
                    "year": r.get("year"),
                    "quarter": r.get("quarter"),
                    "revenue": r.get("revenue"),
                    "net_income": r.get("net_income"),
                    "total_assets": r.get("total_assets"),
                    "equity": r.get("equity"),
                }
            )
        rows = slim
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "symbol": sym,
                    "source": src,
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("statements_cache_write_failed symbol=%s err=%s", sym, exc.__class__.__name__)
    return rows, src


def _roe_pct(ni: Any, equity: Any) -> float | None:
    try:
        n = float(ni)
        e = float(equity)
        if e == 0:
            return None
        roe = (n / e) * 100.0
        if abs(roe) > 200:
            return None
        return round(roe, 2)
    except (TypeError, ValueError):
        return None


def fundamentals_as_of(
    symbol: str,
    as_of: date | str | datetime,
    *,
    rows: list[dict[str, Any]] | None = None,
    publish_lag_days: int = DEFAULT_PUBLISH_LAG_DAYS,
    price: float | None = None,
) -> dict[str, Any]:
    """
    Build financials dict usable by evaluate_thesis at date ``as_of``.

    Returns empty-ish dict with ok=False when insufficient history.
    """
    sym = str(symbol or "").strip().upper()
    cut = _to_date(as_of)
    if not sym or cut is None:
        return {"ok": False, "reason": "bad_input", "symbol": sym}

    all_rows = rows
    src = "provided"
    if all_rows is None:
        all_rows, src = load_statement_rows_cached(sym)
    pit_rows = filter_rows_as_of(all_rows, cut, publish_lag_days=publish_lag_days)
    if not pit_rows:
        return {
            "ok": False,
            "reason": "insufficient_periods",
            "symbol": sym,
            "as_of": cut.isoformat(),
            "periods_available": 0,
            "source": src,
        }

    cur = pit_rows[0]
    # Fireant path: growth already on row
    if cur.get("_provider") == "fireant" or cur.get("sales_growth_ttm_pct") is not None:
        rev_yoy = cur.get("sales_growth_ttm_pct")
        ni_yoy = cur.get("profit_growth_ttm_pct")
        roe = cur.get("roe_ttm_pct")
        q = 4
        try:
            if rev_yoy is not None and float(rev_yoy) > 0:
                q += 1
            if rev_yoy is not None and float(rev_yoy) >= 15:
                q += 1
            if ni_yoy is not None and float(ni_yoy) > 0:
                q += 1
            if ni_yoy is not None and float(ni_yoy) >= 15:
                q += 1
            if roe is not None and float(roe) >= 15:
                q += 1
        except (TypeError, ValueError):
            pass
        return {
            "ok": True,
            "symbol": sym,
            "as_of": cut.isoformat(),
            "source": f"fireant_pit:{src}",
            "fundamentals_note_vi": (
                f"PIT Fireant ≤ {cut.isoformat()} (lag {publish_lag_days}d). "
                f"Q{cur.get('quarter')}/{cur.get('year')}"
            ),
            "revenue_growth_yoy": rev_yoy,
            "profit_growth_yoy": ni_yoy,
            "roe": roe,
            "piotroski_score": max(0, min(9, q)),
            "latest_year": cur.get("year"),
            "latest_quarter": cur.get("quarter"),
            "periods_available": len(pit_rows),
            "eps_ttm": cur.get("eps_ttm"),
            "price_at_as_of": price,
        }

    if len(pit_rows) < 2:
        return {
            "ok": False,
            "reason": "insufficient_periods",
            "symbol": sym,
            "as_of": cut.isoformat(),
            "periods_available": len(pit_rows),
            "source": src,
        }

    trend = compute_trend_metrics(pit_rows)
    cur = pit_rows[0]
    roe = _roe_pct(cur.get("net_income"), cur.get("equity"))
    q = 4
    rev_yoy = trend.get("revenue_yoy_pct")
    ni_yoy = trend.get("profit_yoy_pct")
    try:
        if rev_yoy is not None and float(rev_yoy) > 0:
            q += 1
        if rev_yoy is not None and float(rev_yoy) >= 15:
            q += 1
        if ni_yoy is not None and float(ni_yoy) > 0:
            q += 1
        if ni_yoy is not None and float(ni_yoy) >= 15:
            q += 1
        if roe is not None and roe >= 15:
            q += 1
    except (TypeError, ValueError):
        pass
    q = max(0, min(9, q))

    return {
        "ok": True,
        "symbol": sym,
        "as_of": cut.isoformat(),
        "source": f"vndirect_statements_pit:{src}",
        "fundamentals_note_vi": (
            f"PIT BCTC ≤ {cut.isoformat()} (lag {publish_lag_days}d sau kỳ). "
            f"{trend.get('yoy_compare_label_vi') or ''}"
        ).strip(),
        "revenue_growth_yoy": trend.get("revenue_yoy_pct"),
        "profit_growth_yoy": trend.get("profit_yoy_pct"),
        "revenue_cagr_3y_pct": trend.get("revenue_cagr_3y_pct"),
        "roe": roe,
        "piotroski_score": q,
        "latest_year": cur.get("year"),
        "latest_quarter": cur.get("quarter"),
        "periods_available": len(pit_rows),
        "trend_label": trend.get("trend_label"),
        "net_income": cur.get("net_income"),
        "equity": cur.get("equity"),
        "revenue": cur.get("revenue"),
        "price_at_as_of": price,
    }


def pit_to_valuation_financials(pit: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Map PIT payload → (valuation patch, financials) for build_decision_playbook."""
    if not isinstance(pit, dict) or not pit.get("ok"):
        return {}, {}
    financials = {
        "revenue_growth_yoy": pit.get("revenue_growth_yoy"),
        "profit_growth_yoy": pit.get("profit_growth_yoy"),
        "roe": pit.get("roe"),
        "source": pit.get("source"),
        "as_of_utc": pit.get("as_of"),
        "fundamentals_note_vi": pit.get("fundamentals_note_vi"),
    }
    val_patch: dict[str, Any] = {
        "roe_5y_avg": pit.get("roe"),
        "fundamentals_source": pit.get("source"),
        "fundamentals_note_vi": pit.get("fundamentals_note_vi"),
    }
    try:
        ps = pit.get("piotroski_score")
        if ps is not None:
            val_patch["piotroski_score"] = int(ps)
    except (TypeError, ValueError):
        pass
    # Soft legend boosts from growth quality
    ls: dict[str, Any] = {}
    try:
        if pit.get("revenue_growth_yoy") is not None and float(pit["revenue_growth_yoy"]) >= 10:
            ls["lynch_pass"] = True
        if pit.get("roe") is not None and float(pit["roe"]) >= 15:
            ls["buffett_pass"] = True
    except (TypeError, ValueError):
        pass
    if ls:
        val_patch["legend_scorecard"] = ls
    return val_patch, financials
