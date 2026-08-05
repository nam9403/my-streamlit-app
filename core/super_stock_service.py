from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from core.valuation import value_investing_summary
from scrapers.financial_data import fetch_financial_snapshot
from scrapers.portal import fetch_ohlcv_history


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SuperStockSignal:
    symbol: str
    passed: bool
    f_score: int
    mos_pct: float
    volume_multiple: float
    price_change_pct: float
    is_volume_breakout: bool
    relative_strength_pct: float
    market_relative_outperform: bool
    has_flat_base: bool
    has_vcp: bool
    red_flags: list[str]
    note: str


class DataFetcher:
    """Lớp lấy dữ liệu đầu vào cho bộ lọc Siêu cổ phiếu."""

    def fetch_snapshot(self, symbol: str) -> dict[str, Any] | None:
        return fetch_financial_snapshot(str(symbol or "").strip().upper())

    def fetch_ohlcv(self, symbol: str, sessions: int = 40) -> pd.DataFrame:
        return fetch_ohlcv_history(str(symbol or "").strip().upper(), sessions=max(25, int(sessions)))


class TechnicalAnalyzer:
    """Lớp phân tích kỹ thuật tập trung vào tín hiệu nổ Vol."""

    def detect_volume_breakout(
        self,
        ohlcv: pd.DataFrame,
        *,
        min_volume_multiple: float = 1.5,
        min_price_change_pct: float = 3.0,
    ) -> tuple[bool, float, float]:
        if ohlcv is None or ohlcv.empty or len(ohlcv) < 21:
            return False, 0.0, 0.0
        d = ohlcv.copy()
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
        d = d.dropna(subset=["close", "volume"])
        if len(d) < 21:
            return False, 0.0, 0.0
        last = d.iloc[-1]
        prev = d.iloc[-2]
        vol_ma20 = float(d["volume"].tail(20).mean())
        vol_multiple = (float(last["volume"]) / vol_ma20) if vol_ma20 > 0 else 0.0
        prev_close = float(prev["close"])
        price_change_pct = ((float(last["close"]) - prev_close) / prev_close * 100.0) if prev_close > 0 else 0.0
        passed = vol_multiple >= min_volume_multiple and price_change_pct >= min_price_change_pct
        return passed, round(vol_multiple, 4), round(price_change_pct, 4)

    def compute_relative_strength_vs_index(self, stock_ohlcv: pd.DataFrame, index_ohlcv: pd.DataFrame, lookback: int = 20) -> tuple[float, bool]:
        """
        RS tương đối: hiệu suất cổ phiếu trừ hiệu suất chỉ số.
        Dương nghĩa là cổ phiếu khỏe hơn thị trường.
        """
        if stock_ohlcv is None or index_ohlcv is None or stock_ohlcv.empty or index_ohlcv.empty:
            return 0.0, False
        s = stock_ohlcv.copy()
        i = index_ohlcv.copy()
        s["close"] = pd.to_numeric(s["close"], errors="coerce")
        i["close"] = pd.to_numeric(i["close"], errors="coerce")
        s = s.dropna(subset=["close"]).tail(max(lookback + 1, 5))
        i = i.dropna(subset=["close"]).tail(max(lookback + 1, 5))
        if len(s) < 2 or len(i) < 2:
            return 0.0, False
        s0, s1 = float(s["close"].iloc[0]), float(s["close"].iloc[-1])
        i0, i1 = float(i["close"].iloc[0]), float(i["close"].iloc[-1])
        if s0 <= 0 or i0 <= 0:
            return 0.0, False
        stock_ret = (s1 / s0 - 1.0) * 100.0
        index_ret = (i1 / i0 - 1.0) * 100.0
        rs = stock_ret - index_ret
        return round(rs, 4), bool(rs > 0)

    def detect_flat_base(self, ohlcv: pd.DataFrame, lookback: int = 20, max_range_pct: float = 12.0) -> bool:
        """Flat Base đơn giản: biên dao động 20 phiên đủ hẹp."""
        if ohlcv is None or ohlcv.empty or len(ohlcv) < lookback:
            return False
        d = ohlcv.copy().tail(lookback)
        d["high"] = pd.to_numeric(d["high"], errors="coerce")
        d["low"] = pd.to_numeric(d["low"], errors="coerce")
        d = d.dropna(subset=["high", "low"])
        if d.empty:
            return False
        hh = float(d["high"].max())
        ll = float(d["low"].min())
        if ll <= 0:
            return False
        range_pct = (hh - ll) / ll * 100.0
        return bool(range_pct <= max_range_pct)

    def detect_vcp(self, ohlcv: pd.DataFrame) -> bool:
        """
        VCP proxy: biên dao động và độ lệch volume co hẹp dần.
        Kiểm tra 3 đoạn gần nhất: 30-21, 20-11, 10-1.
        """
        if ohlcv is None or ohlcv.empty or len(ohlcv) < 30:
            return False
        d = ohlcv.copy().tail(30)
        for c in ("high", "low", "volume"):
            d[c] = pd.to_numeric(d[c], errors="coerce")
        d = d.dropna(subset=["high", "low", "volume"])
        if len(d) < 30:
            return False
        segments = [d.iloc[0:10], d.iloc[10:20], d.iloc[20:30]]
        range_vals: list[float] = []
        vol_std_vals: list[float] = []
        for seg in segments:
            ll = float(seg["low"].min())
            hh = float(seg["high"].max())
            if ll <= 0:
                return False
            range_vals.append((hh - ll) / ll * 100.0)
            vol_std_vals.append(float(seg["volume"].std(ddof=0) or 0.0))
        range_contract = range_vals[0] >= range_vals[1] >= range_vals[2]
        vol_contract = vol_std_vals[0] >= vol_std_vals[1] >= vol_std_vals[2]
        return bool(range_contract and vol_contract)


class FundamentalScorer:
    """Lớp chấm điểm cơ bản: F-Score + Margin of Safety + cờ đỏ."""

    def __init__(self, min_f_score: int = 7, min_mos_pct: float = 10.0) -> None:
        self.min_f_score = int(min_f_score)
        self.min_mos_pct = float(min_mos_pct)

    def build_valuation(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return value_investing_summary(snapshot)

    def evaluate_red_flags(self, snapshot: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        pio = snapshot.get("piotroski") if isinstance(snapshot.get("piotroski"), dict) else {}
        ltd = _safe_float((pio or {}).get("long_term_debt"), 0.0)
        ltd_prev = _safe_float((pio or {}).get("long_term_debt_prior"), 0.0)
        if ltd_prev > 0 and ltd >= ltd_prev * 1.35:
            flags.append("Nợ vay dài hạn tăng đột biến >35% so với kỳ trước.")

        fin_income = _safe_float(snapshot.get("financial_income"), 0.0)
        op_income = _safe_float(snapshot.get("operating_income"), 0.0)
        net_income = _safe_float(snapshot.get("net_income"), 0.0)
        if fin_income > 0 and net_income > 0 and fin_income >= net_income * 0.6:
            flags.append("Tỷ trọng lợi nhuận từ doanh thu tài chính ở mức cao.")
        if fin_income > 0 and op_income > 0 and fin_income > op_income:
            flags.append("Doanh thu tài chính vượt lợi nhuận hoạt động cốt lõi.")
        return flags

    def evaluate(
        self,
        symbol: str,
        snapshot: dict[str, Any],
        breakout_ok: bool,
        vol_mult: float,
        price_chg: float,
        *,
        rs_pct: float = 0.0,
        rs_outperform: bool = False,
        has_flat_base: bool = False,
        has_vcp: bool = False,
    ) -> SuperStockSignal:
        val = self.build_valuation(snapshot)
        f_score = int(val.get("piotroski_score") or 0)
        mos_pct = _safe_float(val.get("margin_of_safety_composite_pct"), -999.0)
        red_flags = self.evaluate_red_flags(snapshot)
        passed = f_score >= self.min_f_score and mos_pct >= self.min_mos_pct and breakout_ok and rs_outperform
        note = (
            "Đủ 3 điều kiện Siêu cổ phiếu."
            if passed
            else "Chưa đủ điều kiện đồng thuận (F-Score + MOS + Nổ Vol)."
        )
        return SuperStockSignal(
            symbol=str(symbol or "").strip().upper(),
            passed=passed,
            f_score=f_score,
            mos_pct=round(mos_pct, 2),
            volume_multiple=round(vol_mult, 2),
            price_change_pct=round(price_chg, 2),
            is_volume_breakout=bool(breakout_ok),
            relative_strength_pct=round(rs_pct, 2),
            market_relative_outperform=bool(rs_outperform),
            has_flat_base=bool(has_flat_base),
            has_vcp=bool(has_vcp),
            red_flags=red_flags,
            note=note,
        )


class Notifier:
    """Lớp gửi cảnh báo Telegram khi hội tụ tín hiệu."""

    def __init__(
        self,
        *,
        load_secret_func: Callable[[str, str, str], str],
        dispatch_text_notifications_func: Callable[..., dict[str, int]],
        user_id: str = "default_user",
    ) -> None:
        self.load_secret_func = load_secret_func
        self.dispatch_text_notifications_func = dispatch_text_notifications_func
        self.user_id = str(user_id or "default_user")

    def notify_super_stock(self, signal: SuperStockSignal) -> dict[str, int]:
        token = self.load_secret_func(self.user_id, "telegram_bot_token", "")
        chat_id = self.load_secret_func(self.user_id, "telegram_chat_id", "")
        if not token or not chat_id:
            return {"sent": 0, "failed": 0}
        risks = " | ".join(signal.red_flags[:2]) if signal.red_flags else "Không phát hiện cờ đỏ nổi bật."
        text = (
            f"🚀 Super Stock Alert: {signal.symbol}\n"
            f"F-Score: {signal.f_score}/9\n"
            f"MOS: {signal.mos_pct:.1f}%\n"
            f"Nổ Vol: {'Có' if signal.is_volume_breakout else 'Không'} "
            f"(x{signal.volume_multiple:.2f}, giá {signal.price_change_pct:+.2f}%)\n"
            f"RS vs VN-Index: {signal.relative_strength_pct:+.2f}% "
            f"({'Outperform' if signal.market_relative_outperform else 'Underperform'})\n"
            f"Flat Base: {'Có' if signal.has_flat_base else 'Không'} | VCP: {'Có' if signal.has_vcp else 'Không'}\n"
            f"Cờ đỏ: {risks}\n"
            f"Ghi chú: {signal.note}"
        )
        return self.dispatch_text_notifications_func(
            text,
            telegram_bot_token=token,
            telegram_chat_id=chat_id,
        )


def evaluate_super_stock_signal(
    symbol: str,
    *,
    data_fetcher: DataFetcher | None = None,
    technical_analyzer: TechnicalAnalyzer | None = None,
    fundamental_scorer: FundamentalScorer | None = None,
) -> SuperStockSignal | None:
    fetcher = data_fetcher or DataFetcher()
    ta = technical_analyzer or TechnicalAnalyzer()
    fs = fundamental_scorer or FundamentalScorer()
    sym = str(symbol or "").strip().upper()
    if not sym:
        return None
    snapshot = fetcher.fetch_snapshot(sym)
    if not snapshot:
        return None
    try:
        ohlcv = fetcher.fetch_ohlcv(sym, sessions=45)
    except Exception:
        ohlcv = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    breakout_ok, vol_mult, price_chg = ta.detect_volume_breakout(ohlcv)
    try:
        vnindex = fetcher.fetch_ohlcv("VNINDEX", sessions=45)
    except Exception:
        vnindex = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    rs_pct, rs_outperform = ta.compute_relative_strength_vs_index(ohlcv, vnindex, lookback=20)
    has_flat_base = ta.detect_flat_base(ohlcv, lookback=20, max_range_pct=12.0)
    has_vcp = ta.detect_vcp(ohlcv)
    return fs.evaluate(
        sym,
        snapshot,
        breakout_ok,
        vol_mult,
        price_chg,
        rs_pct=rs_pct,
        rs_outperform=rs_outperform,
        has_flat_base=has_flat_base,
        has_vcp=has_vcp,
    )
