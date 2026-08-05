"""
Enrich stock metadata with `industry_subtype` and seed VN30/watchlist gaps.

Usage:
    python scripts/enrich_industry_subtype.py
    python scripts/enrich_industry_subtype.py --seed-vn30
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
META_PATH = ROOT / "data" / "stock_metadata.json"

# Seed tối thiểu cho VN30 + mã hay dùng (ACB/QTP…) — không ghi đè industry_vi đã có.
_VN30_SEED: dict[str, dict[str, str]] = {
    "ACB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "MBB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "HDB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "STB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "TPB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "VIB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "SSB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "SHB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "LPB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "VPB": {"industry_vi": "Ngân hàng", "industry_cluster": "financial", "industry_subtype": "bank"},
    "MSN": {"industry_vi": "Hàng tiêu dùng", "industry_cluster": "consumer_retail_transport", "industry_subtype": "consumer_staples"},
    "SAB": {"industry_vi": "Đồ uống", "industry_cluster": "consumer_retail_transport", "industry_subtype": "consumer_staples"},
    "VJC": {"industry_vi": "Hàng không — Vận tải", "industry_cluster": "consumer_retail_transport", "industry_subtype": "consumer_staples"},
    "VRE": {"industry_vi": "Bất động sản bán lẻ", "industry_cluster": "real_estate", "industry_subtype": "real_estate_residential"},
    "BCM": {"industry_vi": "Bất động sản", "industry_cluster": "real_estate", "industry_subtype": "real_estate_residential"},
    "GVR": {"industry_vi": "Cao su — Vật liệu", "industry_cluster": "energy_manufacturing", "industry_subtype": "steel_materials"},
    "QTP": {"industry_vi": "Điện — Nhiệt điện", "industry_cluster": "defensive", "industry_subtype": "other"},
    "POW": {"industry_vi": "Điện", "industry_cluster": "defensive", "industry_subtype": "other"},
    "PC1": {"industry_vi": "Điện — Xây lắp", "industry_cluster": "defensive", "industry_subtype": "other"},
}


def _norm(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def infer_subtype(industry_text: str, cluster_id: str) -> str:
    """Ưu tiên classifier dùng chung với valuation nếu import được."""
    try:
        from core.valuation import _classify_industry_subtype

        return str(_classify_industry_subtype(industry_text, cluster_id) or "other")
    except Exception:
        pass

    t = _norm(industry_text)
    c = _norm(cluster_id).replace("-", "_")

    if c == "financial":
        if any(k in t for k in ("ngân hàng", "ngan hang", "bank")):
            return "bank"
        if any(k in t for k in ("chứng khoán", "chung khoan", "securities", "broker", "môi giới", "moi gioi")):
            return "securities"
        if any(k in t for k in ("bảo hiểm", "bao hiem", "insurance", "phi nhân thọ", "nhân thọ", "tai nan")):
            return "insurance"
        return "other"

    if c == "real_estate":
        if any(
            k in t
            for k in (
                "khu công nghiệp",
                "khu cong nghiep",
                "kcn",
                "industrial park",
                "bat dong san cong nghiep",
                "bất động sản công nghiệp",
                "hạ tầng khu công nghiệp",
                "ha tang khu cong nghiep",
            )
        ):
            return "real_estate_kcn"
        return "real_estate_residential"

    if c == "consumer_retail_transport":
        if any(k in t for k in ("bán lẻ", "ban le", "retail", "thế giới di động", "the gioi di dong")):
            return "consumer_retail"
        return "consumer_staples"

    if c == "energy_manufacturing":
        if any(k in t for k in ("dầu khí", "dau khi", "oil", "gas")):
            return "oil_gas"
        if any(k in t for k in ("thép", "thep", "steel", "vật liệu", "vat lieu")):
            return "steel_materials"
        return "other"

    if c == "defensive":
        if any(k in t for k in ("dược", "duoc", "pharma", "y tế", "y te", "health")):
            return "pharma_healthcare"
        return "other"

    if c == "tech_telecom":
        if any(k in t for k in ("công nghệ", "cong nghe", "technology", "software", "it", "dịch vụ công nghệ")):
            return "technology_services"
        return "other"

    return "other"


def _seed_missing(data: dict) -> int:
    added = 0
    for sym, block in _VN30_SEED.items():
        cur = data.get(sym)
        if isinstance(cur, dict) and cur.get("industry_cluster"):
            # Chỉ bổ sung subtype nếu thiếu
            if not str(cur.get("industry_subtype") or "").strip():
                cur["industry_subtype"] = block.get("industry_subtype") or infer_subtype(
                    str(cur.get("industry_vi") or ""), str(cur.get("industry_cluster") or "")
                )
                added += 1
            continue
        data[sym] = dict(block)
        added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich industry_subtype in stock_metadata.json")
    parser.add_argument("--seed-vn30", action="store_true", default=True, help="Seed VN30/watchlist gaps (default on)")
    parser.add_argument("--no-seed", action="store_true", help="Disable seeding")
    args = parser.parse_args()

    if not META_PATH.exists():
        raise SystemExit(f"Missing metadata file: {META_PATH}")

    with open(META_PATH, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit("Invalid metadata format: root must be object")

    seeded = 0
    if args.seed_vn30 and not args.no_seed:
        seeded = _seed_missing(data)

    updated = 0
    by_subtype: dict[str, int] = {}
    for _sym, block in data.items():
        if not isinstance(block, dict):
            continue
        cluster = str(block.get("industry_cluster") or "").strip().lower()
        text = str(block.get("industry_vi") or block.get("industry") or "")
        inferred = infer_subtype(text, cluster)
        old = str(block.get("industry_subtype") or "").strip().lower()
        if old != inferred:
            block["industry_subtype"] = inferred
            updated += 1
        by_subtype[inferred] = by_subtype.get(inferred, 0) + 1

    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"Seeded symbols: {seeded}")
    print(f"Updated symbols: {updated}")
    print(f"Total symbols: {len(data)}")
    print("Subtype distribution:")
    for k in sorted(by_subtype.keys()):
        print(f"- {k}: {by_subtype[k]}")


if __name__ == "__main__":
    main()
