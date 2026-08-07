"""Autopilot MOS sync with published fair value."""

from __future__ import annotations

import pandas as pd

from core.autopilot_nightly_board import _mos_from_fair, _recompute_expected_return, refresh_top_prices
from core.valuation import _resolve_fair_pb_multiple


def test_mos_from_fair_matches_decision_card_formula() -> None:
    # BID-like: fair 37755, price 38250 → MOS ≈ -1.31%
    mos = _mos_from_fair(37755.0, 38250.0)
    assert mos is not None
    assert -1.4 < mos < -1.2


def test_recompute_expected_return() -> None:
    # ER = mos*0.6 + rev*0.2 + fscore*1.2
    assert abs(_recompute_expected_return(27.83, 0.0, 4.0) - 21.498) < 0.01


def test_bank_fair_pb_uplifts_with_roe() -> None:
    base = _resolve_fair_pb_multiple({"symbol": "BID", "is_bank": True, "roe": 12.0})
    strong = _resolve_fair_pb_multiple({"symbol": "BID", "is_bank": True, "roe": 20.0})
    assert base[0] == 1.25
    assert strong[0] >= 1.45


def test_refresh_recomputes_mos_from_stored_fair(monkeypatch) -> None:
    df = pd.DataFrame(
        [
            {
                "Mã": "BID",
                "Giá": 38250.0,
                "Fair": 37755.0,
                "MOS%": 27.83,  # stale Graham-era
                "Rev YoY%": 0.0,
                "F-Score": 4,
                "Expected Return %": 21.5,
            }
        ]
    )

    monkeypatch.setenv("II_AUTOPILOT_MORNING_REVALUE", "0")  # force Fair-only path

    def _fake_snap(sym: str):
        return {"symbol": sym, "price": 38250.0}

    monkeypatch.setattr(
        "core.analysis_runtime_service._snapshot_impl",
        _fake_snap,
        raising=False,
    )
    # refresh imports _snapshot_impl inside function — patch the module used at call time
    import core.autopilot_nightly_board as nb

    monkeypatch.setattr(nb, "refresh_top_prices", nb.refresh_top_prices)

    # Patch import target inside refresh
    import core.analysis_runtime_service as ars

    monkeypatch.setattr(ars, "_snapshot_impl", _fake_snap)

    out, meta = refresh_top_prices(df, max_symbols=1, revalue=False)
    assert meta["refreshed"] == 1
    mos = float(out.iloc[0]["MOS%"])
    assert -1.4 < mos < -1.2
    assert float(out.iloc[0]["Expected Return %"]) < 5.0
