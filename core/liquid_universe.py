"""
Universe ưu tiên thanh khoản cho Autopilot / Finder / Deep Scan.

Tránh cửa sổ rotation thuần alphabet (HLT…HPA) — tín hiệu kém và hay thiếu OHLCV disk.
"""

from __future__ import annotations

import os
from typing import Any

from core.universe_rotation import rotation_offset, slice_universe, universe_auto_rotate_enabled

# VN30 (cập nhật định kỳ khi cơ cấu chỉ số đổi).
VN30_SYMBOLS: tuple[str, ...] = (
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
)


def autopilot_universe_mode() -> str:
    """
    II_AUTOPILOT_UNIVERSE_MODE:
      - dynamic_liquid (mặc định P3): xếp theo thanh khoản disk + VN30 seed
      - liquid: VN30 + HOSE (nhanh hơn, thiên blue-chip)
      - vn30: chỉ VN30
      - rotate_full: xoay vòng TOÀN bộ listing VN (HOSE+HNX+UPCOM)
    """
    raw = str(os.environ.get("II_AUTOPILOT_UNIVERSE_MODE", "dynamic_liquid") or "dynamic_liquid").strip().lower()
    if raw in ("vn30", "vn-30", "index"):
        return "vn30"
    if raw in ("liquid", "hose", "bluechip"):
        return "liquid"
    if raw in ("dynamic_liquid", "dynamic", "vol_rank"):
        return "dynamic_liquid"
    if raw in ("rotate_full", "full", "alphabet", "legacy", "market", "all"):
        return "rotate_full"
    return "dynamic_liquid"


def _hose_symbols(full_listing: list[str]) -> list[str]:
    """
    Lấy HOSE từ cache listing local trước — tránh gọi vnstock API blocking
    (có thể treo hàng phút khi mạng/Vietcap chậm).
    """
    try:
        from scrapers.vn_listing import list_symbols_by_exchange

        hose = [
            str(s).strip().upper()
            for s in list_symbols_by_exchange("HOSE", use_api=False)
            if str(s).strip()
        ]
        if hose:
            return hose
    except Exception:
        pass
    # Fallback: dùng full listing đã có (không phát sinh I/O mạng thêm).
    return [str(s).strip().upper() for s in full_listing if str(s).strip()]


def build_liquid_pool(full_listing: list[str] | None = None) -> list[str]:
    """VN30 trước, sau đó HOSE (loại trùng)."""
    full = list(full_listing or [])
    vn30 = [s for s in VN30_SYMBOLS]
    seen = set(vn30)
    hose = _hose_symbols(full)
    extra = [s for s in hose if s not in seen]
    return vn30 + extra


def build_dynamic_liquid_pool(
    full_listing: list[str] | None = None,
    *,
    top_n: int = 400,
    sessions: int = 20,
) -> list[str]:
    """
    P3: pool thanh khoản động từ ohlcv_store (avg vol 20 phiên).
    Fallback VN30+HOSE khi store trống.
    """
    try:
        from core.ohlcv_store import top_symbols_by_avg_volume

        full = [str(s).strip().upper() for s in (full_listing or []) if str(s).strip()]
        ranked = top_symbols_by_avg_volume(limit=int(top_n), sessions=int(sessions), candidates=full or None)
        if ranked:
            vn30_set = set(VN30_SYMBOLS)
            syms = [s for s, _ in ranked]
            # Always prepend any VN30 missing from vol rank (index continuity)
            for v in VN30_SYMBOLS:
                if v not in syms:
                    syms.insert(0, v)
            seen: set[str] = set()
            out: list[str] = []
            for s in syms:
                if s in seen:
                    continue
                seen.add(s)
                out.append(s)
                if len(out) >= int(top_n):
                    break
            return out
    except Exception:
        pass
    return build_liquid_pool(full_listing)


def resolve_scan_universe(
    limit: int,
    *,
    full_listing: list[str] | None = None,
    rotation_day: int | None = None,
    mode: str | None = None,
    rotation_key: str = "autopilot",
) -> tuple[list[str], dict[str, Any]]:
    """
    Chọn cửa sổ mã cho Autopilot/Finder.

    Returns:
      (symbols, meta) — meta có mode, pool_size, offset, limit.
    """
    lim = max(1, min(int(limit or 30), 200))
    mode_eff = (mode or autopilot_universe_mode()).strip().lower()
    if mode_eff in ("vn-30", "index"):
        mode_eff = "vn30"
    if mode_eff in ("full", "alphabet", "legacy"):
        mode_eff = "rotate_full"

    rotate = universe_auto_rotate_enabled()
    off = 0

    if mode_eff == "vn30":
        pool = list(VN30_SYMBOLS)
        if rotate and len(pool) > lim:
            off = rotation_offset(total=len(pool), window=lim, key=f"{rotation_key}:vn30", day_ordinal=rotation_day)
            symbols = slice_universe(pool, offset=off, limit=lim)
        else:
            symbols = pool[:lim]
        meta = {
            "mode": "vn30",
            "pool_size": len(pool),
            "offset": int(off),
            "limit": lim,
            "rotated": bool(rotate and len(pool) > lim),
        }
        return symbols, meta

    # Chỉ nạp full listing khi thật sự cần (tránh API treo).
    if full_listing is None:
        full = _listing_symbols_disk_first()
    else:
        full = list(full_listing)

    if mode_eff == "rotate_full":
        pool = [str(s).strip().upper() for s in full if str(s).strip()]
        if not pool:
            pool = list(VN30_SYMBOLS)
        if rotate:
            off = rotation_offset(total=len(pool), window=lim, key=rotation_key, day_ordinal=rotation_day)
        symbols = slice_universe(pool, offset=off, limit=lim)
        meta = {
            "mode": "rotate_full",
            "pool_size": len(pool),
            "offset": int(off),
            "limit": lim,
            "rotated": bool(rotate),
        }
        return symbols, meta

    if mode_eff == "dynamic_liquid":
        pool = build_dynamic_liquid_pool(full, top_n=max(lim * 4, 120))
        if not pool:
            pool = build_liquid_pool(full)
        if rotate and len(pool) > lim:
            off = rotation_offset(total=len(pool), window=lim, key=f"{rotation_key}:dynamic", day_ordinal=rotation_day)
            symbols = slice_universe(pool, offset=off, limit=lim)
        else:
            off = 0
            symbols = pool[:lim]
        meta = {
            "mode": "dynamic_liquid",
            "pool_size": len(pool),
            "offset": int(off),
            "limit": lim,
            "rotated": bool(rotate and len(pool) > lim),
            "source": "ohlcv_store_avg_vol",
        }
        return symbols, meta

    # liquid (default) — nếu limit <= VN30 thì không cần HOSE listing.
    if lim <= len(VN30_SYMBOLS) and not rotate:
        symbols = list(VN30_SYMBOLS)[:lim]
        meta = {
            "mode": "liquid",
            "pool_size": len(VN30_SYMBOLS),
            "offset": 0,
            "limit": lim,
            "vn30_core": lim,
            "rotated": False,
        }
        return symbols, meta

    pool = build_liquid_pool(full)
    if not pool:
        pool = list(VN30_SYMBOLS)
    if rotate and len(pool) > lim:
        # Giữ bias VN30: nửa đầu cửa sổ ưu tiên VN30 rotate, phần còn lại từ HOSE.
        vn30 = list(VN30_SYMBOLS)
        n_core = min(len(vn30), max(10, lim // 2) if lim > 20 else lim)
        n_core = min(n_core, lim)
        if len(vn30) > n_core:
            off_core = rotation_offset(
                total=len(vn30),
                window=n_core,
                key=f"{rotation_key}:vn30",
                day_ordinal=rotation_day,
            )
            core = slice_universe(vn30, offset=off_core, limit=n_core)
        else:
            off_core = 0
            core = vn30[:n_core]
        need = lim - len(core)
        extra_pool = [s for s in pool if s not in set(core)]
        off_extra = 0
        if need > 0 and extra_pool:
            if len(extra_pool) > need:
                off_extra = rotation_offset(
                    total=len(extra_pool),
                    window=need,
                    key=f"{rotation_key}:hose",
                    day_ordinal=rotation_day,
                )
            extra = slice_universe(extra_pool, offset=off_extra, limit=need)
        else:
            extra = []
        symbols = core + extra
        off = off_core
        meta = {
            "mode": "liquid",
            "pool_size": len(pool),
            "offset": int(off),
            "offset_extra": int(off_extra),
            "limit": lim,
            "vn30_core": len(core),
            "rotated": True,
        }
        return symbols, meta

    symbols = pool[:lim]
    meta = {
        "mode": "liquid",
        "pool_size": len(pool),
        "offset": 0,
        "limit": lim,
        "vn30_core": min(len(VN30_SYMBOLS), lim),
        "rotated": False,
    }
    return symbols, meta


def _listing_symbols_disk_first() -> list[str]:
    """Đọc listing từ cache đĩa; không gọi API refresh (tránh hang Autopilot)."""
    try:
        from scrapers.vn_listing import list_tradable_vn_symbols

        syms = [str(s).strip().upper() for s in list_tradable_vn_symbols(use_api=False) if str(s).strip()]
        if syms:
            return syms
    except Exception:
        pass
    try:
        from scrapers.financial_data import list_universe_symbols

        return [str(s).strip().upper() for s in (list_universe_symbols(limit=None) or []) if str(s).strip()]
    except Exception:
        return list(VN30_SYMBOLS)
