"""Admin notification service — sends TG messages for configured events."""

import logging
from aiogram import Bot
from db import get_notify_settings, log_activity

log = logging.getLogger(__name__)

# Set by main.py on startup
_bot: Bot | None = None
_admin_ids: set[int] = set()

EVENT_LABELS = {
    "new_user": "👤 Новый пользователь",
    "payment": "💰 Оплата",
    "tool_use": "🔧 Использование",
    "error": "❌ Ошибка",
    "referral": "🤝 Реферал",
    "promo": "🎟 Промокод",
}


def init(bot: Bot, admin_ids: set[int]):
    global _bot, _admin_ids
    _bot = bot
    _admin_ids = admin_ids


async def notify(event: str, text: str, tg_id: int = None,
                 tool: str = "", details: str = ""):
    """Log event + send TG notification if enabled."""
    # Always log to DB
    try:
        await log_activity(tg_id or 0, event, tool, details or text)
    except Exception as e:
        log.warning("Failed to log activity: %s", e)

    if not _bot or not _admin_ids:
        return

    # Check if notifications enabled for this event
    try:
        settings = await get_notify_settings()
        if not settings.get(event, False):
            return
    except Exception:
        return

    label = EVENT_LABELS.get(event, event)
    msg = f"{label}\n{text}"

    for admin_id in _admin_ids:
        try:
            await _bot.send_message(admin_id, msg)
        except Exception as e:
            log.debug("Notify failed for %s: %s", admin_id, e)
