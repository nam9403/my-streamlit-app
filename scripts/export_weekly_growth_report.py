"""
Weekly growth report: cohort, funnel, referral, retention (P3).

  python scripts/export_weekly_growth_report.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def build_weekly_growth_markdown(*, days: int = 7) -> str:
    from core.analytics_service import get_admin_kpi, get_upgrade_funnel
    from core.product_layer import _conn
    from core.referral_service import fetch_referral_stats

    adm = get_admin_kpi(conn_factory=_conn, days=30)
    funnel = get_upgrade_funnel(conn_factory=_conn, days=30)

    lines = [
        "# Weekly growth report",
        "",
        f"Window: last **{days}** days (admin KPI uses 30d where noted)",
        "",
        "## Platform",
        "",
        f"- Users total: **{adm.get('users_total')}**",
        f"- Active users (30d): **{adm.get('active_users_period')}**",
        f"- Events (30d): **{adm.get('events_period')}**",
        f"- Alerts total: **{adm.get('alerts_total')}**",
        "",
        "## Plans",
        "",
    ]
    for row in adm.get("plans") or []:
        lines.append(f"- {row.get('plan_id')}: **{row.get('count')}**")
    lines.extend(["", f"## Upgrade funnel ({days}d / admin window 30d)", ""])
    if funnel:
        lines.extend(["| Variant | Views | Info | CTA | Success |", "|---|---:|---:|---:|---:|"])
        for row in funnel:
            lines.append(
                f"| {row.get('variant') or 'default'} | {row.get('views')} | {row.get('info_clicks')} "
                f"| {row.get('cta_clicks')} | {row.get('success')} |"
            )
    else:
        lines.append("_No funnel events yet._")

    lines.extend(["", f"## Referral ({days}d)", ""])
    ref = fetch_referral_stats(conn_factory=_conn, days=max(1, int(days)))
    lines.append(f"- Signups: **{ref.get('signups')}** · unique codes: **{ref.get('unique_codes')}**")
    top = ref.get("top_referrers") or []
    if top:
        lines.extend(["", "| Code | Signups |", "|---|---:|"])
        for row in top[:15]:
            lines.append(f"| {row.get('code')} | {row.get('signups')} |")

    lines.extend(["", "## Event mix (30d)", ""])
    for row in (adm.get("events_by_type") or [])[:15]:
        lines.append(f"- {row.get('event')}: **{row.get('count')}**")

    try:
        from core.growth_conversion_service import build_growth_conversion_snapshot
        from core.product_layer import get_admin_kpi as pl_admin

        snap = build_growth_conversion_snapshot(
            conn_factory=_conn,
            days=30,
            get_admin_kpi=pl_admin,
        )
        funnel_ob = snap.get("onboarding_funnel") or {}
        pilot = snap.get("pilot") or {}
        lines.extend(
            [
                "",
                "## Wave 6 — Onboarding conversion & pilot",
                "",
                f"- Autopilot seen: **{funnel_ob.get('autopilot_seen')}**",
                f"- Deep analysis: **{funnel_ob.get('deep_analysis')}**",
                f"- Onboarding complete: **{funnel_ob.get('onboarding_complete')}**",
                f"- Waitlist joins: **{funnel_ob.get('waitlist_join')}**",
                f"- Upgrade success: **{funnel_ob.get('upgrade_success')}**",
                f"- Pilot status: **{pilot.get('status')}** — {pilot.get('note_vi')}",
                f"- Paper closed@40d: **{pilot.get('paper_closed_40d')}** ({pilot.get('paper_note')})",
            ]
        )
    except Exception:
        lines.extend(["", "## Wave 6 — Onboarding conversion & pilot", "", "_Snapshot unavailable._"])

    lines.extend(["", "---", "", "Retention proxy: active_users / users_total (not revenue)."])
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export weekly growth markdown + JSON.")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--md-out", default="artifacts/operations/weekly_growth_report.md")
    ap.add_argument("--json-out", default="artifacts/operations/weekly_growth_report.json")
    args = ap.parse_args()

    md = build_weekly_growth_markdown(days=int(args.days))
    md_out = ROOT / str(args.md_out)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(md, encoding="utf-8")

    from core.analytics_service import get_admin_kpi
    from core.product_layer import _conn
    from core.referral_service import fetch_referral_stats

    payload = {
        "admin_kpi": get_admin_kpi(conn_factory=_conn, days=30),
        "referral": fetch_referral_stats(conn_factory=_conn, days=30),
        "markdown_path": str(md_out),
    }
    json_out = ROOT / str(args.json_out)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"markdown": str(md_out), "json": str(json_out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
