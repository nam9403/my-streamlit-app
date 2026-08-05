#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import core.product_layer as product_layer  # noqa: E402


def _resolve_env(explicit_env: str | None = None) -> str:
    raw = str(explicit_env or os.environ.get("II_ENV") or "dev").strip().lower()
    if raw in ("prod", "production"):
        return "prod"
    if raw in ("preprod", "staging", "stage"):
        return "preprod"
    return "dev"


def _ensure_non_prod(env_name: str, *, allow_prod: bool) -> None:
    if env_name == "prod" and not allow_prod:
        raise RuntimeError(
            "Refuse to seed forecast data in production. "
            "Use --allow-prod only when you intentionally run a controlled simulation."
        )


def _append_audit_log(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _build_resolved_rows(
    *,
    user_id: str,
    symbols: list[str],
    samples: int,
    target_win_rate_pct: float,
    base_price: float,
) -> list[tuple[Any, ...]]:
    rng = random.Random(42)
    symbols = [s.strip().upper() for s in symbols if s.strip()]
    if not symbols:
        symbols = ["FPT", "VNM", "HPG", "VCB"]
    target = max(0.0, min(100.0, float(target_win_rate_pct))) / 100.0
    now = datetime.now(UTC)
    out: list[tuple[Any, ...]] = []
    horizons = [30, 60, 90]
    for i in range(max(1, int(samples))):
        sym = symbols[i % len(symbols)]
        created_at = (now - timedelta(days=min(360, i * 3 + 1))).isoformat()
        horizon_days = horizons[i % len(horizons)]
        base = float(base_price) * (1.0 + (i % 5) * 0.02)
        expected_ret = 4.0 + (i % 4) * 2.5
        expected_price = base * (1.0 + expected_ret / 100.0)
        is_win = rng.random() < target
        realized_ret = expected_ret * (0.65 + rng.random() * 0.45) if is_win else -abs(1.5 + rng.random() * 6.0)
        realized_price = base * (1.0 + realized_ret / 100.0)
        abs_error = abs(realized_ret - expected_ret)
        direction_hit = 1 if realized_ret > 0 else 0
        out.append(
            (
                user_id,
                sym,
                created_at,
                int(horizon_days),
                round(base, 4),
                round(expected_price, 4),
                round(expected_ret, 4),
                round(realized_price, 4),
                round(realized_ret, 4),
                round(abs_error, 4),
                int(direction_hit),
                "resolved",
            )
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", default="default_user")
    ap.add_argument("--symbols", default="FPT,VNM,HPG,VCB")
    ap.add_argument("--samples", type=int, default=36)
    ap.add_argument("--target-win-rate-pct", type=float, default=70.0)
    ap.add_argument("--base-price", type=float, default=100.0)
    ap.add_argument("--reset-user", action="store_true")
    ap.add_argument("--env", default="", help="Runtime env (dev/preprod/prod). Defaults to II_ENV.")
    ap.add_argument("--allow-prod", action="store_true", help="Allow seeding in prod (dangerous, explicit only).")
    ap.add_argument("--audit-log", default="artifacts/operations/seed_forecast_audit.jsonl")
    args = ap.parse_args()

    env_name = _resolve_env(str(args.env or "").strip() or None)
    _ensure_non_prod(env_name, allow_prod=bool(args.allow_prod))

    user_id = str(args.user_id).strip() or "default_user"
    symbols = [x.strip().upper() for x in str(args.symbols).split(",") if x.strip()]
    rows = _build_resolved_rows(
        user_id=user_id,
        symbols=symbols,
        samples=max(1, int(args.samples)),
        target_win_rate_pct=float(args.target_win_rate_pct),
        base_price=float(args.base_price),
    )

    with product_layer._conn() as c:  # noqa: SLF001
        if bool(args.reset_user):
            c.execute("DELETE FROM forecast_records WHERE user_id=?", (user_id,))
        c.executemany(
            """
            INSERT INTO forecast_records(
                user_id, symbol, created_at, horizon_days,
                base_price, expected_price, expected_return_pct,
                realized_price, realized_return_pct, abs_error_pct, direction_hit, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    report = product_layer.get_forecast_backtesting_report(user_id, lookback_days=365)
    summary = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "seeded_data": True,
        "env": env_name,
        "user_id": user_id,
        "inserted_rows": len(rows),
        "predicted_up_samples": report.get("predicted_up_samples"),
        "win_rate_pct": report.get("win_rate_pct"),
        "avg_abs_error_pct": report.get("avg_abs_error_pct"),
    }
    _append_audit_log(Path(str(args.audit_log)), summary)
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
