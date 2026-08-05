from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from core import autopilot_nightly_board as nb


def _row(sym: str, *, mos: float, exp: float, action: str = "WATCH", ready: bool = True) -> dict:
    return {
        "Mã": sym,
        "Tiểu ngành": "Ngân hàng",
        "Khuyến nghị": action,
        "Khung thời gian": "Trung hạn (2-6 tháng)",
        "Giá": 20000.0,
        "MOS%": mos,
        "Expected Return %": exp,
        "Risk % (ước tính)": 18.0,
        "Trạng thái": "Sẵn sàng" if ready else "Không đạt lọc thanh khoản",
    }


def test_merge_and_top_n_prefers_higher_score(tmp_path: Path) -> None:
    path = tmp_path / "board.json"
    board = nb.empty_board(profile="growth", universe_mode="liquid")
    board["target_symbols"] = ["AAA", "SHB", "ACB", "FPT"]
    board = nb.merge_batch_into_board(
        board,
        rows=[
            _row("AAA", mos=10, exp=5, action="AVOID"),
            _row("SHB", mos=70, exp=50, action="WATCH"),
            _row("ACB", mos=55, exp=40, action="WATCH"),
            _row("FPT", mos=-10, exp=2, action="WATCH", ready=False),
        ],
        batch_id="b0",
        symbols=["AAA", "SHB", "ACB", "FPT"],
        seconds=1.2,
        ok=3,
        fail=1,
    )
    nb.save_board(board, path)
    loaded = nb.load_board(path)
    assert loaded is not None
    meta = nb.compute_meta(loaded)
    assert meta["scanned_count"] == 4
    assert meta["ready_count"] == 3
    assert meta["liquidity_filtered_count"] == 1
    assert meta["data_error_count"] == 0
    assert meta["fail_count"] == 1
    top = nb.top_n_from_board(loaded, top_n=2, ready_only=True)
    assert list(top["Mã"]) == ["SHB", "ACB"]


def test_summarize_scan_rows_splits_liquidity_and_data_error() -> None:
    rows = [
        _row("A", mos=10, exp=5),
        _row("B", mos=10, exp=5, ready=False),
        {"Mã": "C", "Trạng thái": "Lỗi phân tích"},
    ]
    stats = nb.summarize_scan_rows(rows)
    assert stats["ok"] == 1
    assert stats["liquidity_filtered"] == 1
    assert stats["data_error"] == 1
    assert stats["fail"] == 2
    assert stats["ready_rate_pct"] == 33.33


def test_prefilter_symbols_by_volume(monkeypatch) -> None:
    def _rank(**kwargs):
        cands = kwargs.get("candidates") or []
        vols = {"AAA": 500_000.0, "BBB": 50_000.0, "CCC": 250_000.0}
        return [(s, vols[s]) for s in cands if s in vols]

    monkeypatch.setattr("core.ohlcv_store.top_symbols_by_avg_volume", _rank)
    passed, skipped = nb.prefilter_symbols_by_volume(
        ["AAA", "BBB", "CCC", "VN30X"],
        200_000.0,
        always_include=["VN30X"],
    )
    assert "AAA" in passed and "CCC" in passed and "VN30X" in passed
    assert "BBB" in skipped


def test_resolve_nightly_target_symbols_dynamic_slice(monkeypatch) -> None:
    monkeypatch.setattr(nb, "_listing_symbols_disk_first", lambda: ["AAA", "BBB", "CCC"])
    monkeypatch.setattr(nb, "_build_nightly_pool", lambda mode, full: ["SHB", "ACB", "FPT", "AAA", "BBB"])
    monkeypatch.setattr(
        nb,
        "prefilter_symbols_by_volume",
        lambda syms, min_vol, **kw: ([s for s in syms if s != "BBB"], ["BBB"]),
    )
    syms, meta = nb.resolve_nightly_target_symbols(
        limit=2,
        offset=1,
        universe_mode="dynamic_liquid",
        min_avg_volume_20=200_000.0,
        prefilter_volume=True,
    )
    assert syms == ["ACB", "FPT"]
    assert meta["mode"] == "dynamic_liquid"
    assert meta["prefilter_skipped_count"] == 1


def test_try_serve_respects_freshness_and_coverage(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "board.json"
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_BOARD", "1")
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_BOARD_PATH", str(path))
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_MAX_AGE_HOURS", "36")
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_MIN_COVERAGE_PCT", "50")
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_REFRESH_PRICES", "0")

    board = nb.empty_board()
    board["target_symbols"] = [f"S{i:03d}" for i in range(10)]
    board["rows"] = {f"S{i:03d}": _row(f"S{i:03d}", mos=30 + i, exp=20 + i) for i in range(3)}
    board["updated_at"] = datetime.now(timezone.utc).isoformat()
    nb.save_board(board, path)

    df, meta = nb.try_serve_top_board(profile="growth", top_n=10)
    assert df is None
    assert meta.get("reason") == "low_coverage"

    board["rows"] = {f"S{i:03d}": _row(f"S{i:03d}", mos=30 + i, exp=20 + i) for i in range(6)}
    board["updated_at"] = datetime.now(timezone.utc).isoformat()
    nb.save_board(board, path)
    df, meta = nb.try_serve_top_board(profile="growth", top_n=3)
    assert df is not None and len(df) == 3
    assert meta.get("served") is True
    assert meta.get("mode") == "nightly_board"

    board["updated_at"] = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
    path.write_text(
        __import__("json").dumps(board, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    df2, meta2 = nb.try_serve_top_board(profile="growth", top_n=3)
    assert df2 is None
    assert meta2.get("reason") == "stale"


def test_force_live_skips_board(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "board.json"
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_BOARD", "1")
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_BOARD_PATH", str(path))
    board = nb.empty_board()
    board["target_symbols"] = ["A", "B"]
    board["rows"] = {"A": _row("A", mos=80, exp=60), "B": _row("B", mos=70, exp=55)}
    board["updated_at"] = datetime.now(timezone.utc).isoformat()
    nb.save_board(board, path)
    df, meta = nb.try_serve_top_board(profile="growth", force_live=True)
    assert df is None
    assert meta.get("reason") == "disabled_or_force_live"


def test_board_health_and_score(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "board.json"
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_BOARD_PATH", str(path))
    monkeypatch.setenv("II_AUTOPILOT_NIGHTLY_MIN_COVERAGE_PCT", "50")
    missing = nb.board_health_report()
    assert missing["ok"] is False
    assert missing["severity"] == "critical"

    board = nb.empty_board()
    board["target_symbols"] = [f"S{i:03d}" for i in range(10)]
    board["rows"] = {f"S{i:03d}": _row(f"S{i:03d}", mos=40 + i, exp=25 + i) for i in range(8)}
    board["updated_at"] = datetime.now(timezone.utc).isoformat()
    nb.save_board(board, path)
    ok_rep = nb.board_health_report(min_coverage_pct=50)
    assert ok_rep["ok"] is True
    assert ok_rep["severity"] == "ok"


def test_seed_top_forecast_records_smoke(monkeypatch) -> None:
    calls: list[tuple] = []

    def _rec(uid, sym, report):
        calls.append((uid, sym, report))

    monkeypatch.setattr("core.product_layer.record_forecast_snapshot", _rec)

    df = pd.DataFrame(
        [
            {"Mã": "SHB", "Giá": 12000.0, "Expected Return %": 20.0},
            {"Mã": "ACB", "Giá": 22000.0, "Expected Return %": 15.0},
        ]
    )
    stat = nb.seed_top_forecast_records(df, user_id="t", horizon_days=90)
    assert stat["seeded"] == 2
    assert len(calls) == 2
    assert calls[0][1] == "SHB"
