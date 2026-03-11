"""Background removal handler."""

import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.states import RemoveBG
from bot.keyboards import BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup
from core.bg_remover import remove_background
from bot.services.notifier import notify

router = Router()
log = logging.getLogger(__name__)

COST = 1


@router.message(RemoveBG.waiting_photo, F.photo)
async def on_photo(message: Message, state: FSMContext, bot: Bot):
    tg_id = message.from_user.id
    if not await spend(tg_id, COST, "🗑 Удаление фона"):
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
    async with Progress(status, "🗑 Удаляю фон", "5-15 сек"):
        result = await remove_background(buf.read())
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка удаления фона")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось удалить фон.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    await notify("tool_use", "Удаление фона", tg_id=tg_id, tool="rmbg")
    bal = await get_balance(tg_id)
    size_kb = len(result) / 1024
    await bot.send_document(
        chat_id=message.chat.id,
        document=BufferedInputFile(result, "no_bg.png"),
        caption=(
            f"🗑 Фон удалён!\n\n"
            f"⏱ {elapsed} сек · {size_kb:.0f}KB\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb("tool:rmbg"),
    )
    await status.delete()
    await state.clear()


@router.message(RemoveBG.waiting_photo)
async def on_no_photo(message: Message):
    await message.answer("📤 Отправь <b>фото</b> для удаления фона.")
