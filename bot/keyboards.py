"""Inline keyboards — menu, navigation, admin."""

from aiogram.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB


def _b(text, data):
    return IKB(text=text, callback_data=data)


# ━━━━━━━━━━━━ MAIN MENU ━━━━━━━━━━━━

MAIN = IKM(inline_keyboard=[
    [_b("🖼 Фото", "cat:photo"),
     _b("🎥 Видео", "cat:video")],
    [_b("🛠 Инструменты", "cat:tools")],
    [_b("👤 Профиль", "p:profile"),
     _b("💰 Пополнить", "p:topup"),
     _b("⚙️", "p:settings")],
])

# ━━━━━━━━━━━━ CATEGORIES ━━━━━━━━━━━━

PHOTO = IKM(inline_keyboard=[
    [_b("🎨 Создать из текста · 1⭐", "tool:gen")],
    [_b("✏️ Редактировать фото · 1⭐", "tool:edit")],
    [_b("🔄 Изменить стиль · 1⭐", "tool:style")],
    [_b("◀️ Назад", "nav:main")],
])

VIDEO = IKM(inline_keyboard=[
    [_b("📝 Текст → Видео · 5⭐", "tool:vid_text")],
    [_b("🖼 Фото → Видео · 5⭐", "tool:vid_img")],
    [_b("◀️ Назад", "nav:main")],
])

TOOLS = IKM(inline_keyboard=[
    [_b("🗑 Убрать фон · 1⭐", "tool:rmbg")],
    [_b("🔍 Улучшить качество 2x · 1⭐", "tool:upscale")],
    [_b("◀️ Назад", "nav:main")],
])

# ━━━━━━━━━━━━ PROFILE ━━━━━━━━━━━━

PROFILE = IKM(inline_keyboard=[
    [_b("💰 Пополнить", "p:topup"),
     _b("📊 История", "p:history")],
    [_b("🤝 Пригласить друга", "p:referral")],
    [_b("🎟 Промокод", "p:promo")],
    [_b("◀️ Назад", "nav:main")],
])

BACK_TO_PROFILE = IKM(inline_keyboard=[
    [_b("◀️ Профиль", "p:profile")],
])

# ━━━━━━━━━━━━ TOPUP ━━━━━━━━━━━━

TOPUP_METHOD = IKM(inline_keyboard=[
    [_b("⭐ Telegram Stars", "pay:m:stars")],
    [_b("💎 Криптовалюта", "pay:m:crypto")],
    [_b("◀️ Назад", "p:profile")],
])

TOPUP_STARS = IKM(inline_keyboard=[
    [_b("50 ⭐", "pay:s:50"),
     _b("150 ⭐", "pay:s:150")],
    [_b("500 ⭐", "pay:s:500"),
     _b("1000 ⭐", "pay:s:1000")],
    [_b("◀️ Назад", "p:topup")],
])

TOPUP_CRYPTO = IKM(inline_keyboard=[
    [_b("50⭐ · $1", "pay:c:50"),
     _b("150⭐ · $2.50", "pay:c:150")],
    [_b("500⭐ · $7", "pay:c:500"),
     _b("1000⭐ · $12", "pay:c:1000")],
    [_b("◀️ Назад", "p:topup")],
])

# ━━━━━━━━━━━━ SETTINGS ━━━━━━━━━━━━

def settings_kb(cur: str) -> IKM:
    m = [("gemini", "Gemini Flash ⚡"), ("gemini_pro", "Gemini Pro 🧠"), ("flux", "Flux 🎨")]
    rows = [[IKB(
        text=f"{'🟢' if k == cur else '▫️'} {n}",
        callback_data=f"set:m:{k}",
    )] for k, n in m]
    rows.append([_b("◀️ Назад", "nav:main")])
    return IKM(inline_keyboard=rows)

# ━━━━━━━━━━━━ RESULT — after tool completion ━━━━━━━━━━━━

def result_kb(tool_cb: str) -> IKM:
    return IKM(inline_keyboard=[
        [_b("🔄 Ещё раз", tool_cb),
         _b("◀️ Меню", "nav:main")],
    ])

# ━━━━━━━━━━━━ LOW BALANCE ━━━━━━━━━━━━

LOW_BALANCE = IKM(inline_keyboard=[
    [_b("💰 Пополнить", "p:topup"),
     _b("🤝 Пригласить друга", "p:referral")],
    [_b("◀️ Меню", "nav:main")],
])

# ━━━━━━━━━━━━ COMMON ━━━━━━━━━━━━

BACK = IKM(inline_keyboard=[[_b("◀️ Меню", "nav:main")]])

CANCEL = IKM(inline_keyboard=[[_b("❌ Отмена", "nav:main")]])

# ━━━━━━━━━━━━ ADMIN ━━━━━━━━━━━━

ADMIN = IKM(inline_keyboard=[
    [_b("📊 Статистика", "adm:stats"),
     _b("📋 Логи", "adm:logs")],
    [_b("📢 Рассылка", "adm:broadcast"),
     _b("👤 Юзер", "adm:user")],
    [_b("💰 Начислить", "adm:grant"),
     _b("🚫 Бан", "adm:ban")],
    [_b("🎟 Промокоды", "adm:promos"),
     _b("🔔 Уведомления", "adm:notify")],
    [_b("◀️ Назад", "nav:main")],
])

ADMIN_BACK = IKM(inline_keyboard=[[_b("◀️ Админ", "adm:panel")]])


def notify_settings_kb(settings: dict) -> IKM:
    labels = {
        "new_user": "👤 Новый юзер",
        "payment": "💰 Оплата",
        "tool_use": "🔧 Инструменты",
        "error": "❌ Ошибки",
        "referral": "🤝 Рефералы",
        "promo": "🎟 Промокоды",
    }
    rows = []
    for event, label in labels.items():
        on = settings.get(event, False)
        rows.append([IKB(
            text=f"{'🟢' if on else '🔴'} {label}",
            callback_data=f"adm:ntg:{event}",
        )])
    rows.append([_b("◀️ Админ", "adm:panel")])
    return IKM(inline_keyboard=rows)


def user_card_kb(tg_id: int, is_banned: bool) -> IKM:
    ban_text = "✅ Разбанить" if is_banned else "🚫 Забанить"
    return IKM(inline_keyboard=[
        [_b("💰 Начислить", f"adm:gr:{tg_id}"),
         _b(ban_text, f"adm:bn:{tg_id}")],
        [_b("◀️ Админ", "adm:panel")],
    ])
