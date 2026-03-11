"""Navigation hub — menu, categories, tools, profile, payments, settings, admin."""

import html
import logging

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery, LabeledPrice, PreCheckoutQuery,
)
from aiogram.fsm.context import FSMContext

import bot.keyboards as kb
from bot.states import (
    GenImage, EditPhoto, StyleTransfer, RemoveBG, Upscale,
    GenVideo, ImgToVideo,
    AdminBroadcast, AdminUser, AdminGrant,
)
from db import (
    get_or_create_user, get_user, get_balance, topup, get_model, set_model,
    get_referral_count, get_history, get_stats, get_all_user_ids,
    find_user_by_id, grant_balance,
)
from config import settings

router = Router()
log = logging.getLogger(__name__)

ADMIN_IDS = (
    {int(x) for x in settings.admin_ids.split(",") if x.strip()}
    if settings.admin_ids else set()
)
CRYPTO_USD = {50: 1.0, 150: 2.5, 500: 7.0, 1000: 12.0}
MODEL_NAMES = {
    "gemini": "Gemini Flash ⚡",
    "gemini_pro": "Gemini Pro 🧠",
    "flux": "Flux 🎨",
}
# cost per tool for balance pre-check
TOOL_COST = {
    "tool:gen": 1, "tool:edit": 1, "tool:style": 1,
    "tool:rmbg": 1, "tool:upscale": 1,
    "tool:vid_text": 5, "tool:vid_img": 5,
    "tool:clip": 3,
}


# ═══════════════════════════════════════════════════════════════
#  /start
# ═══════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()

    ref = None
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref"):
        try:
            r = int(args[1][3:])
            if r != message.from_user.id:
                ref = r
        except ValueError:
            pass

    user = await get_or_create_user(
        message.from_user.id,
        message.from_user.username or "",
        message.from_user.first_name or "",
        ref,
    )
    await message.answer(_welcome(user), reply_markup=kb.MAIN)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    s = await get_stats()
    await message.answer(_admin_text(s), reply_markup=kb.ADMIN)


# ═══════════════════════════════════════════════════════════════
#  NAVIGATION
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "nav:main")
async def go_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    user = await get_user(cb.from_user.id)
    await _ed(cb, _welcome(user), kb.MAIN)


# ═══════════════════════════════════════════════════════════════
#  CATEGORIES
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "cat:photo")
async def cat_photo(cb: CallbackQuery):
    await _ed(cb, (
        "🖼 <b>Фото</b>\n\n"
        "AI-генерация и обработка изображений.\n"
        "Выбери инструмент:"
    ), kb.PHOTO)

@router.callback_query(F.data == "cat:video")
async def cat_video(cb: CallbackQuery):
    await _ed(cb, (
        "🎥 <b>Видео</b>\n\n"
        "Генерация видео с помощью AI.\n"
        "Выбери режим:"
    ), kb.VIDEO)

@router.callback_query(F.data == "cat:tools")
async def cat_tools(cb: CallbackQuery):
    await _ed(cb, (
        "🛠 <b>Инструменты</b>\n\n"
        "Полезные утилиты для обработки.\n"
        "Выбери:"
    ), kb.TOOLS)


# ═══════════════════════════════════════════════════════════════
#  TOOL ENTRIES → balance check + FSM state
# ═══════════════════════════════════════════════════════════════

async def _check_balance(cb: CallbackQuery, cost: int) -> bool:
    """Check balance and show topup prompt if insufficient. Returns True if OK."""
    bal = await get_balance(cb.from_user.id)
    if bal < cost:
        await _ed(cb, (
            f"❌ <b>Недостаточно звёзд</b>\n\n"
            f"Нужно: <b>{cost}⭐</b>\n"
            f"Баланс: <b>{bal}⭐</b>\n\n"
            f"Пополни баланс и попробуй снова."
        ), kb.LOW_BALANCE)
        return False
    return True


@router.callback_query(F.data == "tool:gen")
async def t_gen(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:gen"]):
        return
    await state.set_state(GenImage.waiting_prompt)
    await _ed(cb, (
        "🎨 <b>Создать изображение</b>  ·  1⭐\n\n"
        "Напиши текстовое описание того, что хочешь увидеть.\n\n"
        "<i>Пример: киберпанк город ночью, неоновые вывески, дождь</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:edit")
async def t_edit(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:edit"]):
        return
    await state.set_state(EditPhoto.waiting_photo)
    await _ed(cb, (
        "✏️ <b>Редактировать фото</b>  ·  1⭐\n\n"
        "Отправь фото и в подписи напиши, что изменить.\n\n"
        "<i>Пример: сделай фон закатным</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:style")
async def t_style(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:style"]):
        return
    await state.set_state(StyleTransfer.waiting_photo)
    await _ed(cb, (
        "🔄 <b>Изменить стиль</b>  ·  1⭐\n\n"
        "Отправь фото и в подписи укажи стиль.\n\n"
        "<i>Примеры:\n"
        "· в стиле аниме\n"
        "· в стиле Ван Гога\n"
        "· pixel art\n"
        "· 3D рендер</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:rmbg")
async def t_rmbg(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:rmbg"]):
        return
    await state.set_state(RemoveBG.waiting_photo)
    await _ed(cb, (
        "🗑 <b>Убрать фон</b>  ·  1⭐\n\n"
        "Отправь фото — получишь PNG с прозрачным фоном."
    ), kb.BACK)

@router.callback_query(F.data == "tool:upscale")
async def t_upscale(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:upscale"]):
        return
    await state.set_state(Upscale.waiting_photo)
    await _ed(cb, (
        "🔍 <b>Улучшить качество 2x</b>  ·  1⭐\n\n"
        "Отправь фото — увеличу разрешение в 2 раза и улучшу резкость."
    ), kb.BACK)

@router.callback_query(F.data == "tool:clip")
async def t_clip(cb: CallbackQuery):
    if not await _check_balance(cb, TOOL_COST["tool:clip"]):
        return
    await _ed(cb, (
        "🎬 <b>AI-монтаж клипа</b>  ·  3⭐\n\n"
        "Отправь видео геймплея и в подписи напиши,\n"
        "что нужно нарезать.\n\n"
        "AI найдёт нужные моменты, добавит эффекты\n"
        "и соберёт готовый клип для TikTok.\n\n"
        "<i>Примеры:\n"
        "· нарежь моменты попаданий\n"
        "· собери все килы\n"
        "· лучшие моменты</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:vid_text")
async def t_vid_text(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:vid_text"]):
        return
    await state.set_state(GenVideo.waiting_prompt)
    await _ed(cb, (
        "📝 <b>Текст → Видео</b>  ·  5⭐\n\n"
        "Опиши видео, которое хочешь получить.\n\n"
        "<i>Пример: котёнок играет с клубком на фоне тёплого света</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:vid_img")
async def t_vid_img(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:vid_img"]):
        return
    await state.set_state(ImgToVideo.waiting_photo)
    await _ed(cb, (
        "🖼 <b>Фото → Видео</b>  ·  5⭐\n\n"
        "Отправь фото и в подписи опиши движение.\n\n"
        "<i>Пример: камера медленно облетает вокруг</i>"
    ), kb.BACK)


# ═══════════════════════════════════════════════════════════════
#  PROFILE
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "p:profile")
async def p_profile(cb: CallbackQuery):
    u = await get_user(cb.from_user.id)
    if not u:
        await cb.answer("Нажми /start")
        return
    model = MODEL_NAMES.get(u["model"], u["model"])
    await _ed(cb, (
        f"👤 <b>Профиль</b>\n\n"
        f"💰 Баланс: <b>{u['balance']} ⭐</b>\n"
        f"🎯 Генераций: <b>{u['total_gens']}</b>\n"
        f"💸 Потрачено: <b>{u['total_spent']} ⭐</b>\n"
        f"🤖 Модель: <b>{model}</b>\n"
        f"📅 С нами с {str(u['created_at'])[:10]}"
    ), kb.PROFILE)


@router.callback_query(F.data == "p:history")
async def p_history(cb: CallbackQuery):
    txs = await get_history(cb.from_user.id, 15)
    if not txs:
        await _ed(cb, "📊 <b>История</b>\n\nПока пусто — начни пользоваться!", kb.BACK_TO_PROFILE)
        return
    lines = ["📊 <b>История операций</b>\n"]
    for t in txs:
        sign = "+" if t["amount"] > 0 else ""
        icon = "🟢" if t["amount"] > 0 else "🔴"
        lines.append(f"{icon} {sign}{t['amount']}⭐  {t['description']}")
    await _ed(cb, "\n".join(lines), kb.BACK_TO_PROFILE)


@router.callback_query(F.data == "p:referral")
async def p_referral(cb: CallbackQuery, bot: Bot):
    tid = cb.from_user.id
    cnt = await get_referral_count(tid)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{tid}"
    await _ed(cb, (
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей — получай <b>+3⭐</b> за каждого!\n"
        f"Друг тоже получит <b>10⭐</b> при регистрации.\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{cnt}</b>\n"
        f"💰 Заработано: <b>{cnt * 3} ⭐</b>"
    ), kb.BACK_TO_PROFILE)


# ═══════════════════════════════════════════════════════════════
#  TOPUP
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "p:topup")
async def p_topup(cb: CallbackQuery):
    bal = await get_balance(cb.from_user.id)
    await _ed(cb, (
        f"💰 <b>Пополнение баланса</b>\n\n"
        f"Текущий баланс: <b>{bal} ⭐</b>\n\n"
        f"Выбери способ оплаты:"
    ), kb.TOPUP_METHOD)


@router.callback_query(F.data == "pay:m:stars")
async def pay_stars_menu(cb: CallbackQuery):
    await _ed(cb, (
        "⭐ <b>Telegram Stars</b>\n\n"
        "Оплата через встроенные Telegram Stars.\n"
        "Выбери пакет:"
    ), kb.TOPUP_STARS)


@router.callback_query(F.data == "pay:m:crypto")
async def pay_crypto_menu(cb: CallbackQuery):
    await _ed(cb, (
        "💎 <b>Криптовалюта</b>\n\n"
        "Оплата TON / USDT / BTC через @CryptoBot.\n"
        "Выбери пакет:"
    ), kb.TOPUP_CRYPTO)


@router.callback_query(F.data.startswith("pay:s:"))
async def pay_stars(cb: CallbackQuery, bot: Bot):
    amt = int(cb.data.split(":")[2])
    await bot.send_invoice(
        chat_id=cb.message.chat.id,
        title=f"{amt}⭐ VClipAI",
        description=f"Пополнение баланса на {amt} звёзд",
        payload=f"topup_{amt}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{amt} звёзд", amount=amt)],
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:c:"))
async def pay_crypto(cb: CallbackQuery, bot: Bot):
    amt = int(cb.data.split(":")[2])
    usd = CRYPTO_USD.get(amt)
    if not settings.cryptobot_token:
        await cb.answer("💎 Крипто-платежи скоро будут доступны!", show_alert=True)
        return

    import aiohttp
    me = await bot.get_me()
    async with aiohttp.ClientSession() as s:
        r = await s.post(
            "https://pay.crypt.bot/api/createInvoice",
            headers={"Crypto-Pay-API-Token": settings.cryptobot_token},
            json={
                "currency_type": "fiat", "fiat": "USD", "amount": str(usd),
                "description": f"VClipAI: {amt} звёзд",
                "payload": f"{cb.from_user.id}:{amt}",
                "paid_btn_name": "callback",
                "paid_btn_url": f"https://t.me/{me.username}",
            },
        )
        d = await r.json()

    if not d.get("ok"):
        await cb.answer("Ошибка создания платежа", show_alert=True)
        return

    from aiogram.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
    await cb.message.answer(
        f"💎 <b>Оплата {amt}⭐ за ${usd}</b>\n\n"
        f"Нажми кнопку ниже, оплати и вернись сюда.",
        reply_markup=IKM(inline_keyboard=[
            [IKB(text="💎 Перейти к оплате", url=d["result"]["pay_url"])],
            [IKB(text="✅ Я оплатил", callback_data=f"pay:v:{d['result']['invoice_id']}")],
        ]),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("pay:v:"))
async def pay_verify(cb: CallbackQuery):
    if not settings.cryptobot_token:
        return
    inv_id = cb.data.split(":")[2]
    import aiohttp
    async with aiohttp.ClientSession() as s:
        r = await s.post(
            "https://pay.crypt.bot/api/getInvoices",
            headers={"Crypto-Pay-API-Token": settings.cryptobot_token},
            json={"invoice_ids": inv_id},
        )
        d = await r.json()

    if not d.get("ok") or not d["result"]["items"]:
        await cb.answer("Платёж не найден", show_alert=True)
        return

    inv = d["result"]["items"][0]
    if inv["status"] != "paid":
        await cb.answer("⏳ Платёж ещё не подтверждён. Попробуй через минуту.", show_alert=True)
        return

    parts = inv.get("payload", "").split(":")
    if len(parts) == 2:
        tid, amt = int(parts[0]), int(parts[1])
        await topup(tid, amt, f"CryptoBot: +{amt}⭐")
        bal = await get_balance(tid)
        await cb.message.edit_text(
            f"✅ <b>Оплата прошла!</b>\n\n"
            f"+{amt}⭐ зачислено\n"
            f"💰 Баланс: <b>{bal} ⭐</b>",
            reply_markup=kb.BACK,
        )
    await cb.answer("✅ Готово!")


@router.pre_checkout_query()
async def pre_checkout(pcq: PreCheckoutQuery, bot: Bot):
    await bot.answer_pre_checkout_query(pcq.id, ok=True)


@router.message(F.successful_payment)
async def on_paid(msg: Message):
    amt = int(msg.successful_payment.invoice_payload.split("_")[1])
    await topup(msg.from_user.id, amt, f"Stars: +{amt}⭐")
    bal = await get_balance(msg.from_user.id)
    await msg.answer(
        f"✅ <b>Оплата прошла!</b>\n\n"
        f"+{amt}⭐ зачислено\n"
        f"💰 Баланс: <b>{bal} ⭐</b>",
        reply_markup=kb.BACK,
    )


# ═══════════════════════════════════════════════════════════════
#  SETTINGS
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "p:settings")
async def p_settings(cb: CallbackQuery):
    m = await get_model(cb.from_user.id)
    await _ed(cb, (
        "⚙️ <b>Модель генерации</b>\n\n"
        "Выбери AI-модель для создания изображений:\n\n"
        "• <b>Gemini Flash</b> — быстрая, хорошее качество\n"
        "• <b>Gemini Pro</b> — лучшее качество, медленнее\n"
        "• <b>Flux</b> — фотореализм, детали"
    ), kb.settings_kb(m))


@router.callback_query(F.data.startswith("set:m:"))
async def set_model_cb(cb: CallbackQuery):
    m = cb.data.split(":")[2]
    await set_model(cb.from_user.id, m)
    await cb.message.edit_reply_markup(reply_markup=kb.settings_kb(m))
    await cb.answer(f"✅ {MODEL_NAMES.get(m, m)}")


# ═══════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════

def _is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    s = await get_stats()
    await _ed(cb, _admin_text(s), kb.ADMIN)


@router.callback_query(F.data == "adm:broadcast")
async def adm_broadcast(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminBroadcast.waiting_text)
    await _ed(cb, (
        "📢 <b>Рассылка</b>\n\n"
        "Отправь текст сообщения для рассылки всем пользователям.\n"
        "Поддерживается HTML-разметка."
    ), kb.CANCEL)


@router.message(AdminBroadcast.waiting_text, F.text)
async def adm_broadcast_text(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    text = message.text.strip()
    user_ids = await get_all_user_ids()
    status = await message.answer(f"📢 Рассылаю {len(user_ids)} пользователям...")

    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1

    await status.edit_text(
        f"📢 <b>Рассылка завершена</b>\n\n"
        f"✅ Доставлено: {sent}\n"
        f"❌ Ошибки: {failed}",
        reply_markup=kb.ADMIN,
    )
    await state.clear()


@router.callback_query(F.data == "adm:user")
async def adm_user(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminUser.waiting_id)
    await _ed(cb, (
        "👤 <b>Поиск пользователя</b>\n\n"
        "Отправь Telegram ID пользователя:"
    ), kb.CANCEL)


@router.message(AdminUser.waiting_id, F.text)
async def adm_user_search(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        tid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи числовой ID.")
        return

    u = await find_user_by_id(tid)
    if not u:
        await message.answer("❌ Пользователь не найден.", reply_markup=kb.ADMIN)
        await state.clear()
        return

    name = html.escape(u.get("first_name") or "")
    uname = html.escape(u.get("username") or "-")
    await message.answer(
        f"👤 <b>Пользователь</b>\n\n"
        f"ID: <code>{u['tg_id']}</code>\n"
        f"Имя: {name}\n"
        f"Username: @{uname}\n"
        f"💰 Баланс: <b>{u['balance']} ⭐</b>\n"
        f"🎯 Генераций: {u['total_gens']}\n"
        f"💸 Потрачено: {u['total_spent']} ⭐\n"
        f"📅 Регистрация: {str(u['created_at'])[:10]}",
        reply_markup=kb.ADMIN,
    )
    await state.clear()


@router.callback_query(F.data == "adm:grant")
async def adm_grant(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminGrant.waiting_id)
    await _ed(cb, (
        "💰 <b>Начислить баланс</b>\n\n"
        "Отправь Telegram ID пользователя:"
    ), kb.CANCEL)


@router.message(AdminGrant.waiting_id, F.text)
async def adm_grant_id(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        tid = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введи числовой ID.")
        return

    u = await find_user_by_id(tid)
    if not u:
        await message.answer("❌ Пользователь не найден.", reply_markup=kb.ADMIN)
        await state.clear()
        return

    await state.update_data(target_id=tid)
    await state.set_state(AdminGrant.waiting_amount)
    name = html.escape(u.get("first_name") or str(tid))
    await message.answer(
        f"Пользователь: <b>{name}</b> (баланс: {u['balance']}⭐)\n\n"
        f"Сколько звёзд начислить?",
        reply_markup=kb.CANCEL,
    )


@router.message(AdminGrant.waiting_amount, F.text)
async def adm_grant_amount(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    try:
        amount = int(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число.")
        return

    data = await state.get_data()
    tid = data["target_id"]
    await grant_balance(tid, amount)
    bal = await get_balance(tid)
    await message.answer(
        f"✅ <b>Начислено {amount}⭐</b>\n"
        f"Новый баланс пользователя: {bal}⭐",
        reply_markup=kb.ADMIN,
    )
    await state.clear()


# ═══════════════════════════════════════════════════════════════
#  NOOP
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


# ═══════════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════════

def _welcome(u: dict) -> str:
    name = html.escape(u.get("first_name") or "")
    greeting = f"Привет, {name}!" if name else "Привет!"
    return (
        f"✨ <b>VClipAI</b>\n\n"
        f"{greeting}\n\n"
        f"🖼 Генерация и редактирование фото\n"
        f"🎥 Создание видео из текста и фото\n"
        f"🎬 AI-монтаж клипов из геймплея\n"
        f"🛠 Удаление фона, апскейл и другое\n\n"
        f"💰 Баланс: <b>{u['balance']} ⭐</b>"
    )


def _admin_text(s: dict) -> str:
    return (
        f"🔐 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{s['users']}</b> (+{s['today']} сегодня)\n"
        f"🎯 Генераций: <b>{s['gens']}</b>\n"
        f"💰 Доход: <b>{s['revenue']} ⭐</b>"
    )


async def _ed(cb: CallbackQuery, text: str, markup):
    """Edit message or send new if edit fails."""
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()
