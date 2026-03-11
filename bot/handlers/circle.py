"""Video note (circle) editing — apply effects and return as circle."""

import logging
import time
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from bot.states import EditCircle
from bot.keyboards import BACK, LOW_BALANCE, CIRCLE_EFFECTS, result_kb
from bot.progress import Progress
from db import get_balance, spend, topup
from core.circle import process_circle
from bot.services.notifier import notify

router = Router()
log = logging.getLogger(__name__)

COST = 1

EFFECT_NAMES = {
    "bw": "Ч/Б",
    "warm": "Тёплый",
    "cool": "Холодный",
    "vintage": "Винтаж",
    "speed2x": "Ускорение 2x",
    "slow": "Замедление",
    "reverse": "Реверс",
    "sharp": "Чёткость+",
}


@router.callback_query(F.data.startswith("ceff:"))
async def on_effect_pick(cb: CallbackQuery, state: FSMContext):
    effect = cb.data.split(":")[1]
    if effect not in EFFECT_NAMES:
        await cb.answer("?")
        return

    bal = await get_balance(cb.from_user.id)
    if bal < COST:
        from bot.keyboards import LOW_BALANCE
        try:
            await cb.message.edit_text(
                f"❌ <b>Недостаточно звёзд</b>\n\n"
                f"Нужно: <b>{COST}⭐</b>, у тебя: <b>{bal}⭐</b>",
                reply_markup=LOW_BALANCE,
            )
        except Exception:
            pass
        await cb.answer()
        return

    await state.update_data(circle_effect=effect)
    await state.set_state(EditCircle.waiting_video)
    name = EFFECT_NAMES[effect]
    try:
        await cb.message.edit_text(
            f"⚪ <b>Эффект: {name}</b>  ·  {COST}⭐\n\n"
            f"Отправь кружок (видеосообщение) 👇",
            reply_markup=BACK,
        )
    except Exception:
        await cb.message.answer(
            f"⚪ <b>Эффект: {name}</b>  ·  {COST}⭐\n\n"
            f"Отправь кружок (видеосообщение) 👇",
            reply_markup=BACK,
        )
    await cb.answer()


@router.message(EditCircle.waiting_video, F.video_note)
async def on_circle(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    effect = data.get("circle_effect", "sharp")
    tg_id = message.from_user.id

    if not await spend(tg_id, COST, f"⚪ Кружок: {EFFECT_NAMES.get(effect, effect)}"):
        bal = await get_balance(tg_id)
        await message.answer(
            f"❌ Недостаточно звёзд. Нужно {COST}⭐, у тебя {bal}⭐.",
            reply_markup=LOW_BALANCE,
        )
        await state.clear()
        return

    status = await message.answer("⏳")

    # Download video note
    file = await bot.get_file(message.video_note.file_id)
    buf = await bot.download_file(file.file_path)

    from config import settings
    import uuid
    input_path = settings.temp_dir / f"circle_in_{uuid.uuid4().hex[:8]}.mp4"
    input_path.write_bytes(buf.read())

    t0 = time.monotonic()
    async with Progress(status, f"⚪ Применяю эффект: {EFFECT_NAMES.get(effect, effect)}", "5-15 сек"):
        result = await process_circle(input_path, effect)
    elapsed = int(time.monotonic() - t0)

    input_path.unlink(missing_ok=True)

    if not result:
        await topup(tg_id, COST, "Возврат: ошибка обработки кружка")
        bal = await get_balance(tg_id)
        await status.edit_text(
            f"❌ Не удалось обработать кружок за {elapsed} сек.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        return

    await notify("tool_use", f"Кружок: {EFFECT_NAMES.get(effect, effect)}",
                 tg_id=tg_id, tool="circle")

    bal = await get_balance(tg_id)
    await bot.send_video_note(
        chat_id=message.chat.id,
        video_note=FSInputFile(result),
    )
    await status.edit_text(
        f"⚪ <b>{EFFECT_NAMES.get(effect, effect)}</b>\n\n"
        f"⏱ {elapsed} сек\n"
        f"💰 Остаток: {bal}⭐",
        reply_markup=result_kb("tool:circle"),
    )
    result.unlink(missing_ok=True)
    await state.clear()


@router.message(EditCircle.waiting_video)
async def on_no_circle(message: Message):
    await message.answer(
        "📤 Отправь <b>кружок</b> (видеосообщение).\n\n"
        "<i>Зажми кнопку записи голосового и переключи на видео,\n"
        "или перешли чужой кружок.</i>"
    )
