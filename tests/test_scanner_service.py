from __future__ import annotations

import pandas as pd


def test_scan_potential_stocks_returns_sorted_ready_rows(monkeypatch) -> None:
    import core.scanner_service as ss

    def fake_snapshot(sym: str):
        return {"symbol": sym, "price": 100.0}

    def fake_report(sym: str, snap: dict, profile: str, capital: float, quick_mode: bool = True):
        base = {
            "valuation": {
                "price": 100.0,
                "margin_of_safety_composite_pct": 25.0 if sym == "AAA" else 5.0,
                "piotroski_score": 8 if sym == "AAA" else 5,
                "industry_subtype_label_vi": "Test",
            },
            "financials": {"revenue_growth_yoy": 20.0 if sym == "AAA" else 3.0},
            "phase": {"phase": "breakout" if sym == "AAA" else "neutral", "metrics": {"vol_multiple": 1.6 if sym == "AAA" else 1.0}},
        }
        return base

    def fake_ohlcv(sym: str):
        # avg vol20 = 500k for both symbols
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=30, freq="D"),
                "open": [1.0] * 30,
                "high": [1.0] * 30,
                "low": [1.0] * 30,
                "close": [1.0] * 30,
                "volume": [500_000.0] * 30,
            }
        )

    monkeypatch.setattr(ss, "load_snapshot_cached", fake_snapshot)
    monkeypatch.setattr(ss, "load_strategic_report_cached", fake_report)
    monkeypatch.setattr(ss, "load_ohlcv_cached", fake_ohlcv)
    monkeypatch.setattr(ss, "_load_scan_ohlcv", fake_ohlcv)

    df = ss.scan_potential_stocks.__wrapped__(("AAA", "BBB"), "growth", 100_000.0)  # type: ignore[attr-defined]
    assert not df.empty
    assert list(df["Mã"]) == ["AAA", "BBB"]
    assert str(df.iloc[0]["Trạng thái"]) == "Sẵn sàng"
    assert float(df.iloc[0]["Expected Return %"]) >= float(df.iloc[1]["Expected Return %"])


def test_load_autopilot_board_uses_liquid_universe(monkeypatch) -> None:
    import core.scanner_service as ss

    captured: dict = {}

    def fake_scan(universe, profile, min_vol):
        captured["universe"] = list(universe)
        return pd.DataFrame(
            [
                {
                    "Mã": list(universe)[0],
                    "Khuyến nghị": "WATCH",
                    "MOS%": 10.0,
                    "Expected Return %": 12.0,
                    "Risk % (ước tính)": 15.0,
                    "Trạng thái": "Sẵn sàng",
                }
            ]
        )

    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "vn30")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    monkeypatch.setattr(ss, "list_universe_symbols", lambda limit=None: ["AAA", "BBB", "FPT"])
    monkeypatch.setattr(ss, "scan_potential_stocks", fake_scan)

    out = ss.load_autopilot_board.__wrapped__(
        "growth",
        universe_limit=15,
        min_avg_volume_20=100_000.0,
        _rotation_day=1,
        _force_live=True,
    )  # type: ignore[attr-defined]
    assert not out.empty
    assert "FPT" in captured["universe"] or captured["universe"][0] in {"ACB", "BCM", "BID", "FPT"}
    assert "AAA" not in captured["universe"]


def test_load_autopilot_board_keeps_ready_rows_and_limits(monkeypatch) -> None:
    import core.scanner_service as ss

    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "rotate_full")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    monkeypatch.setattr(ss, "list_universe_symbols", lambda limit=30, offset=0: ["AAA", "BBB", "CCC"])
    fake_scan = pd.DataFrame(
        [
            {"Mã": "AAA", "Khuyến nghị": "BUY", "MOS%": 20.0, "Expected Return %": 15.0, "Risk % (ước tính)": 10.0, "Trạng thái": "Sẵn sàng"},
            {"Mã": "BBB", "Khuyến nghị": "HOLD", "MOS%": 12.0, "Expected Return %": 8.0, "Risk % (ước tính)": 12.0, "Trạng thái": "Sẵn sàng"},
            {"Mã": "CCC", "Khuyến nghị": "AVOID", "MOS%": 1.0, "Expected Return %": 1.0, "Risk % (ước tính)": 30.0, "Trạng thái": "Không đạt lọc thanh khoản"},
        ]
    )
    monkeypatch.setattr(ss, "scan_potential_stocks", lambda *a, **k: fake_scan)

    out = ss.load_autopilot_board.__wrapped__(
        "growth",
        universe_limit=30,
        min_avg_volume_20=100_000.0,
        _rotation_day=1,
        _force_live=True,
    )  # type: ignore[attr-defined]
    assert not out.empty
    assert "Mã" in out.columns
    assert out.iloc[0]["Mã"] == "AAA"
    assert "CCC" not in out["Mã"].tolist()


def test_load_autopilot_board_missing_recommendation_column_does_not_crash(monkeypatch) -> None:
    """Graceful degradation when scan returns error rows without 'Khuyến nghị'."""
    import core.scanner_service as ss

    monkeypatch.setenv("II_AUTOPILOT_UNIVERSE_MODE", "rotate_full")
    monkeypatch.setenv("II_UNIVERSE_AUTO_ROTATE", "0")
    monkeypatch.setattr(ss, "list_universe_symbols", lambda limit=30, offset=0: ["AAA", "BBB"])
    fake_scan = pd.DataFrame(
        [
            {"Mã": "AAA", "Giá": None, "Trạng thái": "Không có snapshot"},
            {"Mã": "BBB", "Giá": 10.0, "Trạng thái": "Lỗi hệ thống"},
        ]
    )
    monkeypatch.setattr(ss, "scan_potential_stocks", lambda *a, **k: fake_scan)

    out = ss.load_autopilot_board.__wrapped__(
        "growth",
        universe_limit=30,
        min_avg_volume_20=100_000.0,
        _rotation_day=1,
        _force_live=True,
    )  # type: ignore[attr-defined]
    assert isinstance(out, pd.DataFrame)
    assert "Khuyến nghị" in out.columns
    assert list(out["Khuyến nghị"]) == ["AVOID", "AVOID"]


def test_scan_one_symbol_api_timeout_is_isolated(monkeypatch) -> None:
    """One symbol API timeout must not abort the whole scan batch."""
    import core.scanner_service as ss

    def fake_snapshot(sym: str):
        if sym == "BAD":
            raise TimeoutError("Read timed out. (read timeout=30)")
        return {"symbol": sym, "price": 100.0}

    def fake_report(sym: str, snap: dict, profile: str, capital: float, quick_mode: bool = True):
        return {
            "valuation": {
                "price": 100.0,
                "margin_of_safety_composite_pct": 20.0,
                "piotroski_score": 7,
                "industry_subtype_label_vi": "Test",
            },
            "financials": {"revenue_growth_yoy": 10.0},
            "phase": {"phase": "accumulation", "metrics": {"vol_multiple": 1.2}},
            "final_action": "BUY",
        }

    def fake_ohlcv(sym: str):
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=25, freq="D"),
                "open": [1.0] * 25,
                "high": [1.0] * 25,
                "low": [1.0] * 25,
                "close": [1.0] * 25,
                "volume": [400_000.0] * 25,
            }
        )

    monkeypatch.setattr(ss, "load_snapshot_cached", fake_snapshot)
    monkeypatch.setattr(ss, "load_strategic_report_cached", fake_report)
    monkeypatch.setattr(ss, "load_ohlcv_cached", fake_ohlcv)
    monkeypatch.setattr(ss, "_load_scan_ohlcv", fake_ohlcv)

    out = ss.scan_potential_stocks.__wrapped__(("AAA", "BAD"), "growth", 100_000.0)  # type: ignore[attr-defined]
    assert len(out) == 2
    assert "Khuyến nghị" in out.columns
    bad = out.loc[out["Mã"] == "BAD"].iloc[0]
    assert str(bad["Trạng thái"]) == "Lỗi hệ thống"
    assert str(bad["Khuyến nghị"]) == "AVOID"
    good = out.loc[out["Mã"] == "AAA"].iloc[0]
    assert str(good["Trạng thái"]) == "Sẵn sàng"


def test_simple_view_for_plan_hides_pro_fields_for_free() -> None:
    import core.scanner_service as ss

    df = pd.DataFrame(
        [
            {
                "Mã": "AAA",
                "Hành động": "BUY",
                "Giá hiện tại": 100.0,
                "Giá trị nội tại": 120.0,
                "Biên an toàn %": 20.0,
                "Giá vào": 98.0,
                "SL": 92.0,
                "TP": 120.0,
                "Tỷ trọng %": 10.0,
            }
        ]
    )
    free_df = ss.simple_view_for_plan(df, "free")
    pro_df = ss.simple_view_for_plan(df, "pro")
    assert "Giá vào" not in free_df.columns
    assert "SL" not in free_df.columns
    assert "TP" not in free_df.columns
    assert "Giá vào" in pro_df.columns


def test_scan_potential_stocks_emits_timing_metric(monkeypatch) -> None:
    import core.scanner_service as ss

    metrics: list[dict] = []

    def fake_log_timing(metric: str, duration_ms: float, **fields):
        metrics.append({"metric": metric, "duration_ms": duration_ms, **fields})

    monkeypatch.setattr(ss, "log_timing", fake_log_timing)
    monkeypatch.setattr(ss, "load_snapshot_cached", lambda sym: {"symbol": sym, "price": 100.0})
    monkeypatch.setattr(
        ss,
        "load_strategic_report_cached",
        lambda sym, snap, profile, capital, quick_mode=True: {
            "valuation": {
                "price": 100.0,
                "margin_of_safety_composite_pct": 12.0,
                "piotroski_score": 7,
                "industry_subtype_label_vi": "Test",
            },
            "financials": {"revenue_growth_yoy": 10.0},
            "phase": {"phase": "accumulation", "metrics": {"vol_multiple": 1.2}},
        },
    )
    monkeypatch.setattr(
        ss,
        "load_ohlcv_cached",
        lambda sym: pd.DataFrame(
            {
                "date": pd.date_range("2026-01-01", periods=25, freq="D"),
                "open": [1.0] * 25,
                "high": [1.0] * 25,
                "low": [1.0] * 25,
                "close": [1.0] * 25,
                "volume": [400_000.0] * 25,
            }
        ),
    )
    monkeypatch.setattr(ss, "_load_scan_ohlcv", ss.load_ohlcv_cached)

    out = ss.scan_potential_stocks.__wrapped__(("AAA",), "growth", 100_000.0)  # type: ignore[attr-defined]
    assert not out.empty
    assert any(m.get("metric") == "scanner.scan_potential_stocks" for m in metrics)

