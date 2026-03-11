"""Video generation — text-to-video and image-to-video."""

import logging
import time

from aiogram import Router, F, Bot
from aiogram.types import Message, FSInputFile
from aiogram.fsm.context import FSMContext

from bot.states import GenVideo, ImgToVideo
from bot.keyboards import BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup
from core.video_gen import generate_video_from_text, generate_video_from_image

router = Router()
log = logging.getLogger(__name__)

COST = 5


@router.message(GenVideo.waiting_prompt, F.text)
async def on_text(message: Message, state: FSMContext, bot: Bot):
    prompt = message.text.strip()
    if len(prompt) < 5:
        await message.answer("✍️ Опиши видео подробнее (минимум 5 символов).")
        return

    tg_id = message.from_user.id
    if not await spend(tg_id, COST, f"🎥 {prompt[:50]}"):
        bal = await get_balance(tg_id)
        await message.answer(
            f"❌ Недостаточно звёзд. Нужно {COST}⭐, у тебя {bal}⭐.",
            reply_markup=LOW_BALANCE,
        )
        await state.clear()
        return

    status = await message.answer("⏳")

    t0 = time.monotonic()
    async with Progress(status, "🎥 Генерирую видео", "1-3 мин"):
        result = await generate_video_from_text(prompt)
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка генерации видео")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось сгенерировать видео за {elapsed} сек.\n"
            f"Попробуй другой промпт.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    bal = await get_balance(tg_id)
    await bot.send_video(
        chat_id=message.chat.id, video=FSInputFile(result),
        caption=(
            f"🎥 <i>{prompt[:200]}</i>\n\n"
            f"⏱ {elapsed} сек\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb("tool:vid_text"), supports_streaming=True,
    )
    await status.delete()
    result.unlink(missing_ok=True)
    await state.clear()


@router.message(ImgToVideo.waiting_photo, F.photo)
async def on_img(message: Message, state: FSMContext, bot: Bot):
    caption = message.caption or "animate with smooth camera movement"
    tg_id = message.from_user.id

    if not await spend(tg_id, COST, f"🖼→🎥 {caption[:50]}"):
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
    async with Progress(status, "🎥 Генерирую видео из фото", "1-3 мин"):
        result = await generate_video_from_image(buf.read(), caption)
    elapsed = int(time.monotonic() - t0)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка генерации видео")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось сгенерировать видео за {elapsed} сек.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    bal = await get_balance(tg_id)
    await bot.send_video(
        chat_id=message.chat.id, video=FSInputFile(result),
        caption=(
            f"🎥 Видео из фото\n\n"
            f"⏱ {elapsed} сек\n"
            f"💰 Остаток: {bal}⭐"
        ),
        reply_markup=result_kb("tool:vid_img"), supports_streaming=True,
    )
    await status.delete()
    result.unlink(missing_ok=True)
    await state.clear()


@router.message(ImgToVideo.waiting_photo)
async def on_no_photo(message: Message):
    await message.answer(
        "📤 Отправь <b>фото</b> для создания видео.\n\n"
        "<i>Можешь добавить подпись с описанием движения.</i>"
    )
