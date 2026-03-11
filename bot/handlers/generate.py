"""Image generation handler."""

import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.states import GenImage
from bot.keyboards import BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup, get_model
from core.image_gen import generate_image

router = Router()
log = logging.getLogger(__name__)

COST = 1
MODEL_ESTIMATES = {
    "gemini": "10-20 сек",
    "gemini_pro": "15-30 сек",
    "flux": "20-40 сек",
}


@router.message(GenImage.waiting_prompt, F.text)
async def on_prompt(message: Message, state: FSMContext, bot: Bot):
    prompt = message.text.strip()
    if not prompt or len(prompt) < 3:
        await message.answer("✍️ Напиши описание подлиннее (минимум 3 символа).")
        return

    tg_id = message.from_user.id
    if not await spend(tg_id, COST, f"🎨 {prompt[:50]}"):
        bal = await get_balance(tg_id)
        await message.answer(
            f"❌ Недостаточно звёзд. Нужно {COST}⭐, у тебя {bal}⭐.",
            reply_markup=LOW_BALANCE,
        )
        await state.clear()
        return

    model = await get_model(tg_id)
    estimate = MODEL_ESTIMATES.get(model, "10-30 сек")
    status = await message.answer("⏳")

    t0 = time.monotonic()
    async with Progress(status, f"🎨 Генерирую изображение", estimate):
        result = await generate_image(prompt, model=model)
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка генерации")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось сгенерировать за {elapsed} сек.\n"
            f"Попробуй другой промпт.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    photo = BufferedInputFile(result, filename="generated.png")
    bal = await get_balance(tg_id)
    size_kb = len(result) / 1024
    await bot.send_photo(
        chat_id=message.chat.id, photo=photo,
        caption=(
            f"🎨 <i>{prompt[:200]}</i>\n\n"
            f"⏱ {elapsed} сек · {size_kb:.0f}KB\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb("tool:gen"),
    )
    await status.delete()
    await state.clear()
