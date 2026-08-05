"""
Wave 3 — sector-relative valuation (research brain).

Compare a symbol's PE/PB (and optional MOS) to the median of peers in the same
ICB sector / industry subtype from ``data/financial_indicators_cache.json``.

Not a full PIT peer warehouse: uses the latest disk cache for live decisions.
Backtests should treat this as a soft live-only nudge unless as-of peers exist.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CACHE = ROOT / "data" / "financial_indicators_cache.json"


def _num(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    if x != x:  # NaN
        return None
    return x


def load_indicator_rows(cache_path: Path | None = None) -> list[dict[str, Any]]:
    path = cache_path or DEFAULT_CACHE
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sector_relative_cache_load_failed err=%s", exc.__class__.__name__)
        return []
    if not isinstance(raw, dict):
        return []
    rows: list[dict[str, Any]] = []
    for sym, blob in raw.items():
        if not isinstance(blob, dict):
            continue
        payload = blob.get("payload") if isinstance(blob.get("payload"), dict) else blob
        if not isinstance(payload, dict):
            continue
        pe = _num(payload.get("pe_ratio") or payload.get("pe"))
        pb = _num(payload.get("pb_ratio") or payload.get("pb"))
        roe = _num(payload.get("roe"))
        sector = str(payload.get("icb_sector") or payload.get("sector") or "").strip()
        subtype = str(payload.get("industry_subtype") or payload.get("industry") or "").strip()
        rows.append(
            {
                "symbol": str(sym or payload.get("symbol") or "").upper(),
                "pe": pe,
                "pb": pb,
                "roe": roe,
                "icb_sector": sector,
                "industry_subtype": subtype,
            }
        )
    return rows


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(pd.Series(vals).median())


def peer_universe(
    rows: list[dict[str, Any]],
    *,
    symbol: str,
    icb_sector: str | None = None,
    industry_subtype: str | None = None,
    min_peers: int = 3,
) -> list[dict[str, Any]]:
    sym = str(symbol or "").upper()
    sector = str(icb_sector or "").strip()
    subtype = str(industry_subtype or "").strip()
    peers: list[dict[str, Any]] = []
    if subtype:
        peers = [r for r in rows if r.get("symbol") != sym and str(r.get("industry_subtype") or "") == subtype]
    if len(peers) < min_peers and sector:
        peers = [r for r in rows if r.get("symbol") != sym and str(r.get("icb_sector") or "") == sector]
    # Drop absurd PE/PB for median stability
    cleaned: list[dict[str, Any]] = []
    for r in peers:
        pe = r.get("pe")
        pb = r.get("pb")
        if pe is not None and (pe <= 0 or pe > 120):
            pe = None
        if pb is not None and (pb <= 0 or pb > 30):
            pb = None
        if pe is None and pb is None:
            continue
        cleaned.append({**r, "pe": pe, "pb": pb})
    return cleaned


def assess_sector_relative(
    *,
    symbol: str,
    pe: float | None = None,
    pb: float | None = None,
    mos_pct: float | None = None,
    icb_sector: str | None = None,
    industry_subtype: str | None = None,
    rows: list[dict[str, Any]] | None = None,
    cache_path: Path | None = None,
) -> dict[str, Any]:
    """
    Return relative cheapness vs sector/subtype median.

    ``rel_pe_pct`` = (pe / median_pe - 1) * 100  (negative = cheaper than peers)
    """
    universe = rows if rows is not None else load_indicator_rows(cache_path)
    peers = peer_universe(
        universe,
        symbol=symbol,
        icb_sector=icb_sector,
        industry_subtype=industry_subtype,
    )
    pe_vals = [float(r["pe"]) for r in peers if r.get("pe") is not None]
    pb_vals = [float(r["pb"]) for r in peers if r.get("pb") is not None]
    med_pe = _median(pe_vals)
    med_pb = _median(pb_vals)

    pe_n = _num(pe)
    pb_n = _num(pb)
    if pe_n is not None and (pe_n <= 0 or pe_n > 120):
        pe_n = None
    if pb_n is not None and (pb_n <= 0 or pb_n > 30):
        pb_n = None

    rel_pe = None
    rel_pb = None
    if pe_n is not None and med_pe and med_pe > 0:
        rel_pe = round((pe_n / med_pe - 1.0) * 100.0, 2)
    if pb_n is not None and med_pb and med_pb > 0:
        rel_pb = round((pb_n / med_pb - 1.0) * 100.0, 2)

    # Score nudge: cheaper than peers → positive
    nudge = 0.0
    band = "unknown"
    notes: list[str] = []
    ok = len(peers) >= 3 and (rel_pe is not None or rel_pb is not None)
    if ok:
        # Prefer PE if available
        rel = rel_pe if rel_pe is not None else rel_pb
        assert rel is not None
        if rel <= -20:
            band = "cheap"
            nudge = 8.0
            notes.append(f"Rẻ hơn peer ~{abs(rel):.0f}% (median).")
        elif rel <= -8:
            band = "slightly_cheap"
            nudge = 4.0
            notes.append(f"Hơi rẻ hơn peer ~{abs(rel):.0f}%.")
        elif rel >= 25:
            band = "rich"
            nudge = -10.0
            notes.append(f"Đắt hơn peer ~{rel:.0f}%.")
        elif rel >= 10:
            band = "slightly_rich"
            nudge = -4.0
            notes.append(f"Hơi đắt hơn peer ~{rel:.0f}%.")
        else:
            band = "fair"
            nudge = 0.0
            notes.append("Định giá gần trung vị peer.")
        mos = _num(mos_pct)
        if mos is not None and mos >= 15 and band in ("cheap", "slightly_cheap"):
            nudge += 2.0
            notes.append("MOS dương củng cố relative value.")
        if mos is not None and mos < 0 and band in ("rich", "slightly_rich"):
            nudge -= 2.0

    return {
        "ok": ok,
        "symbol": str(symbol or "").upper(),
        "icb_sector": icb_sector,
        "industry_subtype": industry_subtype,
        "peer_count": len(peers),
        "peer_median_pe": round(med_pe, 2) if med_pe is not None else None,
        "peer_median_pb": round(med_pb, 2) if med_pb is not None else None,
        "pe": pe_n,
        "pb": pb_n,
        "rel_pe_pct": rel_pe,
        "rel_pb_pct": rel_pb,
        "band": band,
        "thesis_score_nudge": round(nudge, 1),
        "notes_vi": notes[:4],
        "source": "financial_indicators_cache",
    }


def attach_sector_relative_to_valuation(
    valuation: dict[str, Any] | None,
    *,
    symbol: str = "",
    financials: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Mutate-safe: returns valuation copy with ``sector_relative`` block."""
    val = dict(valuation or {})
    fin = financials if isinstance(financials, dict) else {}
    snap = snapshot if isinstance(snapshot, dict) else {}
    sym = str(symbol or val.get("symbol") or snap.get("symbol") or "").upper()
    pe = _num(val.get("pe")) or _num(fin.get("pe_ratio")) or _num(snap.get("pe_ratio"))
    pb = _num(val.get("pb")) or _num(fin.get("pb_ratio")) or _num(snap.get("pb_ratio"))
    sector = str(
        snap.get("icb_sector")
        or fin.get("icb_sector")
        or val.get("icb_sector")
        or ""
    )
    subtype = str(
        val.get("industry_subtype_id")
        or val.get("industry_subtype_label_vi")
        or snap.get("industry_subtype")
        or ""
    )
    block = assess_sector_relative(
        symbol=sym,
        pe=pe,
        pb=pb,
        mos_pct=_num(val.get("margin_of_safety_composite_pct")),
        icb_sector=sector or None,
        industry_subtype=subtype or None,
        rows=rows,
    )
    val["sector_relative"] = block
    return val
