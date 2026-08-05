#!/usr/bin/env python3
"""
Export pilot KPI snapshot (Admin + CX) to JSON file.

Usage:
  python scripts/export_pilot_kpi_snapshot.py
  python scripts/export_pilot_kpi_snapshot.py --out data/reports/pilot_kpi_snapshot.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.product_layer import get_admin_cx_kpi, get_admin_kpi  # noqa: E402


def _derive_actions(admin: dict, cx: dict) -> list[str]:
    out: list[str] = []
    cx_avg = float(cx.get("avg_score") or 0.0)
    cx_samples = int(cx.get("samples") or 0)
    queue_rows = admin.get("notification_queue") or []
    q_failed = 0
    q_total = 0
    for r in queue_rows:
        c = int(r.get("count") or 0)
        q_total += c
        if str(r.get("status") or "").lower() == "failed":
            q_failed += c
    q_fail_ratio = (q_failed / q_total) if q_total > 0 else 0.0

    if cx_samples <= 0:
        out.append("P0: Chưa có dữ liệu CX, cần tăng usage Command Center để ghi điểm hằng ngày.")
    if cx_avg < 70 and cx_samples > 0:
        out.append("P0: CX avg dưới ngưỡng, ưu tiên ổn định flow onboarding/alerts/latency.")
    if q_fail_ratio > 0.25:
        out.append("P0: Queue fail ratio cao, cần xử lý lỗi kênh gửi và retry ngay.")
    obs = admin.get("notification_observability") or {}
    tiers = obs.get("retry_tiers") or []
    high_retry = 0
    for t in tiers:
        tier = str(t.get("retry_tier") or "")
        if tier in ("t3_4", "t5_plus"):
            high_retry += int(t.get("count") or 0)
    if high_retry > 0:
        out.append("P1: Có hàng đợi retry cao (t3+), cần giảm nguyên nhân lỗi gốc để tránh burn retry.")
    if int(admin.get("active_users_period") or 0) <= 0:
        out.append("P1: Active user thấp, cần chiến dịch giữ chân tuần đầu.")
    if not out:
        out.append("Tín hiệu ổn định: tiếp tục theo dõi và tối ưu conversion analysis -> decision.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days-admin", type=int, default=30, help="Window days for admin KPI.")
    ap.add_argument("--days-cx", type=int, default=14, help="Window days for CX KPI.")
    ap.add_argument(
        "--out",
        default=str(ROOT / "data" / "reports" / "pilot_kpi_snapshot.json"),
        help="Output JSON path.",
    )
    args = ap.parse_args()

    admin = get_admin_kpi(days=max(1, int(args.days_admin)))
    cx = get_admin_cx_kpi(days=max(1, int(args.days_cx)))
    actions = _derive_actions(admin, cx)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "window_days": {"admin": int(args.days_admin), "cx": int(args.days_cx)},
        "admin": admin,
        "cx": cx,
        "priority_actions": actions,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
