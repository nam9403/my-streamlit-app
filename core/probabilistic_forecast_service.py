from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MonteCarloRange:
    p10_price: float
    p50_price: float
    p90_price: float
    expected_price: float
    prob_reach_target_pct: float
    simulations: int
    mu_annual: float
    sigma_annual: float


def estimate_gbm_mu_sigma(ohlcv: Any) -> tuple[float, float]:
    """
    Ước lượng mu và sigma hàng năm từ log-return lịch sử.
    """
    if ohlcv is None:
        return 0.12, 0.28
    if isinstance(ohlcv, pd.DataFrame):
        d = ohlcv.copy()
    elif isinstance(ohlcv, list):
        d = pd.DataFrame(ohlcv)
    elif isinstance(ohlcv, dict):
        d = pd.DataFrame([ohlcv])
    else:
        return 0.12, 0.28
    if d.empty or "close" not in d.columns:
        return 0.12, 0.28
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    if len(d) < 40:
        return 0.12, 0.28
    close = d["close"].to_numpy(dtype=float)
    log_ret = np.diff(np.log(close))
    if len(log_ret) < 20:
        return 0.12, 0.28
    mu_daily = float(np.mean(log_ret))
    sigma_daily = float(np.std(log_ret, ddof=1))
    mu_annual = mu_daily * 252.0
    sigma_annual = max(0.05, sigma_daily * np.sqrt(252.0))
    mu_annual = max(-0.5, min(0.8, mu_annual))
    sigma_annual = max(0.05, min(1.2, sigma_annual))
    return mu_annual, sigma_annual


def monte_carlo_forecast_range(
    *,
    s0: float,
    horizon_days: int,
    mu_annual: float,
    sigma_annual: float,
    simulations: int = 8000,
    target_price: float | None = None,
    random_seed: int = 42,
) -> MonteCarloRange | None:
    """
    GBM Monte Carlo theo công thức:
    S_t = S_0 * exp((mu - sigma^2/2)t + sigma*epsilon*sqrt(t))
    """
    if s0 <= 0 or horizon_days <= 0:
        return None
    n = max(1000, min(int(simulations), 50000))
    t = float(horizon_days) / 252.0
    rng = np.random.default_rng(seed=random_seed)
    eps = rng.normal(0.0, 1.0, n)
    st = s0 * np.exp((mu_annual - 0.5 * sigma_annual**2) * t + sigma_annual * eps * np.sqrt(t))
    p10 = float(np.percentile(st, 10))
    p50 = float(np.percentile(st, 50))
    p90 = float(np.percentile(st, 90))
    exp_px = float(np.mean(st))
    if target_price is None or target_price <= 0:
        target = s0
    else:
        target = float(target_price)
    prob_target = float(np.mean(st >= target) * 100.0)
    return MonteCarloRange(
        p10_price=round(p10, 2),
        p50_price=round(p50, 2),
        p90_price=round(p90, 2),
        expected_price=round(exp_px, 2),
        prob_reach_target_pct=round(prob_target, 2),
        simulations=n,
        mu_annual=round(float(mu_annual), 4),
        sigma_annual=round(float(sigma_annual), 4),
    )


def signal_alignment_summary(
    *,
    phase_name: str,
    f_score: int,
    mos_pct: float,
    news: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Đánh giá đồng thuận tín hiệu kỹ thuật/cơ bản/tin tức.
    """
    p = str(phase_name or "neutral").strip().lower()
    tech = 1 if p in ("breakout", "accumulation") else (-1 if p == "distribution" else 0)
    fund = 1 if (f_score >= 7 and mos_pct >= 8.0) else (-1 if (f_score <= 4 or mos_pct < 0) else 0)

    news_text = " ".join(str(x.get("title") or "") for x in (news or [])[:8]).lower()
    neg_kw = ("điều tra", "lỗ", "thua lỗ", "hủy niêm yết", "xử phạt", "nợ xấu", "phá sản")
    pos_kw = ("tăng trưởng", "mở rộng", "ký kết", "lợi nhuận tăng", "mua ròng")
    news_sig = 0
    if any(k in news_text for k in neg_kw):
        news_sig = -1
    elif any(k in news_text for k in pos_kw):
        news_sig = 1

    vals = [tech, fund, news_sig]
    pos = sum(1 for x in vals if x > 0)
    neg = sum(1 for x in vals if x < 0)
    if pos >= 2 and neg == 0:
        level = "high_alignment"
    elif neg >= 2 and pos == 0:
        level = "high_risk_conflict"
    elif pos > 0 and neg > 0:
        level = "mixed_conflict"
    else:
        level = "neutral"
    return {
        "technical_signal": tech,
        "fundamental_signal": fund,
        "news_signal": news_sig,
        "positive_count": pos,
        "negative_count": neg,
        "level": level,
        "stand_aside": level in ("high_risk_conflict", "mixed_conflict"),
    }
