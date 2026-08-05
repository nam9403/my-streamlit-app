from __future__ import annotations

import json
from pathlib import Path


def test_regime_dashboard_and_accountability_export(tmp_path, monkeypatch) -> None:
    import core.product_layer as pl

    monkeypatch.setattr(pl, "DB_PATH", tmp_path / "t.db")
    monkeypatch.setattr(pl, "SECRETS_PATH", tmp_path / "sec.json")
    pl._init_db()

    uid = "acct_test_user"
    report_dir = Path(pl.ROOT) / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    regime = pl.get_forecast_regime_dashboard(uid)
    assert "bull" in regime and "sideway" in regime and "bear" in regime

    out = pl.export_model_accountability_report(uid)
    p = Path(out)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert str(data.get("user_id")) == uid
    assert "regime_dashboard" in data
    assert "proof_of_value" in data

