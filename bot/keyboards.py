"""Inline keyboards — 2-level menu, clean navigation."""

from aiogram.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB


def _b(text, data):
    return IKB(text=text, callback_data=data)


# ━━━━━━━━━━━━ MAIN MENU ━━━━━━━━━━━━

MAIN = IKM(inline_keyboard=[
    [_b("🖼 Фото", "cat:photo"),
     _b("🎥 Видео", "cat:video")],
    [_b("🛠 Инструменты", "cat:tools"),
     _b("🎬 Клипы", "tool:clip")],
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
    [_b("🤝 Пригласить друга · +3⭐", "p:referral")],
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

# ━━━━━━━━━━━━ MONTAGE ━━━━━━━━━━━━

def montage_settings_kb(fx: dict, txt: bool) -> IKM:
    def t(label, key, on):
        return _b(f"{'✅' if on else '◻️'} {label}", f"eff:{key}")
    return IKM(inline_keyboard=[
        [t("Zoom", "zoom", fx.get("zoom", True)),
         t("SlowMo", "slowmo", fx.get("slowmo", True)),
         t("Shake", "shake", fx.get("shake", False))],
        [t("Подписи", "text", txt)],
        [_b("🎵 Музыка", "mt:music"),
         _b("🔇 Без", "mt:nomusic")],
        [_b("🎬 Монтировать", "mt:go")],
        [_b("❌ Отмена", "mt:cancel")],
    ])

def moments_kb(n: int) -> IKM:
    return IKM(inline_keyboard=[
        [_b(f"✅ Смонтировать {n} моментов", "mt:settings")],
        [_b("❌ Отмена", "mt:cancel")],
    ])

# ━━━━━━━━━━━━ RESULT — after tool completion ━━━━━━━━━━━━

def result_kb(tool_cb: str) -> IKM:
    """Result screen: repeat + menu."""
    return IKM(inline_keyboard=[
        [_b("🔄 Ещё раз", tool_cb),
         _b("◀️ Меню", "nav:main")],
    ])

# ━━━━━━━━━━━━ LOW BALANCE ━━━━━━━━━━━━

LOW_BALANCE = IKM(inline_keyboard=[
    [_b("💰 Пополнить", "p:topup"),
     _b("◀️ Меню", "nav:main")],
])

# ━━━━━━━━━━━━ COMMON ━━━━━━━━━━━━

BACK = IKM(inline_keyboard=[[_b("◀️ Меню", "nav:main")]])

CANCEL = IKM(inline_keyboard=[[_b("❌ Отмена", "nav:main")]])

ADMIN = IKM(inline_keyboard=[
    [_b("📊 Статистика", "adm:stats")],
    [_b("📢 Рассылка", "adm:broadcast")],
    [_b("👤 Юзер", "adm:user"),
     _b("💰 Начислить", "adm:grant")],
    [_b("◀️ Назад", "nav:main")],
])
