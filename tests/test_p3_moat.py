from __future__ import annotations

import pandas as pd

from core.proprietary_signal import compute_blend_signal, proprietary_score_from_row
from core.referral_service import referral_code_for_user


def test_proprietary_blend_signal_smoke() -> None:
    rep = {
        "final_action": "WATCH",
        "confidence_score": 62,
        "valuation": {"margin_of_safety_composite_pct": 28.0, "piotroski_score": 5, "instant_conclusion": "Theo dõi"},
        "phase": {"phase": "accumulation", "metrics": {"vol_multiple": 1.2}},
        "deep_insight": {"smart_money_flow": {"bias": "bullish", "score": 0.4}},
    }
    sig = compute_blend_signal(rep)
    assert 0 <= sig["blend_score"] <= 100
    assert sig["blend_band"] in ("HIGH", "MEDIUM", "LOW")
    assert sig["phase_score"] > 50


def test_proprietary_blend_playbook_nudge_buy_vs_avoid() -> None:
    base = {
        "valuation": {"margin_of_safety_composite_pct": 20.0, "piotroski_score": 5},
        "phase": {"phase": "accumulation"},
    }
    buy = compute_blend_signal(
        {
            **base,
            "final_action": "BUY",
            "decision_playbook": {"setup": {"status": "ARMED"}, "thesis": {"grade": "A"}},
        }
    )
    avoid = compute_blend_signal(
        {
            **base,
            "final_action": "AVOID",
            "decision_playbook": {"setup": {"status": "ABORT"}},
        }
    )
    assert buy["blend_score"] > avoid["blend_score"]
    assert buy["playbook_nudge"] > 0
    assert avoid["playbook_nudge"] < 0


def test_proprietary_score_from_row() -> None:
    row = {"MOS%": 40.0, "Expected Return %": 15.0, "Pha": "breakout", "Proprietary Score": 72.0}
    assert proprietary_score_from_row(row) == 72.0
    assert proprietary_score_from_row({"MOS%": 10, "Expected Return %": 5, "Khuyến nghị": "BUY"}) > proprietary_score_from_row(
        {"MOS%": 10, "Expected Return %": 5, "Khuyến nghị": "AVOID"}
    )


def test_live_score_rows_conditional_buy_ranks_above_watch() -> None:
    from core.autopilot_nightly_board import score_rows

    rows = [
        {
            "Mã": "AAA",
            "Khuyến nghị": "WATCH",
            "Expected Return %": 20.0,
            "MOS%": 30.0,
            "Risk % (ước tính)": 10.0,
            "is_gate_restricted": False,
        },
        {
            "Mã": "BBB",
            "Khuyến nghị": "CONDITIONAL_BUY",
            "Expected Return %": 8.0,
            "MOS%": 12.0,
            "Risk % (ước tính)": 12.0,
            "is_gate_restricted": False,
        },
    ]
    ranked = score_rows(rows)
    assert ranked.iloc[0]["Mã"] == "BBB"
    assert "Proprietary Score" in ranked.columns


def test_referral_code_stable() -> None:
    a = referral_code_for_user("user_a")
    b = referral_code_for_user("user_a")
    c = referral_code_for_user("user_b")
    assert a == b
    assert a != c
    assert len(a) == 8


def test_referral_signup_records() -> None:
    from core.product_layer import _conn, _utcnow_iso
    from core.referral_service import fetch_referral_stats, record_referral_signup, referral_code_for_user

    code = referral_code_for_user("referrer_x")
    out = record_referral_signup(
        conn_factory=_conn,
        utcnow_iso=_utcnow_iso,
        new_user_id="new_user_p3",
        referrer_code=code,
    )
    assert out.get("recorded") is True
    stats = fetch_referral_stats(conn_factory=_conn, days=30)
    assert stats.get("signups", 0) >= 1


def test_top_symbols_by_avg_volume(tmp_path, monkeypatch) -> None:
    from core import ohlcv_store as store

    db = tmp_path / "ohlcv.db"
    monkeypatch.setattr(store, "DB_PATH", db)
    df = pd.DataFrame(
        {
            "date": pd.date_range("2026-01-01", periods=25, freq="B"),
            "open": [10.0] * 25,
            "high": [11.0] * 25,
            "low": [9.0] * 25,
            "close": [10.5] * 25,
            "volume": [100_000.0 + i * 1000 for i in range(25)],
        }
    )
    df2 = df.copy()
    df2["volume"] = [500_000.0] * 25
    store.upsert_ohlcv("AAA", df, source="test")
    store.upsert_ohlcv("BBB", df2, source="test")
    ranked = store.top_symbols_by_avg_volume(limit=10, sessions=20)
    assert ranked[0][0] == "BBB"
    assert ranked[0][1] > ranked[1][1]


def test_dynamic_liquid_pool_returns_list() -> None:
    from core.liquid_universe import build_dynamic_liquid_pool

    pool = build_dynamic_liquid_pool(["ACB", "FPT"], top_n=10)
    assert isinstance(pool, list)
    assert len(pool) >= 1


def test_resolve_scan_universe_dynamic_liquid(monkeypatch) -> None:
    from core.liquid_universe import resolve_scan_universe

    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "dynamic_liquid")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    syms, meta = resolve_scan_universe(15, full_listing=["ACB", "FPT", "HPG", "ZZZ"], rotation_day=0)
    assert meta["mode"] == "dynamic_liquid"
    assert len(syms) >= 1


def test_ensure_production_profile_dev_ok() -> None:
    from scripts.ensure_production_profile import check_production_profile

    rep = check_production_profile(strict=False)
    assert "ok" in rep
    assert "issues" in rep


def test_process_audit_pack_builds() -> None:
    from scripts.export_process_audit_pack import build_audit_markdown

    md = build_audit_markdown(run_pytest=False)
    assert "Process audit pack" in md
    assert "data_integrity" in md
    assert "decision_playbook" in md
    assert "không cam kết" in md.lower() or "Không cam kết" in md
