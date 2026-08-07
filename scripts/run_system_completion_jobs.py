"""
Chạy các job hoàn thiện hệ thống theo thứ tự ROI (đêm / cuối tuần).

Thứ tự:
  1) Enrich ngành (seed VN30 + subtype)
  2) Refresh macro snapshot
  3) Refresh BCTC (watchlist ∪ VN30) — optional, có thể lâu

Ví dụ:
  python scripts/run_system_completion_jobs.py
  python scripts/run_system_completion_jobs.py --skip-financial
  python scripts/run_system_completion_jobs.py --symbols ACB,QTP,FPT
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass


def _run_py(script: str, *args: str) -> int:
    cmd = [sys.executable, str(ROOT / "scripts" / script), *args]
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    return int(subprocess.call(cmd, cwd=str(ROOT)))


def main() -> int:
    p = argparse.ArgumentParser(description="System completion jobs (industry → macro → BCTC)")
    p.add_argument("--skip-financial", action="store_true", help="Bỏ bước refresh BCTC live")
    p.add_argument("--skip-macro", action="store_true")
    p.add_argument("--skip-industry", action="store_true")
    p.add_argument("--skip-metadata-expand", action="store_true", help="Bỏ seed metadata liquid pool")
    p.add_argument("--liquid-financial", action="store_true", help="Refresh BCTC cho liquid pool (đêm)")
    p.add_argument("--liquid-limit", type=int, default=120, help="Cap symbols khi --liquid-financial")
    p.add_argument("--symbols", default="", help="CSV ghi đè universe BCTC (mặc định vn30+watchlist)")
    p.add_argument("--sleep", type=float, default=0.35)
    p.add_argument("--paper-resolve", action="store_true", help="Resolve due paper trades")
    p.add_argument("--paper-report", action="store_true", help="Export paper accountability JSON/MD")
    p.add_argument("--paper-weekly", action="store_true", help="Export Wave4 paper weekly + kill-switch")
    p.add_argument("--vn30-completeness", action="store_true", help="Audit VN30 missing_items")
    p.add_argument("--morning-digest", action="store_true", help="Send/dry-run morning digest")
    p.add_argument("--morning-digest-dry", action="store_true", help="Morning digest dry-run only")
    p.add_argument("--slo-export", action="store_true", help="Export SLO snapshot JSON")
    p.add_argument("--trust-page", action="store_true", help="Export public trust markdown")
    p.add_argument("--weekly-growth", action="store_true", help="Export weekly growth report")
    p.add_argument("--audit-pack", action="store_true", help="Export process audit pack")
    p.add_argument("--production-check", action="store_true", help="Verify II_ENV=prod profile")
    args = p.parse_args()

    rc = 0
    if not args.skip_industry:
        code = _run_py("enrich_industry_subtype.py", "--seed-vn30")
        rc = max(rc, code)

    if not args.skip_metadata_expand:
        code = _run_py("expand_stock_metadata_liquid.py")
        rc = max(rc, code)

    if not args.skip_macro:
        print("\n>>> refresh macro snapshot", flush=True)
        try:
            # Ép hết TTL bằng cách xóa age — gọi live refresh path
            from core.news_macro_service import get_macro_snapshot, macro_snapshot_path

            path = macro_snapshot_path()
            if path.exists():
                # Đánh dấu stale bằng cách ghi saved_at cũ
                import json
                from datetime import datetime, timedelta, timezone

                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    raw = {}
                if isinstance(raw, dict):
                    raw["saved_at"] = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
                    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            snap = get_macro_snapshot()
            print(
                f"macro source={snap.get('source')} bias={snap.get('market_bias')} "
                f"usd_vnd={snap.get('usd_vnd')} policy={snap.get('policy_rate_pct')}"
            )
        except Exception as e:
            print(f"macro ERROR: {e}", file=sys.stderr)
            rc = max(rc, 1)

    if not args.skip_financial:
        fin_args = ["--force", "--sleep", str(args.sleep)]
        if args.symbols.strip():
            fin_args.extend(["--symbols", args.symbols.strip()])
        elif args.liquid_financial:
            fin_args.extend(["--liquid", "--top10", "--watchlist"])
            if int(args.liquid_limit or 0) > 0:
                fin_args.extend(["--liquid-limit", str(int(args.liquid_limit))])
        else:
            fin_args.extend(["--vn30", "--watchlist", "--top10"])
        code = _run_py("refresh_financial_indicators.py", *fin_args)
        rc = max(rc, code)
        # Rebuild P/E–P/B ngành đa năm sau khi BCTC/indicators cập nhật.
        # --liquid mở rộng coverage; refresh statements để có BVPS.
        code = _run_py(
            "build_sector_multiples_5y.py",
            "--years",
            "5",
            "--liquid",
            "--liquid-limit",
            "120",
            "--refresh-statements",
            "--sleep",
            "0.3",
        )
        rc = max(rc, code)

    if args.paper_resolve:
        code = _run_py("resolve_paper_trades.py")
        rc = max(rc, code)

    if args.paper_report:
        code = _run_py("export_paper_accountability_report.py", *(["--resolve"] if args.paper_resolve else []))
        rc = max(rc, code)

    if args.paper_weekly:
        code = _run_py("export_paper_weekly_report.py", *(["--resolve"] if args.paper_resolve else []))
        rc = max(rc, code)

    if args.vn30_completeness:
        code = _run_py("audit_vn30_completeness.py")
        rc = max(rc, code)

    if args.morning_digest or args.morning_digest_dry:
        digest_args = ["--dry-run"] if (args.morning_digest_dry or not args.morning_digest) else []
        code = _run_py("send_morning_digest.py", *digest_args)
        rc = max(rc, code)

    if args.slo_export:
        code = _run_py("export_slo_snapshot.py")
        rc = max(rc, code)

    if args.trust_page:
        code = _run_py("export_public_trust_page.py")
        rc = max(rc, code)

    if args.weekly_growth:
        code = _run_py("export_weekly_growth_report.py")
        rc = max(rc, code)
        code = _run_py("export_growth_conversion_snapshot.py")
        rc = max(rc, code)

    if args.audit_pack:
        code = _run_py("export_process_audit_pack.py")
        rc = max(rc, code)

    if args.production_check:
        code = _run_py("ensure_production_profile.py", "--strict")
        rc = max(rc, code)

    print(f"\nCompletion jobs finished rc={rc}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
