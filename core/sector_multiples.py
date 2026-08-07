"""
Sector / peer multiples for fair value (P/E & P/B ngành).

Ưu tiên:
1. Median peer cùng industry_subtype (metadata + indicator cache)
2. Median peer cùng ICB sector
3. Bảng subtype VN (mid-cycle) khi peer mỏng
4. Caller fallback bank/non-bank defaults trong valuation.py

Ghi chú nguồn luôn gắn vào snapshot để UI/trust phân biệt peer-spot vs mặc định.
Chưa phải P/E–P/B TB 5 năm lịch sử — dùng cross-section cache (spot) cho đến khi có warehouse.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.sector_relative import load_indicator_rows, peer_universe

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
_METADATA_PATH = ROOT / "data" / "stock_metadata.json"

# Mid-cycle VN priors khi peer cache mỏng (không thay thế peer khi đủ mẫu).
_SUBTYPE_FAIR_MULTIPLES: dict[str, tuple[float, float]] = {
    # (PE, PB)
    "bank": (12.5, 1.55),
    "securities": (14.0, 1.35),
    "insurance": (12.0, 1.45),
    "real_estate_residential": (12.0, 1.35),
    "real_estate_kcn": (14.0, 1.75),
    "consumer_staples": (16.0, 2.40),
    "consumer_retail": (17.0, 2.80),
    "oil_gas": (11.0, 1.20),
    "steel_materials": (10.0, 1.10),
    "pharma_healthcare": (15.0, 2.20),
    "technology_services": (18.0, 3.20),
    "other": (14.0, 1.80),
}

_CLUSTER_FAIR_MULTIPLES: dict[str, tuple[float, float]] = {
    "financial": (12.5, 1.50),
    "real_estate": (13.0, 1.45),
    "technology": (17.0, 3.00),
    "consumer_retail_transport": (16.0, 2.50),
    "energy_materials_industrials": (11.0, 1.20),
    "defensive_utilities_health": (14.0, 1.80),
}


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


@lru_cache(maxsize=1)
def _load_metadata() -> dict[str, dict[str, Any]]:
    if not _METADATA_PATH.is_file():
        return {}
    try:
        raw = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("sector_multiples_metadata_failed err=%s", exc.__class__.__name__)
        return {}
    return raw if isinstance(raw, dict) else {}


def _enriched_indicator_rows(cache_path: Path | None = None) -> list[dict[str, Any]]:
    """Gắn industry_subtype / cluster từ stock_metadata vào indicator cache."""
    rows = load_indicator_rows(cache_path)
    meta = _load_metadata()
    out: list[dict[str, Any]] = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        m = meta.get(sym) if isinstance(meta.get(sym), dict) else {}
        subtype = str(r.get("industry_subtype") or "").strip() or str(m.get("industry_subtype") or "").strip()
        cluster = str(m.get("industry_cluster") or "").strip()
        out.append(
            {
                **r,
                "industry_subtype": subtype,
                "industry_cluster": cluster,
                "industry_vi": str(m.get("industry_vi") or ""),
            }
        )
    return out


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    try:
        import pandas as pd

        return float(pd.Series(vals).median())
    except Exception:
        s = sorted(vals)
        n = len(s)
        mid = n // 2
        return float(s[mid]) if n % 2 else float((s[mid - 1] + s[mid]) / 2.0)


def _clamp_pe(pe: float | None) -> float | None:
    if pe is None or pe <= 0:
        return None
    return max(4.0, min(40.0, float(pe)))


def _clamp_pb(pb: float | None) -> float | None:
    if pb is None or pb <= 0:
        return None
    return max(0.4, min(8.0, float(pb)))


def _prior_multiples(
    *,
    industry_subtype: str | None,
    industry_cluster: str | None,
) -> tuple[float | None, float | None, str]:
    st = str(industry_subtype or "").strip().lower()
    if st in _SUBTYPE_FAIR_MULTIPLES:
        pe, pb = _SUBTYPE_FAIR_MULTIPLES[st]
        return pe, pb, f"subtype_prior:{st}"
    cl = str(industry_cluster or "").strip().lower()
    if cl in _CLUSTER_FAIR_MULTIPLES:
        pe, pb = _CLUSTER_FAIR_MULTIPLES[cl]
        return pe, pb, f"cluster_prior:{cl}"
    pe, pb = _SUBTYPE_FAIR_MULTIPLES["other"]
    return pe, pb, "subtype_prior:other"


def resolve_sector_multiples(
    *,
    symbol: str,
    icb_sector: str | None = None,
    industry_subtype: str | None = None,
    industry_cluster: str | None = None,
    min_peers: int = 2,
    cache_path: Path | None = None,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Trả P/E & P/B ngành dùng cho fair value + meta nguồn.

    Ưu tiên: warehouse đa năm (5y/multi_year) → peer spot → prior subtype.
    """
    sym = str(symbol or "").strip().upper()
    meta = _load_metadata()
    m = meta.get(sym) if isinstance(meta.get(sym), dict) else {}
    subtype = str(industry_subtype or m.get("industry_subtype") or "").strip()
    cluster = str(industry_cluster or m.get("industry_cluster") or "").strip()

    # --- Tier 0: true multi-year warehouse ---
    try:
        from core.sector_multiples_5y import lookup_5y_multiples

        hist = lookup_5y_multiples(
            symbol=sym,
            industry_subtype=subtype or None,
            icb_sector=icb_sector,
        )
    except Exception:
        hist = None
    if isinstance(hist, dict) and (hist.get("sector_pe") or hist.get("sector_pb")):
        pe_h = hist.get("sector_pe")
        pb_h = hist.get("sector_pb")
        # Blend nhẹ với peer spot / prior để tránh kẹt regime quá khứ (vd. NH PE 5x).
        prior_pe, prior_pb, _prior_src = _prior_multiples(
            industry_subtype=subtype or None,
            industry_cluster=cluster or None,
        )
        spot_pe = None
        spot_pb = None
        try:
            universe = rows if rows is not None else _enriched_indicator_rows(cache_path)
            peers_spot = peer_universe(
                universe,
                symbol=sym,
                icb_sector=icb_sector,
                industry_subtype=subtype or None,
                min_peers=min_peers,
            )
            pe_vals = [float(r["pe"]) for r in peers_spot if r.get("pe") is not None]
            pb_vals = [float(r["pb"]) for r in peers_spot if r.get("pb") is not None]
            spot_pe = _clamp_pe(_median(pe_vals)) if len(pe_vals) >= min_peers else None
            spot_pb = _clamp_pb(_median(pb_vals)) if len(pb_vals) >= min_peers else None
        except Exception:
            pass

        def _blend(hist_v: float | None, spot_v: float | None, prior_v: float | None) -> float | None:
            if hist_v is None:
                return spot_v if spot_v is not None else prior_v
            anchor = spot_v if spot_v is not None else prior_v
            if anchor is None:
                return hist_v
            # Chính mã: tin lịch sử mã hơn; ngành: cân bằng với neo hiện tại.
            w_hist = 0.80 if str(hist.get("match") or "").startswith("symbol:") else 0.65
            return round(w_hist * float(hist_v) + (1.0 - w_hist) * float(anchor), 2)

        pe_out = _blend(float(pe_h) if pe_h else None, spot_pe, prior_pe)
        pb_out = _blend(float(pb_h) if pb_h else None, spot_pb, prior_pb)
        w_hist = 0.80 if str(hist.get("match") or "").startswith("symbol:") else 0.65
        notes = [
            f"P/E ngành {pe_out:.1f} = {w_hist:.0%} warehouse {hist.get('coverage')} ({pe_h}) "
            f"+ {1-w_hist:.0%} neo ({hist.get('match')})."
            if pe_out
            else "",
            f"P/B ngành {pb_out:.2f} = {w_hist:.0%} warehouse {hist.get('coverage')} ({pb_h}) "
            f"+ {1-w_hist:.0%} neo ({hist.get('match')})."
            if pb_out
            else "",
        ]
        return {
            "symbol": sym,
            "industry_subtype": subtype or None,
            "industry_cluster": cluster or None,
            "icb_sector": icb_sector,
            "peer_count": int(hist.get("n_names") or 0),
            "peer_pe_count": int(hist.get("n_names") or 0) if pe_out else 0,
            "peer_pb_count": int(hist.get("n_names") or 0) if pb_out else 0,
            "peer_median_pe": pe_h,
            "peer_median_pb": pb_h,
            "sector_pe": pe_out,
            "sector_pb": pb_out,
            "source_pe": f"sector_multiples_5y_blend:{hist.get('coverage')}" if pe_out else "none",
            "source_pb": f"sector_multiples_5y_blend:{hist.get('coverage')}" if pb_out else "none",
            "notes_vi": [n for n in notes if n],
            "is_peer_based": True,
            "horizon": str(hist.get("horizon") or "5y_reconstruct"),
            "coverage": hist.get("coverage"),
            "match": hist.get("match"),
        }

    universe = rows if rows is not None else _enriched_indicator_rows(cache_path)

    peers = peer_universe(
        universe,
        symbol=sym,
        icb_sector=icb_sector,
        industry_subtype=subtype or None,
        min_peers=min_peers,
    )
    # Nếu subtype không đủ, peer_universe đã fallback ICB; nếu vẫn mỏng — thử cluster.
    if len(peers) < min_peers and cluster:
        cluster_peers = [
            r
            for r in universe
            if r.get("symbol") != sym and str(r.get("industry_cluster") or "") == cluster
        ]
        cleaned: list[dict[str, Any]] = []
        for r in cluster_peers:
            pe = r.get("pe")
            pb = r.get("pb")
            if pe is not None and (float(pe) <= 0 or float(pe) > 120):
                pe = None
            if pb is not None and (float(pb) <= 0 or float(pb) > 30):
                pb = None
            if pe is None and pb is None:
                continue
            cleaned.append({**r, "pe": pe, "pb": pb})
        if len(cleaned) >= min_peers:
            peers = cleaned

    pe_vals = [float(r["pe"]) for r in peers if r.get("pe") is not None]
    pb_vals = [float(r["pb"]) for r in peers if r.get("pb") is not None]
    med_pe = _clamp_pe(_median(pe_vals))
    med_pb = _clamp_pb(_median(pb_vals))
    prior_pe, prior_pb, prior_src = _prior_multiples(
        industry_subtype=subtype or None,
        industry_cluster=cluster or None,
    )

    source_pe = "none"
    source_pb = "none"
    pe_out = None
    pb_out = None
    notes: list[str] = []

    if med_pe is not None and len(pe_vals) >= min_peers:
        # Shrink cực trị về prior khi peer mỏng (<5).
        if prior_pe and len(pe_vals) < 5:
            w = min(0.55, 0.25 + 0.1 * len(pe_vals))
            pe_out = round(w * med_pe + (1.0 - w) * float(prior_pe), 2)
            source_pe = f"peer_median_blend:{len(pe_vals)}"
            notes.append(
                f"P/E ngành {pe_out:.1f} = blend peer median {med_pe:.1f} (n={len(pe_vals)}) + prior {prior_pe:.1f}."
            )
        else:
            pe_out = round(float(med_pe), 2)
            source_pe = f"peer_median:{len(pe_vals)}"
            notes.append(f"P/E ngành {pe_out:.1f} từ median peer (n={len(pe_vals)}).")
    elif prior_pe:
        pe_out = round(float(prior_pe), 2)
        source_pe = prior_src
        notes.append(f"P/E ngành {pe_out:.1f} từ prior subtype/cluster (peer mỏng).")

    if med_pb is not None and len(pb_vals) >= min_peers:
        if prior_pb and len(pb_vals) < 5:
            w = min(0.55, 0.25 + 0.1 * len(pb_vals))
            pb_out = round(w * med_pb + (1.0 - w) * float(prior_pb), 2)
            source_pb = f"peer_median_blend:{len(pb_vals)}"
            notes.append(
                f"P/B ngành {pb_out:.2f} = blend peer median {med_pb:.2f} (n={len(pb_vals)}) + prior {prior_pb:.2f}."
            )
        else:
            pb_out = round(float(med_pb), 2)
            source_pb = f"peer_median:{len(pb_vals)}"
            notes.append(f"P/B ngành {pb_out:.2f} từ median peer (n={len(pb_vals)}).")
    elif prior_pb:
        pb_out = round(float(prior_pb), 2)
        source_pb = prior_src
        notes.append(f"P/B ngành {pb_out:.2f} từ prior subtype/cluster (peer mỏng).")

    return {
        "symbol": sym,
        "industry_subtype": subtype or None,
        "industry_cluster": cluster or None,
        "icb_sector": icb_sector,
        "peer_count": len(peers),
        "peer_pe_count": len(pe_vals),
        "peer_pb_count": len(pb_vals),
        "peer_median_pe": round(med_pe, 2) if med_pe is not None else None,
        "peer_median_pb": round(med_pb, 2) if med_pb is not None else None,
        "sector_pe": pe_out,
        "sector_pb": pb_out,
        "source_pe": source_pe,
        "source_pb": source_pb,
        "notes_vi": notes,
        "is_peer_based": bool(
            str(source_pe).startswith("peer_") or str(source_pb).startswith("peer_")
        ),
        "horizon": "spot_cross_section",  # chưa phải 5Y lịch sử
    }


def inject_sector_multiples_into_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """
    In-place: gắn sector_pe_5y_avg / sector_pb_5y_avg khi thiếu.
    Không đè giá trị đã cung cấp từ ngoài (true 5Y / manual).
    """
    notes: list[str] = []
    if not isinstance(snapshot, dict):
        return notes

    has_pe = _num(snapshot.get("sector_pe_5y_avg")) is not None and float(snapshot.get("sector_pe_5y_avg")) > 0
    has_pb = _num(snapshot.get("sector_pb_5y_avg")) is not None and float(snapshot.get("sector_pb_5y_avg")) > 0
    if has_pe and has_pb:
        return notes

    sym = str(snapshot.get("symbol") or "").strip().upper()
    if not sym:
        return notes

    try:
        resolved = resolve_sector_multiples(
            symbol=sym,
            icb_sector=str(snapshot.get("icb_sector") or "") or None,
            industry_subtype=str(snapshot.get("industry_subtype") or "") or None,
            industry_cluster=str(snapshot.get("industry_cluster") or "") or None,
        )
    except Exception as exc:
        logger.warning("inject_sector_multiples_failed sym=%s err=%s", sym, exc.__class__.__name__)
        return notes

    snapshot["sector_multiples_meta"] = {
        "source_pe": resolved.get("source_pe"),
        "source_pb": resolved.get("source_pb"),
        "peer_count": resolved.get("peer_count"),
        "peer_pe_count": resolved.get("peer_pe_count"),
        "peer_pb_count": resolved.get("peer_pb_count"),
        "horizon": resolved.get("horizon"),
        "notes_vi": list(resolved.get("notes_vi") or []),
    }

    if not has_pe and resolved.get("sector_pe"):
        snapshot["sector_pe_5y_avg"] = float(resolved["sector_pe"])
        snapshot["sector_pe_source"] = str(resolved.get("source_pe") or "sector_multiples")
        snapshot["industry_pe"] = float(resolved["sector_pe"])
        notes.append(f"P/E ngành ← {resolved.get('source_pe')} ({resolved['sector_pe']:.1f})")

    if not has_pb and resolved.get("sector_pb"):
        snapshot["sector_pb_5y_avg"] = float(resolved["sector_pb"])
        snapshot["sector_pb_source"] = str(resolved.get("source_pb") or "sector_multiples")
        notes.append(f"P/B ngành ← {resolved.get('source_pb')} ({resolved['sector_pb']:.2f})")

    if resolved.get("horizon"):
        meta = snapshot.get("sector_multiples_meta")
        if isinstance(meta, dict):
            meta["horizon"] = resolved.get("horizon")
            meta["coverage"] = resolved.get("coverage")
            meta["match"] = resolved.get("match")
            snapshot["sector_multiples_meta"] = meta

    if not snapshot.get("industry_subtype") and resolved.get("industry_subtype"):
        snapshot["industry_subtype"] = resolved["industry_subtype"]
    if not snapshot.get("industry_cluster") and resolved.get("industry_cluster"):
        snapshot["industry_cluster"] = resolved["industry_cluster"]

    if notes:
        merge_notes = list(snapshot.get("fundamentals_merge_notes") or [])
        if isinstance(merge_notes, list):
            merge_notes.extend(notes)
            snapshot["fundamentals_merge_notes"] = list(dict.fromkeys(merge_notes))
    return notes


# ---------------------------------------------------------------------------
# Graham Filter — ngưỡng D/E & CR động theo nhóm ngành (Legend)
# ---------------------------------------------------------------------------

_GRAHAM_ASSET_LIGHT_CLUSTERS = frozenset({"tech_telecom", "technology"})
_GRAHAM_ASSET_LIGHT_SUBTYPES = frozenset({"technology_services"})
_GRAHAM_ASSET_LIGHT_KEYWORDS = (
    "công nghệ",
    "cong nghe",
    "technology",
    "software",
    "phần mềm",
    "phan mem",
    "viễn thông",
    "vien thong",
    "telecom",
    "telecommunications",
    "it services",
    "dịch vụ công nghệ",
    "dich vu cong nghe",
    "dịch vụ số",
    "dich vu so",
    "asset-light",
    "asset light",
)


def is_graham_asset_light_sector(
    *,
    industry_cluster: str | None = None,
    industry_subtype: str | None = None,
    industry_text: str | None = None,
) -> bool:
    """True nếu ngành thuộc nhóm Asset-light (CNTT / phần mềm / dịch vụ số / viễn thông)."""
    cl = str(industry_cluster or "").strip().lower().replace("-", "_")
    if cl in _GRAHAM_ASSET_LIGHT_CLUSTERS:
        return True
    st = str(industry_subtype or "").strip().lower().replace("-", "_")
    if st in _GRAHAM_ASSET_LIGHT_SUBTYPES:
        return True
    t = str(industry_text or "").strip().lower()
    if not t:
        return False
    return any(k in t for k in _GRAHAM_ASSET_LIGHT_KEYWORDS)


def graham_filter_criteria_for_sector(
    *,
    industry_cluster: str | None = None,
    industry_subtype: str | None = None,
    industry_text: str | None = None,
    is_bank: bool = False,
    bank_max_pe: float | None = None,
) -> dict[str, Any]:
    """
    Tiêu chí Graham Filter theo nhóm ngành.

    - Ngân hàng: lọc P/E (+ ROE/EPS/BV — caller kiểm tra inputs); không dùng CR/D/E công nghiệp.
    - Asset-light (Tech / Software / Dịch vụ số / Viễn thông): CR >= 1.1, D/E <= 0.8.
    - Sản xuất / Thương mại / còn lại (phi-NH): CR >= 1.5, D/E <= 0.5.
    """
    if is_bank:
        try:
            max_pe = float(bank_max_pe) if bank_max_pe is not None else 12.0
        except (TypeError, ValueError):
            max_pe = 12.0
        max_pe = max(5.0, min(25.0, max_pe))
        return {
            "group_id": "bank",
            "group_label_vi": "Chuẩn Ngân hàng",
            "mode": "bank_pe_roe",
            "max_debt_to_equity": None,
            "min_current_ratio": None,
            "bank_max_pe": max_pe,
        }

    if is_graham_asset_light_sector(
        industry_cluster=industry_cluster,
        industry_subtype=industry_subtype,
        industry_text=industry_text,
    ):
        return {
            "group_id": "asset_light",
            "group_label_vi": "Chuẩn Asset-light (CNTT/DV/Viễn thông)",
            "mode": "leverage_liquidity",
            "max_debt_to_equity": 0.8,
            "min_current_ratio": 1.1,
            "bank_max_pe": None,
        }

    # Phi-NH sản xuất / thương mại / mặc định — giữ Graham cổ điển.
    return {
        "group_id": "manufacturing_trade",
        "group_label_vi": "Chuẩn Sản xuất",
        "mode": "leverage_liquidity",
        "max_debt_to_equity": 0.5,
        "min_current_ratio": 1.5,
        "bank_max_pe": None,
    }