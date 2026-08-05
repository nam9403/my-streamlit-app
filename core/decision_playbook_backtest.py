"""
Replay P0/P1 decision playbook trên OHLCV lịch sử (no look-ahead).

Mỗi bar ``i`` chỉ dùng ``ohlcv[:i+1]`` + chỉ số cùng ngày (hoặc trước đó).
Valuation dùng **proxy kỹ thuật point-in-time** (giá vs MA200/MA50/RSI) —
không giả vờ có fundamentals lịch sử đầy đủ. Báo cáo ghi rõ giới hạn này.

Chỉ mở tín hiệu khi playbook ∈ {BUY, CONDITIONAL_BUY} (khớp paper allowlist P0).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from core.decision_playbook import build_decision_playbook
from core.engine import compute_technical_indicators, detect_market_phase_at_index
from core.market_regime import assess_market_regime

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS: tuple[int, ...] = (20, 60, 90)
ENTRY_ACTIONS = frozenset({"BUY", "CONDITIONAL_BUY"})


ENTRY_STYLES = frozenset({"value_accum", "breakout", "both", "pit_quality", "pit_strict", "armed_pool"})


@dataclass(frozen=True)
class PlaybookBacktestConfig:
    min_history: int = 120
    stride: int = 5
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    entry_actions: frozenset[str] = ENTRY_ACTIONS
    roundtrip_cost_pct: float = 0.50  # VN fee+tax+slip default (see vn_trade_cost)
    track_watch_control: bool = True  # nhóm đối chứng nếu mua cả WATCH
    track_avoid_control: bool = True  # đo AVOID có bảo vệ vốn không
    require_trigger_ready: bool = True  # chỉ vào lệnh khi Trigger READY
    max_entry_rsi: float = 72.0  # tránh đuổi quá mua
    min_mos_proxy: float = 8.0
    entry_phases: frozenset[str] = frozenset({"accumulation", "breakout"})
    # value_accum / breakout / both / pit_quality / pit_strict / armed_pool
    entry_style: str = "value_accum"
    use_pit_fundamentals: bool = True
    require_pit_growth_ok: bool = True  # yêu cầu Rev hoặc LN YoY không quá xấu
    buy_only: bool = False
    require_pit_ok: bool = False
    require_both_growth_positive: bool = False
    min_rev_yoy: float | None = None
    min_profit_yoy: float | None = None
    block_risk_off: bool = False
    min_rs_20d: float | None = None  # excess return 20d trước entry vs bench

    def normalize(self) -> PlaybookBacktestConfig:
        hist = max(80, min(2000, int(self.min_history or 120)))
        stride = max(1, min(40, int(self.stride or 5)))
        horizons = tuple(sorted({max(1, int(h)) for h in (self.horizons or DEFAULT_HORIZONS)}))
        acts = frozenset(str(a).upper() for a in (self.entry_actions or ENTRY_ACTIONS))
        if not acts:
            acts = ENTRY_ACTIONS
        cost = max(0.0, min(5.0, float(self.roundtrip_cost_pct or 0.0)))
        phases = frozenset(str(p).lower() for p in (self.entry_phases or ("accumulation", "breakout")))
        style = str(self.entry_style or "value_accum").strip().lower()
        if style not in ENTRY_STYLES:
            style = "value_accum"
        # pit_quality mặc định = cấu hình thắng sweep (PIT bắt buộc + Rev&LN ≥ 0)
        require_pit_ok = bool(self.require_pit_ok) or style in ("pit_quality", "pit_strict")
        require_both = bool(self.require_both_growth_positive) or style in ("pit_quality", "pit_strict")
        return PlaybookBacktestConfig(
            min_history=hist,
            stride=stride,
            horizons=horizons,
            entry_actions=acts,
            roundtrip_cost_pct=cost,
            track_watch_control=bool(self.track_watch_control),
            track_avoid_control=bool(self.track_avoid_control),
            require_trigger_ready=bool(self.require_trigger_ready),
            max_entry_rsi=max(50.0, min(90.0, float(self.max_entry_rsi or 72.0))),
            min_mos_proxy=float(self.min_mos_proxy if self.min_mos_proxy is not None else 8.0),
            entry_phases=phases or frozenset({"accumulation", "breakout"}),
            entry_style=style,
            use_pit_fundamentals=bool(self.use_pit_fundamentals),
            require_pit_growth_ok=bool(self.require_pit_growth_ok),
            buy_only=bool(self.buy_only),
            require_pit_ok=require_pit_ok,
            require_both_growth_positive=require_both,
            min_rev_yoy=self.min_rev_yoy,
            min_profit_yoy=self.min_profit_yoy,
            block_risk_off=bool(self.block_risk_off),
            min_rs_20d=self.min_rs_20d,
        )


def _num_or_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def growth_ok_for_row(
    row: dict[str, Any],
    *,
    require_pit_growth_ok: bool = True,
    require_both_growth_positive: bool = False,
    min_rev_yoy: float | None = None,
    min_profit_yoy: float | None = None,
) -> bool:
    """PIT growth gate. Missing PIT → pass (không zero hết trade khi cache trống)."""
    if not require_pit_growth_ok and min_rev_yoy is None and min_profit_yoy is None and not require_both_growth_positive:
        return True
    pit_ok = bool(row.get("pit_ok"))
    if not pit_ok:
        return True
    r = _num_or_none(row.get("rev_yoy"))
    p = _num_or_none(row.get("profit_yoy"))
    if require_both_growth_positive:
        if r is None or p is None:
            return False
        return r >= 0.0 and p >= 0.0
    if min_rev_yoy is not None and (r is None or r < float(min_rev_yoy)):
        return False
    if min_profit_yoy is not None and (p is None or p < float(min_profit_yoy)):
        return False
    if not require_pit_growth_ok:
        return True
    if r is None and p is None:
        return True
    if r is not None and p is not None:
        return not (r < -5 and p < -10)
    if r is not None:
        return r >= -5
    return p is not None and p >= -10


def passes_entry_filters(row: dict[str, Any], cfg: PlaybookBacktestConfig) -> bool:
    """Apply style + optional strict gates to an ARMED+READY candidate row."""
    cfg = cfg.normalize()
    action = str(row.get("action") or "").upper()
    if action not in cfg.entry_actions:
        return False
    if cfg.buy_only and action != "BUY":
        return False
    if cfg.require_trigger_ready and str(row.get("trigger") or "") != "READY":
        return False
    if str(row.get("setup") or "") != "ARMED":
        return False
    phase_name = str(row.get("phase") or "").lower()
    if phase_name and phase_name not in cfg.entry_phases and cfg.entry_style != "armed_pool":
        return False
    rsi = _num_or_none(row.get("rsi")) or 50.0
    mos_px = _num_or_none(row.get("mos_proxy")) or 0.0
    regime = str(row.get("regime") or "").lower()
    if cfg.block_risk_off and regime in ("risk_off", "defensive", "bear"):
        return False
    if cfg.require_pit_ok and not bool(row.get("pit_ok")):
        return False
    if cfg.min_rs_20d is not None:
        rs = _num_or_none(row.get("rs_20d"))
        if rs is None or rs < float(cfg.min_rs_20d):
            return False

    style = cfg.entry_style
    growth_kwargs = dict(
        require_pit_growth_ok=cfg.require_pit_growth_ok,
        require_both_growth_positive=cfg.require_both_growth_positive,
        min_rev_yoy=cfg.min_rev_yoy,
        min_profit_yoy=cfg.min_profit_yoy,
    )
    if style == "armed_pool":
        if rsi > cfg.max_entry_rsi:
            return False
        if mos_px < cfg.min_mos_proxy:
            return False
        return growth_ok_for_row(row, **growth_kwargs)
    if style == "value_accum":
        if phase_name != "accumulation":
            return False
        if mos_px < max(cfg.min_mos_proxy, 12.0):
            return False
        if rsi > min(cfg.max_entry_rsi, 55.0):
            return False
        return growth_ok_for_row(row, **growth_kwargs)
    if style == "breakout":
        if phase_name != "breakout":
            return False
        if not (48.0 <= rsi <= cfg.max_entry_rsi):
            return False
        if mos_px < -5.0:
            return False
        return growth_ok_for_row(row, **growth_kwargs)
    if style == "pit_quality":
        if rsi > cfg.max_entry_rsi:
            return False
        if mos_px < cfg.min_mos_proxy:
            return False
        if not growth_ok_for_row(row, **growth_kwargs):
            return False
        if bool(row.get("pit_ok")):
            r = _num_or_none(row.get("rev_yoy"))
            p = _num_or_none(row.get("profit_yoy"))
            if r is None or p is None:
                return False
            return r >= 0.0 and p >= 0.0
        return True
    if style == "pit_strict":
        # BUY-only + PIT bắt buộc + Rev&LN ≥0 + RSI/MOS siết + không risk_off
        if action != "BUY":
            return False
        if not bool(row.get("pit_ok")):
            return False
        if rsi > min(cfg.max_entry_rsi, 62.0):
            return False
        if mos_px < max(cfg.min_mos_proxy, 12.0):
            return False
        if regime in ("risk_off", "defensive", "bear"):
            return False
        return growth_ok_for_row(
            row,
            require_pit_growth_ok=True,
            require_both_growth_positive=True,
            min_rev_yoy=0.0,
            min_profit_yoy=0.0,
        )
    # both
    if rsi > cfg.max_entry_rsi:
        return False
    if mos_px < cfg.min_mos_proxy:
        return False
    return growth_ok_for_row(row, **growth_kwargs)


def filter_trade_pool(pool: list[dict[str, Any]], cfg: PlaybookBacktestConfig) -> list[dict[str, Any]]:
    return [r for r in pool if passes_entry_filters(r, cfg)]


def _normalize_ohlcv(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    out = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = out.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    else:
        out = out.dropna(subset=["close"]).reset_index(drop=True)
    return out


def sanitize_ohlcv_for_backtest(df: pd.DataFrame | None, *, max_day_change_pct: float = 35.0) -> pd.DataFrame:
    """
    P0 sanitize + drop unit-break gaps (vd. FPT 10.5 ↔ 67000 trong cùng series).
    """
    base = _normalize_ohlcv(df)
    if base.empty:
        return base
    try:
        from core.data_integrity import sanitize_ohlcv_frame

        cleaned, _rep = sanitize_ohlcv_frame(base)
        base = _normalize_ohlcv(cleaned)
    except Exception:
        pass
    if base.empty or len(base) < 3:
        return base
    close = pd.to_numeric(base["close"], errors="coerce")
    prev = close.shift(1)
    chg = ((close - prev).abs() / prev.replace(0, pd.NA) * 100.0).fillna(0.0)
    keep = chg <= float(max_day_change_pct)
    # Always keep first row
    keep.iloc[0] = True
    out = base.loc[keep].copy().reset_index(drop=True)
    # If still multi-scale (max/median > 50), keep the densest recent scale cluster
    if len(out) >= 80:
        c = pd.to_numeric(out["close"], errors="coerce")
        med = float(c.tail(60).median() or 0.0)
        if med > 0:
            ratio = c / med
            cluster = (ratio >= 0.25) & (ratio <= 4.0)
            if int(cluster.sum()) >= 80:
                out = out.loc[cluster].copy().reset_index(drop=True)
    return out


_HORIZON_ABS_CAP = {20: 45.0, 60: 80.0, 90: 120.0, 5: 25.0, 10: 35.0}


def _return_plausible(h: int, ret: float | None) -> bool:
    if ret is None:
        return False
    cap = _HORIZON_ABS_CAP.get(int(h), max(50.0, float(h) * 1.5))
    return abs(float(ret)) <= cap


def _resolve_date(ohlcv: pd.DataFrame, idx: int) -> str:
    if "date" in ohlcv.columns:
        try:
            return pd.Timestamp(ohlcv.iloc[idx]["date"]).date().isoformat()
        except Exception:
            pass
    return str(idx)


def _slice_bench_to_date(bench: pd.DataFrame | None, as_of: str) -> pd.DataFrame | None:
    b = _normalize_ohlcv(bench)
    if b.empty or "date" not in b.columns:
        return None if b.empty else b
    try:
        cut = pd.Timestamp(as_of)
    except Exception:
        return b
    sliced = b.loc[b["date"] <= cut].copy()
    return sliced if len(sliced) >= 20 else sliced


def valuation_proxy_from_bar(
    *,
    close: float,
    ma200: float,
    ma50: float,
    rsi14: float,
    closes_window: pd.Series | None = None,
) -> dict[str, Any]:
    """
    Point-in-time valuation surrogate (technical only).

    Blend:
    - discount vs MA200
    - own-history percentile (cheap when near local lows) — hoạt động cả thị trường tăng
    """
    px = float(close or 0.0)
    m200 = float(ma200 or 0.0)
    m50 = float(ma50 or 0.0)
    rsi = float(rsi14 if rsi14 == rsi14 else 50.0)  # NaN-safe
    if m200 > 0 and px > 0:
        ma_mos = ((m200 - px) / m200) * 100.0
    else:
        ma_mos = 0.0

    pct_mos = 0.0
    if closes_window is not None and len(closes_window) >= 40 and px > 0:
        w = pd.to_numeric(closes_window, errors="coerce").dropna()
        if len(w) >= 40:
            rank = float((w < px).sum()) / float(len(w))  # 0 = rẻ nhất cửa sổ
            pct_mos = (0.5 - rank) * 80.0  # rank0→+40, rank1→-40

    mos = 0.40 * ma_mos + 0.60 * pct_mos
    mos = max(-45.0, min(55.0, mos))

    fscore = 4
    if m50 > 0 and px >= m50:
        fscore += 2
    if rsi <= 65:
        fscore += 1
    if mos >= 10:
        fscore += 1
    fscore = max(0, min(9, fscore))

    if mos >= 20 and rsi <= 55:
        legend = "Mua mạnh"
    elif mos >= 8:
        legend = "Theo dõi"
    elif mos <= -15:
        legend = "Tránh"
    else:
        legend = "Theo dõi"

    return {
        "price": px,
        "margin_of_safety_composite_pct": round(mos, 2),
        "piotroski_score": fscore,
        "instant_conclusion": legend,
        "legend_scorecard": {
            "graham_pass": mos >= 15 and rsi <= 50,
            "buffett_pass": mos >= 10 and px >= m50 > 0,
            "lynch_pass": mos >= 8 and rsi <= 60,
        },
        "is_bank_sector": False,
        "valuation_proxy": True,
        "valuation_proxy_note_vi": (
            "MOS proxy = 40% vs MA200 + 60% percentile 1Y — không phải BCTC point-in-time."
        ),
    }


def risk_plan_from_metrics(
    *,
    price: float,
    ma50: float,
    atr_pct: float | None = None,
    phase: str = "neutral",
) -> dict[str, Any]:
    px = float(price or 0.0)
    m50 = float(ma50 or 0.0)
    ph = str(phase or "neutral").lower()
    if px <= 0:
        return {}
    band = 0.03
    if atr_pct is not None and atr_pct > 0:
        band = max(0.02, min(0.06, float(atr_pct) / 100.0 * 1.2))
    # Breakout: zone quanh giá hiện tại (không bắt hồi MA50). Accumulation: quanh MA50.
    if ph == "breakout":
        entry = px
    elif m50 > 0:
        entry = m50
    else:
        entry = px
    return {
        "entry_price": round(entry, 2),
        "buy_zone_low": round(entry * (1.0 - band), 2),
        "buy_zone_high": round(entry * (1.0 + band), 2),
        "stop_loss_price": round(entry * 0.92, 2),
        "take_profit_price": round(entry * 1.15, 2),
    }


def load_fundamentals_cache(symbol: str) -> dict[str, Any]:
    """Best-effort fundamentals from disk cache (not true PIT — documented)."""
    sym = str(symbol or "").strip().upper()
    if not sym:
        return {}
    try:
        from pathlib import Path
        import json

        path = Path(__file__).resolve().parent.parent / "data" / "financial_indicators_cache.json"
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        row = raw.get(sym) if isinstance(raw, dict) else None
        payload = row.get("payload") if isinstance(row, dict) else None
        if not isinstance(payload, dict):
            return {}
        return {
            "pe_ratio": payload.get("pe_ratio"),
            "pb_ratio": payload.get("pb_ratio"),
            "roe": payload.get("roe"),
            "revenue_growth_yoy": payload.get("revenue_growth_yoy"),
            "eps_growth_yoy": payload.get("eps_growth_yoy"),
            "debt_to_equity": payload.get("debt_to_equity"),
            "piotroski": payload.get("piotroski") or payload.get("piotroski_score"),
            "fundamentals_source": "financial_indicators_cache",
            "fundamentals_note_vi": "Cache hiện tại — không phải BCTC đúng ngày T (xấp xỉ chất lượng).",
        }
    except Exception:
        return {}


def enrich_valuation_with_fundamentals(val: dict[str, Any], fund: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge fundamentals (cache or PIT) into valuation + financials for evaluate_thesis."""
    v = dict(val or {})
    f = dict(fund or {})
    financials: dict[str, Any] = {}
    if not f:
        return v, financials

    # Prefer PIT mapper when payload looks like fundamentals_as_of
    if f.get("ok") is True or f.get("source", "").startswith("vndirect_statements_pit"):
        try:
            from core.fundamentals_pit import pit_to_valuation_financials

            patch, fin = pit_to_valuation_financials(f)
            if patch.get("legend_scorecard"):
                ls = dict(v.get("legend_scorecard") or {})
                ls.update(patch.pop("legend_scorecard"))
                v["legend_scorecard"] = ls
            # Keep max of technical proxy F-score and PIT quality score
            if patch.get("piotroski_score") is not None:
                try:
                    v["piotroski_score"] = max(
                        int(v.get("piotroski_score") or 0),
                        int(patch.pop("piotroski_score")),
                    )
                except (TypeError, ValueError):
                    pass
            v.update(patch)
            financials.update({k: x for k, x in fin.items() if x is not None})
            return v, financials
        except Exception:
            pass

    pe = f.get("pe_ratio")
    roe = f.get("roe")
    try:
        if pe is not None and float(pe) > 0:
            if float(pe) <= 12:
                ls = dict(v.get("legend_scorecard") or {})
                ls["lynch_pass"] = True
                v["legend_scorecard"] = ls
    except (TypeError, ValueError):
        pass
    try:
        if roe is not None:
            r = float(roe)
            if 0 < r <= 1.5:
                r *= 100.0
            v["roe_5y_avg"] = r
            financials["roe"] = r
    except (TypeError, ValueError):
        pass
    for k in ("revenue_growth_yoy", "eps_growth_yoy", "debt_to_equity", "profit_growth_yoy"):
        if f.get(k) is not None:
            financials[k] = f.get(k)
    try:
        ps = f.get("piotroski") or f.get("piotroski_score")
        if ps is not None and int(float(ps)) > 0:
            v["piotroski_score"] = max(int(v.get("piotroski_score") or 0), int(float(ps)))
    except (TypeError, ValueError):
        pass
    v["fundamentals_source"] = f.get("fundamentals_source") or f.get("source")
    return v, financials


def _atr_pct(ohlcv: pd.DataFrame, idx: int, window: int = 14) -> float | None:
    if idx < window:
        return None
    window_df = ohlcv.iloc[idx - window + 1 : idx + 1]
    high = pd.to_numeric(window_df["high"], errors="coerce")
    low = pd.to_numeric(window_df["low"], errors="coerce")
    close = pd.to_numeric(window_df["close"], errors="coerce")
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.mean()) if len(tr) else 0.0
    c = float(close.iloc[-1] or 0.0)
    if c <= 0 or atr <= 0:
        return None
    return (atr / c) * 100.0


def compute_forward_returns(
    ohlcv: pd.DataFrame,
    *,
    signal_index: int,
    horizons: tuple[int, ...],
    cost_pct: float = 0.0,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    i = int(signal_index)
    if i < 0 or i >= len(ohlcv):
        return out
    entry = float(ohlcv.iloc[i]["close"])
    if entry <= 0:
        return out
    for h in horizons:
        j = i + int(h)
        key = f"fwd_{h}d_pct"
        if j >= len(ohlcv):
            out[key] = None
            out[f"hit_{h}d"] = None
            continue
        exit_px = float(ohlcv.iloc[j]["close"])
        raw = ((exit_px / entry) - 1.0) * 100.0
        net = raw - float(cost_pct)
        out[key] = round(net, 4)
        out[f"hit_{h}d"] = bool(net > 0)
        out[f"raw_{h}d_pct"] = round(raw, 4)
    return out


def compute_benchmark_forward(
    bench: pd.DataFrame | None,
    *,
    as_of: str,
    horizons: tuple[int, ...],
) -> dict[str, Any]:
    b = _normalize_ohlcv(bench)
    if b.empty or "date" not in b.columns:
        return {f"bench_fwd_{h}d_pct": None for h in horizons}
    try:
        cut = pd.Timestamp(as_of)
    except Exception:
        return {f"bench_fwd_{h}d_pct": None for h in horizons}
    # entry = last close on/before as_of
    eligible = b.loc[b["date"] <= cut]
    if eligible.empty:
        return {f"bench_fwd_{h}d_pct": None for h in horizons}
    i = int(eligible.index[-1])
    # Map to positional index in full bench
    pos = b.index.get_loc(i)
    if isinstance(pos, slice):
        pos = pos.start or 0
    if isinstance(pos, (list, tuple)):
        pos = int(pos[-1])
    pos = int(pos)
    out: dict[str, Any] = {}
    entry = float(b.iloc[pos]["close"])
    for h in horizons:
        j = pos + int(h)
        if entry <= 0 or j >= len(b):
            out[f"bench_fwd_{h}d_pct"] = None
            continue
        exit_px = float(b.iloc[j]["close"])
        out[f"bench_fwd_{h}d_pct"] = round(((exit_px / entry) - 1.0) * 100.0, 4)
    return out


def past_relative_strength(
    ohlcv: pd.DataFrame,
    bench: pd.DataFrame | None,
    *,
    signal_index: int,
    as_of: str,
    lookback: int = 20,
) -> float | None:
    """Stock return − bench return over prior ``lookback`` bars (no look-ahead)."""
    lb = max(5, int(lookback))
    if signal_index < lb or ohlcv is None or getattr(ohlcv, "empty", True):
        return None
    try:
        c_now = float(ohlcv.iloc[signal_index]["close"])
        c_past = float(ohlcv.iloc[signal_index - lb]["close"])
    except Exception:
        return None
    if c_now <= 0 or c_past <= 0:
        return None
    stock_ret = (c_now / c_past - 1.0) * 100.0
    b = _normalize_ohlcv(bench)
    if b.empty or "date" not in b.columns:
        return round(stock_ret, 4)
    try:
        cut = pd.Timestamp(as_of)
    except Exception:
        return round(stock_ret, 4)
    eligible = b.loc[b["date"] <= cut]
    if len(eligible) <= lb:
        return round(stock_ret, 4)
    last_idx = int(eligible.index[-1])
    # positional index in normalized bench
    try:
        pos = int(list(b.index).index(last_idx))
    except ValueError:
        pos = len(eligible) - 1
    if pos < lb:
        return round(stock_ret, 4)
    try:
        be = float(b.iloc[pos]["close"])
        bp = float(b.iloc[pos - lb]["close"])
    except Exception:
        return round(stock_ret, 4)
    if be <= 0 or bp <= 0:
        return round(stock_ret, 4)
    return round(stock_ret - ((be / bp - 1.0) * 100.0), 4)

def replay_playbook_on_ohlcv(
    ohlcv: pd.DataFrame,
    *,
    symbol: str = "",
    benchmark_ohlcv: pd.DataFrame | None = None,
    config: PlaybookBacktestConfig | None = None,
) -> dict[str, Any]:
    """
    Rolling replay. Returns trades (entry actions) + optional WATCH control + summary.
    """
    cfg = (config or PlaybookBacktestConfig()).normalize()
    df = sanitize_ohlcv_for_backtest(ohlcv)
    sym = str(symbol or "").upper()
    if len(df) < cfg.min_history + max(cfg.horizons):
        return {
            "symbol": sym,
            "ok": False,
            "reason": "insufficient_history",
            "n_bars": len(df),
            "trades": [],
            "watch_control": [],
            "summary": {},
        }

    indicators = compute_technical_indicators(df)
    trades: list[dict[str, Any]] = []
    armed_pool: list[dict[str, Any]] = []
    watch_control: list[dict[str, Any]] = []
    avoid_control: list[dict[str, Any]] = []
    action_counts: dict[str, int] = {}

    statement_rows: list[dict[str, Any]] | None = None
    statement_src = "none"
    if cfg.use_pit_fundamentals:
        try:
            from core.fundamentals_pit import load_statement_rows_cached

            statement_rows, statement_src = load_statement_rows_cached(sym, size=20)
        except Exception as exc:
            logger.warning("pit_statements_load_failed symbol=%s err=%s", sym, exc.__class__.__name__)
            statement_rows = []
    fund_cache = {} if cfg.use_pit_fundamentals else load_fundamentals_cache(sym)

    start = cfg.min_history
    end = len(df) - max(cfg.horizons)
    closes = pd.to_numeric(df["close"], errors="coerce")
    pit_ok_count = 0
    for i in range(start, max(start, end + 1), cfg.stride):
        if i >= len(indicators):
            break
        try:
            phase_res = detect_market_phase_at_index(df, indicators, i)
        except Exception as exc:
            logger.debug("phase_fail symbol=%s i=%s err=%s", sym, i, exc.__class__.__name__)
            continue

        metrics = dict(phase_res.metrics or {})
        close = float(metrics.get("close") or df.iloc[i]["close"])
        ma50 = float(metrics.get("ma50") or 0.0)
        row = indicators.iloc[i]
        ma200 = 0.0
        if "ma200" in indicators.columns and pd.notna(row.get("ma200")):
            ma200 = float(row["ma200"])
        if ma200 <= 0 and i >= 199:
            ma200 = float(closes.iloc[i - 199 : i + 1].mean())
        rsi = float(metrics.get("rsi14") or 50.0)
        win = closes.iloc[max(0, i - 251) : i + 1]

        as_of = _resolve_date(df, i)
        bench_slice = _slice_bench_to_date(benchmark_ohlcv, as_of)
        regime = assess_market_regime(vnindex_ohlcv=bench_slice, macro=None)

        val = valuation_proxy_from_bar(
            close=close, ma200=ma200, ma50=ma50, rsi14=rsi, closes_window=win
        )
        fund_payload: dict[str, Any] = fund_cache
        if cfg.use_pit_fundamentals:
            try:
                from core.fundamentals_pit import fundamentals_as_of

                fund_payload = fundamentals_as_of(
                    sym, as_of, rows=statement_rows, price=close
                )
                if fund_payload.get("ok"):
                    pit_ok_count += 1
            except Exception:
                fund_payload = {}
        val, financials = enrich_valuation_with_fundamentals(val, fund_payload)
        atrp = _atr_pct(df, i)
        risk = risk_plan_from_metrics(
            price=close, ma50=ma50, atr_pct=atrp, phase=str(phase_res.phase)
        )

        integrity = {
            "ok": not bool(metrics.get("rsi_indicator_fail")),
            "rsi_indicator_fail": bool(metrics.get("rsi_indicator_fail")),
            "notes_vi": [],
        }
        if metrics.get("rsi_indicator_fail"):
            integrity["notes_vi"] = ["RSI indicator fail (P0)."]

        conf = 55.0
        if str(phase_res.phase) in ("accumulation", "breakout"):
            conf += 10.0
        if regime.get("label") == "risk_on":
            conf += 5.0
        if regime.get("label") == "risk_off":
            conf -= 10.0
        if financials.get("revenue_growth_yoy") is not None:
            try:
                ry = float(financials["revenue_growth_yoy"])
                if ry >= 10:
                    conf += 5.0
                elif ry < -10:
                    conf -= 8.0
            except (TypeError, ValueError):
                pass
        if financials.get("profit_growth_yoy") is not None:
            try:
                if float(financials["profit_growth_yoy"]) >= 10:
                    conf += 4.0
                elif float(financials["profit_growth_yoy"]) < -15:
                    conf -= 6.0
            except (TypeError, ValueError):
                pass

        pb = build_decision_playbook(
            valuation=val,
            phase={"phase": phase_res.phase, "reason": phase_res.reason, "metrics": metrics},
            financials=financials or None,
            confidence=conf,
            risk_plan=risk,
            deep_insight=None,
            market_regime=regime,
            data_trust={"band": "MEDIUM"},
            ohlcv_integrity=integrity,
        )
        action = str(pb.get("recommended_action") or "WATCH").upper()
        action_counts[action] = action_counts.get(action, 0) + 1

        fwd = compute_forward_returns(
            df, signal_index=i, horizons=cfg.horizons, cost_pct=cfg.roundtrip_cost_pct
        )
        for h in cfg.horizons:
            key = f"fwd_{h}d_pct"
            if not _return_plausible(h, fwd.get(key)):
                fwd[key] = None
                fwd[f"hit_{h}d"] = None
        bench_fwd = compute_benchmark_forward(benchmark_ohlcv, as_of=as_of, horizons=cfg.horizons)
        excess: dict[str, Any] = {}
        for h in cfg.horizons:
            a = fwd.get(f"fwd_{h}d_pct")
            b = bench_fwd.get(f"bench_fwd_{h}d_pct")
            if a is not None and b is not None and _return_plausible(h, b):
                excess[f"excess_{h}d_pct"] = round(float(a) - float(b), 4)
            else:
                excess[f"excess_{h}d_pct"] = None

        setup_st = str((pb.get("setup") or {}).get("status") or "")
        trig_st = str((pb.get("trigger") or {}).get("status") or "")
        mos_px = float(val.get("margin_of_safety_composite_pct") or 0.0)
        rev_yoy = financials.get("revenue_growth_yoy")
        ni_yoy = financials.get("profit_growth_yoy")
        rs_20 = past_relative_strength(
            df, benchmark_ohlcv, signal_index=i, as_of=as_of, lookback=20
        )
        row_out = {
            "symbol": sym,
            "date": as_of,
            "signal_index": i,
            "action": action,
            "phase": phase_res.phase,
            "thesis": (pb.get("thesis") or {}).get("grade"),
            "thesis_attractive": bool((pb.get("thesis") or {}).get("attractive")),
            "setup": setup_st,
            "trigger": trig_st,
            "regime": (pb.get("regime") or {}).get("label"),
            "mos_proxy": mos_px,
            "rsi": round(rsi, 2),
            "rev_yoy": rev_yoy,
            "profit_yoy": ni_yoy,
            "pit_ok": bool(fund_payload.get("ok")) if isinstance(fund_payload, dict) else False,
            "rs_20d": rs_20,
            "price": close,
            **fwd,
            **bench_fwd,
            **excess,
        }

        # Pool ARMED+READY (mọi style) để sweep filter offline
        armed_ok = action in ENTRY_ACTIONS and setup_st == "ARMED" and trig_st == "READY"
        if armed_ok:
            armed_pool.append(row_out)

        entry_ok = passes_entry_filters(row_out, cfg)
        if entry_ok:
            trades.append(row_out)
        elif cfg.track_watch_control and action in ("WATCH", "HOLD"):
            watch_control.append(row_out)
        elif cfg.track_avoid_control and action == "AVOID":
            avoid_control.append(row_out)

    summary = summarize_playbook_trades(trades, horizons=cfg.horizons)
    watch_summary = summarize_playbook_trades(watch_control, horizons=cfg.horizons) if watch_control else {}
    avoid_summary = summarize_playbook_trades(avoid_control, horizons=cfg.horizons) if avoid_control else {}
    return {
        "symbol": sym,
        "ok": True,
        "n_bars": len(df),
        "n_replays": sum(action_counts.values()),
        "action_counts": action_counts,
        "n_trades": len(trades),
        "n_armed_pool": len(armed_pool),
        "n_watch_control": len(watch_control),
        "n_avoid_control": len(avoid_control),
        "trades": trades,
        "armed_pool": armed_pool,
        "watch_control": watch_control,
        "avoid_control": avoid_control,
        "summary": summary,
        "watch_summary": watch_summary,
        "avoid_summary": avoid_summary,
        "config": {
            "min_history": cfg.min_history,
            "stride": cfg.stride,
            "horizons": list(cfg.horizons),
            "entry_actions": sorted(cfg.entry_actions),
            "roundtrip_cost_pct": cfg.roundtrip_cost_pct,
            "require_trigger_ready": cfg.require_trigger_ready,
            "max_entry_rsi": cfg.max_entry_rsi,
            "min_mos_proxy": cfg.min_mos_proxy,
            "use_pit_fundamentals": cfg.use_pit_fundamentals,
            "require_pit_growth_ok": cfg.require_pit_growth_ok,
            "entry_style": cfg.entry_style,
            "buy_only": cfg.buy_only,
            "require_pit_ok": cfg.require_pit_ok,
            "require_both_growth_positive": cfg.require_both_growth_positive,
            "statements_source": statement_src,
            "pit_ok_bars": pit_ok_count,
        },
        "method_note_vi": (
            "Replay playbook P1+PIT: BCTC ≤ ngày T (lag 45d); entry ARMED+READY + growth filter; "
            f"style={cfg.entry_style}. Không look-ahead giá."
        ),
    }


def summarize_playbook_trades(
    trades: list[dict[str, Any]],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    if not trades:
        return {"samples": 0, "by_horizon": {}, "by_action": {}}
    by_h: dict[str, Any] = {}
    for h in horizons:
        rets = [
            float(t[f"fwd_{h}d_pct"])
            for t in trades
            if t.get(f"fwd_{h}d_pct") is not None and _return_plausible(h, t.get(f"fwd_{h}d_pct"))
        ]
        hits = [r > 0 for r in rets]
        excess = [
            float(t[f"excess_{h}d_pct"])
            for t in trades
            if t.get(f"excess_{h}d_pct") is not None and _return_plausible(h, t.get(f"excess_{h}d_pct"))
        ]
        by_h[str(h)] = {
            "samples": len(rets),
            "hit_rate_pct": round(100.0 * sum(hits) / len(hits), 2) if hits else None,
            "avg_return_pct": round(sum(rets) / len(rets), 3) if rets else None,
            "median_return_pct": round(float(pd.Series(rets).median()), 3) if rets else None,
            "avg_excess_vs_bench_pct": round(sum(excess) / len(excess), 3) if excess else None,
            "expectancy_pct": round(sum(rets) / len(rets), 3) if rets else None,
        }
    by_action: dict[str, int] = {}
    for t in trades:
        a = str(t.get("action") or "?")
        by_action[a] = by_action.get(a, 0) + 1
    return {"samples": len(trades), "by_horizon": by_h, "by_action": by_action}


def compare_entry_vs_watch(
    entry_summary: dict[str, Any],
    watch_summary: dict[str, Any],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Verdict: entry beats WATCH control on avg return / hit-rate."""
    by_e = (entry_summary or {}).get("by_horizon") or {}
    by_w = (watch_summary or {}).get("by_horizon") or {}
    rows: list[dict[str, Any]] = []
    wins = 0
    compared = 0
    for h in horizons:
        e = by_e.get(str(h)) or {}
        w = by_w.get(str(h)) or {}
        e_avg = e.get("avg_return_pct")
        w_avg = w.get("avg_return_pct")
        e_hit = e.get("hit_rate_pct")
        w_hit = w.get("hit_rate_pct")
        beat_avg = None
        beat_hit = None
        if e_avg is not None and w_avg is not None and int(e.get("samples") or 0) >= 8:
            compared += 1
            beat_avg = float(e_avg) > float(w_avg)
            if beat_avg:
                wins += 1
        if e_hit is not None and w_hit is not None:
            beat_hit = float(e_hit) >= float(w_hit)
        rows.append(
            {
                "horizon_d": h,
                "entry_avg": e_avg,
                "watch_avg": w_avg,
                "entry_hit": e_hit,
                "watch_hit": w_hit,
                "entry_samples": e.get("samples"),
                "beats_watch_avg": beat_avg,
                "beats_watch_hit": beat_hit,
            }
        )
    return {
        "horizons": rows,
        "compared": compared,
        "wins_avg": wins,
        "entry_beats_watch": bool(compared > 0 and wins >= max(1, (compared + 1) // 2)),
        "note_vi": (
            "Entry thắng WATCH nếu hơn nửa horizon có avg_return cao hơn (min 8 samples/horizon)."
        ),
    }


def compare_avoid_vs_watch(
    avoid_summary: dict[str, Any],
    watch_summary: dict[str, Any],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """
    Protective gate: AVOID có ý nghĩa nếu avg_return thấp hơn WATCH
    (tránh mua vào lúc xấu hơn).
    """
    by_a = (avoid_summary or {}).get("by_horizon") or {}
    by_w = (watch_summary or {}).get("by_horizon") or {}
    rows: list[dict[str, Any]] = []
    protective = 0
    compared = 0
    for h in horizons:
        a = by_a.get(str(h)) or {}
        w = by_w.get(str(h)) or {}
        a_avg = a.get("avg_return_pct")
        w_avg = w.get("avg_return_pct")
        ok = None
        if a_avg is not None and w_avg is not None and int(a.get("samples") or 0) >= 8:
            compared += 1
            ok = float(a_avg) < float(w_avg)
            if ok:
                protective += 1
        rows.append(
            {
                "horizon_d": h,
                "avoid_avg": a_avg,
                "watch_avg": w_avg,
                "avoid_samples": a.get("samples"),
                "avoid_lower_than_watch": ok,
            }
        )
    return {
        "horizons": rows,
        "compared": compared,
        "protective_wins": protective,
        "avoid_is_protective": bool(compared > 0 and protective >= max(1, (compared + 1) // 2)),
        "note_vi": (
            "AVOID bảo vệ nếu avg_return thấp hơn WATCH trên ≥ nửa horizon (min 8 samples)."
        ),
    }


def sweep_entry_filter_variants(
    armed_pool: list[dict[str, Any]],
    watch_summary: dict[str, Any],
    *,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
) -> dict[str, Any]:
    """Offline grid trên pool ARMED+READY — không cần replay lại OHLCV."""
    variants: list[PlaybookBacktestConfig] = [
        PlaybookBacktestConfig(entry_style="pit_quality").normalize(),
        PlaybookBacktestConfig(entry_style="pit_strict").normalize(),
        PlaybookBacktestConfig(entry_style="value_accum").normalize(),
        PlaybookBacktestConfig(entry_style="breakout").normalize(),
        PlaybookBacktestConfig(entry_style="both").normalize(),
        PlaybookBacktestConfig(entry_style="pit_quality", buy_only=True).normalize(),
        PlaybookBacktestConfig(entry_style="pit_quality", min_rs_20d=0.0).normalize(),
        PlaybookBacktestConfig(entry_style="pit_quality", min_rs_20d=2.0).normalize(),
        PlaybookBacktestConfig(
            entry_style="pit_quality", min_rs_20d=0.0, block_risk_off=True
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="pit_quality",
            min_rs_20d=0.0,
            max_entry_rsi=65.0,
            min_mos_proxy=10.0,
            block_risk_off=True,
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="pit_quality",
            buy_only=True,
            min_rs_20d=0.0,
            max_entry_rsi=60.0,
            min_mos_proxy=12.0,
            block_risk_off=True,
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="pit_quality",
            min_rev_yoy=5.0,
            min_profit_yoy=0.0,
            min_rs_20d=0.0,
            max_entry_rsi=62.0,
            min_mos_proxy=12.0,
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="value_accum",
            require_pit_ok=True,
            require_both_growth_positive=True,
            max_entry_rsi=55.0,
            min_mos_proxy=15.0,
            min_rs_20d=0.0,
            block_risk_off=True,
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="armed_pool",
            buy_only=True,
            require_pit_ok=True,
            require_both_growth_positive=True,
            max_entry_rsi=55.0,
            min_mos_proxy=15.0,
            min_rs_20d=0.0,
            block_risk_off=True,
        ).normalize(),
        PlaybookBacktestConfig(
            entry_style="pit_quality",
            min_rs_20d=-2.0,
            max_entry_rsi=68.0,
            min_mos_proxy=10.0,
        ).normalize(),
    ]
    scored: list[dict[str, Any]] = []
    for cfg in variants:
        trades = filter_trade_pool(armed_pool, cfg)
        summary = summarize_playbook_trades(trades, horizons=horizons)
        verdict = compare_entry_vs_watch(summary, watch_summary, horizons=horizons)
        by_h = summary.get("by_horizon") or {}
        avg60 = (by_h.get("60") or {}).get("avg_return_pct")
        avg20 = (by_h.get("20") or {}).get("avg_return_pct")
        ex20 = (by_h.get("20") or {}).get("avg_excess_vs_bench_pct")
        ex60 = (by_h.get("60") or {}).get("avg_excess_vs_bench_pct")
        excess_wins = sum(
            1
            for h in horizons
            if isinstance((by_h.get(str(h)) or {}).get("avg_excess_vs_bench_pct"), (int, float))
            and float((by_h.get(str(h)) or {}).get("avg_excess_vs_bench_pct")) > 0
            and int((by_h.get(str(h)) or {}).get("samples") or 0) >= 8
        )
        scored.append(
            {
                "label": (
                    f"style={cfg.entry_style};buy_only={cfg.buy_only};pit_ok={cfg.require_pit_ok};"
                    f"both_g={cfg.require_both_growth_positive};rsi≤{cfg.max_entry_rsi};"
                    f"mos≥{cfg.min_mos_proxy};rev≥{cfg.min_rev_yoy};ni≥{cfg.min_profit_yoy};"
                    f"rs≥{cfg.min_rs_20d};block_roff={cfg.block_risk_off}"
                ),
                "n_trades": len(trades),
                "summary": summary,
                "entry_vs_watch": verdict,
                "avg_return_20d": avg20,
                "avg_return_60d": avg60,
                "avg_excess_20d": ex20,
                "avg_excess_60d": ex60,
                "excess_positive_horizons": excess_wins,
                "config": {
                    "entry_style": cfg.entry_style,
                    "buy_only": cfg.buy_only,
                    "require_pit_ok": cfg.require_pit_ok,
                    "require_both_growth_positive": cfg.require_both_growth_positive,
                    "max_entry_rsi": cfg.max_entry_rsi,
                    "min_mos_proxy": cfg.min_mos_proxy,
                    "min_rev_yoy": cfg.min_rev_yoy,
                    "min_profit_yoy": cfg.min_profit_yoy,
                    "block_risk_off": cfg.block_risk_off,
                    "min_rs_20d": cfg.min_rs_20d,
                },
            }
        )
    scored.sort(
        key=lambda r: (
            int((r.get("entry_vs_watch") or {}).get("wins_avg") or 0),
            1 if (r.get("entry_vs_watch") or {}).get("entry_beats_watch") else 0,
            int(r.get("excess_positive_horizons") or 0),
            float(r.get("avg_excess_20d") or -999.0),
            float(r.get("avg_return_60d") or -999.0),
            int(r.get("n_trades") or 0),
        ),
        reverse=True,
    )
    best = scored[0] if scored else {}
    return {
        "variants_tested": len(scored),
        "best": best,
        "ranked": scored,
        "any_beats_watch": any((r.get("entry_vs_watch") or {}).get("entry_beats_watch") for r in scored),
    }


def aggregate_universe_results(results: list[dict[str, Any]], *, horizons: tuple[int, ...]) -> dict[str, Any]:
    pooled: list[dict[str, Any]] = []
    armed_pooled: list[dict[str, Any]] = []
    watch_pooled: list[dict[str, Any]] = []
    avoid_pooled: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        per_symbol.append(
            {
                "symbol": r.get("symbol"),
                "ok": r.get("ok"),
                "n_trades": r.get("n_trades"),
                "n_armed_pool": r.get("n_armed_pool"),
                "action_counts": r.get("action_counts"),
                "summary": r.get("summary"),
            }
        )
        pooled.extend(list(r.get("trades") or []))
        armed_pooled.extend(list(r.get("armed_pool") or []))
        watch_pooled.extend(list(r.get("watch_control") or []))
        avoid_pooled.extend(list(r.get("avoid_control") or []))
    pooled_summary = summarize_playbook_trades(pooled, horizons=horizons)
    watch_summary = summarize_playbook_trades(watch_pooled, horizons=horizons)
    avoid_summary = summarize_playbook_trades(avoid_pooled, horizons=horizons)
    verdict = compare_entry_vs_watch(pooled_summary, watch_summary, horizons=horizons)
    avoid_verdict = compare_avoid_vs_watch(avoid_summary, watch_summary, horizons=horizons)
    sweep = sweep_entry_filter_variants(armed_pooled, watch_summary, horizons=horizons)
    return {
        "symbols_ok": sum(1 for r in results if r.get("ok")),
        "symbols_total": len(results),
        "pooled_trades": len(pooled),
        "armed_pool_size": len(armed_pooled),
        "pooled_summary": pooled_summary,
        "watch_control_summary": watch_summary,
        "avoid_control_summary": avoid_summary,
        "entry_vs_watch": verdict,
        "avoid_vs_watch": avoid_verdict,
        "filter_sweep": {
            "variants_tested": sweep.get("variants_tested"),
            "any_beats_watch": sweep.get("any_beats_watch"),
            "best": {
                "label": (sweep.get("best") or {}).get("label"),
                "n_trades": (sweep.get("best") or {}).get("n_trades"),
                "avg_return_60d": (sweep.get("best") or {}).get("avg_return_60d"),
                "avg_excess_20d": (sweep.get("best") or {}).get("avg_excess_20d"),
                "avg_excess_60d": (sweep.get("best") or {}).get("avg_excess_60d"),
                "excess_positive_horizons": (sweep.get("best") or {}).get("excess_positive_horizons"),
                "entry_vs_watch": (sweep.get("best") or {}).get("entry_vs_watch"),
                "config": (sweep.get("best") or {}).get("config"),
                "summary": (sweep.get("best") or {}).get("summary"),
            },
            "top5": [
                {
                    "label": x.get("label"),
                    "n_trades": x.get("n_trades"),
                    "avg_return_60d": x.get("avg_return_60d"),
                    "avg_excess_20d": x.get("avg_excess_20d"),
                    "avg_excess_60d": x.get("avg_excess_60d"),
                    "excess_positive_horizons": x.get("excess_positive_horizons"),
                    "entry_beats_watch": (x.get("entry_vs_watch") or {}).get("entry_beats_watch"),
                    "wins_avg": (x.get("entry_vs_watch") or {}).get("wins_avg"),
                }
                for x in (sweep.get("ranked") or [])[:5]
            ],
        },
        "per_symbol": per_symbol,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "disclaimer_vi": (
            "Backtest học tập — valuation proxy + fundamentals cache, không cam kết lợi nhuận tương lai. "
            "So sánh excess vs VNINDEX/ETF (nếu có). Paper live vẫn cần để xác nhận."
        ),
    }


def load_ohlcv_for_replay(
    symbol: str,
    *,
    sessions: int = 520,
    prefer_yahoo: bool = True,
) -> tuple[pd.DataFrame, str]:
    """
    Prefer Yahoo long history for backtest (cleaner than mixed-unit local store),
    then disk store, then portal.
    """
    sym = str(symbol or "").strip().upper()
    if prefer_yahoo and sym not in ("VNINDEX", "VN30"):
        try:
            from core.strategy_backtest import fetch_long_ohlcv_for_backtest

            df, rng = fetch_long_ohlcv_for_backtest(sym, range_preference="5y")
            cleaned = sanitize_ohlcv_for_backtest(df)
            if len(cleaned) >= 120:
                return cleaned, f"yahoo:{rng}"
        except Exception as exc:
            logger.debug("yahoo_ohlcv_skip symbol=%s err=%s", sym, exc.__class__.__name__)
    try:
        from core.ohlcv_store import load_recent_ohlcv

        df = load_recent_ohlcv(sym, sessions=int(sessions))
        if df is not None and not df.empty and len(df) >= 120:
            return sanitize_ohlcv_for_backtest(df), "ohlcv_store"
    except Exception:
        pass
    try:
        from scrapers.portal import fetch_ohlcv_history

        df = fetch_ohlcv_history(sym, sessions=int(sessions))
        return sanitize_ohlcv_for_backtest(df), "portal"
    except Exception as exc:
        logger.warning("load_ohlcv_failed symbol=%s err=%s", sym, exc.__class__.__name__)
        return sanitize_ohlcv_for_backtest(None), "none"
