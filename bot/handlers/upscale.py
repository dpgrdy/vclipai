"""Image upscale handler."""

import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.states import Upscale
from bot.keyboards import BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup
from core.upscaler import upscale_image
from bot.services.notifier import notify

router = Router()
log = logging.getLogger(__name__)

COST = 1


@router.message(Upscale.waiting_photo, F.photo)
async def on_photo(message: Message, state: FSMContext, bot: Bot):
    tg_id = message.from_user.id
    if not await spend(tg_id, COST, "🔍 Апскейл"):
        bal = await get_balance(tg_id)
        await message.answer(
            f"❌ Недостаточно звёзд. Нужно {COST}⭐, у тебя {bal}⭐.",
            reply_markup=LOW_BALANCE,
        )
        await state.clear()
        return

    status = await message.answer("⏳")
    file = await bot.get_file(message.photo[-1].file_id)
    buf = await bot.download_file(file.file_path)

    t0 = time.monotonic()
    async with Progress(status, "🔍 Улучшаю качество 2x", "3-10 сек"):
        result = await upscale_image(buf.read(), scale=2)
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка апскейла")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось улучшить.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    await notify("tool_use", "Апскейл 2x", tg_id=tg_id, tool="upscale")
    bal = await get_balance(tg_id)
    size_mb = len(result) / 1024 / 1024
    await bot.send_document(
        chat_id=message.chat.id,
        document=BufferedInputFile(result, "upscaled.png"),
        caption=(
            f"🔍 Качество улучшено 2x\n\n"
            f"⏱ {elapsed} сек · {size_mb:.1f}MB\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb("tool:upscale"),
    )
    await status.delete()
    await state.clear()


@router.message(Upscale.waiting_photo)
async def on_no_photo(message: Message):
    await message.answer("📤 Отправь <b>фото</b> для улучшения качества.")
