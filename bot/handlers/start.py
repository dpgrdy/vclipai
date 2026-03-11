"""Navigation hub — menu, profile, payments, referral, promos, admin."""

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
    GenVideo, ImgToVideo, EditCircle, PromoRedeem,
    AdminBroadcast, AdminUser, AdminGrant, AdminBan, AdminPromo,
)
from bot.services.notifier import notify
from db import (
    get_or_create_user, get_user, get_balance, topup, get_model, set_model,
    get_referral_count, get_referral_earnings, get_history, get_stats,
    get_all_user_ids, find_user_by_id, grant_balance,
    is_banned, ban_user, redeem_promo, create_promo, get_promos,
    get_notify_settings, toggle_notify, get_recent_logs, get_top_referrers,
    check_daily_limit,
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
TOOL_COST = {
    "tool:gen": 1, "tool:edit": 1, "tool:style": 1,
    "tool:rmbg": 1, "tool:upscale": 1, "tool:circle": 1,
    "tool:vid_text": 5, "tool:vid_img": 5,
}
TOOL_NAMES = {
    "tool:gen": "Генерация", "tool:edit": "Редактирование",
    "tool:style": "Стиль", "tool:rmbg": "Удаление фона",
    "tool:upscale": "Апскейл", "tool:circle": "Кружок",
    "tool:vid_text": "Текст→Видео", "tool:vid_img": "Фото→Видео",
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

    # Notify admin about new users
    if user.get("balance") == 5 and user.get("total_gens") == 0:
        name = html.escape(user.get("first_name") or "")
        await notify("new_user",
                      f"<b>{name}</b> (@{user.get('username', '?')})\n"
                      f"ID: <code>{user['tg_id']}</code>\n"
                      f"Реферер: {ref or 'organic'}",
                      tg_id=user["tg_id"])

    await message.answer(_welcome(user), reply_markup=kb.MAIN)


@router.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    s = await get_stats()
    await message.answer(_admin_text(s), reply_markup=kb.ADMIN)


@router.message(Command("promo"))
async def cmd_promo(message: Message, state: FSMContext):
    args = message.text.split()
    if len(args) > 1:
        code = args[1].strip()
        ok, msg = await redeem_promo(message.from_user.id, code)
        if ok:
            bal = await get_balance(message.from_user.id)
            await notify("promo", f"Промокод {code} активирован",
                         tg_id=message.from_user.id, tool="promo")
            await message.answer(
                f"✅ <b>{msg}</b>\n💰 Баланс: <b>{bal}⭐</b>",
                reply_markup=kb.BACK)
        else:
            await message.answer(f"❌ {msg}", reply_markup=kb.BACK)
    else:
        await state.set_state(PromoRedeem.waiting_code)
        await message.answer(
            "🎟 <b>Введи промокод:</b>", reply_markup=kb.CANCEL)


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
    bal = await get_balance(cb.from_user.id)
    if bal < cost:
        await _ed(cb, (
            f"❌ <b>Недостаточно звёзд</b>\n\n"
            f"Нужно: <b>{cost}⭐</b>, у тебя: <b>{bal}⭐</b>\n\n"
            f"Пополни баланс или пригласи друга (+3⭐)."
        ), kb.LOW_BALANCE)
        return False
    # Daily limit check
    ok, remaining = await check_daily_limit(cb.from_user.id, settings.daily_free_limit)
    if not ok:
        await _ed(cb, (
            f"⏳ <b>Дневной лимит исчерпан</b>\n\n"
            f"Максимум {settings.daily_free_limit} операций в день.\n"
            f"Попробуй завтра!"
        ), kb.BACK)
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
        "<i>Примеры:\n"
        "· киберпанк город ночью, неоновые вывески\n"
        "· милый котёнок в космосе\n"
        "· логотип для кофейни в минималистичном стиле</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:edit")
async def t_edit(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:edit"]):
        return
    await state.set_state(EditPhoto.waiting_photo)
    await _ed(cb, (
        "✏️ <b>Редактировать фото</b>  ·  1⭐\n\n"
        "Отправь фото и в подписи напиши, что изменить.\n\n"
        "<i>Примеры:\n"
        "· сделай фон закатным\n"
        "· убери текст с картинки\n"
        "· добавь снег</i>"
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
        "· 3D рендер\n"
        "· комикс</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:rmbg")
async def t_rmbg(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:rmbg"]):
        return
    await state.set_state(RemoveBG.waiting_photo)
    await _ed(cb, (
        "🗑 <b>Убрать фон</b>  ·  1⭐\n\n"
        "Отправь фото — получишь PNG с прозрачным фоном.\n"
        "Подходит для стикеров, логотипов, товаров."
    ), kb.BACK)

@router.callback_query(F.data == "tool:upscale")
async def t_upscale(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:upscale"]):
        return
    await state.set_state(Upscale.waiting_photo)
    await _ed(cb, (
        "🔍 <b>Улучшить качество 2x</b>  ·  1⭐\n\n"
        "Отправь фото — увеличу разрешение в 2 раза\n"
        "и улучшу резкость."
    ), kb.BACK)

@router.callback_query(F.data == "tool:vid_text")
async def t_vid_text(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:vid_text"]):
        return
    await state.set_state(GenVideo.waiting_prompt)
    await _ed(cb, (
        "📝 <b>Текст → Видео</b>  ·  5⭐\n\n"
        "Опиши видео, которое хочешь получить.\n\n"
        "<i>Примеры:\n"
        "· котёнок играет с клубком на фоне тёплого света\n"
        "· закат над океаном, волны, чайки\n"
        "· машина едет по ночному городу</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:vid_img")
async def t_vid_img(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:vid_img"]):
        return
    await state.set_state(ImgToVideo.waiting_photo)
    await _ed(cb, (
        "🖼 <b>Фото → Видео</b>  ·  5⭐\n\n"
        "Отправь фото и в подписи опиши движение.\n\n"
        "<i>Примеры:\n"
        "· камера медленно облетает вокруг\n"
        "· лёгкий ветер шевелит волосы\n"
        "· zoom in на лицо</i>"
    ), kb.BACK)

@router.callback_query(F.data == "tool:circle")
async def t_circle(cb: CallbackQuery, state: FSMContext):
    if not await _check_balance(cb, TOOL_COST["tool:circle"]):
        return
    await _ed(cb, (
        "⚪ <b>Редактировать кружок</b>  ·  1⭐\n\n"
        "Выбери эффект, затем отправь кружок.\n"
        "Получишь обработанный кружок обратно!"
    ), kb.CIRCLE_EFFECTS)


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
    ref_count = await get_referral_count(cb.from_user.id)
    await _ed(cb, (
        f"👤 <b>Профиль</b>\n\n"
        f"💰 Баланс: <b>{u['balance']}⭐</b>\n"
        f"🎯 Генераций: <b>{u['total_gens']}</b>\n"
        f"💸 Потрачено: <b>{u['total_spent']}⭐</b>\n"
        f"🤖 Модель: <b>{model}</b>\n"
        f"👥 Рефералов: <b>{ref_count}</b>\n"
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
    earnings = await get_referral_earnings(tid)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref{tid}"

    # Calculate current tier
    base_bonus = min(3 + cnt // 5, 10)

    await _ed(cb, (
        f"🤝 <b>Реферальная программа</b>\n\n"
        f"Приглашай друзей и получай звёзды!\n\n"
        f"<b>Бонусы за приглашение:</b>\n"
        f"· Базовый: <b>+3⭐</b> за каждого друга\n"
        f"· За каждые 5 рефералов бонус растёт на +1⭐\n"
        f"· Максимум: <b>+10⭐</b> за друга\n"
        f"· Друг получает <b>5⭐</b> при регистрации\n\n"
        f"Сейчас за друга: <b>+{base_bonus}⭐</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"👥 Приглашено: <b>{cnt}</b>\n"
        f"💰 Заработано: <b>{earnings}⭐</b>"
    ), kb.BACK_TO_PROFILE)


@router.callback_query(F.data == "p:promo")
async def p_promo(cb: CallbackQuery, state: FSMContext):
    await state.set_state(PromoRedeem.waiting_code)
    await _ed(cb, (
        "🎟 <b>Промокод</b>\n\n"
        "Введи промокод для получения бонусных звёзд:"
    ), kb.CANCEL)


@router.message(PromoRedeem.waiting_code, F.text)
async def promo_redeem(message: Message, state: FSMContext):
    code = message.text.strip()
    ok, msg = await redeem_promo(message.from_user.id, code)
    if ok:
        bal = await get_balance(message.from_user.id)
        await notify("promo", f"Промокод <b>{code}</b> активирован\nUser: {message.from_user.id}",
                     tg_id=message.from_user.id, tool="promo")
        await message.answer(
            f"✅ <b>{msg}</b>\n💰 Баланс: <b>{bal}⭐</b>",
            reply_markup=kb.BACK)
    else:
        await message.answer(f"❌ {msg}", reply_markup=kb.BACK)
    await state.clear()


# ═══════════════════════════════════════════════════════════════
#  TOPUP
# ═══════════════════════════════════════════════════════════════

@router.callback_query(F.data == "p:topup")
async def p_topup(cb: CallbackQuery):
    bal = await get_balance(cb.from_user.id)
    await _ed(cb, (
        f"💰 <b>Пополнение баланса</b>\n\n"
        f"Текущий баланс: <b>{bal}⭐</b>\n\n"
        f"Выбери способ оплаты:"
    ), kb.TOPUP_METHOD)


@router.callback_query(F.data == "pay:m:stars")
async def pay_stars_menu(cb: CallbackQuery):
    await _ed(cb, (
        "⭐ <b>Telegram Stars</b>\n\n"
        "Мгновенная оплата через Telegram.\n"
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
        await notify("payment", f"CryptoBot +{amt}⭐ (${CRYPTO_USD.get(amt, '?')})\nUser: {tid}",
                     tg_id=tid, tool="payment")
        await cb.message.edit_text(
            f"✅ <b>Оплата прошла!</b>\n\n"
            f"+{amt}⭐ зачислено\n"
            f"💰 Баланс: <b>{bal}⭐</b>",
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
    await notify("payment", f"TG Stars +{amt}⭐\nUser: {msg.from_user.id}",
                 tg_id=msg.from_user.id, tool="payment")
    await msg.answer(
        f"✅ <b>Оплата прошла!</b>\n\n"
        f"+{amt}⭐ зачислено\n"
        f"💰 Баланс: <b>{bal}⭐</b>",
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
        "· <b>Gemini Flash</b> — быстрая, хорошее качество\n"
        "· <b>Gemini Pro</b> — лучшее качество, медленнее\n"
        "· <b>Flux</b> — фотореализм, детали"
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


@router.callback_query(F.data == "adm:panel")
async def adm_panel(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    s = await get_stats()
    await _ed(cb, _admin_text(s), kb.ADMIN)


@router.callback_query(F.data == "adm:stats")
async def adm_stats(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    s = await get_stats()
    await _ed(cb, _admin_text(s), kb.ADMIN)


@router.callback_query(F.data == "adm:logs")
async def adm_logs(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    logs = await get_recent_logs(20)
    if not logs:
        await _ed(cb, "📋 <b>Логи</b>\n\nПока пусто.", kb.ADMIN_BACK)
        return
    lines = ["📋 <b>Последние события</b>\n"]
    for l in logs:
        ts = str(l["created_at"])[11:16] if l["created_at"] else "?"
        evt_icon = {"new_user": "👤", "payment": "💰", "tool_use": "🔧",
                     "error": "❌", "referral": "🤝", "promo": "🎟"}.get(l["event"], "📌")
        tool_str = f" [{l['tool']}]" if l.get("tool") else ""
        det = (l.get("details") or "")[:60]
        lines.append(f"{evt_icon} {ts} · {l['tg_id']}{tool_str} {det}")
    await _ed(cb, "\n".join(lines), kb.ADMIN_BACK)


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
    await _ed(cb, "👤 <b>Поиск пользователя</b>\n\nОтправь Telegram ID:", kb.CANCEL)


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
    await message.answer(_user_card(u), reply_markup=kb.user_card_kb(tid, bool(u.get("is_banned"))))
    await state.clear()


@router.callback_query(F.data == "adm:grant")
async def adm_grant(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminGrant.waiting_id)
    await _ed(cb, "💰 <b>Начислить баланс</b>\n\nОтправь Telegram ID:", kb.CANCEL)


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
        f"Пользователь: <b>{name}</b> (баланс: {u['balance']}⭐)\n\nСколько звёзд начислить?",
        reply_markup=kb.CANCEL,
    )


@router.callback_query(F.data.startswith("adm:gr:"))
async def adm_grant_quick(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    tid = int(cb.data.split(":")[2])
    await state.update_data(target_id=tid)
    await state.set_state(AdminGrant.waiting_amount)
    await _ed(cb, f"💰 Сколько звёзд начислить юзеру {tid}?", kb.CANCEL)


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
        f"✅ <b>Начислено {amount}⭐</b>\nНовый баланс: {bal}⭐",
        reply_markup=kb.ADMIN,
    )
    await state.clear()


@router.callback_query(F.data == "adm:ban")
async def adm_ban(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminBan.waiting_id)
    await _ed(cb, "🚫 <b>Бан/разбан</b>\n\nОтправь Telegram ID:", kb.CANCEL)


@router.message(AdminBan.waiting_id, F.text)
async def adm_ban_id(message: Message, state: FSMContext):
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
    new_state = not bool(u.get("is_banned"))
    await ban_user(tid, new_state)
    status = "забанен 🚫" if new_state else "разбанен ✅"
    name = html.escape(u.get("first_name") or str(tid))
    await message.answer(f"<b>{name}</b> — {status}", reply_markup=kb.ADMIN)
    await state.clear()


@router.callback_query(F.data.startswith("adm:bn:"))
async def adm_ban_quick(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    tid = int(cb.data.split(":")[2])
    u = await find_user_by_id(tid)
    if not u:
        await cb.answer("Не найден")
        return
    new_state = not bool(u.get("is_banned"))
    await ban_user(tid, new_state)
    status = "забанен 🚫" if new_state else "разбанен ✅"
    await cb.answer(f"{status}")
    await cb.message.edit_text(
        _user_card(await find_user_by_id(tid)),
        reply_markup=kb.user_card_kb(tid, new_state),
    )


# ── Admin: Promos ──

@router.callback_query(F.data == "adm:promos")
async def adm_promos(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    promos = await get_promos(active_only=False)
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПока нет промокодов."
    else:
        lines = ["🎟 <b>Промокоды</b>\n"]
        for p in promos[:15]:
            status = "✅" if p["used_count"] < p["max_uses"] else "❌"
            lines.append(
                f"{status} <code>{p['code']}</code> — {p['stars']}⭐ "
                f"({p['used_count']}/{p['max_uses']})"
            )
        text = "\n".join(lines)

    from aiogram.types import InlineKeyboardMarkup as IKM, InlineKeyboardButton as IKB
    await _ed(cb, text, IKM(inline_keyboard=[
        [IKB(text="➕ Создать промокод", callback_data="adm:promo_new")],
        [IKB(text="◀️ Админ", callback_data="adm:panel")],
    ]))


@router.callback_query(F.data == "adm:promo_new")
async def adm_promo_new(cb: CallbackQuery, state: FSMContext):
    if not _is_admin(cb.from_user.id):
        return
    await state.set_state(AdminPromo.waiting_code)
    await _ed(cb, (
        "🎟 <b>Новый промокод</b>\n\n"
        "Введи код (латиница, цифры):"
    ), kb.CANCEL)


@router.message(AdminPromo.waiting_code, F.text)
async def adm_promo_code(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    code = message.text.strip().upper()
    if not code.isalnum() or len(code) < 3:
        await message.answer("❌ Код должен быть 3+ символов (A-Z, 0-9).")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminPromo.waiting_stars)
    await message.answer(f"Код: <code>{code}</code>\n\nСколько звёзд начислять?", reply_markup=kb.CANCEL)


@router.message(AdminPromo.waiting_stars, F.text)
async def adm_promo_stars(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        stars = int(message.text.strip())
        if stars <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи положительное число.")
        return
    await state.update_data(promo_stars=stars)
    await state.set_state(AdminPromo.waiting_uses)
    await message.answer(
        f"Звёзд: <b>{stars}⭐</b>\n\n"
        f"Макс. использований (число или 0 = безлимит):",
        reply_markup=kb.CANCEL,
    )


@router.message(AdminPromo.waiting_uses, F.text)
async def adm_promo_uses(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        await state.clear()
        return
    try:
        uses = int(message.text.strip())
        if uses < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введи число >= 0.")
        return
    data = await state.get_data()
    code = data["promo_code"]
    stars = data["promo_stars"]
    max_uses = uses if uses > 0 else 999999
    ok = await create_promo(code, stars, max_uses, created_by=message.from_user.id)
    if ok:
        uses_text = f"{max_uses}" if uses > 0 else "безлимит"
        await message.answer(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"Код: <code>{code}</code>\n"
            f"Звёзды: <b>{stars}⭐</b>\n"
            f"Использований: <b>{uses_text}</b>",
            reply_markup=kb.ADMIN,
        )
    else:
        await message.answer("❌ Такой код уже существует.", reply_markup=kb.ADMIN)
    await state.clear()


# ── Admin: Notifications ──

@router.callback_query(F.data == "adm:notify")
async def adm_notify(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    s = await get_notify_settings()
    await _ed(cb, (
        "🔔 <b>Уведомления</b>\n\n"
        "Включи/выключи уведомления для каждого типа событий.\n"
        "Уведомления приходят в этот чат."
    ), kb.notify_settings_kb(s))


@router.callback_query(F.data.startswith("adm:ntg:"))
async def adm_notify_toggle(cb: CallbackQuery):
    if not _is_admin(cb.from_user.id):
        return
    event = cb.data.split(":")[2]
    new_state = await toggle_notify(event)
    s = await get_notify_settings()
    await cb.message.edit_reply_markup(reply_markup=kb.notify_settings_kb(s))
    status = "включены ✅" if new_state else "выключены 🔴"
    await cb.answer(f"Уведомления {status}")


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
        f"⚪ Редактирование кружков с эффектами\n"
        f"🛠 Удаление фона, апскейл и другое\n\n"
        f"💰 Баланс: <b>{u['balance']}⭐</b>\n"
        f"🎟 Есть промокод? → /promo КОД"
    )


def _admin_text(s: dict) -> str:
    tools_text = ""
    if s.get("top_tools"):
        tools_lines = [f"  · {t}: {c}" for t, c in s["top_tools"].items()]
        tools_text = "\n🔧 Популярные инструменты:\n" + "\n".join(tools_lines)

    return (
        f"🔐 <b>Админ-панель</b>\n\n"
        f"👥 Пользователей: <b>{s['users']}</b> (+{s['today_users']} сегодня)\n"
        f"🟢 Активных (24ч): <b>{s['active_24h']}</b>\n"
        f"🎯 Генераций: <b>{s['gens']}</b> (+{s['today_gens']} сегодня)\n"
        f"💰 Доход: <b>{s['revenue']}⭐</b> (+{s['today_revenue']} сегодня)"
        f"{tools_text}"
    )


def _user_card(u: dict) -> str:
    name = html.escape(u.get("first_name") or "")
    uname = html.escape(u.get("username") or "-")
    banned = " 🚫 ЗАБАНЕН" if u.get("is_banned") else ""
    return (
        f"👤 <b>Пользователь</b>{banned}\n\n"
        f"ID: <code>{u['tg_id']}</code>\n"
        f"Имя: {name}\n"
        f"Username: @{uname}\n"
        f"💰 Баланс: <b>{u['balance']}⭐</b>\n"
        f"🎯 Генераций: {u['total_gens']}\n"
        f"💸 Потрачено: {u['total_spent']}⭐\n"
        f"👥 Заработано рефералами: {u.get('ref_earnings', 0)}⭐\n"
        f"📅 Регистрация: {str(u['created_at'])[:10]}\n"
        f"🕐 Последняя активность: {str(u.get('last_active') or '-')[:16]}"
    )


async def _ed(cb: CallbackQuery, text: str, markup):
    try:
        await cb.message.edit_text(text, reply_markup=markup)
    except Exception:
        await cb.message.answer(text, reply_markup=markup)
    await cb.answer()
