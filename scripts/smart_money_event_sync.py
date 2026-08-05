#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scrapers.portal import fetch_latest_news  # noqa: E402


def _parse_vnd_value(text: str) -> float:
    t = str(text or "").lower().replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(tỷ|ty|triệu|trieu|nghìn tỷ|nghin ty)", t)
    if not m:
        return 0.0
    amount = float(m.group(1))
    unit = str(m.group(2))
    if unit in ("nghìn tỷ", "nghin ty"):
        return amount * 1_000_000_000_000.0
    if unit in ("tỷ", "ty"):
        return amount * 1_000_000_000.0
    if unit in ("triệu", "trieu"):
        return amount * 1_000_000.0
    return 0.0


def _detect_actor_type(text: str) -> str:
    t = str(text or "").lower()
    if "ban lãnh đạo" in t or "nội bộ" in t or "noi bo" in t:
        return "insider"
    if "cổ đông lớn" in t or "co dong lon" in t:
        return "major_shareholder"
    if "khối ngoại" in t or "khoi ngoai" in t or "foreign" in t:
        return "foreign"
    return "foreign"


def _detect_side(text: str) -> str | None:
    t = str(text or "").lower()
    pos = ("mua ròng", "mua", "đăng ký mua", "dang ky mua", "gom", "tăng sở hữu", "tang so huu")
    neg = ("bán ròng", "bán", "đăng ký bán", "dang ky ban", "thoái vốn", "thoai von", "giảm sở hữu", "giam so huu")
    for kw in pos:
        if kw in t:
            return "buy"
    for kw in neg:
        if kw in t:
            return "sell"
    return None


def _extract_actor_name(text: str, actor_type: str) -> str:
    raw = str(text or "").strip()
    t = raw.lower()
    if actor_type == "foreign":
        return "Khoi ngoai"
    if actor_type == "major_shareholder":
        m = re.search(r"(?:cổ đông lớn|co dong lon)\s+([^,.;:]+)", t)
        if m:
            return m.group(1).strip().title()
    if actor_type == "insider":
        m = re.search(r"(?:ông|ong|bà|ba)\s+([A-Za-zÀ-ỹ\s]{4,40})", raw, flags=re.IGNORECASE)
        if m:
            return m.group(0).strip()
        m2 = re.search(r"(?:ban lãnh đạo|noi bo|nội bộ)\s+([^,.;:]+)", raw, flags=re.IGNORECASE)
        if m2:
            return m2.group(1).strip()
    return "Unknown"


def _event_confidence(title: str, side: str, actor_type: str, net_value: float, source: str) -> float:
    score = 0.35
    tt = str(title or "").lower()
    if side in ("buy", "sell"):
        score += 0.2
    if any(k in tt for k in ("đăng ký", "dang ky", "mua ròng", "bán ròng", "ban rong")):
        score += 0.2
    if net_value > 0:
        score += 0.15
    if actor_type in ("insider", "major_shareholder", "foreign"):
        score += 0.05
    if str(source or "").strip().lower() in ("cafef", "vietstock", "exchange_disclosure", "hose", "hnx", "upcom"):
        score += 0.05
    return round(min(1.0, max(0.0, score)), 2)


def _build_event(symbol: str, row: dict[str, Any]) -> dict[str, Any] | None:
    title = str(row.get("title") or "").strip()
    if not title:
        return None
    side = _detect_side(title)
    if side is None:
        return None
    actor_type = _detect_actor_type(title)
    net_value = _parse_vnd_value(title)
    source = str(row.get("source") or "news")
    actor_name = _extract_actor_name(title, actor_type)
    confidence = _event_confidence(title, side, actor_type, net_value, source)
    return {
        "symbol": str(symbol).strip().upper(),
        "event_date": datetime.now(UTC).date().isoformat(),
        "actor_type": actor_type,
        "actor_name": actor_name,
        "side": side,
        "net_value_vnd": round(float(net_value), 2),
        "confidence": confidence,
        "source": source,
        "headline": title,
        "url": str(row.get("url") or ""),
        "synced_at_utc": datetime.now(UTC).isoformat(),
    }


def extract_events_from_news(symbol: str, news_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in news_rows or []:
        if not isinstance(row, dict):
            continue
        evt = _build_event(symbol, row)
        if evt is not None:
            out.append(evt)
    return out


def merge_events(existing: list[dict[str, Any]], incoming: list[dict[str, Any]], *, max_per_symbol: int = 200) -> list[dict[str, Any]]:
    pool = [x for x in existing if isinstance(x, dict)] + [x for x in incoming if isinstance(x, dict)]
    dedup: dict[str, dict[str, Any]] = {}
    for row in pool:
        actor_type = str(row.get("actor_type") or "foreign").strip().lower()
        side = str(row.get("side") or "").strip().lower()
        title = str(row.get("headline") or "")
        source = str(row.get("source") or "news")
        net_value = float(row.get("net_value_vnd") or 0.0)
        enriched = dict(row)
        enriched["actor_type"] = actor_type
        enriched["actor_name"] = str(row.get("actor_name") or _extract_actor_name(title, actor_type))
        enriched["confidence"] = float(
            row.get("confidence")
            if row.get("confidence") is not None
            else _event_confidence(title, side, actor_type, net_value, source)
        )
        k = "|".join(
            [
                str(enriched.get("symbol") or ""),
                str(enriched.get("event_date") or ""),
                str(enriched.get("actor_type") or ""),
                str(enriched.get("side") or ""),
                str(enriched.get("source") or ""),
                str(enriched.get("headline") or ""),
            ]
        )
        if k not in dedup:
            dedup[k] = enriched
    rows = list(dedup.values())
    rows.sort(key=lambda x: str(x.get("synced_at_utc") or ""), reverse=True)
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sym = str(row.get("symbol") or "").strip().upper()
        if not sym:
            continue
        by_symbol.setdefault(sym, []).append(row)
    out: list[dict[str, Any]] = []
    for sym in sorted(by_symbol.keys()):
        out.extend(by_symbol[sym][: max(1, int(max_per_symbol))])
    return out


def _read_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="FPT,VNM,HPG,VCB")
    ap.add_argument("--limit-per-symbol", type=int, default=20)
    ap.add_argument("--out", default="data/smart_money_events.json")
    ap.add_argument("--max-per-symbol", type=int, default=200)
    args = ap.parse_args()

    symbols = [x.strip().upper() for x in str(args.symbols).split(",") if x.strip()]
    incoming: list[dict[str, Any]] = []
    for sym in symbols:
        try:
            news = fetch_latest_news(sym, limit=max(1, int(args.limit_per_symbol)))
        except Exception:
            news = []
        incoming.extend(extract_events_from_news(sym, news))
    out_path = Path(str(args.out))
    existing = _read_existing(out_path)
    merged = merge_events(existing, incoming, max_per_symbol=max(1, int(args.max_per_symbol)))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "symbols": symbols,
        "incoming_events": len(incoming),
        "stored_events": len(merged),
        "out_path": str(out_path),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
