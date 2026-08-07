"""
Warehouse P/E–P/B đa năm theo ngành (hybrid annual reconstruct).

Nguồn mỗi mã/năm:
- EPS TTM (FireAnt Q4 hoặc quý gần cuối năm) × giá đóng cửa cuối năm (OHLCV store)
- BVPS nếu có → PB; không có thì PB ≈ PE × ROE (tỉ lệ)

Ghi ``data/sector_multiples_5y.json``; ``resolve_sector_multiples`` ưu tiên file này
khi coverage ∈ {5y, multi_year}.
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "data" / "sector_multiples_5y.json"
STATEMENTS_DIR = ROOT / "data" / "runtime" / "statements_cache"
METADATA_PATH = ROOT / "data" / "stock_metadata.json"
INDICATORS_CACHE = ROOT / "data" / "financial_indicators_cache.json"

_PE_LO, _PE_HI = 4.0, 40.0
_PB_LO, _PB_HI = 0.4, 8.0


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:
        return None
    return x


def _clamp_pe(pe: float | None) -> float | None:
    if pe is None or pe <= 0:
        return None
    return max(_PE_LO, min(_PE_HI, float(pe)))


def _clamp_pb(pb: float | None) -> float | None:
    if pb is None or pb <= 0:
        return None
    return max(_PB_LO, min(_PB_HI, float(pb)))


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_metadata() -> dict[str, dict[str, Any]]:
    raw = _load_json(METADATA_PATH)
    return raw if isinstance(raw, dict) else {}


def _icb_map_from_indicators() -> dict[str, str]:
    raw = _load_json(INDICATORS_CACHE)
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for sym, blob in raw.items():
        payload = blob.get("payload") if isinstance(blob, dict) and isinstance(blob.get("payload"), dict) else blob
        if not isinstance(payload, dict):
            continue
        icb = str(payload.get("icb_sector") or payload.get("sector") or "").strip()
        if icb:
            out[str(sym).upper()] = icb
    return out


def list_statement_symbols() -> list[str]:
    if not STATEMENTS_DIR.is_dir():
        return []
    return sorted(p.stem.upper() for p in STATEMENTS_DIR.glob("*.json") if p.stem.upper() != "TEST")


def load_statement_rows(symbol: str) -> list[dict[str, Any]]:
    path = STATEMENTS_DIR / f"{symbol.strip().upper()}.json"
    raw = _load_json(path)
    if not isinstance(raw, dict):
        return []
    rows = raw.get("rows")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _pick_year_end_fundamental(rows: list[dict[str, Any]], year: int) -> dict[str, Any] | None:
    """Ưu tiên Q4; fallback quý cao nhất trong năm."""
    year_rows = [r for r in rows if int(r.get("year") or 0) == int(year)]
    if not year_rows:
        return None
    q4 = [r for r in year_rows if int(r.get("quarter") or 0) == 4]
    pool = q4 or year_rows
    pool.sort(key=lambda r: int(r.get("quarter") or 0), reverse=True)
    return pool[0]


def reconstruct_annual_multiples(
    symbol: str,
    *,
    years: int = 5,
    as_of_year: int | None = None,
) -> list[dict[str, Any]]:
    """
    Trả list điểm năm: {year, pe, pb, eps, bvps, close, roe, pb_source}.
    """
    from core.ohlcv_store import get_close_on_or_before

    sym = str(symbol or "").strip().upper()
    rows = load_statement_rows(sym)
    if not rows:
        return []
    end_y = int(as_of_year or date.today().year) - 1  # năm hoàn tất gần nhất
    start_y = end_y - max(1, int(years)) + 1
    out: list[dict[str, Any]] = []
    for y in range(start_y, end_y + 1):
        fund = _pick_year_end_fundamental(rows, y)
        if not fund:
            continue
        eps = _num(fund.get("eps_ttm") or fund.get("eps"))
        if eps is None or eps <= 0:
            continue
        close, close_date = get_close_on_or_before(sym, date(y, 12, 31))
        if close is None or close <= 0:
            continue
        pe = _clamp_pe(close / eps)
        if pe is None:
            continue
        bvps = _num(fund.get("bvps") or fund.get("book_value_per_share"))
        roe = _num(fund.get("roe_ttm_pct") or fund.get("roe"))
        pb = None
        pb_source = "missing"
        if bvps is not None and bvps > 0:
            pb = _clamp_pb(close / bvps)
            pb_source = "bvps"
        elif roe is not None and roe > 0:
            # ROE % → PB ≈ PE × ROE
            pb = _clamp_pb(pe * (roe / 100.0 if roe > 1.5 else roe))
            pb_source = "pe_x_roe"
        out.append(
            {
                "year": y,
                "pe": round(float(pe), 3),
                "pb": round(float(pb), 3) if pb is not None else None,
                "eps": round(float(eps), 4),
                "bvps": round(float(bvps), 4) if bvps is not None else None,
                "close": round(float(close), 2),
                "close_date": close_date,
                "roe": round(float(roe), 3) if roe is not None else None,
                "pb_source": pb_source,
            }
        )
    return out


def _name_avg(points: list[dict[str, Any]], key: str) -> float | None:
    """Trung bình có trọng số lệch về năm gần (đúng chế độ định giá hiện tại hơn)."""
    vals: list[tuple[int, float]] = []
    for p in points:
        v = _num(p.get(key))
        y = int(p.get("year") or 0)
        if v is None or y <= 0:
            continue
        vals.append((y, float(v)))
    if not vals:
        return None
    vals.sort(key=lambda t: t[0])
    # weights 1..n theo thứ tự năm
    weighted = 0.0
    wsum = 0.0
    for i, (_y, v) in enumerate(vals, start=1):
        w = float(i)
        weighted += v * w
        wsum += w
    return float(weighted / wsum) if wsum > 0 else None


def _coverage_label(n_years: int, span_years: int) -> str:
    if n_years >= 4 and span_years >= 4:
        return "5y"
    if n_years >= 2:
        return "multi_year"
    if n_years == 1:
        return "single_year"
    return "none"


def _aggregate_bucket(
    name_stats: list[dict[str, Any]],
    *,
    key: str,
    key_value: str,
) -> dict[str, Any] | None:
    pe_vals = [float(s["pe_avg"]) for s in name_stats if s.get("pe_avg") is not None]
    pb_vals = [float(s["pb_avg"]) for s in name_stats if s.get("pb_avg") is not None]
    if len(pe_vals) < 2 and len(pb_vals) < 2:
        return None
    years_med = statistics.median([int(s.get("n_years") or 0) for s in name_stats]) if name_stats else 0
    spans = [int(s.get("span_years") or 0) for s in name_stats]
    span_med = int(statistics.median(spans)) if spans else 0
    cov = _coverage_label(int(years_med), span_med)
    # Đủ tên: subtype ≥3 hoặc ICB ≥3; nếu 2 tên vẫn ghi nhưng coverage hạ.
    n_names = max(len(pe_vals), len(pb_vals))
    if n_names < 3 and cov == "5y":
        cov = "multi_year"
    return {
        key: key_value,
        "pe_avg": round(float(statistics.median(pe_vals)), 2) if pe_vals else None,
        "pb_avg": round(float(statistics.median(pb_vals)), 2) if pb_vals else None,
        "n_names": n_names,
        "n_pe_names": len(pe_vals),
        "n_pb_names": len(pb_vals),
        "years_used_median": int(years_med),
        "span_years_median": span_med,
        "coverage": cov,
        "source": "fireant_eps_x_ohlcv_hybrid",
    }


def build_sector_multiples_5y(
    *,
    symbols: list[str] | None = None,
    years: int = 5,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """
    Build warehouse JSON from local statements_cache + ohlcv_store.
    """
    syms = [s.upper() for s in (symbols or list_statement_symbols())]
    meta = _load_metadata()
    icb_map = _icb_map_from_indicators()

    per_symbol: dict[str, Any] = {}
    by_subtype: dict[str, list[dict[str, Any]]] = {}
    by_icb: dict[str, list[dict[str, Any]]] = {}

    for sym in syms:
        points = reconstruct_annual_multiples(sym, years=years)
        if not points:
            continue
        pe_avg = _name_avg(points, "pe")
        pb_avg = _name_avg(points, "pb")
        ys = [int(p["year"]) for p in points]
        span = (max(ys) - min(ys) + 1) if ys else 0
        m = meta.get(sym) if isinstance(meta.get(sym), dict) else {}
        subtype = str(m.get("industry_subtype") or "other").strip() or "other"
        cluster = str(m.get("industry_cluster") or "").strip()
        icb = icb_map.get(sym) or str(m.get("icb_sector") or "").strip()
        stat = {
            "symbol": sym,
            "pe_avg": round(pe_avg, 3) if pe_avg is not None else None,
            "pb_avg": round(pb_avg, 3) if pb_avg is not None else None,
            "n_years": len(points),
            "span_years": span,
            "coverage": _coverage_label(len(points), span),
            "industry_subtype": subtype,
            "industry_cluster": cluster,
            "icb_sector": icb or None,
            "years": points,
        }
        per_symbol[sym] = stat
        by_subtype.setdefault(subtype, []).append(stat)
        if icb:
            by_icb.setdefault(icb, []).append(stat)

    subtype_out: dict[str, Any] = {}
    for k, stats in by_subtype.items():
        agg = _aggregate_bucket(stats, key="industry_subtype", key_value=k)
        if agg:
            subtype_out[k] = agg

    icb_out: dict[str, Any] = {}
    for k, stats in by_icb.items():
        agg = _aggregate_bucket(stats, key="icb_sector", key_value=k)
        if agg:
            icb_out[k] = agg

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "hybrid_annual_reconstruct",
        "honesty": (
            "Không phải P/E–P/B TB 5 năm từ vendor. "
            "Rolling multi-year: EPS TTM (FireAnt) × giá cuối năm (OHLCV); "
            "PB từ BVPS nếu có, không thì PE×ROE. "
            "coverage=5y khi ≥4 năm; multi_year khi 2–3 năm."
        ),
        "years_window": int(years),
        "symbols_input": len(syms),
        "symbols_with_points": len(per_symbol),
        "by_industry_subtype": subtype_out,
        "by_icb_sector": icb_out,
        "per_symbol": per_symbol,
    }

    path = out_path or DEFAULT_OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "sector_multiples_5y_written path=%s symbols=%s subtypes=%s",
        path,
        len(per_symbol),
        len(subtype_out),
    )
    return payload


def load_sector_multiples_5y(path: Path | None = None) -> dict[str, Any] | None:
    raw = _load_json(path or DEFAULT_OUT)
    return raw if isinstance(raw, dict) else None


def lookup_5y_multiples(
    *,
    symbol: str = "",
    industry_subtype: str | None = None,
    icb_sector: str | None = None,
    warehouse: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    Tra cứu P/E–P/B đa năm.
    Ưu tiên: chính mã (chuẩn nhất) → subtype → ICB.
    Chỉ trả khi coverage ∈ {5y, multi_year}.
    """
    data = warehouse if warehouse is not None else load_sector_multiples_5y()
    if not data:
        return None
    sym = str(symbol or "").strip().upper()
    subtype = str(industry_subtype or "").strip()
    icb = str(icb_sector or "").strip()

    def _ok(block: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(block, dict):
            return None
        cov = str(block.get("coverage") or "")
        if cov not in ("5y", "multi_year"):
            return None
        pe = _clamp_pe(_num(block.get("pe_avg")))
        pb = _clamp_pb(_num(block.get("pb_avg")))
        if pe is None and pb is None:
            return None
        return {
            "sector_pe": pe,
            "sector_pb": pb,
            "coverage": cov,
            "n_names": block.get("n_names") or block.get("n_years"),
            "years_used_median": block.get("years_used_median") or block.get("n_years"),
            "source": f"sector_multiples_5y:{cov}",
            "horizon": "multi_year_reconstruct" if cov == "multi_year" else "5y_reconstruct",
            "bucket": block.get("industry_subtype") or block.get("icb_sector") or sym,
        }

    by_st = data.get("by_industry_subtype") if isinstance(data.get("by_industry_subtype"), dict) else {}
    by_icb = data.get("by_icb_sector") if isinstance(data.get("by_icb_sector"), dict) else {}
    per = data.get("per_symbol") if isinstance(data.get("per_symbol"), dict) else {}

    # 1) Chính mã — chuẩn xác nhất cho định giá từng cổ phiếu.
    if sym and sym in per:
        hit = _ok(per.get(sym))
        if hit:
            hit["match"] = f"symbol:{sym}"
            hit["n_names"] = 1
            hit["source"] = f"symbol_history_5y:{hit.get('coverage')}"
            return hit
    # 2) Subtype ngành
    if subtype and subtype in by_st:
        hit = _ok(by_st.get(subtype))
        if hit:
            hit["match"] = f"subtype:{subtype}"
            return hit
    # 3) ICB
    if icb and icb in by_icb:
        hit = _ok(by_icb.get(icb))
        if hit:
            hit["match"] = f"icb:{icb}"
            return hit
    return None
