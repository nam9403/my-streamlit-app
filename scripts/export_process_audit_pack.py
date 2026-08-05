"""
Process audit pack (P3): chứng nhận quy trình — không cam kết lợi nhuận.

  python scripts/export_process_audit_pack.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

_PROCESS_DISCLAIMER = (
    "Gói audit quy trình mô tả kiểm soát vận hành và minh bạch dữ liệu. "
    "Không phải chứng nhận đầu tư, không cam kết lợi nhuận."
)


def _read_json(rel: str) -> dict:
    p = ROOT / rel
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _pytest_passed() -> str:
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no", "-x"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=600,
        )
        tail = (r.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else f"exit={r.returncode}"
        return "PASS" if r.returncode == 0 else f"FAIL ({summary})"
    except Exception as exc:
        return f"SKIP ({exc.__class__.__name__})"


def build_audit_markdown(*, run_pytest: bool = False) -> str:
    from core.slo_ops_panel import collect_slo_snapshot

    snap = collect_slo_snapshot()
    health = snap.get("nightly_health") or {}
    paper = snap.get("paper_accountability") or _read_json("artifacts/operations/paper_trade_accountability.json")
    vn30 = _read_json("artifacts/operations/vn30_completeness_audit.json")
    trust_exists = (ROOT / "artifacts/operations/public_trust_page.md").exists()

    lines = [
        "# Process audit pack (P3)",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
        _PROCESS_DISCLAIMER,
        "",
        "## 1. Data & nightly pipeline",
        "",
        f"- Nightly board OK: **{health.get('ok')}**",
        f"- Coverage: **{health.get('coverage_pct')}%**",
        f"- Fail rate: **{snap.get('fail_rate_pct')}%**",
        f"- Board age (h): **{health.get('age_hours')}**",
        "",
        "## 2. Decision quality controls",
        "",
        "- Completeness gate (CFO/NI/bank-aware): `core/decision_completeness.py`",
        "- Unified action gate: `core/decision_action_gate.py`",
        "- Decision playbook (Thesis/Setup/Trigger): `core/decision_playbook.py`",
        "- CONDITIONAL_BUY in gate + board ranking",
        "- Data integrity (OHLCV/MOS/RSI/paper allowlist): `core/data_integrity.py`",
        "- Data trust score: `core/data_trust_score.py`",
        "- Proprietary blend (flow+val+phase+WF+playbook nudge): `core/proprietary_signal.py`",
        "- Live Autopilot ranking = nightly `score_rows`",
        "",
        "## 3. Accountability artifacts",
        "",
    ]
    if isinstance(paper, dict):
        wins = paper.get("windows") or {}
        w30 = wins.get("30") if isinstance(wins, dict) else {}
        lines.append(f"- Paper 30d samples: **{(w30 or {}).get('samples', '—')}**")
        lines.append(f"- Paper 30d hit-rate: **{(w30 or {}).get('hit_rate_pct', '—')}%**")
    lines.append(f"- Public trust page present: **{trust_exists}**")
    if vn30:
        lines.append(
            f"- VN30 completeness avg missing: **{vn30.get('avg_missing_count')}** "
            f"({vn30.get('symbols_with_missing')}/{vn30.get('audited_ok')} with gaps)"
        )

    lines.extend(
        [
            "",
            "## 4. SLO / performance",
            "",
        ]
    )
    ap = snap.get("autopilot_timing") or {}
    lines.append(f"- Autopilot p95: **{ap.get('p95_ms') or ap.get('p95') or '—'}**")
    lines.append(f"- Fail rate nightly scan: **{snap.get('fail_rate_pct') or '—'}%**")

    lines.extend(["", "## 5. Test suite", ""])
    if run_pytest:
        lines.append(f"- Pytest (quick): **{_pytest_passed()}**")
    else:
        lines.append("- Pytest: _not run (use `--with-pytest` to include)_")

    lines.extend(
        [
            "",
            "## 6. Production database & growth",
            "",
            f"- II_DB_URL set: **{bool(__import__('os').environ.get('II_DB_URL'))}**",
            f"- II_ENV: **{__import__('os').environ.get('II_ENV') or 'dev'}**",
            f"- Universe mode default: **dynamic_liquid** (`II_AUTOPILOT_UNIVERSE_MODE`)",
            "",
        ]
    )
    try:
        from scripts.ensure_production_profile import check_production_profile

        prod = check_production_profile(strict=False)
        lines.append(f"- Production profile ok: **{prod.get('ok')}**")
        if prod.get("issues"):
            lines.append(f"- Issues: {', '.join(prod['issues'])}")
        if prod.get("warnings"):
            lines.append(f"- Warnings: {', '.join(prod['warnings'])}")
    except Exception as exc:
        lines.append(f"- Production profile check: skip ({exc.__class__.__name__})")

    lines.extend(
        [
            "",
            "---",
            "",
            "Audit này mô tả quy trình nội bộ; không thay thế tư vấn pháp lý/đầu tư.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="Export process audit pack.")
    ap.add_argument("--md-out", default="artifacts/operations/process_audit_pack.md")
    ap.add_argument("--json-out", default="artifacts/operations/process_audit_pack.json")
    ap.add_argument("--with-pytest", action="store_true")
    args = ap.parse_args()

    md = build_audit_markdown(run_pytest=bool(args.with_pytest))
    md_out = ROOT / str(args.md_out)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.write_text(md, encoding="utf-8")

    payload = {"markdown_path": str(md_out), "disclaimer": _PROCESS_DISCLAIMER, "generated_at": datetime.now(timezone.utc).isoformat()}
    json_out = ROOT / str(args.json_out)
    json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
