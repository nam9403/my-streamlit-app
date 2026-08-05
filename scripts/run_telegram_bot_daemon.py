"""
Telegram Bot daemon — interactive commands + morning digest + watchlist alerts.

Requires: python-telegram-bot>=21 (async), TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID.

Foreground:
  python scripts/run_telegram_bot_daemon.py

Background (Windows PowerShell):
  Start-Process -WindowStyle Hidden -FilePath python `
    -ArgumentList "scripts/run_telegram_bot_daemon.py" `
    -WorkingDirectory "E:\\Du an 1" `
    -RedirectStandardOutput "data\\runtime\\telegram_bot.out.log" `
    -RedirectStandardError "data\\runtime\\telegram_bot.err.log"

  # hoặc Job:
  Start-Job -Name ii_tg_bot -ScriptBlock {
    Set-Location "E:\\Du an 1"
    python scripts/run_telegram_bot_daemon.py
  }

Background (Linux/macOS):
  nohup python scripts/run_telegram_bot_daemon.py >> data/runtime/telegram_bot.log 2>&1 &

Dry-run (không poll Telegram, chỉ in digest/top):
  python scripts/run_telegram_bot_daemon.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import env_bootstrap  # noqa: F401
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [tg-bot] %(message)s",
)
logger = logging.getLogger("telegram_bot_daemon")

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{2,6}$")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Investment Intelligence Telegram bot daemon")
    ap.add_argument("--user-id", default=os.environ.get("II_TG_USER_ID", "default_user"))
    ap.add_argument("--profile", default=os.environ.get("II_DEFAULT_PROFILE", "growth"))
    ap.add_argument("--capital", type=float, default=float(os.environ.get("II_TG_CAPITAL", "200000000") or 2e8))
    ap.add_argument("--alert-interval-sec", type=int, default=int(os.environ.get("II_TG_ALERT_INTERVAL_SEC", "900") or 900))
    ap.add_argument("--dry-run", action="store_true", help="In digest/top, không chạy long-poll")
    ap.add_argument("--once-digest", action="store_true", help="Gửi Morning Digest một lần rồi thoát")
    ap.add_argument("--once-alerts", action="store_true", help="Quét watchlist alerts một lần rồi thoát")
    return ap.parse_args()


def _inline_keyboard():
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Top 5 Autopilot", callback_data="cmd:top"),
                InlineKeyboardButton("Hướng dẫn", callback_data="cmd:help"),
            ],
            [
                InlineKeyboardButton("PNJ", callback_data="analyze:PNJ"),
                InlineKeyboardButton("ACB", callback_data="analyze:ACB"),
                InlineKeyboardButton("FPT", callback_data="analyze:FPT"),
            ],
        ]
    )


async def _reply_html(update, text: str, *, reply_markup=None) -> None:
    msg = update.effective_message
    if msg is None:
        return
    await msg.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
        disable_web_page_preview=True,
    )


async def _send_owner_html(bot, chat_id: str, text: str) -> None:
    if not chat_id:
        return
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def _authorized(update, allowed: set[str]) -> bool:
    if not allowed:
        return True  # open if no owner configured (local/dev)
    chat = update.effective_chat
    user = update.effective_user
    cid = str(chat.id) if chat else ""
    uid = str(user.id) if user else ""
    return cid in allowed or uid in allowed


async def cmd_start(update, context) -> None:
    from core.telegram_bot_service import HELP_TEXT_HTML

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return
    await _reply_html(update, HELP_TEXT_HTML, reply_markup=_inline_keyboard())


async def cmd_help(update, context) -> None:
    await cmd_start(update, context)


async def cmd_p(update, context) -> None:
    from core.product_layer import get_deep_analysis
    from core.telegram_bot_service import format_mini_decision_card_html

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return

    args = context.args or []
    sym = str(args[0]).strip().upper() if args else ""
    if not _SYMBOL_RE.match(sym):
        await _reply_html(update, "Dùng: <code>/p PNJ</code>")
        return

    await _reply_html(update, f"⏳ Đang phân tích <b>{sym}</b>…")
    profile = str(context.application.bot_data.get("profile") or "growth")
    capital = float(context.application.bot_data.get("capital") or 2e8)

    def _run():
        return get_deep_analysis(sym, profile=profile, total_capital_vnd=capital, quick_mode=True, llm_live=False)

    try:
        analysis = await asyncio.to_thread(_run)
    except Exception as exc:
        await _reply_html(update, f"❌ Lỗi phân tích: <code>{exc.__class__.__name__}</code>")
        return

    if analysis.get("error") and not analysis.get("report"):
        await _reply_html(update, f"❌ Không phân tích được {sym}: <code>{analysis.get('error')}</code>")
        return

    try:
        card = format_mini_decision_card_html(analysis)
    except Exception as exc:
        await _reply_html(update, f"❌ Format card lỗi: <code>{exc.__class__.__name__}</code>")
        return
    await _reply_html(update, card)


async def cmd_top(update, context) -> None:
    from core.telegram_bot_service import format_top5_html, load_top5_from_board

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return

    def _run():
        return load_top5_from_board(top_n=5)

    rows, meta = await asyncio.to_thread(_run)
    await _reply_html(update, format_top5_html(rows, board_meta=meta))


async def cmd_watch(update, context) -> None:
    from core.telegram_bot_service import add_to_watchlist, load_watchlist

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return
    args = context.args or []
    sym = str(args[0]).strip().upper() if args else ""
    if not _SYMBOL_RE.match(sym):
        await _reply_html(update, "Dùng: <code>/watch PNJ</code>")
        return
    lst, added = add_to_watchlist(sym)
    if added:
        await _reply_html(update, f"✅ Đã thêm <b>{sym}</b> vào watchlist ({len(lst)} mã).")
    else:
        await _reply_html(update, f"ℹ️ <b>{sym}</b> đã có trong watchlist ({len(lst)} mã).")


async def cmd_unwatch(update, context) -> None:
    from core.telegram_bot_service import remove_from_watchlist

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return
    args = context.args or []
    sym = str(args[0]).strip().upper() if args else ""
    if not _SYMBOL_RE.match(sym):
        await _reply_html(update, "Dùng: <code>/unwatch PNJ</code>")
        return
    lst, removed = remove_from_watchlist(sym)
    if removed:
        await _reply_html(update, f"✅ Đã gỡ <b>{sym}</b>. Còn {len(lst)} mã.")
    else:
        await _reply_html(update, f"ℹ️ <b>{sym}</b> không có trong watchlist.")


async def cmd_watchlist(update, context) -> None:
    from core.telegram_bot_service import load_watchlist

    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await _reply_html(update, "⛔ Không có quyền dùng bot này.")
        return
    lst = load_watchlist()
    if not lst:
        await _reply_html(update, "Watchlist trống. Thêm bằng <code>/watch PNJ</code>.")
        return
    body = ", ".join(f"<code>{s}</code>" for s in lst)
    await _reply_html(update, f"<b>Watchlist ({len(lst)})</b>\n{body}")


async def on_callback(update, context) -> None:
    q = update.callback_query
    if q is None:
        return
    await q.answer()
    data = str(q.data or "")
    if not _authorized(update, context.application.bot_data.get("allowed_chats") or set()):
        await q.edit_message_text("⛔ Không có quyền.")
        return
    if data == "cmd:help":
        from core.telegram_bot_service import HELP_TEXT_HTML

        await q.edit_message_text(HELP_TEXT_HTML, parse_mode="HTML", reply_markup=_inline_keyboard())
        return
    if data == "cmd:top":
        from core.telegram_bot_service import format_top5_html, load_top5_from_board

        rows, meta = await asyncio.to_thread(lambda: load_top5_from_board(top_n=5))
        await q.edit_message_text(format_top5_html(rows, board_meta=meta), parse_mode="HTML")
        return
    if data.startswith("analyze:"):
        sym = data.split(":", 1)[-1].strip().upper()
        # Reuse /p flow via fake args
        context.args = [sym]
        await cmd_p(update, context)


async def _scheduler_loop(application) -> None:
    """Morning digest 08:15 VN + watchlist alerts mỗi N giây trong phiên."""
    import time as time_mod

    from core.telegram_bot_service import (
        build_morning_digest_html,
        is_vn_session_hours,
        is_vn_trading_day,
        scan_watchlist_alerts,
        vn_now,
    )

    owner = str(application.bot_data.get("owner_chat_id") or "")
    interval = int(application.bot_data.get("alert_interval_sec") or 900)
    last_digest_day: str | None = None
    last_alert_ts = 0.0
    logger.info("scheduler started owner=%s interval=%ss", owner or "(none)", interval)

    while True:
        try:
            now = vn_now()
            day_key = now.strftime("%Y-%m-%d")

            # Morning digest window: 08:15–08:29 trading days
            if (
                owner
                and is_vn_trading_day(now)
                and last_digest_day != day_key
                and time(8, 15) <= now.time() < time(8, 30)
            ):
                html = await asyncio.to_thread(lambda: build_morning_digest_html(top_n=5))
                await _send_owner_html(application.bot, owner, html)
                last_digest_day = day_key
                logger.info("morning digest sent day=%s", day_key)

            now_ts = time_mod.time()
            if owner and is_vn_session_hours(now) and (now_ts - last_alert_ts) >= interval:
                last_alert_ts = now_ts
                alerts = await asyncio.to_thread(scan_watchlist_alerts)
                for a in alerts:
                    await _send_owner_html(application.bot, owner, str(a.get("text_html") or ""))
                    logger.info("watchlist alert symbol=%s", a.get("symbol"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("scheduler tick failed: %s", exc.__class__.__name__, exc_info=True)

        await asyncio.sleep(45)


async def _post_init(application) -> None:
    asyncio.create_task(_scheduler_loop(application))


def build_application(*, token: str, owner_chat: str, profile: str, capital: float, alert_interval: int, user_id: str):
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler

    from core.telegram_bot_service import allowed_chat_ids

    app = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .build()
    )
    app.bot_data["owner_chat_id"] = owner_chat
    app.bot_data["allowed_chats"] = allowed_chat_ids(owner_chat)
    app.bot_data["profile"] = profile
    app.bot_data["capital"] = capital
    app.bot_data["alert_interval_sec"] = alert_interval
    app.bot_data["user_id"] = user_id

    app.add_handler(CommandHandler(["start", "help"], cmd_start))
    app.add_handler(CommandHandler("p", cmd_p))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("watchlist", cmd_watchlist))
    app.add_handler(CallbackQueryHandler(on_callback))
    return app


def main() -> int:
    args = _parse_args()
    from core.telegram_bot_service import (
        build_morning_digest_html,
        format_top5_html,
        load_top5_from_board,
        resolve_bot_credentials,
        scan_watchlist_alerts,
    )

    token, chat = resolve_bot_credentials(user_id=str(args.user_id))

    if args.dry_run:
        rows, meta = load_top5_from_board(top_n=5)
        out = format_top5_html(rows, board_meta=meta) + "\n---\n" + build_morning_digest_html(top_n=5)
        try:
            print(out)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((out + "\n").encode("utf-8", errors="replace"))
        return 0

    if args.once_digest:
        if not token or not chat:
            print("ERROR: cần TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID", flush=True)
            return 1
        import requests

        html = build_morning_digest_html(top_n=5)
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": html, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=20,
        )
        print({"ok": r.status_code == 200, "status": r.status_code, "body": r.text[:200]})
        return 0 if r.status_code == 200 else 1

    if args.once_alerts:
        alerts = scan_watchlist_alerts()
        print({"alerts": len(alerts), "symbols": [a.get("symbol") for a in alerts]})
        if token and chat:
            import requests

            for a in alerts:
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat,
                        "text": a.get("text_html"),
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=20,
                )
        return 0

    if not token:
        print(
            "ERROR: thiếu TELEGRAM_BOT_TOKEN (env hoặc secret vault).\n"
            "Xem: python scripts/run_telegram_bot_daemon.py --help",
            flush=True,
        )
        return 1

    try:
        from telegram.ext import Application  # noqa: F401
    except ImportError:
        print("ERROR: cài python-telegram-bot>=21: pip install 'python-telegram-bot>=21'", flush=True)
        return 1

    app = build_application(
        token=token,
        owner_chat=chat,
        profile=str(args.profile),
        capital=float(args.capital),
        alert_interval=int(args.alert_interval_sec),
        user_id=str(args.user_id),
    )
    logger.info(
        "bot starting owner_chat=%s profile=%s alert_interval=%ss",
        chat or "(open)",
        args.profile,
        args.alert_interval_sec,
    )
    # drop_pending_updates tránh xử lý backlog khi restart
    app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
