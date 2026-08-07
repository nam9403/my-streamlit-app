"""
Lấy snapshot tài chính: mặc định ưu tiên giá/dữ liệu live; mock_json làm dự phòng hoặc khi II_SNAPSHOT_PREFER_LIVE=0.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests  # type: ignore

from core.snapshot_disk_cache import get_cached_snapshot, get_disk_snapshot_any_age, put_snapshot
from core.valuation import value_investing_summary
from scrapers.vn_listing import list_tradable_vn_symbols, tradable_vn_symbol_count

# Đường dẫn tới mock JSON (cùng cây dự án)
_ROOT = Path(__file__).resolve().parent.parent
_MOCK_PATH = _ROOT / "data" / "mock_financials.json"
_META_PATH = _ROOT / "data" / "stock_metadata.json"
_SWR_REFRESH_LAST_TS: dict[str, float] = {}

# Tránh đọc/parsing JSON lặp khi file không đổi (scan + panels gọi nhiều lần mỗi rerun).
_meta_cache_mtime: float = -2.0
_meta_cache_data: dict[str, Any] | None = None
_subtype_cache_mtime: float = -2.0
_subtype_cache_data: dict[str, str] | None = None
_peer_buckets_mtime: float = -2.0
_peer_buckets: dict[Any, list[str]] | None = None
_mock_cache_mtime: float = -2.0
_mock_cache_data: dict[str, Any] | None = None


def _meta_path_mtime() -> float:
    try:
        if not _META_PATH.exists():
            return -1.0
        return float(_META_PATH.stat().st_mtime)
    except OSError:
        return -1.0


def _mock_path_mtime() -> float:
    try:
        if not _MOCK_PATH.exists():
            return -1.0
        return float(_MOCK_PATH.stat().st_mtime)
    except OSError:
        return -1.0


def clear_stock_metadata_cache() -> None:
    """Gọi sau khi sửa stock_metadata.json trong test hoặc reload thủ công."""
    global _meta_cache_mtime, _meta_cache_data, _subtype_cache_mtime, _subtype_cache_data
    global _peer_buckets_mtime, _peer_buckets, _mock_cache_mtime, _mock_cache_data
    _meta_cache_mtime = -2.0
    _meta_cache_data = None
    _subtype_cache_mtime = -2.0
    _subtype_cache_data = None
    _peer_buckets_mtime = -2.0
    _peer_buckets = None
    _mock_cache_mtime = -2.0
    _mock_cache_data = None


def universe_symbol_count() -> int:
    """Tổng số mã universe (nhất quán với list_universe_symbols khi offset=0, limit=None)."""
    return tradable_vn_symbol_count(use_api=True)


def _is_pure_demo_mock_source(source: str | None) -> bool:
    """
    True chỉ khi snapshot là mock demo thuần (chưa gắn giá thị trường).

    `mock_json+market_fallback` / quote live KHÔNG coi là demo — được phép dùng cache.
    """
    s = str(source or "").strip().lower()
    if not s:
        return False
    if "market_fallback" in s:
        return False
    if any(
        tok in s
        for tok in (
            "quote_fast",
            "quote_fresh",
            "request_live",
            "vietstock",
            "vndirect",
            "cafef",
            "vnstock",
        )
    ):
        return False
    base = s[:-4] if s.endswith(":swr") else s
    return base == "mock_json" or base.startswith("mock_json+")


def _prefer_live_snapshot() -> bool:
    """
    Policy:
    - II_SNAPSHOT_PREFER_LIVE=1 → luôn ưu tiên nguồn live (giá thật).
    - II_SNAPSHOT_PREFER_LIVE=0 → ưu tiên mock_json khi có (offline / siêu nhanh).
    - Không set biến: mặc định ưu tiên live (đúng kỳ vọng khi mở app xem giá thật).
    """
    force = str(os.environ.get("II_SNAPSHOT_PREFER_LIVE", "") or "").strip().lower()
    if force in ("1", "true", "yes", "on"):
        return True
    if force in ("0", "false", "no", "off"):
        return False
    return True


def _quote_order_prefers_cafef_first() -> bool:
    raw = str(os.environ.get("II_QUOTE_PROVIDER_ORDER", "vndirect,cafef,vietstock") or "").strip().lower()
    if not raw:
        return False
    first = raw.split(",")[0].strip()
    return first.startswith("cafef")


def _snapshot_uses_ohlcv_store_fastpath_price(snap: dict[str, Any]) -> bool:
    ps = str(snap.get("price_source") or "").lower()
    if "ohlcv_store_fastpath" in ps:
        return True
    return "ohlcv_store_fastpath" in str(snap.get("source") or "").lower()


def _skip_disk_cache_for_fresh_cafef_quote(snap: dict[str, Any]) -> bool:
    """Khi ưu tiên CafeF, không phục vụ snapshot đĩa cũ chỉ còn dấu OHLCV store (tránh 'treo' nguồn sai)."""
    return _quote_order_prefers_cafef_first() and _snapshot_uses_ohlcv_store_fastpath_price(snap)


def _stale_ohlcv_disk_bypass_enabled() -> bool:
    """
    Mặc định tắt: tránh quét Finder/scan (hàng chục–trăm mã) mỗi lần đều bỏ cache đĩa → gọi mạng lặp cực chậm.

    Bật II_SNAPSHOT_BYPASS_STALE_OHLCV_DISK=1 khi cần ép refresh snapshot đĩa có price_source OHLCV fastpath
    (bảng kệ đã ưu tiên quote live riêng khi II_SNAPSHOT_PREFER_LIVE=1, không phụ thuộc cờ này).
    """
    v = str(os.environ.get("II_SNAPSHOT_BYPASS_STALE_OHLCV_DISK", "0") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _unified_live_price_enabled() -> bool:
    """
    Giá thống nhất toàn app + ưu tiên quote mới nhất (get_stock_data, không cache).

    Khi bật (mặc định ON): không dùng đóng cửa OHLCV để ghi đè `row["price"]`;
    luôn thử quote tươi. Biểu đồ OHLCV vẫn dùng nguồn portal riêng.

    Tắt bằng II_UNIFIED_LIVE_PRICE=0 nếu cần khớp chart với OHLCV kho (không khuyến nghị cho khách).
    """
    v = str(os.environ.get("II_UNIFIED_LIVE_PRICE", "1") or "").strip().lower()
    return v not in ("0", "false", "no", "off")


def _ohlcv_max_stale_days() -> int:
    try:
        return max(1, min(14, int(os.environ.get("II_OHLCV_PRICE_MAX_STALE_DAYS", "3") or 3)))
    except ValueError:
        return 3


def _ohlcv_frame_is_stale(ohlcv: Any, *, max_age_days: int | None = None) -> bool:
    """True nếu nến cuối quá cũ so với hôm nay — không được dùng làm giá khách."""
    try:
        if ohlcv is None or getattr(ohlcv, "empty", True):
            return True
        last_d = ohlcv.iloc[-1].get("date")
        ts = pd.Timestamp(last_d)
        if pd.isna(ts):
            return True
        today = pd.Timestamp.now(tz=None).normalize()
        age = int((today - ts.normalize()).days)
        return age > int(max_age_days if max_age_days is not None else _ohlcv_max_stale_days())
    except Exception:
        return True


def ensure_request_time_live_price(row: dict[str, Any], symbol: str) -> dict[str, Any]:
    """
    Ép cập nhật giá quote tại thời điểm khách yêu cầu phân tích.

    Không lấy giá đóng cửa OHLCV kho làm giá hiện tại. Fail-soft: giữ giá cũ nếu mạng lỗi.
    """
    if not isinstance(row, dict):
        return {}
    out = row
    sym = str(symbol or out.get("symbol") or "").strip().upper()
    if not sym:
        return out
    try:
        old_px = float(out.get("price") or 0)
    except (TypeError, ValueError):
        old_px = 0.0

    # 1) Quote đầy đủ không cache
    try:
        from scrapers.finance_scraper import ScraperError, get_stock_data

        q = get_stock_data(sym, use_cache=False)
        px = float((q or {}).get("price") or 0)
        if px > 0:
            out["price"] = px
            out["price_source"] = f"request_live:{q.get('source', 'unknown')}"
            out["price_fetched_at"] = datetime.now(timezone.utc).isoformat()
            if old_px > 0 and abs(px - old_px) / max(old_px, px, 1e-6) > 0.03:
                out["price_crosscheck_note_vi"] = (
                    f"Đã làm mới giá live {px:,.0f} đ (kho/cache trước đó {old_px:,.0f} đ)."
                )
            return out
    except Exception:
        pass

    # 2) Quote nhanh 1 provider
    try:
        from scrapers.finance_scraper import get_quote_price_fast

        q2 = get_quote_price_fast(sym, budget_sec=3.0, max_providers=2)
        px2 = float((q2 or {}).get("price") or 0)
        if px2 > 0:
            out["price"] = px2
            out["price_source"] = f"request_live_fast:{q2.get('source', 'unknown')}"
            out["price_fetched_at"] = datetime.now(timezone.utc).isoformat()
            return out
    except Exception:
        pass

    out.setdefault(
        "price_crosscheck_note_vi",
        "Không lấy được giá live lúc yêu cầu — tạm dùng giá trong snapshot (có thể cũ).",
    )
    return out


def _snapshot_attach_live_enabled() -> bool:
    """
    Mặc định tắt live attach để ưu tiên tốc độ mở app.
    Bật lại bằng II_SNAPSHOT_ATTACH_LIVE=1 khi cần ép lấy giá live ngay.
    """
    v = os.environ.get("II_SNAPSHOT_ATTACH_LIVE", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _align_price_with_ohlcv_enabled() -> bool:
    """
    Khi bật (II_ALIGN_PRICE_WITH_OHLCV=1): đồng bộ giá định giá với giá đóng cửa OHLCV (cùng nguồn biểu đồ).
    Mặc định tắt để tránh gọi thêm mạng; script run_app.* bật giúp người dùng khi cần khớp chart.
    Luôn có sửa chọn phiên mới nhất từ VNDirect quote (finance_scraper) khi không bật align.
    """
    v = os.environ.get("II_ALIGN_PRICE_WITH_OHLCV", "0").strip().lower()
    return v in ("1", "true", "yes", "on")


def _snapshot_swr_enabled() -> bool:
    # Mặc định bật: trả disk ngay + refresh nền — giảm cold-start ~20s khi TTL hết.
    v = os.environ.get("II_SNAPSHOT_STALE_WHILE_REVALIDATE", "1").strip().lower()
    return v in ("1", "true", "yes", "on")


def _snapshot_swr_refresh_min_interval_sec() -> float:
    try:
        return max(10.0, float(os.environ.get("II_SNAPSHOT_SWR_MIN_REFRESH_SEC", "60")))
    except ValueError:
        return 60.0


def _snapshot_swr_price_overlay_enabled() -> bool:
    """
    Trên đường SWR / cache hit: cập nhật giá nhanh trước khi trả về UI.
    Mặc định BẬT — tránh hiện giá đĩa/mock cũ khi fundamentals vẫn dùng cache.
    Tắt bằng II_SNAPSHOT_SWR_PRICE_OVERLAY=0 nếu cần first-paint tuyệt đối không mạng.
    """
    v = os.environ.get("II_SNAPSHOT_SWR_PRICE_OVERLAY", "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def _snapshot_swr_price_budget_sec() -> float:
    try:
        return max(0.5, min(8.0, float(os.environ.get("II_SNAPSHOT_SWR_PRICE_BUDGET_SEC", "2.5"))))
    except ValueError:
        return 2.5


def _overlay_live_price_fast(row: dict[str, Any], sym: str, *, budget_sec: float) -> bool:
    """Cập nhật price từ quote nhanh / fallback thị trường; giữ fundamentals. True nếu đổi được giá."""
    try:
        from scrapers.finance_scraper import get_quote_price_fast

        # Ưu tiên 2 provider trong budget ngắn — giảm miss khi VNDirect chậm.
        q = get_quote_price_fast(sym, budget_sec=budget_sec, max_providers=2)
        if isinstance(q, dict):
            px = float(q.get("price") or 0)
            if px > 0:
                row["price"] = px
                row["price_source"] = f"quote_fast:{q.get('source', 'unknown')}"
                if q.get("pe_ratio") is not None and row.get("pe_ratio") in (None, 0, 0.0):
                    row["pe_ratio"] = q.get("pe_ratio")
                if q.get("pb_ratio") is not None and row.get("pb_ratio") in (None, 0, 0.0):
                    row["pb_ratio"] = q.get("pb_ratio")
                return True
    except Exception:
        pass
    px_fb, src_fb = _market_price_fallback(sym)
    if px_fb and px_fb > 0:
        row["price"] = float(px_fb)
        row["price_source"] = f"quote_fast_fallback:{src_fb}"
        return True
    return False


def _refresh_price_on_cached_snapshot(row: dict[str, Any], sym: str) -> dict[str, Any]:
    """Khi trả snapshot từ cache/SWR: luôn cố lấy giá mới nhất nếu overlay bật (mặc định)."""
    out = dict(row)
    if not _snapshot_swr_price_overlay_enabled():
        return out
    price_ok = _overlay_live_price_fast(out, sym, budget_sec=_snapshot_swr_price_budget_sec())
    if price_ok:
        out["snapshot_fundamentals_note_vi"] = (
            "Fundamentals từ cache; giá đã làm mới live tại thời điểm mở."
        )
    return out


def _launch_snapshot_refresh(sym: str) -> None:
    now = time.time()
    key = str(sym or "").strip().upper()
    last = float(_SWR_REFRESH_LAST_TS.get(key, 0.0))
    if (now - last) < _snapshot_swr_refresh_min_interval_sec():
        return
    _SWR_REFRESH_LAST_TS[key] = now

    def _refresh() -> None:
        try:
            fetch_financial_snapshot(key, bypass_cache=True)
        except Exception:
            return

    t = threading.Thread(target=_refresh, name=f"snapshot_swr_refresh_{key}", daemon=True)
    t.start()


def _load_mock_json() -> dict[str, Any]:
    global _mock_cache_mtime, _mock_cache_data
    mt = _mock_path_mtime()
    if _mock_cache_data is not None and _mock_cache_mtime == mt:
        return _mock_cache_data
    if not _MOCK_PATH.exists():
        _mock_cache_mtime = mt
        _mock_cache_data = {}
        return _mock_cache_data
    with open(_MOCK_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    payload = raw if isinstance(raw, dict) else {}
    _mock_cache_mtime = mt
    _mock_cache_data = payload
    return payload


def _load_stock_metadata() -> dict[str, Any]:
    global _meta_cache_mtime, _meta_cache_data
    mt = _meta_path_mtime()
    if _meta_cache_data is not None and _meta_cache_mtime == mt:
        return _meta_cache_data
    if not _META_PATH.exists():
        _meta_cache_mtime = mt
        _meta_cache_data = {}
        return _meta_cache_data
    try:
        with open(_META_PATH, encoding="utf-8") as f:
            data = json.load(f)
        payload = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    _meta_cache_mtime = mt
    _meta_cache_data = payload
    return _meta_cache_data


def _merge_stock_metadata(row: dict[str, Any], sym: str) -> None:
    """Bổ sung industry / industry_cluster từ stock_metadata.json nếu thiếu."""
    meta_all = _load_stock_metadata()
    block = meta_all.get(sym.upper())
    if not isinstance(block, dict):
        return
    if not row.get("industry") and not row.get("industry_name"):
        iv = block.get("industry_vi") or block.get("industry")
        if iv:
            row["industry"] = str(iv)
    if not row.get("industry_cluster") and block.get("industry_cluster"):
        row["industry_cluster"] = str(block["industry_cluster"]).strip().lower()
    if not row.get("industry_subtype") and block.get("industry_subtype"):
        row["industry_subtype"] = str(block["industry_subtype"]).strip().lower()


def _market_price_fallback(sym: str) -> tuple[float | None, str]:
    """
    Khi scrape live lỗi: lấy giá thị trường gần đúng thay vì giá mock demo (vd. FPT 98k).
    Thứ tự: quote vnstock → OHLCV store → Autopilot board.
    """
    s = str(sym or "").strip().upper()
    if not s:
        return None, ""
    try:
        from scrapers.vnstock_provider import fetch_latest_quote_price

        q = fetch_latest_quote_price(s)
        if isinstance(q, dict):
            px = float(q.get("price") or q.get("last") or 0)
            if px > 0:
                return px, str(q.get("source") or "vnstock_quote")
    except Exception:
        pass
    try:
        from core.ohlcv_store import load_recent_ohlcv

        df = load_recent_ohlcv(s, sessions=8)
        if df is not None and not getattr(df, "empty", True):
            close = float(df.iloc[-1].get("close") or 0)
            if close > 0:
                return close, "ohlcv_store_fallback"
    except Exception:
        pass
    try:
        from core.autopilot_nightly_board import load_board

        board = load_board() or {}
        rows = board.get("rows") if isinstance(board, dict) else {}
        row = rows.get(s) if isinstance(rows, dict) else None
        if isinstance(row, dict):
            px = float(row.get("Giá") or row.get("price") or 0)
            if px > 0:
                return px, "autopilot_board_fallback"
    except Exception:
        pass
    return None, ""


def _apply_price_fallback_over_mock(row: dict[str, Any], sym: str) -> bool:
    """Ghi đè giá mock nếu lệch mạnh so với fallback thị trường. True nếu đã đổi giá."""
    px, src = _market_price_fallback(sym)
    if not px or px <= 0:
        return False
    try:
        mock_px = float(row.get("price") or 0)
    except (TypeError, ValueError):
        mock_px = 0.0
    if mock_px > 0:
        rel = abs(mock_px - px) / max(mock_px, px)
        if rel < 0.08:
            return False
    row["price"] = float(px)
    row["price_source"] = src
    src0 = str(row.get("source") or "mock_json")
    if "market_fallback" not in src0:
        row["source"] = f"{src0}+market_fallback"
    row["snapshot_fundamentals_note_vi"] = (
        f"Giá mock demo đã bị thay bằng giá thị trường gần nhất ({src}: {px:,.0f})."
    )
    return True


def _resolve_snapshot_market_price(
    row: dict[str, Any],
    sym: str,
    *,
    skip_duplicate_live_quote: bool = False,
) -> None:
    """
    Chuẩn hóa giá cho MOS / P/E / P/B:
    - Mặc định II_UNIFIED_LIVE_PRICE=1: không ghi đè `price` bằng OHLCV kho; ưu tiên quote tươi (get_stock_data, không cache).
    - II_UNIFIED_LIVE_PRICE=0 + II_ALIGN_PRICE_WITH_OHLCV=1: có thể đồng bộ với đóng cửa OHLCV *chỉ khi nến còn tươi*.
    - skip_duplicate_live_quote: khi vừa scrape live trong fetch_financial_snapshot, tránh gọi get_stock_data lần 2
      (giảm treo Finder/scan nhiều mã).
    - II_SNAPSHOT_ATTACH_LIVE=1: (khi không unified) sau OHLCV có thể fallback quote tươi.
    """
    force_ohlcv = str(os.environ.get("II_SNAPSHOT_FORCE_OHLCV_CROSSCHECK", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    unified = _unified_live_price_enabled()
    src_main = str(row.get("source") or "").strip().lower()
    try:
        qpx = float(row.get("price") or 0)
    except (TypeError, ValueError):
        qpx = 0.0
    if (
        not force_ohlcv
        and not unified
        and src_main.startswith("cafef")
        and qpx > 0
    ):
        # Giữ giá CafeF; không ghi đè bằng OHLCV disk/store (dễ cũ hoặc lệch kỳ vọng "giá sàn").
        return

    align = _align_price_with_ohlcv_enabled()
    attach = _snapshot_attach_live_enabled()

    if not (align or attach or unified):
        return

    quote_px = float(row.get("price") or 0)

    if align and not unified:
        try:
            from scrapers.portal import fetch_ohlcv_history

            ohlcv = fetch_ohlcv_history(sym, sessions=80)
            if not ohlcv.empty:
                close = float(ohlcv.iloc[-1].get("close") or 0)
                if close > 0:
                    src = str(ohlcv.attrs.get("source", "live"))
                    # Không bao giờ lấy OHLCV kho cũ làm "giá hiện tại" cho khách.
                    if _ohlcv_frame_is_stale(ohlcv):
                        last_d = ohlcv.iloc[-1].get("date")
                        try:
                            as_of = str(pd.Timestamp(last_d).date())
                        except Exception:
                            as_of = str(last_d)
                        if quote_px > 0:
                            row["price_crosscheck_note_vi"] = (
                                f"OHLCV dừng ở {as_of} (đóng {close:,.0f}) — quá cũ; "
                                "giữ giá quote và sẽ ưu tiên live nếu có."
                            )
                        else:
                            row["price_crosscheck_note_vi"] = (
                                f"OHLCV dừng ở {as_of} — quá cũ, không dùng làm giá hiện tại."
                            )
                        # Fall through → nhánh quote live (attach/unified) hoặc giữ quote.
                    else:
                        # Tránh ghi đè giá quote VND hợp lệ bằng OHLCV nhầm sàn (vd. ticker US trùng mã).
                        ohlcv_suspect = False
                        if quote_px <= 0 and close < 500:
                            ohlcv_suspect = True
                        elif quote_px >= 3000 and close < min(3000.0, quote_px * 0.05):
                            ohlcv_suspect = True
                        elif quote_px > 0 and close > 0:
                            rel = abs(close - quote_px) / max(quote_px, close, 1e-6)
                            if rel > 0.08 and quote_px >= 5000 and close < 5000 and close < quote_px * 0.1:
                                ohlcv_suspect = True
                        if ohlcv_suspect:
                            if quote_px > 0:
                                row["price_crosscheck_note_vi"] = (
                                    f"Đóng cửa OHLCV ({close:,.4g}) không khớp thang giá VND với quote ({quote_px:,.0f}); "
                                    "giữ giá quote cho hiển thị/định giá."
                                )
                                return
                            row["price_crosscheck_note_vi"] = (
                                f"Đóng cửa OHLCV ({close:,.4g}) không hợp lý cho cổ phiếu VN — có thể nhầm mã quốc tế; "
                                "không dùng làm giá (thử nguồn live nếu bật)."
                            )
                            # Không return: cho phép nhánh get_stock_data bên dưới (attach live).
                        else:
                            row["price"] = close
                            row["price_source"] = f"ohlcv_session_close:{src}"
                            last_d = ohlcv.iloc[-1].get("date")
                            if last_d is not None:
                                ts = pd.Timestamp(last_d)
                                if pd.notna(ts):
                                    row["price_as_of"] = str(ts.date())
                            if quote_px > 0 and abs(close - quote_px) / max(quote_px, close, 1e-6) > 0.08:
                                row["price_crosscheck_note_vi"] = (
                                    f"Giá quote ({quote_px:,.0f}) lệch >8% so với đóng cửa OHLCV ({close:,.0f}); "
                                    "đã dùng OHLCV cho định giá."
                                )
                            return
        except Exception:
            pass

    # Ưu tiên quote live cho giá khách (không dùng OHLCV kho cũ).
    if attach or unified or align:
        try:
            from scrapers.finance_scraper import ScraperError, get_stock_data

            if skip_duplicate_live_quote and unified:
                try:
                    px0 = float(row.get("price") or 0)
                except (TypeError, ValueError):
                    px0 = 0.0
                if px0 > 0:
                    row["price_source"] = f"quote_fresh:{row.get('source', 'unknown')}"
                    return

            q = get_stock_data(sym, use_cache=False)
            px = float(q.get("price") or 0)
            if px > 0:
                row["price"] = px
                row["price_source"] = f"quote_fresh:{q.get('source', 'unknown')}"
        except (ValueError, ScraperError):
            pass
        except Exception:
            pass


def _enrich_snapshot_decision_fields(row: dict[str, Any], sym: str) -> dict[str, Any]:
    """
    Gộp fundamentals đã có trên disk + ước ROE/LNST — không gọi mạng.
    Copy trước khi merge để không làm bẩn object trong mem-cache.
    """
    out = dict(row)
    out.setdefault("symbol", sym)
    try:
        _merge_stock_metadata(out, sym)
    except Exception:
        pass
    try:
        from core.financial_enrichment import merge_cached_fundamentals_into_snapshot, normalize_eps_in_snapshot

        eps_notes = normalize_eps_in_snapshot(out)
        if eps_notes:
            out.setdefault("fundamentals_merge_notes", [])
            out["fundamentals_merge_notes"] = list(
                dict.fromkeys(list(out.get("fundamentals_merge_notes") or []) + eps_notes)
            )
        merge_cached_fundamentals_into_snapshot(out)
    except Exception:
        pass
    return out


def _fundamental_richness(row: dict[str, Any] | None) -> int:
    """Điểm giàu fundamentals — dùng để không ghi đè snapshot đầy đủ bằng bản chỉ có giá."""
    if not isinstance(row, dict):
        return 0
    score = 0
    for k in ("eps", "eps_ttm", "normalized_eps", "book_value_per_share", "bvps"):
        try:
            if float(row.get(k) or 0) > 0:
                score += 2
        except (TypeError, ValueError):
            pass
    for k in ("pe_ratio", "pb_ratio", "roe", "debt_to_equity", "current_ratio", "growth_rate_pct"):
        try:
            if float(row.get(k) or 0) != 0:
                score += 1
        except (TypeError, ValueError):
            pass
    pio = row.get("piotroski")
    if isinstance(pio, dict) and pio:
        score += min(3, len(pio))
    return score


def _merge_live_price_onto_fundamentals(
    sym: str,
    *,
    price: float,
    price_source: str,
    note_vi: str = "",
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Cập nhật giá lên snapshot đã có fundamentals (disk/stale/mock) thay vì ghi bản chỉ có giá.
    Tránh QTP/mã khác bị xóa EPS/BV → fair=giá, MOS=0%.
    """
    from core.snapshot_disk_cache import get_disk_snapshot_any_age

    prior = base if isinstance(base, dict) else None
    if prior is None:
        prior = get_disk_snapshot_any_age(sym)
    out: dict[str, Any] = {}
    if isinstance(prior, dict):
        out = {k: v for k, v in prior.items() if not str(k).startswith("_disk_cache")}
    out["symbol"] = sym
    out["price"] = float(price)
    out["price_source"] = str(price_source or "")
    out["currency"] = out.get("currency") or "VND"
    src0 = str(out.get("source") or "").strip()
    if not src0 or _is_pure_demo_mock_source(src0) or src0.startswith("market_fallback"):
        out["source"] = f"market_fallback:{price_source}"
    else:
        # Giữ nguồn fundamentals, đánh dấu đã gắn giá fallback.
        if "price_overlay" not in src0:
            out["source"] = f"{src0}+price_overlay"
    if note_vi:
        out["snapshot_fundamentals_note_vi"] = note_vi
    elif not out.get("snapshot_fundamentals_note_vi"):
        out["snapshot_fundamentals_note_vi"] = (
            f"Scrape live lỗi — giữ BCTC cache, cập nhật giá ({price_source}: {price:,.0f})."
        )
    return out


def fetch_financial_snapshot(symbol: str, *, bypass_cache: bool = False) -> dict[str, Any] | None:
    """
    Trả về dict chứa giá, EPS, tăng trưởng, book value, block piotroski, v.v.
    symbol: mã không phân biệt hoa thường (VNM, fpt).
    """
    sym = symbol.strip().upper()
    if str(os.environ.get("II_VN_SYMBOL_GUARD", "1")).strip().lower() not in ("0", "false", "no", "off"):
        try:
            from scrapers.vn_listing import is_tradable_vn_symbol

            if not is_tradable_vn_symbol(sym):
                return None
        except Exception:
            pass
    stale_disk: dict[str, Any] | None = None
    prefer_live = _prefer_live_snapshot()
    if not bypass_cache:
        hot = get_cached_snapshot(sym)
        if isinstance(hot, dict):
            hot_source = str(hot.get("source") or "").strip().lower()
            if prefer_live and _is_pure_demo_mock_source(hot_source):
                pass
            elif _stale_ohlcv_disk_bypass_enabled() and _skip_disk_cache_for_fresh_cafef_quote(hot):
                pass
            else:
                # TTL còn hạn nhưng giá có thể đã lệch — làm mới giá trước khi trả UI.
                out_hot = _refresh_price_on_cached_snapshot(hot, sym) if prefer_live else dict(hot)
                return _enrich_snapshot_decision_fields(out_hot, sym)
        if os.environ.get("II_READ_STALE_DISK", "1").strip().lower() in ("1", "true", "yes", "on"):
            stale_disk = get_disk_snapshot_any_age(sym)
            if isinstance(stale_disk, dict):
                stale_source = str(stale_disk.get("source") or "").strip().lower()
                if prefer_live and _is_pure_demo_mock_source(stale_source):
                    stale_disk = None
                elif _stale_ohlcv_disk_bypass_enabled() and _skip_disk_cache_for_fresh_cafef_quote(stale_disk):
                    stale_disk = None
        if prefer_live and stale_disk is not None and _snapshot_swr_enabled():
            out_stale = _refresh_price_on_cached_snapshot(stale_disk, sym)
            src0 = str(out_stale.get("source") or "unknown")
            # Tránh chồng suffix :swr nhiều lần khi đọc lại disk SWR.
            base_src = src0[:-4] if src0.endswith(":swr") else src0
            out_stale["source"] = f"{base_src}:swr"
            ps = str(out_stale.get("price_source") or "")
            if ps.startswith("quote_fast") or ps.startswith("quote_fast_fallback"):
                out_stale["snapshot_fundamentals_note_vi"] = (
                    "Đang dùng fundamentals từ cache + giá live nhanh; làm mới đầy đủ chạy nền."
                )
            else:
                out_stale["snapshot_fundamentals_note_vi"] = (
                    "Đang dùng snapshot cache để phản hồi nhanh; dữ liệu live sẽ được làm mới nền."
                )
            _launch_snapshot_refresh(sym)
            return _enrich_snapshot_decision_fields(out_stale, sym)

    data = _load_mock_json()
    mock_row: dict[str, Any] | None = None
    if sym in data:
        mock_row = dict(data[sym])
        mock_row["source"] = "mock_json"

    if not prefer_live and mock_row is not None:
        _resolve_snapshot_market_price(mock_row, sym)
        _merge_stock_metadata(mock_row, sym)
        put_snapshot(sym, mock_row)
        return _enrich_snapshot_decision_fields(mock_row, sym)

    try:
        from scrapers.finance_scraper import ScraperError, get_stock_data

        scraped = get_stock_data(sym, use_cache=not prefer_live)
        if stale_disk is not None and stale_disk.get("_disk_cache", {}).get("stale"):
            ttl = stale_disk.get("_disk_cache", {}).get("ttl_sec")
            scraped["snapshot_fundamentals_note_vi"] = (
                f"TTL cache cơ bản đã cũ ({ttl}s); đã làm mới giá live và giữ chế độ thận trọng."
            )
            scraped.setdefault("symbol", sym)
        _resolve_snapshot_market_price(
            scraped,
            sym,
            skip_duplicate_live_quote=bool(prefer_live and _unified_live_price_enabled()),
        )
        _merge_stock_metadata(scraped, sym)
        put_snapshot(sym, scraped)
        return _enrich_snapshot_decision_fields(scraped, sym)
    except ScraperError:
        if mock_row is not None:
            out_mock = dict(mock_row)
            if prefer_live:
                _apply_price_fallback_over_mock(out_mock, sym)
            _resolve_snapshot_market_price(out_mock, sym)
            _merge_stock_metadata(out_mock, sym)
            # Không ghi đè disk bằng mock demo thuần khi đang ưu tiên live.
            if prefer_live and _is_pure_demo_mock_source(str(out_mock.get("source") or "")):
                # Fallback giá thất bại — không đưa giá demo (vd. FPT 98k) ra UI.
                px2, src2 = _market_price_fallback(sym)
                if px2 and px2 > 0:
                    out_mock["price"] = float(px2)
                    out_mock["price_source"] = src2
                    out_mock["source"] = f"mock_json+market_fallback"
                    put_snapshot(sym, out_mock)
                    return _enrich_snapshot_decision_fields(out_mock, sym)
                if stale_disk is not None and float(stale_disk.get("price") or 0) > 0:
                    return _enrich_snapshot_decision_fields(dict(stale_disk), sym)
                return _enrich_snapshot_decision_fields(out_mock, sym)
            put_snapshot(sym, out_mock)
            return _enrich_snapshot_decision_fields(out_mock, sym)
        if prefer_live:
            px, src = _market_price_fallback(sym)
            if px and px > 0:
                # Không put bản chỉ có giá — merge lên disk/stale/mock để giữ EPS/BV.
                base = stale_disk if isinstance(stale_disk, dict) else mock_row
                merged = _merge_live_price_onto_fundamentals(
                    sym,
                    price=float(px),
                    price_source=str(src),
                    note_vi=(
                        f"Scrape live lỗi — giữ BCTC cache/enrich, cập nhật giá ({src}: {px:,.0f})."
                    ),
                    base=base,
                )
                _merge_stock_metadata(merged, sym)
                # Chỉ ghi đĩa nếu không làm nghèo fundamentals so với bản cũ.
                prior_score = _fundamental_richness(stale_disk) if isinstance(stale_disk, dict) else 0
                if _fundamental_richness(merged) >= prior_score:
                    put_snapshot(sym, merged)
                return _enrich_snapshot_decision_fields(merged, sym)
        if stale_disk is not None:
            return _enrich_snapshot_decision_fields(stale_disk, sym)

    # Stub: gọi API công khai (ví dụ Stooq / FMP)
    env_url = os.environ.get("VALUE_INVESTOR_FINANCIAL_API_URL")
    if env_url:
        try:
            r = requests.get(f"{env_url.rstrip('/')}/{sym}", timeout=10)
            r.raise_for_status()
            payload = r.json()
            if not isinstance(payload, dict):
                payload = {}
            payload["source"] = "http_api"
            _merge_stock_metadata(payload, sym)
            put_snapshot(sym, payload)
            return _enrich_snapshot_decision_fields(payload, sym)
        except (requests.RequestException, ValueError):
            pass

    if mock_row is not None:
        _resolve_snapshot_market_price(mock_row, sym)
        _merge_stock_metadata(mock_row, sym)
        put_snapshot(sym, mock_row)
        return _enrich_snapshot_decision_fields(mock_row, sym)
    if stale_disk is not None:
        return _enrich_snapshot_decision_fields(stale_disk, sym)
    return None


def _cluster_bucket_key(c: Any) -> Any:
    """Khóa nhóm cluster (hashable) — khớp so sánh `industry_cluster` trong metadata."""
    try:
        hash(c)
        return c
    except TypeError:
        if isinstance(c, (dict, list)):
            return ("__json__", json.dumps(c, sort_keys=True, default=str))
        return ("__repr__", repr(c))


def _build_peer_cluster_buckets(meta_all: dict[str, Any]) -> dict[Any, list[str]]:
    """Một lần / mtime: symbol đã sắp theo mã (giống vòng lặp cũ)."""
    buckets: dict[Any, list[str]] = {}
    for k, v in sorted(meta_all.items(), key=lambda x: str(x[0]).upper()):
        if not isinstance(v, dict):
            continue
        c = v.get("industry_cluster")
        if not c:
            continue
        sym = str(k).strip().upper()
        if not sym:
            continue
        buckets.setdefault(_cluster_bucket_key(c), []).append(sym)
    return buckets


def peer_symbols_same_cluster(symbol: str, limit: int = 8) -> list[str]:
    """
    Các mã trong `stock_metadata.json` cùng `industry_cluster` với `symbol`.
    Luôn đặt `symbol` đầu danh sách. Nếu không có cluster → chỉ `[symbol]`.
    """
    sym_u = symbol.strip().upper()
    meta_all = _load_stock_metadata()
    me = meta_all.get(sym_u)
    cluster = None
    if isinstance(me, dict):
        cluster = me.get("industry_cluster")
    if not cluster:
        return [sym_u]

    global _peer_buckets_mtime, _peer_buckets
    mt = _meta_path_mtime()
    if _peer_buckets is None or _peer_buckets_mtime != mt:
        _peer_buckets = _build_peer_cluster_buckets(meta_all)
        _peer_buckets_mtime = mt

    peers = list(_peer_buckets.get(_cluster_bucket_key(cluster), []))
    ordered = [sym_u] + [p for p in peers if p != sym_u]
    return ordered[:limit]


def build_peer_comparison_dataframe(symbols: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """
    Tra cứu từng mã, tính định giá; trả (bảng, danh sách mã không tải được).
    """
    rows: list[dict[str, Any]] = []
    failed: list[str] = []
    for sym in symbols:
        sym_u = sym.strip().upper()
        snap = fetch_financial_snapshot(sym_u)
        if snap is None:
            failed.append(sym_u)
            continue
        s = value_investing_summary(snap)
        price = float(s.get("price") or 0)
        eps = float(s.get("eps") or 0)
        bv = float(s.get("book_value_per_share") or 0)
        pe = (price / eps) if eps > 0 else None
        pb = (price / bv) if bv > 0 else None
        mos_g = s.get("margin_of_safety_pct")
        mos_c = s.get("margin_of_safety_composite_pct")
        rows.append(
            {
                "Mã": s.get("symbol", sym_u),
                "Tên": str(s.get("name") or "")[:40],
                "Giá": round(price, 1),
                "P/E": round(pe, 2) if pe is not None else None,
                "P/B": round(pb, 2) if pb is not None else None,
                "Graham": round(float(s.get("intrinsic_value_graham") or 0), 1),
                "Mục tiêu TH": round(float(s.get("composite_target_price") or 0), 1),
                "MOS G%": round(float(mos_g), 2) if mos_g is not None else None,
                "MOS TH%": round(float(mos_c), 2) if mos_c is not None else None,
                "F-Score": int(s.get("piotroski_score") or 0),
                "Nguồn": str(s.get("data_source", "")),
            }
        )
    return pd.DataFrame(rows), failed


def financials_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Tiện ích: nhiều mã -> một bảng (dùng sau cho so sánh ngành)."""
    return pd.DataFrame(records)


def list_universe_symbols(limit: int | None = None, offset: int = 0) -> list[str]:
    """
    Danh sách mã cho quét cơ hội.
    Ưu tiên full listing VN (HOSE/HNX/UPCOM) + metadata/extra.
    `offset` bỏ qua N mã đầu (dùng khi đã warm một đoạn đầu universe).
    """
    syms = list_tradable_vn_symbols(use_api=True)
    o = max(0, int(offset or 0))
    if o:
        syms = syms[o:]
    if limit is not None and limit > 0:
        return syms[:limit]
    return syms


def universe_subtype_map() -> dict[str, str]:
    """
    Map symbol -> industry_subtype from stock_metadata.json.
    Missing subtype defaults to 'other'.
    """
    global _subtype_cache_mtime, _subtype_cache_data
    mt = _meta_path_mtime()
    if _subtype_cache_data is not None and _subtype_cache_mtime == mt:
        return _subtype_cache_data
    meta_all = _load_stock_metadata()
    out: dict[str, str] = {}
    for k, v in meta_all.items():
        sym = str(k).strip().upper()
        if not sym or not isinstance(v, dict):
            continue
        out[sym] = str(v.get("industry_subtype") or "other").strip().lower()
    _subtype_cache_mtime = mt
    _subtype_cache_data = out
    return out
