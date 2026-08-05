#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_guardian_health(
    payload: dict[str, Any],
    *,
    max_failures: int,
    min_checked: int,
    max_suppressed_ratio: float,
) -> tuple[str, list[str]]:
    checked = int(payload.get("checked") or 0)
    failures = int(payload.get("failures") or 0)
    suppressed = int(payload.get("suppressed_cooldown") or 0)
    reasons: list[str] = []
    status = "ok"

    if checked < int(min_checked):
        status = "warn"
        reasons.append("Số lượng mã được quét thấp hơn ngưỡng kỳ vọng.")
    if failures > int(max_failures):
        status = "critical"
        reasons.append("Số lỗi runtime trong chu kỳ guardian vượt ngưỡng.")
    if checked > 0:
        suppressed_ratio = suppressed / checked
        if suppressed_ratio > float(max_suppressed_ratio):
            status = "warn" if status != "critical" else status
            reasons.append("Tỷ lệ cảnh báo bị cooldown quá cao, cần rà lại tín hiệu và chu kỳ quét.")
    return status, reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--in",
        dest="in_path",
        default="artifacts/operations/runtime_guardian_health.json",
        help="Guardian health artifact path",
    )
    ap.add_argument("--max-failures", type=int, default=3)
    ap.add_argument("--min-checked", type=int, default=5)
    ap.add_argument("--max-suppressed-ratio", type=float, default=0.85)
    ap.add_argument("--require-ok", action="store_true")
    args = ap.parse_args()

    p = Path(str(args.in_path))
    if not p.exists():
        print(json.dumps({"status": "critical", "reasons": ["Guardian health artifact not found."], "path": str(p)}, ensure_ascii=False, indent=2))
        return 2
    payload = json.loads(p.read_text(encoding="utf-8"))
    status, reasons = evaluate_guardian_health(
        payload,
        max_failures=max(0, int(args.max_failures)),
        min_checked=max(0, int(args.min_checked)),
        max_suppressed_ratio=max(0.0, min(float(args.max_suppressed_ratio), 1.0)),
    )
    out = {"status": status, "reasons": reasons, "input": str(p), "stats": payload}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.require_ok and status != "ok":
        return 3 if status == "warn" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
