from __future__ import annotations

from pathlib import Path


def test_export_monthly_accountability_markdown(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "sec.json")
    pl._init_db()

    out = pl.export_monthly_accountability_markdown("monthly_test_user")
    p = Path(out)
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "Monthly Model Accountability Report" in txt
    assert "Regime Dashboard" in txt

