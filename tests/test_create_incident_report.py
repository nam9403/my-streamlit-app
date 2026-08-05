from __future__ import annotations

from scripts.create_incident_report import build_incident_markdown


def test_build_incident_markdown_contains_required_sections() -> None:
    md = build_incident_markdown(
        incident_id="INC-2026-001",
        severity="SEV-1",
        title="API outage",
        owner="alice",
    )
    assert "Incident INC-2026-001 - API outage" in md
    assert "## Metadata" in md
    assert "## Executive Summary" in md
    assert "## Timeline (UTC)" in md
    assert "## Root Cause" in md
    assert "## Action Items" in md

