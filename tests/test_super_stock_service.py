from __future__ import annotations

import pandas as pd

from core.super_stock_service import FundamentalScorer, Notifier, TechnicalAnalyzer


def test_detect_volume_breakout_positive_case() -> None:
    base_close = [100.0] * 20 + [104.5]
    base_vol = [1_000_000.0] * 20 + [1_800_000.0]
    df = pd.DataFrame(
        {
            "open": base_close,
            "high": base_close,
            "low": base_close,
            "close": base_close,
            "volume": base_vol,
        }
    )
    ok, vol_mult, chg = TechnicalAnalyzer().detect_volume_breakout(df)
    assert ok is True
    assert vol_mult >= 1.5
    assert chg >= 3.0


def test_fundamental_scorer_requires_three_conditions() -> None:
    scorer = FundamentalScorer(min_f_score=7, min_mos_pct=10.0)
    snapshot = {
        "symbol": "AAA",
        "price": 80,
        "eps": 5,
        "growth_rate_pct": 12,
        "book_value_per_share": 30,
        "piotroski": {"net_income": 1, "operating_cash_flow": 1},
    }
    signal = scorer.evaluate(
        "AAA",
        snapshot,
        breakout_ok=False,
        vol_mult=1.1,
        price_chg=1.2,
        rs_pct=2.5,
        rs_outperform=True,
        has_flat_base=True,
        has_vcp=False,
    )
    assert signal.passed is False
    assert "Chưa đủ điều kiện" in signal.note


def test_notifier_uses_telegram_credentials() -> None:
    sent_payload: dict[str, str] = {}

    def fake_load_secret(_user_id: str, name: str, _default: str = "") -> str:
        return "token_x" if name == "telegram_bot_token" else "chat_x"

    def fake_dispatch(text: str, **kwargs: str) -> dict[str, int]:
        sent_payload["text"] = text
        sent_payload["token"] = kwargs.get("telegram_bot_token", "")
        sent_payload["chat"] = kwargs.get("telegram_chat_id", "")
        return {"sent": 1, "failed": 0}

    notifier = Notifier(
        load_secret_func=fake_load_secret,
        dispatch_text_notifications_func=fake_dispatch,
        user_id="u1",
    )
    stat = notifier.notify_super_stock(
        signal=type(
            "S",
            (),
            {
                "symbol": "FPT",
                "f_score": 8,
                "mos_pct": 22.5,
                "is_volume_breakout": True,
                "relative_strength_pct": 5.0,
                "market_relative_outperform": True,
                "has_flat_base": True,
                "has_vcp": True,
                "volume_multiple": 1.8,
                "price_change_pct": 4.2,
                "red_flags": [],
                "note": "Đủ 3 điều kiện Siêu cổ phiếu.",
            },
        )()
    )
    assert stat["sent"] == 1
    assert sent_payload["token"] == "token_x"
    assert sent_payload["chat"] == "chat_x"
    assert "Super Stock Alert: FPT" in sent_payload["text"]


def test_relative_strength_outperform() -> None:
    ta = TechnicalAnalyzer()
    stock = pd.DataFrame({"close": [100, 101, 103, 106, 110], "volume": [1, 1, 1, 1, 1]})
    index = pd.DataFrame({"close": [100, 101, 101.5, 102, 103], "volume": [1, 1, 1, 1, 1]})
    rs, ok = ta.compute_relative_strength_vs_index(stock, index, lookback=4)
    assert rs > 0
    assert ok is True


def test_detect_flat_base_and_vcp() -> None:
    ta = TechnicalAnalyzer()
    flat = pd.DataFrame(
        {
            "high": [110] * 20,
            "low": [100] * 20,
            "close": [105] * 20,
            "volume": [1_000_000] * 20,
        }
    )
    assert ta.detect_flat_base(flat, lookback=20, max_range_pct=12.0) is True

    vcp = pd.DataFrame(
        {
            "high": [120] * 10 + [115] * 10 + [112] * 10,
            "low": [100] * 10 + [101] * 10 + [102] * 10,
            "close": [110] * 30,
            "volume": [1_000_000 + i * 20_000 for i in range(10)]
            + [900_000 + i * 10_000 for i in range(10)]
            + [850_000 + i * 2_000 for i in range(10)],
        }
    )
    assert ta.detect_vcp(vcp) is True
