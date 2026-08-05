#!/usr/bin/env python3
"""
Create a structured incident report markdown file from a standard template.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INCIDENT_DIR = ROOT / "artifacts" / "incidents"


def build_incident_markdown(*, incident_id: str, severity: str, title: str, owner: str) -> str:
    now_utc = datetime.now(UTC).isoformat()
    lines: list[str] = []
    lines.append(f"# Incident {incident_id} - {title}")
    lines.append("")
    lines.append("## Metadata")
    lines.append("")
    lines.append(f"- Incident ID: {incident_id}")
    lines.append(f"- Severity: {severity}")
    lines.append(f"- Created at (UTC): {now_utc}")
    lines.append(f"- Incident commander: {owner}")
    lines.append("- Status: Draft")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("- What happened:")
    lines.append("- User impact:")
    lines.append("- Current status:")
    lines.append("")
    lines.append("## Timeline (UTC)")
    lines.append("")
    lines.append("- T0:")
    lines.append("- Detection:")
    lines.append("- Mitigation:")
    lines.append("- Recovery:")
    lines.append("")
    lines.append("## Root Cause")
    lines.append("")
    lines.append("- Primary root cause:")
    lines.append("- Contributing factors:")
    lines.append("")
    lines.append("## Action Items")
    lines.append("")
    lines.append("| Action | Owner | Due date | Status |")
    lines.append("|---|---|---|---|")
    lines.append("|  |  |  |  |")
    lines.append("")
    return "\n".join(lines)


def _sanitize_slug(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
    safe = safe.strip("-_")
    return safe or "incident"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--incident-id", required=True, help="Incident identifier, e.g. INC-2026-001")
    parser.add_argument("--severity", default="SEV-2", help="SEV-1/SEV-2/SEV-3")
    parser.add_argument("--title", required=True, help="Short incident title")
    parser.add_argument("--owner", default="incident-commander", help="Incident commander name")
    args = parser.parse_args()

    INCIDENT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_slug(args.incident_id)
    path = INCIDENT_DIR / f"{slug}.md"
    content = build_incident_markdown(
        incident_id=args.incident_id.strip(),
        severity=args.severity.strip(),
        title=args.title.strip(),
        owner=args.owner.strip(),
    )
    path.write_text(content, encoding="utf-8")
    print(f"[OK] Created {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

