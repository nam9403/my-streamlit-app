"""Tier 1 — Intraday Flow Service.

Phát hiện dấu vết dòng tiền lớn ("Big Boys") theo tinh thần market microstructure,
nhưng được thiết kế *frequency-agnostic*: chấp nhận bất kỳ DataFrame OHLCV nào
(daily / 5-min / 1-min / aggregated ticks) miễn là có các cột chuẩn
`open`, `high`, `low`, `close`, `volume`.

Hợp đồng output (`FlowSignal`) giữ nguyên theo đặc tả TickFlowAnalyzer:
- ``is_big_boy``
- ``aggregated_volume``
- ``delta_status``
- ``intensity_score`` (1-10)

Cách tiếp cận:
- Dynamic Z-score thay ngưỡng cứng (μ_N + k·σ_N trên cửa sổ trượt).
- Isolation Forest trên đặc trưng tổng hợp để phát hiện bất thường thay vì hardcode VND.
- Pseudo-delta theo tick rule trên close-of-bar khi không có tick thật.
- Aggregation gom các bar liên tiếp cùng chiều (proxy cho VWAP/TWAP slicing).
- Cumulative delta + buy/sell imbalance để chấm `delta_status`.

Module hoàn toàn thuần (không import streamlit) ⇒ dễ tái sử dụng ở UI panel,
background job, hoặc microservice Tier 3 sau này.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal

import numpy as np
import pandas as pd

DeltaStatus = Literal[
    "bullish",
    "bearish",
    "absorption",
    "distribution",
    "neutral",
]

_REQUIRED_COLS: tuple[str, ...] = ("open", "high", "low", "close", "volume")


class IntradayFlowError(Exception):
    """Lỗi khi dữ liệu đầu vào không đủ điều kiện phân tích."""


@dataclass(frozen=True)
class FlowConfig:
    """Cấu hình ngưỡng và cửa sổ phân tích.

    - ``rolling_window`` mặc định 120: phù hợp daily (~6 tháng) hoặc bar 1-phút (~2 giờ).
    - ``z_threshold`` 3.0: giữ tinh thần "3-sigma" của đặc tả gốc.
    - ``anomaly_contamination`` 0.05: kỳ vọng ~5% phiên bất thường trong lịch sử mã đó.
    - ``streak_min_bars`` 2: số bar liền kề cùng chiều tối thiểu để gom "super volume".
    - ``min_rows`` 30: dưới ngưỡng này không đủ tin cậy để chạy Z-score / Isolation Forest.
    """

    z_threshold: float = 3.0
    rolling_window: int = 120
    anomaly_contamination: float = 0.05
    streak_min_bars: int = 2
    min_rows: int = 30
    imbalance_ratio: float = 3.0


@dataclass(frozen=True)
class FlowSignal:
    """Hợp đồng output — tương thích đặc tả TickFlowAnalyzer.

    Các field mở rộng (B1/B3) đều có default ⇒ backward-compatible với
    journal JSONL cũ và caller dùng FlowSignal(...) chỉ với field cốt lõi.
    """

    symbol: str
    timeframe: str
    is_big_boy: bool
    aggregated_volume: float
    delta_status: DeltaStatus
    intensity_score: float
    z_volume: float
    pseudo_delta: float
    cumulative_delta: float
    anomaly_score: float
    last_close: float
    last_volume: float
    context_note: str
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    data_quality: str = "ok"
    # B3 — Buy/Sell imbalance lộ ra ngoài (thay vì chôn trong reasons).
    buy_sell_ratio: float = 1.0
    imbalance_direction: str = "balanced"
    # B1 — Technical context (kháng cự / hỗ trợ).
    resistance_level: float = 0.0
    support_level: float = 0.0
    price_position_pct: float = 50.0
    near_resistance: bool = False
    near_support: bool = False
    distance_to_resistance_pct: float = 0.0
    distance_to_support_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "is_big_boy": bool(self.is_big_boy),
            "aggregated_volume": float(self.aggregated_volume),
            "delta_status": self.delta_status,
            "intensity_score": round(float(self.intensity_score), 2),
            "z_volume": round(float(self.z_volume), 3),
            "pseudo_delta": round(float(self.pseudo_delta), 4),
            "cumulative_delta": round(float(self.cumulative_delta), 2),
            "anomaly_score": round(float(self.anomaly_score), 4),
            "last_close": round(float(self.last_close), 4),
            "last_volume": round(float(self.last_volume), 2),
            "context_note": self.context_note,
            "reasons": list(self.reasons),
            "risks": list(self.risks),
            "data_quality": self.data_quality,
            "buy_sell_ratio": round(float(self.buy_sell_ratio), 3),
            "imbalance_direction": str(self.imbalance_direction),
            "resistance_level": round(float(self.resistance_level), 4),
            "support_level": round(float(self.support_level), 4),
            "price_position_pct": round(float(self.price_position_pct), 2),
            "near_resistance": bool(self.near_resistance),
            "near_support": bool(self.near_support),
            "distance_to_resistance_pct": round(float(self.distance_to_resistance_pct), 2),
            "distance_to_support_pct": round(float(self.distance_to_support_pct), 2),
        }


def _validate_ohlcv(df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    if df is None or len(df) == 0:
        raise IntradayFlowError("OHLCV trống.")
    miss = [c for c in _REQUIRED_COLS if c not in df.columns]
    if miss:
        raise IntradayFlowError(f"Thiếu cột OHLCV bắt buộc: {', '.join(miss)}")
    out = df.copy()
    for col in _REQUIRED_COLS:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out = out.dropna(subset=list(_REQUIRED_COLS)).reset_index(drop=True)
    if len(out) < min_rows:
        raise IntradayFlowError(
            f"Không đủ dữ liệu: cần >= {min_rows} bar, hiện có {len(out)}."
        )
    return out


def compute_pseudo_delta(row: pd.Series) -> float:
    """Pseudo-delta theo tick rule áp dụng cho bar.

    Quy ước:
    - Nếu close gần high của bar ⇒ áp lực mua chủ động (delta > 0).
    - Nếu close gần low của bar ⇒ áp lực bán chủ động (delta < 0).
    - Khoảng giá trị: [-1.0, +1.0].

    Đây là proxy khi không có tick thật/L2 — sẽ được thay bằng delta thực
    (lệnh khớp tại Ask vs Bid) ở Tier 3.
    """
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    if high <= low:
        return 0.0
    position = (close - low) / (high - low)
    return float((position - 0.5) * 2.0)


def compute_dynamic_z(volumes: pd.Series, window: int) -> pd.Series:
    """Z-score trượt với cửa sổ ``window`` — thay ngưỡng cứng "1 tỷ VND".

    ``min_periods`` ~25% cửa sổ để vẫn cho ra giá trị sớm trong lịch sử mã mới.
    """
    if window < 5:
        raise IntradayFlowError("rolling_window phải >= 5.")
    min_periods = max(5, window // 4)
    mu = volumes.rolling(window, min_periods=min_periods).mean()
    sigma = volumes.rolling(window, min_periods=min_periods).std(ddof=0)
    z = (volumes - mu) / sigma.replace(0, np.nan)
    return z.fillna(0.0).astype(float)


def aggregate_super_bars(df: pd.DataFrame, *, streak_min_bars: int = 2) -> pd.DataFrame:
    """Gom các bar liên tiếp cùng chiều pseudo_delta thành "super bar".

    Cột mới:
    - ``direction`` ∈ {-1, 0, +1}
    - ``streak_id``: ID streak cùng chiều
    - ``streak_len``: số bar trong streak
    - ``super_volume``: tổng volume trong streak (chỉ điền với streak >= ``streak_min_bars``)

    Đây là proxy cho VWAP/TWAP slicing: tạo lập chia lệnh lớn thành nhiều lệnh
    nhỏ cùng chiều ở các bar gần nhau ⇒ nếu không gom lại sẽ bỏ lỡ dấu vết.
    """
    out = df.copy()
    if "pseudo_delta" not in out.columns:
        out["pseudo_delta"] = out.apply(compute_pseudo_delta, axis=1)
    out["direction"] = np.sign(out["pseudo_delta"]).astype(int)
    streak_break = (out["direction"] != out["direction"].shift()).fillna(True)
    out["streak_id"] = streak_break.cumsum().astype(int)
    grouped = out.groupby("streak_id")
    out["streak_len"] = grouped["volume"].transform("count").astype(int)
    out["super_volume"] = grouped["volume"].transform("sum").astype(float)
    weak = out["streak_len"] < int(max(1, streak_min_bars))
    out.loc[weak, "super_volume"] = out.loc[weak, "volume"]
    return out


class BatchAnomalyScorer:
    """Fit Isolation Forest once on pooled universe features; score per symbol."""

    def __init__(self) -> None:
        self._model: Any | None = None

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    def fit(self, feature_frames: list[pd.DataFrame], *, contamination: float) -> bool:
        parts: list[pd.DataFrame] = []
        for feat in feature_frames:
            if feat is None or feat.empty:
                continue
            parts.append(feat)
        if not parts:
            self._model = None
            return False
        combined = pd.concat(parts, axis=0, ignore_index=True)
        if len(combined) < 50:
            self._model = None
            return False
        try:
            from sklearn.ensemble import IsolationForest
        except Exception:
            self._model = None
            return False
        contam = float(min(0.45, max(0.005, contamination)))
        model = IsolationForest(
            n_estimators=100,
            contamination=contam,
            random_state=42,
            n_jobs=1,
        )
        arr = combined.to_numpy(dtype=float, copy=False)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        model.fit(arr)
        self._model = model
        return True

    def score(self, features: pd.DataFrame) -> pd.Series:
        if (
            self._model is None
            or features is None
            or features.empty
            or len(features) < 50
        ):
            n = len(features) if features is not None else 0
            return pd.Series([0.0] * n, index=getattr(features, "index", None))
        arr = features.to_numpy(dtype=float, copy=False)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        scores = self._model.score_samples(arr)
        return pd.Series(scores, index=features.index, dtype=float)


def detect_volume_anomalies(features: pd.DataFrame, contamination: float) -> pd.Series:
    """Fit + score on a single feature matrix (single-symbol path)."""
    scorer = BatchAnomalyScorer()
    scorer.fit([features], contamination=contamination)
    return scorer.score(features)


def _classify_delta_status(
    *,
    pseudo_delta: float,
    z_volume: float,
    return_pct: float,
    cumulative_delta: float,
) -> DeltaStatus:
    """Phân loại trạng thái dòng tiền tại bar hiện tại.

    - ``absorption``: volume cao bất thường nhưng giá ít thay đổi và delta ~0
      (lực bán bị hấp thụ — đặc trưng pha tích lũy cạn kiệt).
    - ``distribution``: volume cao + giá giảm + delta âm rõ.
    - ``bullish``: delta + cumulative_delta đều dương rõ.
    - ``bearish``: delta + cumulative_delta đều âm rõ.
    - ``neutral``: còn lại.
    """
    abs_delta = abs(pseudo_delta)
    if z_volume >= 1.5 and abs_delta < 0.15 and abs(return_pct) < 0.5:
        return "absorption"
    if z_volume >= 1.2 and return_pct < -0.4 and pseudo_delta < -0.15:
        return "distribution"
    if pseudo_delta > 0.2 and cumulative_delta > 0:
        return "bullish"
    if pseudo_delta < -0.2 and cumulative_delta < 0:
        return "bearish"
    return "neutral"


def _score_intensity(
    *,
    z_volume: float,
    anomaly_score: float,
    pseudo_delta: float,
    streak_len: int,
) -> float:
    """Map các tín hiệu thô về thang 1-10 (khẩn trương)."""
    z_component = min(4.0, max(0.0, (abs(z_volume) - 1.0) / 1.5 * 2.0))
    anomaly_component = min(3.0, max(0.0, -float(anomaly_score) * 6.0))
    delta_component = min(2.0, abs(float(pseudo_delta)) * 2.0)
    streak_component = min(1.0, max(0.0, (int(streak_len) - 1) * 0.5))
    raw = 1.0 + z_component + anomaly_component + delta_component + streak_component
    return float(min(10.0, max(1.0, raw)))


def _build_features_for_anomaly(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "z_volume": df["z_volume"].astype(float),
            "abs_delta": df["pseudo_delta"].abs().astype(float),
            "return_pct": df["return_pct"].astype(float),
            "log_volume": np.log1p(df["volume"].clip(lower=0.0).astype(float)),
        },
        index=df.index,
    )


def compute_price_context(
    df: pd.DataFrame,
    last_close: float,
    *,
    window: int = 60,
    near_threshold_pct: float = 2.0,
) -> dict[str, Any]:
    """Tính kháng cự / hỗ trợ từ rolling high/low + vị trí giá hiện tại.

    Window 60 bar: trên daily ≈ 3 tháng, trên 5min ≈ 5 giờ. Đủ ổn để gọi
    là "vùng" thay vì noise nhất thời.

    Returns dict gồm:
    - ``resistance_level`` / ``support_level``: giá tuyệt đối.
    - ``price_position_pct``: vị trí close trong dải support→resistance, 0..100.
    - ``near_resistance`` / ``near_support``: bool — true khi pos ≥85% / ≤15%
      hoặc khoảng cách giá ≤ ``near_threshold_pct``.
    - ``distance_to_resistance_pct`` / ``distance_to_support_pct``: %% so với close.
    """
    if df is None or len(df) < 5 or last_close <= 0:
        return {
            "resistance_level": 0.0,
            "support_level": 0.0,
            "price_position_pct": 50.0,
            "near_resistance": False,
            "near_support": False,
            "distance_to_resistance_pct": 0.0,
            "distance_to_support_pct": 0.0,
        }
    w = min(int(max(5, window)), len(df))
    tail = df.tail(w)
    resistance = float(tail["high"].max())
    support = float(tail["low"].min())
    if resistance <= 0 or support <= 0 or resistance <= support:
        return {
            "resistance_level": float(max(0.0, resistance)),
            "support_level": float(max(0.0, support)),
            "price_position_pct": 50.0,
            "near_resistance": False,
            "near_support": False,
            "distance_to_resistance_pct": 0.0,
            "distance_to_support_pct": 0.0,
        }
    rng = resistance - support
    pos_pct = max(0.0, min(100.0, (last_close - support) / rng * 100.0))
    dist_res_pct = (resistance - last_close) / last_close * 100.0
    dist_sup_pct = (last_close - support) / last_close * 100.0
    threshold = float(max(0.0, near_threshold_pct))
    near_res = pos_pct >= 85.0 or (dist_res_pct >= 0 and dist_res_pct <= threshold)
    near_sup = pos_pct <= 15.0 or (dist_sup_pct >= 0 and dist_sup_pct <= threshold)
    return {
        "resistance_level": float(resistance),
        "support_level": float(support),
        "price_position_pct": float(pos_pct),
        "near_resistance": bool(near_res),
        "near_support": bool(near_sup),
        "distance_to_resistance_pct": float(dist_res_pct),
        "distance_to_support_pct": float(dist_sup_pct),
    }


def compute_buy_sell_ratio(df: pd.DataFrame, window: int) -> dict[str, Any]:
    """Tỷ lệ volume mua chủ động / bán chủ động trên cửa sổ cuối.

    Yêu cầu DataFrame đã có cột ``pseudo_delta`` (sẽ tự build nếu thiếu).

    Returns dict:
    - ``buy_volume`` / ``sell_volume``: tổng volume từng phía.
    - ``buy_sell_ratio``: buy/sell (clip 999.0 để tránh inf khi sell=0).
    - ``imbalance_direction``: ``buy_dominant`` / ``sell_dominant`` / ``balanced``.
    """
    if df is None or df.empty:
        return {
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "buy_sell_ratio": 1.0,
            "imbalance_direction": "balanced",
        }
    work = df.copy()
    if "pseudo_delta" not in work.columns:
        work["pseudo_delta"] = work.apply(compute_pseudo_delta, axis=1)
    w = int(max(10, window))
    tail = work.tail(w)
    buy_vol = float(tail.loc[tail["pseudo_delta"] > 0, "volume"].sum())
    sell_vol = float(tail.loc[tail["pseudo_delta"] < 0, "volume"].sum())
    if buy_vol <= 0 and sell_vol <= 0:
        return {
            "buy_volume": 0.0,
            "sell_volume": 0.0,
            "buy_sell_ratio": 1.0,
            "imbalance_direction": "balanced",
        }
    if sell_vol <= 0:
        return {
            "buy_volume": buy_vol,
            "sell_volume": 0.0,
            "buy_sell_ratio": 999.0,
            "imbalance_direction": "buy_dominant",
        }
    if buy_vol <= 0:
        return {
            "buy_volume": 0.0,
            "sell_volume": sell_vol,
            "buy_sell_ratio": 0.0,
            "imbalance_direction": "sell_dominant",
        }
    ratio = buy_vol / sell_vol
    direction = "balanced"
    if ratio >= 3.0:
        direction = "buy_dominant"
    elif sell_vol / buy_vol >= 3.0:
        direction = "sell_dominant"
    return {
        "buy_volume": buy_vol,
        "sell_volume": sell_vol,
        "buy_sell_ratio": float(ratio),
        "imbalance_direction": direction,
    }


def apply_context_intensity_adjustment(
    intensity: float,
    *,
    delta_status: str,
    near_resistance: bool,
    near_support: bool,
) -> tuple[float, list[str], list[str]]:
    """Adjust intensity dựa trên vị trí giá so với kháng cự / hỗ trợ.

    Triết lý (matchen yêu cầu gốc của user về Contextual Overlay):
    - Bullish gần KHÁNG CỰ ⇒ **giảm** (có thể là bull-trap / xả hàng).
    - Bullish gần HỖ TRỢ ⇒ **boost** (pattern tích lũy chuẩn).
    - Bearish gần HỖ TRỢ ⇒ **giảm** (false breakdown phổ biến).
    - Absorption gần HỖ TRỢ ⇒ **boost mạnh** (lực bán cạn ngay đáy).

    Returns ``(intensity_mới, reasons_thêm, risks_thêm)``.
    """
    extra_reasons: list[str] = []
    extra_risks: list[str] = []
    out = float(intensity)
    status = str(delta_status or "").lower()

    if status == "bullish" and near_resistance:
        capped = min(out, 7.0)
        if capped < out - 1e-6:
            extra_risks.append(
                f"Intensity {out:.1f} → {capped:.1f}: bullish sát kháng cự — rủi ro bull trap."
            )
            out = capped
    elif status == "bullish" and near_support:
        boosted = min(10.0, out * 1.1)
        if boosted > out + 1e-6:
            extra_reasons.append(
                f"Intensity {out:.1f} → {boosted:.1f}: bullish sát hỗ trợ — pattern tích lũy."
            )
            out = boosted
    elif status == "bearish" and near_support:
        capped = min(out, 7.0)
        if capped < out - 1e-6:
            extra_risks.append(
                f"Intensity {out:.1f} → {capped:.1f}: bearish sát hỗ trợ — có thể false breakdown."
            )
            out = capped
    elif status == "absorption" and near_support:
        boosted = min(10.0, out * 1.15)
        if boosted > out + 1e-6:
            extra_reasons.append(
                f"Intensity {out:.1f} → {boosted:.1f}: absorption sát hỗ trợ — lực bán cạn ngay đáy."
            )
            out = boosted
    elif status == "distribution" and near_resistance:
        boosted = min(10.0, out * 1.15)
        if boosted > out + 1e-6:
            extra_risks.append(
                f"Intensity {out:.1f} → {boosted:.1f}: distribution sát kháng cự — phân phối đỉnh."
            )
            out = boosted

    return out, extra_reasons, extra_risks


def _context_note(
    *,
    last_close: float,
    df: pd.DataFrame,
    context: dict[str, Any] | None,
) -> str:
    """Lớp Contextual Overlay — vị trí giá so với kháng cự/hỗ trợ + ghi chú ngành.

    Nhằm tránh giải thích thiếu ngữ cảnh: "Big Boy" ở đỉnh kháng cự rất khác
    "Big Boy" ở vùng tích lũy cạn kiệt.
    """
    notes: list[str] = []
    if last_close > 0 and len(df) >= 20:
        recent_high = float(df["high"].tail(20).max())
        recent_low = float(df["low"].tail(20).min())
        rng = recent_high - recent_low
        if rng > 0:
            position = (last_close - recent_low) / rng
            if position >= 0.85:
                notes.append("gần kháng cự ngắn hạn (90% biên độ 20 bar)")
            elif position <= 0.15:
                notes.append("gần hỗ trợ ngắn hạn (10% biên độ 20 bar)")
            else:
                notes.append(f"vị trí ~{position * 100:.0f}% biên độ 20 bar")
    if context:
        subtype = str(context.get("industry_subtype") or "").strip()
        if subtype:
            notes.append(f"ngành: {subtype}")
        sector_flow = context.get("sector_flow_bias")
        if sector_flow:
            notes.append(f"dòng tiền ngành: {sector_flow}")
    return "; ".join(notes) if notes else "không có ngữ cảnh bổ sung"


def _prepare_flow_frame(ohlcv: pd.DataFrame, cfg: FlowConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build flow features without fitting anomaly model."""
    df = _validate_ohlcv(ohlcv, min_rows=cfg.min_rows)
    df["pseudo_delta"] = df.apply(compute_pseudo_delta, axis=1)
    df["z_volume"] = compute_dynamic_z(df["volume"], window=cfg.rolling_window)
    df["return_pct"] = (df["close"].pct_change() * 100.0).fillna(0.0).astype(float)
    df["delta_volume"] = (df["pseudo_delta"] * df["volume"]).astype(float)
    df["cumulative_delta"] = df["delta_volume"].cumsum().astype(float)
    df = aggregate_super_bars(df, streak_min_bars=cfg.streak_min_bars)
    features = _build_features_for_anomaly(df)
    return df, features


def _flow_signal_from_df(
    df: pd.DataFrame,
    sym: str,
    *,
    cfg: FlowConfig,
    context: dict[str, Any] | None,
    timeframe: str,
) -> FlowSignal:
    last = df.iloc[-1]
    z_volume = float(last["z_volume"])
    pseudo_delta = float(last["pseudo_delta"])
    cumulative_delta = float(last["cumulative_delta"])
    anomaly_score = float(last["anomaly_score"])
    return_pct = float(last["return_pct"])
    streak_len = int(last["streak_len"])
    super_volume = float(last["super_volume"])
    last_close = float(last["close"])
    last_volume = float(last["volume"])

    delta_status = _classify_delta_status(
        pseudo_delta=pseudo_delta,
        z_volume=z_volume,
        return_pct=return_pct,
        cumulative_delta=cumulative_delta,
    )

    bs = compute_buy_sell_ratio(df, window=cfg.rolling_window)
    buy_vol = float(bs["buy_volume"])
    sell_vol = float(bs["sell_volume"])
    buy_sell_ratio = float(bs["buy_sell_ratio"])
    imbalance_dir = str(bs["imbalance_direction"])
    imbalance_alert = (
        (sell_vol > 0 and buy_sell_ratio >= cfg.imbalance_ratio)
        or (buy_vol > 0 and sell_vol > 0 and (sell_vol / buy_vol) >= cfg.imbalance_ratio)
    )
    if imbalance_alert and imbalance_dir == "balanced":
        imbalance_dir = (
            "buy_dominant"
            if (sell_vol > 0 and buy_sell_ratio >= cfg.imbalance_ratio)
            else "sell_dominant"
        )

    intensity = _score_intensity(
        z_volume=z_volume,
        anomaly_score=anomaly_score,
        pseudo_delta=pseudo_delta,
        streak_len=streak_len,
    )

    price_ctx = compute_price_context(df, last_close=last_close, window=cfg.rolling_window)

    intensity_adj, ctx_reasons, ctx_risks = apply_context_intensity_adjustment(
        intensity,
        delta_status=str(delta_status),
        near_resistance=bool(price_ctx["near_resistance"]),
        near_support=bool(price_ctx["near_support"]),
    )

    z_signal = abs(z_volume) >= cfg.z_threshold
    anomaly_signal = anomaly_score <= -0.05 and abs(pseudo_delta) >= 0.1
    streak_signal = streak_len >= max(3, cfg.streak_min_bars + 1) and abs(pseudo_delta) >= 0.15
    is_big_boy = bool(z_signal or anomaly_signal or (streak_signal and z_volume >= 1.5))

    reasons: list[str] = []
    risks: list[str] = []
    if z_signal:
        reasons.append(f"Volume Z-score = {z_volume:+.2f}σ (vượt {cfg.z_threshold:.1f}σ).")
    if anomaly_signal:
        reasons.append(
            f"Isolation Forest đánh dấu bất thường (score={anomaly_score:.3f}) kèm delta {pseudo_delta:+.2f}."
        )
    if streak_signal:
        reasons.append(
            f"Chuỗi {streak_len} bar liên tiếp cùng chiều, super_volume={super_volume:,.0f}."
        )
    if imbalance_alert:
        reasons.append(
            f"Imbalance {imbalance_dir} (tỷ lệ buy/sell={buy_sell_ratio:.2f}x trên {cfg.rolling_window} bar gần nhất)."
        )
    if delta_status == "absorption":
        reasons.append("Volume cao nhưng giá đi ngang ⇒ lực bán bị hấp thụ (proxy pha tích lũy cạn kiệt).")
    if delta_status == "distribution":
        risks.append("Volume cao + giá giảm + delta âm ⇒ rủi ro phân phối.")
    reasons.extend(ctx_reasons)
    risks.extend(ctx_risks)

    note = _context_note(last_close=last_close, df=df, context=context)
    if (
        "kháng cự" in note
        and delta_status in ("bullish", "absorption")
        and not any("bull trap" in r.lower() for r in risks)
    ):
        risks.append(
            "Tín hiệu mua xuất hiện sát vùng kháng cự — cần cảnh giác bull trap, đợi xác nhận breakout."
        )

    data_quality = "partial" if len(df) < max(cfg.rolling_window // 2, 60) else "ok"

    return FlowSignal(
        symbol=sym,
        timeframe=str(timeframe or "1D"),
        is_big_boy=is_big_boy,
        aggregated_volume=float(super_volume),
        delta_status=delta_status,
        intensity_score=round(intensity_adj, 2),
        z_volume=z_volume,
        pseudo_delta=pseudo_delta,
        cumulative_delta=cumulative_delta,
        anomaly_score=anomaly_score,
        last_close=last_close,
        last_volume=last_volume,
        context_note=note,
        reasons=reasons,
        risks=risks,
        data_quality=data_quality,
        buy_sell_ratio=round(float(buy_sell_ratio), 3),
        imbalance_direction=str(imbalance_dir),
        resistance_level=float(price_ctx["resistance_level"]),
        support_level=float(price_ctx["support_level"]),
        price_position_pct=float(price_ctx["price_position_pct"]),
        near_resistance=bool(price_ctx["near_resistance"]),
        near_support=bool(price_ctx["near_support"]),
        distance_to_resistance_pct=float(price_ctx["distance_to_resistance_pct"]),
        distance_to_support_pct=float(price_ctx["distance_to_support_pct"]),
    )


def analyze_flow(
    ohlcv: pd.DataFrame,
    symbol: str,
    *,
    config: FlowConfig | None = None,
    context: dict[str, Any] | None = None,
    timeframe: str = "1D",
) -> FlowSignal:
    """Phân tích dòng tiền cho 1 mã trên một khung thời gian bất kỳ.

    Trả về ``FlowSignal`` chứa đủ trường theo đặc tả gốc của TickFlowAnalyzer.
    """
    cfg = config or FlowConfig()
    sym = str(symbol or "").strip().upper() or "UNKNOWN"
    df, features = _prepare_flow_frame(ohlcv, cfg)
    df = df.copy()
    df["anomaly_score"] = detect_volume_anomalies(features, contamination=cfg.anomaly_contamination)
    return _flow_signal_from_df(df, sym, cfg=cfg, context=context, timeframe=timeframe)


def batch_analyze_flow(
    frames: dict[str, pd.DataFrame],
    *,
    config: FlowConfig | None = None,
    contexts: dict[str, dict[str, Any]] | None = None,
    timeframe: str = "1D",
) -> dict[str, FlowSignal]:
    """Phân tích hàng loạt — sentinel giữ kết quả lỗi cục bộ thay vì hủy cả lô.

    Mã nào lỗi sẽ bị bỏ qua trong dict trả về; caller có thể đối chiếu với keys
    của ``frames`` để biết mã nào không đủ dữ liệu.
    """
    cfg = config or FlowConfig()
    prepared: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for sym, df in (frames or {}).items():
        try:
            prepared[str(sym).strip().upper()] = _prepare_flow_frame(df, cfg)
        except IntradayFlowError:
            continue

    scorer = BatchAnomalyScorer()
    scorer.fit([feat for _, feat in prepared.values()], contamination=cfg.anomaly_contamination)

    out: dict[str, FlowSignal] = {}
    for sym, (df_raw, features) in prepared.items():
        try:
            df = df_raw.copy()
            if scorer.is_fitted:
                df["anomaly_score"] = scorer.score(features)
            else:
                df["anomaly_score"] = detect_volume_anomalies(
                    features, contamination=cfg.anomaly_contamination
                )
            ctx = (contexts or {}).get(sym)
            out[sym] = _flow_signal_from_df(
                df, sym, cfg=cfg, context=ctx, timeframe=timeframe
            )
        except IntradayFlowError:
            continue
    return out


def _extract_sector_from_note(note: str) -> str:
    """Helper: parse 'ngành: X' segment khỏi context_note."""
    for token in str(note or "").split(";"):
        token = token.strip()
        if token.startswith("ngành:"):
            return token.split(":", 1)[1].strip()
    return ""


def _resolve_sector_for_symbol(
    sym: str,
    *,
    contexts: dict[str, dict[str, Any]] | None,
    signal: FlowSignal | None = None,
) -> str:
    """Ưu tiên context['industry_subtype'] → fallback parse context_note."""
    if contexts:
        ctx = contexts.get(sym) or {}
        sub = str(ctx.get("industry_subtype") or "").strip()
        if sub:
            return sub
    if signal is not None:
        return _extract_sector_from_note(signal.context_note)
    return ""


def apply_sector_intensity_adjustment(
    intensity: float,
    *,
    delta_status: str,
    sector_net_intensity: float,
    sector_member_count: int,
    alignment_boost: float = 1.10,
    divergence_penalty: float = 0.85,
    min_members_for_signal: int = 3,
    bias_threshold: float = 2.0,
) -> tuple[float, list[str], list[str]]:
    """Adjust intensity dựa trên bias dòng tiền của cả ngành.

    Triết lý (đặc tả gốc của user):
    - Một mã lẻ loi nhận flow lớn ngược chiều ngành ⇒ có thể là "quỹ cơ cấu"
      hoặc "tay chơi đơn lẻ", không phải sóng ngành thật ⇒ **penalty**.
    - Symbol cùng chiều với ngành (sector bias mạnh) ⇒ **boost** (sóng ngành).
    - Ngành quá ít mã (< ``min_members_for_signal``) ⇒ skip để tránh noise.

    Args:
        intensity: intensity_score hiện tại của symbol (1-10).
        delta_status: trạng thái flow của symbol.
        sector_net_intensity: net (bullish + absorption − bearish − distribution)
            của ngành, từ ``sector_flow_bias``.
        sector_member_count: số symbol trong ngành đã có signal.
        alignment_boost: hệ số nhân khi cùng chiều ngành (mặc định 1.10).
        divergence_penalty: hệ số nhân khi ngược chiều ngành (mặc định 0.85).
        min_members_for_signal: ngưỡng tối thiểu để xét bias ngành.
        bias_threshold: |net_intensity| tối thiểu để xem ngành "có bias rõ".

    Returns:
        Tuple ``(intensity_mới, reasons_thêm, risks_thêm)``.
    """
    extra_reasons: list[str] = []
    extra_risks: list[str] = []
    out = float(intensity)
    if sector_member_count < int(min_members_for_signal):
        return out, extra_reasons, extra_risks
    if abs(sector_net_intensity) < float(bias_threshold):
        return out, extra_reasons, extra_risks

    sector_bullish = sector_net_intensity > 0
    sector_bearish = sector_net_intensity < 0
    status = str(delta_status or "").lower()

    if status in ("bullish", "absorption") and sector_bullish:
        boosted = min(10.0, out * float(alignment_boost))
        if boosted > out + 1e-6:
            extra_reasons.append(
                f"Intensity {out:.1f} → {boosted:.1f}: cùng chiều dòng tiền ngành "
                f"(net {sector_net_intensity:+.1f}, {sector_member_count} mã)."
            )
            out = boosted
    elif status in ("bearish", "distribution") and sector_bearish:
        boosted = min(10.0, out * float(alignment_boost))
        if boosted > out + 1e-6:
            extra_risks.append(
                f"Intensity {out:.1f} → {boosted:.1f}: cùng chiều bias bán của ngành "
                f"(net {sector_net_intensity:+.1f}, {sector_member_count} mã)."
            )
            out = boosted
    elif status in ("bullish", "absorption") and sector_bearish:
        reduced = max(1.0, out * float(divergence_penalty))
        if reduced < out - 1e-6:
            extra_risks.append(
                f"Intensity {out:.1f} → {reduced:.1f}: bullish đơn lẻ trong ngành "
                f"đang bearish (net {sector_net_intensity:+.1f}) — có thể là quỹ cơ cấu, không phải sóng ngành."
            )
            out = reduced
    elif status in ("bearish", "distribution") and sector_bullish:
        reduced = max(1.0, out * float(divergence_penalty))
        if reduced < out - 1e-6:
            extra_reasons.append(
                f"Intensity {out:.1f} → {reduced:.1f}: bearish đơn lẻ trong ngành "
                f"đang bullish (net {sector_net_intensity:+.1f}) — ít có khả năng sóng phân phối ngành."
            )
            out = reduced

    return out, extra_reasons, extra_risks


def adjust_signals_with_sector_context(
    signals: dict[str, FlowSignal],
    *,
    contexts: dict[str, dict[str, Any]] | None = None,
    alignment_boost: float = 1.10,
    divergence_penalty: float = 0.85,
    min_members_for_signal: int = 3,
    bias_threshold: float = 2.0,
) -> dict[str, FlowSignal]:
    """Áp sector adjustment lên dict signals **đã có** (không re-analyze).

    Dùng được cả ở orchestrator hai-pass lẫn ở cycle background đã có sẵn
    signals từ vòng lặp per-symbol — tránh chạy ``analyze_flow`` lần 2.

    Quy trình:
    1. Tính ``sector_flow_bias`` trên signals.
    2. Đếm số member per-sector (từ contexts hoặc parse context_note).
    3. Với mỗi signal: lookup sector → áp ``apply_sector_intensity_adjustment``.

    Idempotent: gọi 2 lần với cùng input → cùng output.
    """
    if not signals:
        return signals

    bias_payload = sector_flow_bias(signals)
    sector_stats: dict[str, dict[str, Any]] = {}
    member_counts: dict[str, int] = {}

    for sym, sig in signals.items():
        sector = _resolve_sector_for_symbol(sym, contexts=contexts, signal=sig)
        if sector:
            member_counts[sector] = member_counts.get(sector, 0) + 1

    for entry in bias_payload.get("sectors", []):
        sector = str(entry.get("sector") or "")
        if not sector:
            continue
        sector_stats[sector] = {
            "net_intensity": float(entry.get("net_intensity") or 0.0),
            "members": int(member_counts.get(sector, 0)),
        }

    adjusted: dict[str, FlowSignal] = {}
    for sym, sig in signals.items():
        sector = _resolve_sector_for_symbol(sym, contexts=contexts, signal=sig)
        stats = sector_stats.get(sector) if sector else None
        if not stats:
            adjusted[sym] = sig
            continue
        new_intensity, extra_reasons, extra_risks = apply_sector_intensity_adjustment(
            sig.intensity_score,
            delta_status=str(sig.delta_status),
            sector_net_intensity=float(stats["net_intensity"]),
            sector_member_count=int(stats["members"]),
            alignment_boost=alignment_boost,
            divergence_penalty=divergence_penalty,
            min_members_for_signal=min_members_for_signal,
            bias_threshold=bias_threshold,
        )
        if abs(new_intensity - sig.intensity_score) < 1e-6:
            adjusted[sym] = sig
            continue
        adjusted[sym] = replace(
            sig,
            intensity_score=round(float(new_intensity), 2),
            reasons=list(sig.reasons) + extra_reasons,
            risks=list(sig.risks) + extra_risks,
        )
    return adjusted


def batch_analyze_flow_with_sector_context(
    frames: dict[str, pd.DataFrame],
    *,
    contexts: dict[str, dict[str, Any]] | None = None,
    config: FlowConfig | None = None,
    timeframe: str = "1D",
    alignment_boost: float = 1.10,
    divergence_penalty: float = 0.85,
    min_members_for_signal: int = 3,
    bias_threshold: float = 2.0,
) -> dict[str, FlowSignal]:
    """Two-pass orchestrator: bắt sóng ngành & loại "lẻ loi cơ cấu".

    Wrapper tiện lợi: phân tích từ frames + áp sector adjustment trong cùng
    một call. Nếu caller đã có signals (vd. background cycle), nên gọi
    ``adjust_signals_with_sector_context`` để tránh re-analyze.
    """
    first_pass = batch_analyze_flow(frames, config=config, contexts=contexts, timeframe=timeframe)
    return adjust_signals_with_sector_context(
        first_pass,
        contexts=contexts,
        alignment_boost=alignment_boost,
        divergence_penalty=divergence_penalty,
        min_members_for_signal=min_members_for_signal,
        bias_threshold=bias_threshold,
    )


def sector_flow_bias(signals: dict[str, FlowSignal]) -> dict[str, Any]:
    """Tổng hợp dòng tiền theo ngành để phục vụ Contextual Overlay.

    Trả về dict {industry_subtype: {bullish: n, bearish: n, ...}} + xếp hạng ngành
    bias mua / bán dựa trên intensity_score tổng.
    """
    by_sector: dict[str, dict[str, float]] = {}
    for sig in signals.values():
        sector = ""
        for token in sig.context_note.split(";"):
            token = token.strip()
            if token.startswith("ngành:"):
                sector = token.split(":", 1)[1].strip()
                break
        if not sector:
            continue
        bucket = by_sector.setdefault(
            sector,
            {"bullish": 0.0, "bearish": 0.0, "absorption": 0.0, "distribution": 0.0, "neutral": 0.0},
        )
        bucket[sig.delta_status] = bucket.get(sig.delta_status, 0.0) + float(sig.intensity_score)
    ranked: list[dict[str, Any]] = []
    for sector, bucket in by_sector.items():
        net = float(bucket.get("bullish", 0.0)) + float(bucket.get("absorption", 0.0)) - float(
            bucket.get("bearish", 0.0)
        ) - float(bucket.get("distribution", 0.0))
        ranked.append({"sector": sector, "net_intensity": round(net, 2), "breakdown": bucket})
    ranked.sort(key=lambda r: r["net_intensity"], reverse=True)
    return {"sectors": ranked}


def screen_universe_for_flow(
    symbols: list[str],
    ohlcv_loader: Callable[[str], pd.DataFrame | None],
    *,
    config: FlowConfig | None = None,
    contexts: dict[str, dict[str, Any]] | None = None,
    timeframe: str = "1D",
    min_intensity: float = 5.0,
    only_big_boy: bool = False,
) -> pd.DataFrame:
    """Quét universe và trả bảng xếp hạng dòng tiền giảm dần theo intensity.

    Tham số ``ohlcv_loader`` là callable nhận symbol → DataFrame OHLCV (hoặc None).
    Caller có thể truyền cached loader (vd. ``analysis_runtime_service.load_ohlcv_cached``)
    hoặc bất cứ fetcher nào tuân hợp đồng — service này không tự gắn cache hay streamlit.

    Bảng đầu ra:
    - ``Mã``, ``Big Boy``, ``Trạng thái``, ``Intensity``, ``Z-Vol``, ``Pseudo Δ``,
      ``Cumulative Δ``, ``Aggregated Vol``, ``Bối cảnh``.
    """
    cfg = config or FlowConfig()
    frames: dict[str, pd.DataFrame] = {}
    for raw in symbols or []:
        sym = str(raw or "").strip().upper()
        if not sym or sym in frames:
            continue
        try:
            df = ohlcv_loader(sym)
        except Exception:
            continue
        if df is None or len(df) < cfg.min_rows:
            continue
        frames[sym] = df
    signals = batch_analyze_flow(frames, config=cfg, contexts=contexts, timeframe=timeframe)
    rows: list[dict[str, Any]] = []
    for sym, sig in signals.items():
        if only_big_boy and not sig.is_big_boy:
            continue
        if float(sig.intensity_score) < float(min_intensity):
            continue
        rows.append(
            {
                "Mã": sym,
                "Big Boy": "🐳" if sig.is_big_boy else "—",
                "Trạng thái": str(sig.delta_status),
                "Intensity": round(float(sig.intensity_score), 2),
                "Z-Vol": round(float(sig.z_volume), 2),
                "Pseudo Δ": round(float(sig.pseudo_delta), 3),
                "Cumulative Δ": round(float(sig.cumulative_delta), 0),
                "Aggregated Vol": int(round(float(sig.aggregated_volume))),
                "Bối cảnh": str(sig.context_note),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "Mã",
                "Big Boy",
                "Trạng thái",
                "Intensity",
                "Z-Vol",
                "Pseudo Δ",
                "Cumulative Δ",
                "Aggregated Vol",
                "Bối cảnh",
            ]
        )
    out = pd.DataFrame(rows)
    return out.sort_values(["Big Boy", "Intensity"], ascending=[False, False]).reset_index(drop=True)


__all__ = [
    "DeltaStatus",
    "FlowConfig",
    "FlowSignal",
    "IntradayFlowError",
    "adjust_signals_with_sector_context",
    "aggregate_super_bars",
    "analyze_flow",
    "apply_context_intensity_adjustment",
    "apply_sector_intensity_adjustment",
    "batch_analyze_flow",
    "batch_analyze_flow_with_sector_context",
    "compute_buy_sell_ratio",
    "compute_dynamic_z",
    "compute_price_context",
    "compute_pseudo_delta",
    "detect_volume_anomalies",
    "screen_universe_for_flow",
    "sector_flow_bias",
]
