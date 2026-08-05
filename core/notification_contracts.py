from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotificationChannels:
    tg_bot: str = ""
    tg_chat: str = ""
    webhook_url: str = ""
    email_to: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    auto_notify: bool = False

    def has_any_channel(self) -> bool:
        return bool((self.tg_bot and self.tg_chat) or self.webhook_url or self.smtp_ready())

    def smtp_ready(self) -> bool:
        return bool(self.email_to and self.smtp_host and self.smtp_user and self.smtp_password)

    def dispatch_kwargs(self) -> dict[str, object]:
        return {
            "telegram_bot_token": self.tg_bot,
            "telegram_chat_id": self.tg_chat,
            "webhook_url": self.webhook_url,
            "email_to": self.email_to,
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "smtp_user": self.smtp_user,
            "smtp_password": self.smtp_password,
            "smtp_from": self.smtp_from,
        }
