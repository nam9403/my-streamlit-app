from __future__ import annotations

import concurrent.futures
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.intraday_flow_journal import (
    append_flow_signal,
    append_flow_signals_batch,
    prune_old_journal_files,
    read_recent_flow_signals,
    summarize_recent_flow_signals,
)
from core.intraday_flow_service import FlowSignal


def _make_signal(symbol: str = "FPT", intensity: float = 7.5, big: bool = True) -> FlowSignal:
    return FlowSignal(
        symbol=symbol,
        timeframe="5m",
        is_big_boy=big,
        aggregated_volume=5_000_000.0,
        delta_status="bullish",
        intensity_score=intensity,
        z_volume=3.2,
        pseudo_delta=0.55,
        cumulative_delta=1_200_000.0,
        anomaly_score=-0.15,
        last_close=27_500.0,
        last_volume=5_000_000.0,
        context_note="ngành: it",
    )


def test_append_single_signal_creates_weekly_file(tmp_path: Path) -> None:
    sig = _make_signal()
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    written = append_flow_signal(sig, base_dir=tmp_path, now=ts)
    assert written.exists()
    assert "2026W20" in written.name  # 2026-05-11 is ISO week 20
    lines = written.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["symbol"] == "FPT"
    assert row["is_big_boy"] is True
    assert row["intensity_score"] == 7.5
    assert "journaled_at_utc" in row


def test_append_signal_merges_extra_context(tmp_path: Path) -> None:
    sig = _make_signal("HPG")
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    file_path = append_flow_signal(
        sig,
        base_dir=tmp_path,
        extra_context={"phase": "background_cycle", "resolution": "5"},
        now=ts,
    )
    row = json.loads(file_path.read_text(encoding="utf-8").strip())
    assert row["phase"] == "background_cycle"
    assert row["resolution"] == "5"
    assert row["symbol"] == "HPG"


def test_append_signal_handles_dict_payload(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    file_path = append_flow_signal(
        {"symbol": "VNM", "intensity_score": 4.0, "is_big_boy": False},
        base_dir=tmp_path,
        now=ts,
    )
    row = json.loads(file_path.read_text(encoding="utf-8").strip())
    assert row["symbol"] == "VNM"
    assert row["intensity_score"] == 4.0
    assert row["is_big_boy"] is False


def test_batch_append_writes_all_signals(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    sigs = [_make_signal("FPT"), _make_signal("HPG"), _make_signal("VNM")]
    count = append_flow_signals_batch(sigs, base_dir=tmp_path, now=ts)
    assert count == 3
    files = list(tmp_path.glob("flow_signals_*.jsonl"))
    assert len(files) == 1
    rows = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    syms = {r["symbol"] for r in rows}
    assert syms == {"FPT", "HPG", "VNM"}


def test_read_recent_filters_by_hours(tmp_path: Path) -> None:
    now_ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    append_flow_signal(_make_signal("FPT"), base_dir=tmp_path, now=now_ts)
    append_flow_signal(_make_signal("HPG"), base_dir=tmp_path, now=now_ts - timedelta(hours=48))
    recent = read_recent_flow_signals(hours=24, base_dir=tmp_path, now=now_ts)
    syms = {r["symbol"] for r in recent}
    assert "FPT" in syms
    assert "HPG" not in syms


def test_read_recent_filters_by_symbol(tmp_path: Path) -> None:
    now_ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    for sym in ["FPT", "HPG", "VNM"]:
        append_flow_signal(_make_signal(sym), base_dir=tmp_path, now=now_ts)
    fpt_only = read_recent_flow_signals(hours=24, symbol="fpt", base_dir=tmp_path, now=now_ts)
    assert all(r["symbol"] == "FPT" for r in fpt_only)
    assert len(fpt_only) == 1


def test_read_recent_returns_empty_when_no_files(tmp_path: Path) -> None:
    out = read_recent_flow_signals(
        hours=24, base_dir=tmp_path, now=datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    )
    assert out == []


def test_read_recent_handles_corrupted_lines(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    append_flow_signal(_make_signal("FPT"), base_dir=tmp_path, now=ts)
    file_path = next(tmp_path.glob("flow_signals_*.jsonl"))
    with file_path.open("a", encoding="utf-8") as fh:
        fh.write("not-a-json-line\n")
        fh.write("\n")
    rows = read_recent_flow_signals(hours=24, base_dir=tmp_path, now=ts)
    assert len(rows) == 1


def test_read_recent_crosses_week_boundary(tmp_path: Path) -> None:
    # 2026-05-11 = ISO week 20 (Monday); look back 48h ⇒ also covers W19 (Sunday).
    now_ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    prev_ts = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)  # ISO week 19
    append_flow_signal(_make_signal("FPT"), base_dir=tmp_path, now=now_ts)
    append_flow_signal(_make_signal("HPG"), base_dir=tmp_path, now=prev_ts)
    files = sorted(tmp_path.glob("flow_signals_*.jsonl"))
    assert len(files) == 2  # different weeks ⇒ different files
    rows = read_recent_flow_signals(hours=48, base_dir=tmp_path, now=now_ts)
    syms = {r["symbol"] for r in rows}
    assert syms == {"FPT", "HPG"}


def test_prune_removes_old_files(tmp_path: Path) -> None:
    old_ts = datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc)
    recent_ts = datetime(2026, 5, 11, 10, 0, tzinfo=timezone.utc)
    append_flow_signal(_make_signal("OLD"), base_dir=tmp_path, now=old_ts)
    append_flow_signal(_make_signal("NEW"), base_dir=tmp_path, now=recent_ts)
    before = len(list(tmp_path.glob("flow_signals_*.jsonl")))
    assert before == 2
    pruned = prune_old_journal_files(retention_weeks=4, base_dir=tmp_path, now=recent_ts)
    assert len(pruned) == 1
    remaining = list(tmp_path.glob("flow_signals_*.jsonl"))
    assert len(remaining) == 1
    rows = read_recent_flow_signals(hours=24, base_dir=tmp_path, now=recent_ts)
    assert all(r["symbol"] != "OLD" for r in rows)


def test_summarize_aggregates_metrics(tmp_path: Path) -> None:
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    append_flow_signal(_make_signal("FPT", intensity=8.0, big=True), base_dir=tmp_path, now=ts)
    append_flow_signal(_make_signal("HPG", intensity=5.0, big=False), base_dir=tmp_path, now=ts)
    append_flow_signal(_make_signal("FPT", intensity=9.5, big=True), base_dir=tmp_path, now=ts)
    summary = summarize_recent_flow_signals(hours=24, base_dir=tmp_path, now=ts)
    assert summary["total"] == 3
    assert summary["big_boy_count"] == 2
    assert summary["bullish_count"] == 3
    top = {x["symbol"]: x["max_intensity"] for x in summary["top_symbols"]}
    assert top["FPT"] == 9.5
    assert top["HPG"] == 5.0


def test_concurrent_appends_dont_corrupt_jsonl(tmp_path: Path) -> None:
    """Nhiều thread cùng ghi (mô phỏng dispatch song song) → mọi dòng phải
    là JSON hợp lệ, đếm đúng số bản ghi.

    Note: smaller N để giảm thời gian test trên Windows (msvcrt.locking
    block-and-wait có overhead ~1-2s/lock contention). Core invariant cần
    verify: không có dòng corrupt + đúng count, đã đạt với 10 writes.
    """
    ts = datetime(2026, 5, 11, 10, 30, tzinfo=timezone.utc)
    N = 10

    def _writer(idx: int) -> None:
        sig = _make_signal(symbol=f"SYM{idx % 5}", intensity=5.0 + (idx % 5))
        append_flow_signal(sig, base_dir=tmp_path, now=ts, extra_context={"idx": idx})

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_writer, range(N)))

    files = list(tmp_path.glob("flow_signals_*.jsonl"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    assert len(lines) == N
    parsed = [json.loads(ln) for ln in lines]
    indices = sorted([int(p["idx"]) for p in parsed])
    assert indices == list(range(N))
