"""Photo editing + style transfer — send photo + caption."""

import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.states import EditPhoto, StyleTransfer
from bot.keyboards import BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup, get_model
from core.image_gen import edit_image

router = Router()
log = logging.getLogger(__name__)

COST = 1


async def _process_photo(message: Message, state: FSMContext, bot: Bot, label: str, tool_cb: str):
    caption = (message.caption or "").strip()
    if not caption:
        await message.answer(
            "✍️ Отправь фото <b>с подписью</b> — напиши что нужно сделать.\n\n"
            "<i>Подпись добавляется при отправке фото (поле под фото).</i>"
        )
        return

    tg_id = message.from_user.id
    if not await spend(tg_id, COST, f"{label} {caption[:50]}"):
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

    model = await get_model(tg_id)
    t0 = time.monotonic()
    async with Progress(status, f"{label} Обрабатываю фото", "10-20 сек"):
        result = await edit_image(buf.read(), caption, model=model)
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка обработки")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось обработать за {elapsed} сек.\n"
            f"Попробуй другое описание.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    bal = await get_balance(tg_id)
    size_kb = len(result) / 1024
    await bot.send_photo(
        chat_id=message.chat.id,
        photo=BufferedInputFile(result, "result.png"),
        caption=(
            f"{label} <i>{caption[:200]}</i>\n\n"
            f"⏱ {elapsed} сек · {size_kb:.0f}KB\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb(tool_cb),
    )
    await status.delete()
    await state.clear()


# ── Edit Photo ──

@router.message(EditPhoto.waiting_photo, F.photo)
async def on_edit_photo(message: Message, state: FSMContext, bot: Bot):
    await _process_photo(message, state, bot, "✏️", "tool:edit")


@router.message(EditPhoto.waiting_photo)
async def on_edit_no_photo(message: Message):
    await message.answer(
        "📤 Отправь <b>фото с подписью</b> — что изменить.\n\n"
        "<i>Подпись добавляется при отправке фото (поле под фото).</i>"
    )


# ── Style Transfer ──

@router.message(StyleTransfer.waiting_photo, F.photo)
async def on_style_photo(message: Message, state: FSMContext, bot: Bot):
    await _process_photo(message, state, bot, "🔄", "tool:style")


@router.message(StyleTransfer.waiting_photo)
async def on_style_no_photo(message: Message):
    await message.answer(
        "📤 Отправь <b>фото с подписью</b> — укажи стиль.\n\n"
        "<i>Подпись добавляется при отправке фото (поле под фото).</i>"
    )
