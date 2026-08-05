"""
Send morning Autopilot digest to Telegram / webhook / email.

  python scripts/send_morning_digest.py
  python scripts/send_morning_digest.py --dry-run
  python scripts/send_morning_digest.py --user-id default_user
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Send morning Autopilot digest.")
    ap.add_argument("--user-id", default="default_user")
    ap.add_argument("--top-n", type=int, default=10)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default="artifacts/operations/morning_digest_latest.json")
    args = ap.parse_args()

    from core.morning_digest_service import load_digest_payload
    from core.product_layer import dispatch_text_notifications, load_secret

    df, meta, text = load_digest_payload(top_n=int(args.top_n))
    uid = str(args.user_id or "default_user")
    tg_bot = str(load_secret(uid, "telegram_bot_token") or "")
    tg_chat = str(load_secret(uid, "telegram_chat_id") or "")
    webhook = str(load_secret(uid, "webhook_url") or "")
    email_to = str(load_secret(uid, "alert_email_to") or "")

    send_stat = {"sent": 0, "failed": 0, "dry_run": bool(args.dry_run)}
    if not args.dry_run:
        send_stat = dispatch_text_notifications(
            text,
            telegram_bot_token=tg_bot,
            telegram_chat_id=tg_chat,
            webhook_url=webhook,
            email_to=email_to,
        )
    paper = (meta or {}).get("paper") if isinstance(meta, dict) else None
    payload = {
        "user_id": uid,
        "meta": meta,
        "paper": paper,
        "top_symbols": []
        if df is None or df.empty
        else [str(x) for x in df["Mã"].head(10).tolist()]
        if "Mã" in df.columns
        else [],
        "text": text,
        "send": send_stat,
        "channels_configured": {
            "telegram": bool(tg_bot and tg_chat),
            "webhook": bool(webhook),
            "email": bool(email_to),
        },
    }
    out = ROOT / str(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: payload[k]
                for k in ("top_symbols", "send", "channels_configured", "paper", "meta")
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("\n--- DIGEST ---\n" + text)
    if not args.dry_run and not payload["channels_configured"]["telegram"] and not payload["channels_configured"]["webhook"]:
        print("WARN: no telegram/webhook configured for user; nothing delivered.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
