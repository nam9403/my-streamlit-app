from __future__ import annotations

from scripts.architecture_gate import ROOT


def test_architecture_gate_root_points_workspace() -> None:
    assert ROOT.exists()
    assert (ROOT / "scripts").exists()

