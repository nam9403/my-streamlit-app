"""
Tin tức Vi mô & Vĩ mô (P0) — disk-first, opt-in boost, fail-soft.

- Không import Streamlit (giữ core độc lập UI).
- Post-scan: ``apply_news_macro_boost`` chỉ đọc cache/local; không HTTP.
- Micro bundle: mặc định disk-only; ``allow_network=True`` chỉ cho lazy UI.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import pandas as pd

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MACRO_PATH = _ROOT / "data" / "runtime" / "macro_snapshot.json"
_DEFAULT_MACRO_TTL_SEC = 7200.0  # 2h trong khoảng 1–4h
_DEFAULT_SCORE_WEIGHT = 1.0

_POS_EVENT_KW = (
    "cổ tức",
    "chia cổ tức",
    "tạm ứng cổ tức",
    "phát hành",
    "đăng ký mua",
    "mua ròng",
    "lợi nhuận tăng",
    "lợi nhuận",
    "đạt lợi nhuận",
    "kết quả kinh doanh tích cực",
    "hồi phục",
    "tăng giá",
    "đhđcđ",
    "đại hội cổ đông",
    "bctc",
    "báo cáo tài chính",
)
_NEG_EVENT_KW = (
    "hủy",
    "hoãn",
    "phạt",
    "kiểm toán ngoại trừ",
    "lỗ",
    "bán ròng",
    "đăng ký bán",
    "cảnh báo",
    "hủy niêm yết",
    "pha loãng",
    "suy giảm",
    "cắt lỗ",
)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    if not math.isfinite(v):
        return 0.0
    return max(lo, min(hi, float(v)))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# AI plugin slot
# ---------------------------------------------------------------------------


class SentimentResult(dict):
    """Lightweight mapping: score / label / rationale."""


@runtime_checkable
class NewsAnalyzerProtocol(Protocol):
    def analyze(
        self,
        texts: list[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return dict with at least ``score`` in [-1, 1]."""


class NullNewsAnalyzer:
    """Default analyzer — neutral 0.0. Swap with Gemini/LLM later."""

    def analyze(
        self,
        texts: list[str],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = texts, context
        return {
            "score": 0.0,
            "label": "neutral",
            "rationale": "null_analyzer",
        }


_DEFAULT_ANALYZER: NewsAnalyzerProtocol = NullNewsAnalyzer()


# ---------------------------------------------------------------------------
# Macro snapshot (disk TTL)
# ---------------------------------------------------------------------------


def macro_snapshot_path() -> Path:
    raw = str(os.environ.get("II_MACRO_SNAPSHOT_PATH") or "").strip()
    return Path(raw) if raw else _DEFAULT_MACRO_PATH


def macro_snapshot_ttl_sec() -> float:
    return max(3600.0, min(14400.0, _env_float("II_MACRO_SNAPSHOT_TTL_SEC", _DEFAULT_MACRO_TTL_SEC)))


def default_macro_snapshot() -> dict[str, Any]:
    return {
        "saved_at": _utc_now_iso(),
        "ttl_sec": macro_snapshot_ttl_sec(),
        "market_bias": 0.0,
        "usd_vnd": None,
        "policy_rate_pct": None,
        "cpi_yoy_pct": None,
        "notes_vi": "P0 placeholder — chưa gắn feed vĩ mô live; bias=0.",
        "source": "default",
    }


def _macro_age_sec(payload: dict[str, Any]) -> float | None:
    ts = _parse_iso(str(payload.get("saved_at") or "") or None)
    if ts is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())


def _write_macro_snapshot(payload: dict[str, Any]) -> None:
    path = macro_snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _vnindex_bias_from_disk() -> tuple[float | None, str]:
    """Bias nhẹ từ OHLCV VNINDEX đã cache (không mạng)."""
    try:
        from core.ohlcv_store import load_recent_ohlcv

        df = load_recent_ohlcv("VNINDEX", sessions=12)
        if df is None or getattr(df, "empty", True) or len(df) < 6:
            return None, "vnindex_disk_missing"
        closes = [float(x) for x in df["close"].tolist() if x is not None]
        if len(closes) < 6 or closes[-6] <= 0:
            return None, "vnindex_disk_thin"
        chg = closes[-1] / closes[-6] - 1.0
        return _clamp(chg * 4.0, -0.35, 0.35), "vnindex_disk_5d"
    except Exception:
        return None, "vnindex_disk_error"


def _try_refresh_macro_live(prev: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Macro nhẹ: USD/VND (API) + policy rate (env) + VNINDEX disk proxy.
    Fail-soft → default.
    """
    out = default_macro_snapshot()
    timeout = max(1.0, min(4.0, _env_float("II_MACRO_HTTP_TIMEOUT_SEC", 2.0)))
    sources: list[str] = []
    bias_parts: list[float] = []

    # Policy rate proxy (SBV / cấu hình tay)
    policy = _env_float("II_MACRO_POLICY_RATE_PCT", 0.0)
    if policy <= 0:
        policy = _env_float("II_MACRO_POLICY_RATE_DEFAULT", 4.5)
    out["policy_rate_pct"] = policy
    sources.append("policy_env")
    prev_policy = None
    if isinstance(prev, dict) and prev.get("policy_rate_pct") is not None:
        try:
            prev_policy = float(prev.get("policy_rate_pct"))
        except (TypeError, ValueError):
            prev_policy = None
    if prev_policy and prev_policy > 0:
        # Lãi suất tăng → bias âm nhẹ
        bias_parts.append(_clamp((prev_policy - policy) * 0.15, -0.2, 0.2))

    cpi = _env_float("II_MACRO_CPI_YOY_PCT", 0.0)
    if cpi != 0.0:
        out["cpi_yoy_pct"] = cpi
        sources.append("cpi_env")
        # CPI cao → bias âm nhẹ
        bias_parts.append(_clamp(-(cpi - 3.5) * 0.05, -0.2, 0.2))

    vn_bias, vn_src = _vnindex_bias_from_disk()
    if vn_bias is not None:
        bias_parts.append(vn_bias)
        sources.append(vn_src)

    if str(os.environ.get("II_MACRO_LIVE_REFRESH", "1")).strip().lower() not in ("0", "false", "no", "off"):
        try:
            import requests

            url = str(
                os.environ.get("II_MACRO_FX_URL")
                or "https://open.er-api.com/v6/latest/USD"
            ).strip()
            r = requests.get(url, timeout=timeout)
            if r.status_code == 200:
                js = r.json()
                rates = js.get("rates") if isinstance(js, dict) else None
                if isinstance(rates, dict) and rates.get("VND") is not None:
                    usd_vnd_f = float(rates.get("VND"))
                    out["usd_vnd"] = usd_vnd_f
                    sources.append("open_er_api")
                    prev_px = None
                    if isinstance(prev, dict) and prev.get("usd_vnd") is not None:
                        try:
                            prev_px = float(prev.get("usd_vnd"))
                        except (TypeError, ValueError):
                            prev_px = None
                    if prev_px and prev_px > 0:
                        chg = (usd_vnd_f / prev_px) - 1.0
                        bias_parts.append(_clamp(-chg * 8.0, -0.35, 0.35))
        except Exception as exc:
            logger.warning("macro_live_refresh_failed error=%s", exc.__class__.__name__)

    if bias_parts:
        out["market_bias"] = _clamp(sum(bias_parts) / len(bias_parts))
    else:
        out["market_bias"] = 0.0
    out["source"] = "+".join(sources) if sources else "default"
    out["notes_vi"] = (
        "Macro blend: USD/VND (optional) + policy/CPI env + VNINDEX disk proxy; fail-soft."
    )
    return out


def get_macro_snapshot(*, force_default: bool = False) -> dict[str, Any]:
    """
    Đọc macro snapshot từ disk. Hỏng/thiếu/hết TTL → thử live nhẹ rồi ghi disk.
    """
    if force_default:
        out = default_macro_snapshot()
        try:
            _write_macro_snapshot(out)
        except OSError as exc:
            logger.warning("macro_snapshot_write_failed error=%s", exc.__class__.__name__)
        return out

    path = macro_snapshot_path()
    ttl = macro_snapshot_ttl_sec()
    prev: dict[str, Any] | None = None
    try:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                prev = dict(raw)
                age = _macro_age_sec(raw)
                file_ttl = float(raw.get("ttl_sec") or ttl)
                if age is not None and age <= max(ttl, file_ttl):
                    out = dict(raw)
                    out.setdefault("market_bias", 0.0)
                    out["market_bias"] = _clamp(float(out.get("market_bias") or 0.0))
                    return out
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("macro_snapshot_read_failed error=%s", exc.__class__.__name__)

    out = _try_refresh_macro_live(prev)
    try:
        _write_macro_snapshot(out)
    except OSError as exc:
        logger.warning("macro_snapshot_write_failed error=%s", exc.__class__.__name__)
    return out


# ---------------------------------------------------------------------------
# Micro bundle
# ---------------------------------------------------------------------------


def _read_news_from_disk(sym: str) -> list[dict[str, Any]]:
    try:
        from scrapers.portal import _read_news_disk_cache

        hit = _read_news_disk_cache(sym)
        if not hit:
            return []
        items, _saved = hit
        return list(items or [])
    except Exception as exc:
        logger.warning("micro_news_disk_failed symbol=%s error=%s", sym, exc.__class__.__name__)
        return []


def _fetch_news_safe(sym: str, *, limit: int = 8) -> list[dict[str, Any]]:
    try:
        from scrapers.portal import fetch_latest_news

        rows = fetch_latest_news(sym, limit=limit)
        return list(rows or []) if isinstance(rows, list) else []
    except Exception as exc:
        logger.warning("micro_news_live_failed symbol=%s error=%s", sym, exc.__class__.__name__)
        return []


def get_micro_bundle(ticker: str, *, allow_network: bool = False, news_limit: int = 8) -> dict[str, Any]:
    """
    Bundle vi mô theo mã: tin + meta.
    Mặc định ``allow_network=False`` (scan-safe). UI lazy có thể bật mạng.
    """
    sym = str(ticker or "").strip().upper()
    if not sym:
        return {"symbol": "", "news": [], "source": "empty", "events_hint": []}

    news: list[dict[str, Any]] = _read_news_from_disk(sym)
    source = "news_disk_cache" if news else "empty"
    if allow_network and not news:
        news = _fetch_news_safe(sym, limit=news_limit)
        source = "live_or_portal" if news else "empty"

    titles = [str(x.get("title") or "") for x in news[:20]]
    events_hint = [t for t in titles if any(k in t.lower() for k in (*_POS_EVENT_KW, *_NEG_EVENT_KW))][:6]
    return {
        "symbol": sym,
        "news": news[: max(1, int(news_limit))],
        "source": source,
        "events_hint": events_hint,
    }


def _headline_event_score(news: list[dict[str, Any]]) -> float:
    text = " | ".join(str(x.get("title") or "") for x in (news or [])[:20]).lower()
    if not text:
        return 0.0
    score = 0.0
    for k in _POS_EVENT_KW:
        if k in text:
            score += 0.15
    for k in _NEG_EVENT_KW:
        if k in text:
            score -= 0.15
    return _clamp(score)


def _smart_money_component(symbol: str, news: list[dict[str, Any]]) -> float:
    try:
        from core.deep_insight_service import analyze_smart_money_flow

        sm = analyze_smart_money_flow(news or [], symbol=symbol)
        raw = float(sm.get("score") or 0.0)
        # Scale soft về [-0.5, 0.5]
        return _clamp(math.tanh(raw / 4.0) * 0.5, -0.5, 0.5)
    except Exception as exc:
        logger.warning("smart_money_component_failed symbol=%s error=%s", symbol, exc.__class__.__name__)
        return 0.0


def score_catalyst(
    ticker: str,
    *,
    analyzer: NewsAnalyzerProtocol | None = None,
    allow_network: bool = False,
    macro: dict[str, Any] | None = None,
    bundle: dict[str, Any] | None = None,
) -> float:
    """
    Điểm catalyst ∈ [-1, 1]. Fail-soft → 0.0.
    Scan path: ``allow_network=False``.
    """
    try:
        sym = str(ticker or "").strip().upper()
        if not sym:
            return 0.0
        macro_payload = macro if isinstance(macro, dict) else get_macro_snapshot()
        macro_bias = _clamp(float(macro_payload.get("market_bias") or 0.0)) * 0.35
        micro = bundle if isinstance(bundle, dict) else get_micro_bundle(sym, allow_network=allow_network)
        news = list(micro.get("news") or []) if isinstance(micro, dict) else []
        event_s = _headline_event_score(news)
        sm_s = _smart_money_component(sym, news)
        ai = analyzer or _DEFAULT_ANALYZER
        try:
            titles = [str(x.get("title") or "") for x in news[:12] if str(x.get("title") or "").strip()]
            ai_out = ai.analyze(titles, context={"symbol": sym})
            ai_s = _clamp(float((ai_out or {}).get("score") or 0.0)) * 0.25
        except Exception:
            ai_s = 0.0
        return _clamp(macro_bias + event_s + sm_s + ai_s)
    except Exception as exc:
        logger.warning("score_catalyst_failed ticker=%s error=%s", ticker, exc.__class__.__name__)
        return 0.0


def format_news_macro_bias_caption(ticker: str, *, allow_network: bool = True) -> str:
    """Caption nhẹ cho UI (lazy theo mã đang chọn)."""
    sym = str(ticker or "").strip().upper()
    if not sym:
        return "News/Macro Bias: —"
    try:
        score = score_catalyst(sym, allow_network=allow_network)
        macro = get_macro_snapshot()
        src = str(macro.get("source") or "default")
        sign = f"{score:+.2f}"
        return f"News/Macro Bias **{sym}**: `{sign}` (macro_src={src}; P0 heuristic)"
    except Exception as exc:
        logger.warning("bias_caption_failed ticker=%s error=%s", sym, exc.__class__.__name__)
        return f"News/Macro Bias **{sym}**: `0.00` (fallback)"


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _events_story_component(events_hint: list[str]) -> tuple[float, list[str]]:
    score = 0.0
    notes: list[str] = []
    if not events_hint:
        return score, notes
    merged = " | ".join(str(x or "").lower() for x in events_hint)
    positive_story_kw = (
        "bán vốn",
        "thoái vốn",
        "mở rộng",
        "mở nhà máy",
        "dự án",
        "khởi công",
        "vận hành",
        "hợp đồng",
        "ký kết",
        "nâng công suất",
    )
    negative_story_kw = ("đình trệ", "hủy", "hoãn", "phạt", "suy giảm", "cảnh báo")
    for kw in positive_story_kw:
        if kw in merged:
            score += 0.15
            notes.append(f"Sự kiện tích cực: {kw}.")
    for kw in negative_story_kw:
        if kw in merged:
            score -= 0.2
            notes.append(f"Sự kiện rủi ro: {kw}.")
    return _clamp(score, -0.5, 0.5), notes


def detect_story_catalysts(ticker: str) -> dict[str, Any]:
    """
    Tổng hợp catalyst/câu chuyện theo mã (fail-soft, disk-first).

    Bao gồm:
    - Cổ tức: years/events/latest value/yield (nếu có)
    - Tăng trưởng lợi nhuận & doanh thu YoY
    - Sự kiện doanh nghiệp (headline hints)
    - Vĩ mô (USDVND / lãi suất / CPI + macro bias)
    """
    sym = str(ticker or "").strip().upper()
    if not sym:
        return {
            "symbol": "",
            "story_score": 0.0,
            "dividend": {},
            "earnings_growth": {},
            "corporate_events": {},
            "macro_support": {},
            "notes_vi": [],
            "source": "empty",
        }

    notes: list[str] = []
    source_parts: list[str] = []
    story_score = 0.0
    dividend: dict[str, Any] = {}
    earnings_growth: dict[str, Any] = {}
    corporate_events: dict[str, Any] = {}
    macro_support: dict[str, Any] = {}

    try:
        from scrapers.portal import PortalDataError, fetch_financial_indicators

        try:
            fin = fetch_financial_indicators(sym, fast_mode=True) or {}
        except PortalDataError:
            # Backward-compat nếu portal vẫn raise; đọc disk trực tiếp.
            from scrapers.portal import _read_fin_disk_cache

            fin = _read_fin_disk_cache(sym) or {}
        if str(fin.get("source") or "").startswith("unavailable"):
            from scrapers.portal import _read_fin_disk_cache

            disk = _read_fin_disk_cache(sym)
            if isinstance(disk, dict) and disk:
                fin = disk
        source_parts.append(str(fin.get("source") or "financial_indicators"))

        div_years = int(fin.get("dividend_paid_years") or 0)
        div_events = int(fin.get("dividend_events_count") or 0)
        div_latest = _safe_float(fin.get("latest_dividend_value"))
        div_yield = _safe_float(fin.get("dividend_yield_pct"))
        dividend = {
            "dividend_paid_years": div_years,
            "dividend_events_count": div_events,
            "latest_dividend_value": div_latest,
            "dividend_yield_pct": div_yield,
            "dividend_years_list": fin.get("dividend_years_list") or [],
        }
        if div_yield is not None:
            if div_yield >= 6.0:
                story_score += 0.25
                notes.append(f"Cổ tức hấp dẫn: dividend yield ~{div_yield:.1f}%.")
            elif div_yield >= 3.0:
                story_score += 0.12
                notes.append(f"Có lợi suất cổ tức: ~{div_yield:.1f}%.")
        elif div_years >= 3 or div_events >= 3:
            story_score += 0.08
            notes.append("Lịch sử chi trả cổ tức đều trong nhiều năm.")

        rev_yoy = _safe_float(fin.get("revenue_growth_yoy"))
        prof_yoy = _safe_float(fin.get("profit_growth_yoy"))
        earnings_growth = {
            "revenue_growth_yoy": rev_yoy,
            "profit_growth_yoy": prof_yoy,
        }
        if prof_yoy is not None:
            if prof_yoy >= 25:
                story_score += 0.25
                notes.append(f"Lợi nhuận YoY tăng mạnh ({prof_yoy:.1f}%).")
            elif prof_yoy >= 10:
                story_score += 0.12
                notes.append(f"Lợi nhuận YoY tăng tích cực ({prof_yoy:.1f}%).")
            elif prof_yoy <= -10:
                story_score -= 0.2
                notes.append(f"Lợi nhuận YoY suy giảm ({prof_yoy:.1f}%).")
        if rev_yoy is not None:
            if rev_yoy >= 15:
                story_score += 0.15
                notes.append(f"Doanh thu YoY tăng tốt ({rev_yoy:.1f}%).")
            elif rev_yoy <= -10:
                story_score -= 0.12
                notes.append(f"Doanh thu YoY giảm ({rev_yoy:.1f}%).")
    except Exception as exc:
        logger.warning("detect_story_financial_failed ticker=%s error=%s", sym, exc.__class__.__name__)

    try:
        micro = get_micro_bundle(sym, allow_network=False, news_limit=12)
        events_hint = list(micro.get("events_hint") or [])
        ev_score, ev_notes = _events_story_component(events_hint)
        story_score += ev_score
        notes.extend(ev_notes)
        corporate_events = {
            "events_hint": events_hint,
            "headline_event_score": round(ev_score, 3),
            "news_count": len(list(micro.get("news") or [])),
        }
        source_parts.append(str(micro.get("source") or "micro_bundle"))
    except Exception as exc:
        logger.warning("detect_story_events_failed ticker=%s error=%s", sym, exc.__class__.__name__)

    try:
        macro = get_macro_snapshot()
        macro_bias = _clamp(float(macro.get("market_bias") or 0.0))
        usd_vnd = _safe_float(macro.get("usd_vnd"))
        policy = _safe_float(macro.get("policy_rate_pct"))
        cpi = _safe_float(macro.get("cpi_yoy_pct"))
        macro_support = {
            "market_bias": macro_bias,
            "usd_vnd": usd_vnd,
            "policy_rate_pct": policy,
            "cpi_yoy_pct": cpi,
            "source": macro.get("source"),
        }
        # Nhẹ tay để macro không lấn át nội tại doanh nghiệp.
        story_score += macro_bias * 0.3
        if policy is not None and policy <= 5.0:
            story_score += 0.05
            notes.append("Mặt bằng lãi suất hỗ trợ định giá/chi phí vốn.")
        if cpi is not None and cpi >= 5.0:
            story_score -= 0.08
            notes.append("Rủi ro CPI cao ảnh hưởng định giá.")
        source_parts.append(str(macro.get("source") or "macro_snapshot"))
    except Exception as exc:
        logger.warning("detect_story_macro_failed ticker=%s error=%s", sym, exc.__class__.__name__)

    return {
        "symbol": sym,
        "story_score": _clamp(story_score),
        "dividend": dividend,
        "earnings_growth": earnings_growth,
        "corporate_events": corporate_events,
        "macro_support": macro_support,
        "notes_vi": notes[:10],
        "source": "+".join([x for x in source_parts if x]) or "story_heuristic",
    }


def get_combined_story_score(ticker: str) -> float:
    """
    Điểm Story/Catalyst chuẩn hóa [-1.0, +1.0].

    Blend:
    - detect_story_catalysts (nội dung câu chuyện)
    - score_catalyst (news/macro/smart money existing)
    """
    sym = str(ticker or "").strip().upper()
    if not sym:
        return 0.0
    try:
        story = detect_story_catalysts(sym)
        story_s = _clamp(float(story.get("story_score") or 0.0))
        catalyst_s = score_catalyst(sym, allow_network=False)
        # Ưu tiên story fundamentals 60%, catalyst động 40%.
        return _clamp(story_s * 0.6 + catalyst_s * 0.4)
    except Exception as exc:
        logger.warning("combined_story_score_failed ticker=%s error=%s", sym, exc.__class__.__name__)
        return 0.0


def is_news_macro_boost_enabled() -> bool:
    return _env_bool("II_SCANNER_NEWS_MACRO_BOOST", default=False)


def news_macro_score_weight() -> float:
    return max(0.0, min(5.0, _env_float("II_NEWS_MACRO_SCORE_WEIGHT", _DEFAULT_SCORE_WEIGHT)))


def apply_news_macro_boost(df: pd.DataFrame, *, force: bool = False) -> pd.DataFrame:
    """
    Post-scan boost (opt-in). Không HTTP — chỉ disk/heuristic.
    Fail-soft: mọi lỗi → trả DataFrame gốc.
    ``force=True``: dùng cho nightly board ranking (P1), vẫn disk-only.
    """
    try:
        if not isinstance(df, pd.DataFrame):
            return df
        if (not force) and (not is_news_macro_boost_enabled()):
            return df
        if df.empty:
            return df

        ticker_col = "Mã" if "Mã" in df.columns else ("symbol" if "symbol" in df.columns else None)
        if ticker_col is None:
            return df

        out = df.copy()
        macro = get_macro_snapshot()
        weight = news_macro_score_weight()
        biases: list[float] = []
        for raw in out[ticker_col].tolist():
            biases.append(score_catalyst(str(raw or ""), allow_network=False, macro=macro))
        out["News/Macro Bias"] = [round(x, 3) for x in biases]

        if "__score" in out.columns and weight > 0:
            # Scale nhỏ: bias ∈ [-1,1] → đóng góp tối đa ~±10 * weight vào __score
            out["__score"] = out["__score"].fillna(0.0) + out["News/Macro Bias"] * (10.0 * weight)
        return out
    except Exception as exc:
        logger.warning("apply_news_macro_boost_failed error=%s", exc.__class__.__name__)
        return df
