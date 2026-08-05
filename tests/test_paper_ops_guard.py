from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from core.paper_ops_guard import PaperKillSwitchConfig, evaluate_paper_kill_switch
from core.paper_trade_ledger import open_paper_trades_from_top, save_ledger


def _closed(sym: str, hit: bool, days_ago: int) -> dict:
    now = datetime.now(timezone.utc)
    closed = now - timedelta(days=days_ago)
    return {
        "id": f"t-{sym}-{days_ago}",
        "symbol": sym,
        "status": "CLOSED",
        "direction_hit": 1 if hit else 0,
        "realized_pct": 2.0 if hit else -3.0,
        "closed_at": closed.isoformat(),
        "opened_at": (closed - timedelta(days=40)).isoformat(),
        "entry_price": 100.0,
        "exit_price": 102.0 if hit else 97.0,
        "source": "test",
        "action": "BUY",
    }


def test_kill_switch_consecutive_losses() -> None:
    ledger = {"trades": [_closed(f"S{i}", False, i) for i in range(10)]}
    g = evaluate_paper_kill_switch(
        ledger, config=PaperKillSwitchConfig(consecutive_losses=8, lookback_closed=20)
    )
    assert g["halt_new_opens"] is True
    assert g["consecutive_losses"] >= 8


def test_kill_switch_ok_after_win() -> None:
    trades = [_closed("W", True, 0)] + [_closed(f"L{i}", False, i + 1) for i in range(10)]
    g = evaluate_paper_kill_switch(
        {"trades": trades},
        config=PaperKillSwitchConfig(consecutive_losses=8, lookback_closed=5, min_samples_for_avg_rule=50),
    )
    assert g["consecutive_losses"] == 0
    assert g["halt_new_opens"] is False


def test_open_paper_blocked_by_kill_switch(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "ledger.json"
    # Seed losing streak
    save_ledger({"trades": [_closed(f"S{i}", False, i) for i in range(10)]}, path)
    monkeypatch.delenv("II_PAPER_KILL_SWITCH", raising=False)
    rows = [
        {
            "Mã": "FPT",
            "Giá": 100000.0,
            "Khuyến nghị": "BUY",
            "Setup": "ARMED",
            "Trigger": "READY",
        }
    ]
    st = open_paper_trades_from_top(rows, source="test", horizon_days=40, path=path)
    assert st["opened"] == 0
    assert st.get("kill_switch_halt") is True
