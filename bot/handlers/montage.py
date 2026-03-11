"""Montage handler — video analysis + clip assembly."""

import logging
import asyncio
import time
from pathlib import Path

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, FSInputFile
from aiogram.fsm.context import FSMContext

from config import settings
from bot.states import MontageFlow
from bot.keyboards import montage_settings_kb, moments_kb, BACK, LOW_BALANCE, result_kb
from bot.progress import Progress
from core.analyzer import analyze_video
from core.editor import process_video, MontageSettings
from db import get_balance, spend, topup

router = Router()
log = logging.getLogger(__name__)

DEFAULT_EFFECTS = {"zoom": True, "slowmo": True, "shake": False}
COST = 3

TG_DOWNLOAD_LIMIT_MB = 20
ANALYSIS_TIMEOUT = 600
MONTAGE_TIMEOUT = 900


def _is_video_document(message: Message) -> bool:
    if not message.document:
        return False
    mime = message.document.mime_type or ""
    return mime.startswith("video/")


@router.message(F.video)
async def on_video(message: Message, state: FSMContext, bot: Bot):
    await _handle_video(message, state, bot)


@router.message(F.document)
async def on_document(message: Message, state: FSMContext, bot: Bot):
    if not _is_video_document(message):
        return
    await _handle_video(message, state, bot)


async def _handle_video(message: Message, state: FSMContext, bot: Bot):
    caption = message.caption or ""
    if not caption.strip():
        await message.answer(
            "🎬 <b>Чтобы смонтировать клип:</b>\n\n"
            "Отправь видео <b>с подписью</b> — напиши, что нарезать.\n\n"
            "<i>Примеры подписей:\n"
            "· нарежь моменты попаданий\n"
            "· собери все килы\n"
            "· лучшие моменты</i>",
        )
        return

    tg_id = message.from_user.id

    # File info
    if message.video:
        file_id = message.video.file_id
        file_size = message.video.file_size or 0
        duration = message.video.duration or 0
    else:
        file_id = message.document.file_id
        file_size = message.document.file_size or 0
        duration = 0

    size_mb = file_size / (1024 * 1024)

    # TG download limit
    has_local_api = bool(settings.local_bot_api_url)
    if not has_local_api and size_mb > TG_DOWNLOAD_LIMIT_MB:
        await message.answer(
            f"❌ <b>Видео слишком большое: {size_mb:.0f}MB</b>\n\n"
            f"Telegram ограничивает скачивание до {TG_DOWNLOAD_LIMIT_MB}MB.\n\n"
            f"💡 <b>Что делать:</b>\n"
            f"· Отправь без галочки «оригинал» — Telegram сожмёт\n"
            f"· Обрежь до нужного фрагмента\n"
            f"· Запиши покороче",
        )
        return

    if size_mb > settings.max_video_size_mb:
        await message.answer(
            f"❌ Видео слишком большое: <b>{size_mb:.0f}MB</b>\n"
            f"Лимит: {settings.max_video_size_mb}MB.",
        )
        return

    if duration > settings.max_video_duration:
        mins, secs = divmod(duration, 60)
        max_mins = settings.max_video_duration // 60
        await message.answer(
            f"❌ Видео слишком длинное: <b>{mins}:{secs:02d}</b>\n"
            f"Лимит: {max_mins} мин.",
        )
        return

    # Balance
    if not await spend(tg_id, COST, f"🎬 {caption[:50]}"):
        bal = await get_balance(tg_id)
        await message.answer(
            f"❌ Недостаточно звёзд. Нужно {COST}⭐, у тебя {bal}⭐.",
            reply_markup=LOW_BALANCE,
        )
        return

    # ── STEP 1: Download ──
    dur_str = f" · {duration // 60}:{duration % 60:02d}" if duration else ""
    status_msg = await message.answer(
        f"📥 <b>Шаг 1/3</b> — Скачиваю видео\n"
        f"<i>{size_mb:.1f}MB{dur_str}</i>"
    )

    t_total = time.monotonic()
    try:
        file = await bot.get_file(file_id)
        ext = Path(file.file_path).suffix if file.file_path else ".mp4"
        video_path = settings.temp_dir / f"{message.message_id}{ext}"
        log.info("Downloading file: %s (%.1fMB, local_api=%s)", file.file_path, size_mb, has_local_api)
        await bot.download_file(file.file_path, destination=video_path)
    except Exception as e:
        log.error("Video download failed: %s", e)
        await topup(tg_id, COST, "Возврат: ошибка загрузки")
        bal = await get_balance(tg_id)
        err = ""
        if "too big" in str(e).lower():
            err = f"\n\nВидео слишком большое для Telegram API ({size_mb:.0f}MB)."
        await status_msg.edit_text(
            f"❌ Не удалось скачать видео.{err}\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        return

    t_download = int(time.monotonic() - t_total)
    log.info("Downloaded video: %s (%.1fMB) in %ds", video_path, size_mb, t_download)

    # ── STEP 2: Analyze ──
    await state.set_state(MontageFlow.analyzing)
    t_analyze_start = time.monotonic()

    async with Progress(
        status_msg,
        f"🔍 <b>Шаг 2/3</b> — Загружаю и анализирую через AI\n"
        f"<i>Загрузка {size_mb:.0f}MB + анализ</i>",
        "1-3 мин",
    ):
        try:
            edit_data = await analyze_video(str(video_path), caption)
            moments = edit_data.get("segments", [])
        except Exception as e:
            log.error("Gemini analysis failed: %s", e)
            await topup(tg_id, COST, "Возврат: ошибка анализа")
            bal = await get_balance(tg_id)
            await status_msg.edit_text(
                f"❌ Не удалось проанализировать видео.\n"
                f"Попробуй другое видео или другую инструкцию.\n\n"
                f"💰 {bal}⭐ (звёзды возвращены)",
                reply_markup=BACK,
            )
            await state.clear()
            _cleanup(video_path)
            return

    t_analyze = int(time.monotonic() - t_analyze_start)

    if not moments:
        await topup(tg_id, COST, "Возврат: моменты не найдены")
        bal = await get_balance(tg_id)
        await status_msg.edit_text(
            f"🤷 Не нашёл подходящих моментов по запросу:\n"
            f"<i>«{caption[:100]}»</i>\n\n"
            f"Анализ занял {t_analyze} сек.\n"
            f"Попробуй другую инструкцию.\n\n"
            f"💰 {bal}⭐ (звёзды возвращены)",
            reply_markup=BACK,
        )
        await state.clear()
        _cleanup(video_path)
        return

    n_effects = len(edit_data.get("effects", []))

    # Show segments
    preview_lines = [
        f"🎯 <b>Найдено {len(moments)} сегментов, {n_effects} эффектов</b>"
        f" <i>(анализ: {t_analyze} сек)</i>\n",
    ]
    for i, m in enumerate(moments, 1):
        start_ts = _fmt_time(m["start"])
        end_ts = _fmt_time(m["end"])
        note = m.get("note", m.get("description", ""))
        seg_type = m.get("type", "action")
        preview_lines.append(f"{i}. [{seg_type}] {start_ts}–{end_ts} — {note}")

    await status_msg.edit_text(
        "\n".join(preview_lines),
        reply_markup=moments_kb(len(moments)),
    )

    await state.update_data(
        video_path=str(video_path),
        instruction=caption,
        edit_data=edit_data,
        moments=moments,
        effects=DEFAULT_EFFECTS.copy(),
        text_on=True,
        music_path=None,
    )
    await state.set_state(MontageFlow.configure)


@router.callback_query(F.data == "mt:settings")
async def on_settings(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    effects = data.get("effects", DEFAULT_EFFECTS)
    text_on = data.get("text_on", True)
    await callback.message.edit_text(
        "⚙️ <b>Настройки монтажа:</b>\n\n"
        "Включи/выключи эффекты и нажми «Монтировать».",
        reply_markup=montage_settings_kb(effects, text_on),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("eff:"))
async def on_toggle_effect(callback: CallbackQuery, state: FSMContext):
    key = callback.data.split(":")[1]
    data = await state.get_data()
    if key == "text":
        data["text_on"] = not data.get("text_on", True)
    else:
        effects = data.get("effects", DEFAULT_EFFECTS.copy())
        effects[key] = not effects.get(key, False)
        data["effects"] = effects
    await state.update_data(**data)
    await callback.message.edit_reply_markup(
        reply_markup=montage_settings_kb(data["effects"], data["text_on"]),
    )
    await callback.answer()


@router.callback_query(F.data == "mt:music")
async def on_music_request(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "🎵 Отправь аудио-файл с музыкой.\n<i>MP3, WAV или OGG.</i>"
    )
    await state.set_state(MontageFlow.waiting_music)
    await callback.answer()


@router.message(MontageFlow.waiting_music, F.audio | F.document)
async def on_music_file(message: Message, state: FSMContext, bot: Bot):
    file_id = (message.audio or message.document).file_id
    file = await bot.get_file(file_id)
    ext = Path(file.file_path).suffix if file.file_path else ".mp3"
    music_path = settings.temp_dir / f"music_{message.message_id}{ext}"
    await bot.download_file(file.file_path, destination=music_path)
    await state.update_data(music_path=str(music_path))
    await state.set_state(MontageFlow.configure)
    data = await state.get_data()
    await message.answer(
        "✅ Музыка загружена!\n\n⚙️ <b>Настройки монтажа:</b>",
        reply_markup=montage_settings_kb(data["effects"], data["text_on"]),
    )


@router.callback_query(F.data == "mt:nomusic")
async def on_no_music(callback: CallbackQuery, state: FSMContext):
    await state.update_data(music_path=None)
    await callback.answer("Без музыки ✅")


@router.callback_query(F.data == "mt:go")
async def on_go(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    video_path = data.get("video_path")
    moments = data.get("moments", [])

    if not video_path or not moments:
        await callback.answer("Нет данных. Отправь видео заново.", show_alert=True)
        await state.clear()
        return

    await state.set_state(MontageFlow.processing)
    n = len(moments)
    fx_list = [k for k, v in data.get("effects", {}).items() if v]
    fx_str = ", ".join(fx_list) if fx_list else "без эффектов"
    await callback.answer()

    montage_settings = MontageSettings(
        effects=data.get("effects", DEFAULT_EFFECTS),
        text_on=data.get("text_on", True),
        music_path=data.get("music_path"),
    )

    # ── STEP 3: Montage ──
    t0 = time.monotonic()
    async with Progress(
        callback.message,
        f"🎬 <b>Шаг 3/3</b> — Монтирую клип\n📎 {n} моментов · {fx_str}",
        "1-3 мин",
    ):
        try:
            edit_data = data.get("edit_data", {"segments": moments, "effects": []})
            result_path = await asyncio.to_thread(
                process_video, video_path, edit_data, montage_settings,
            )
        except Exception as e:
            log.error("Montage failed: %s", e, exc_info=True)
            elapsed = int(time.monotonic() - t0)
            await callback.message.edit_text(
                f"❌ Ошибка при монтаже (через {elapsed} сек).\n"
                f"Попробуй другое видео.",
                reply_markup=BACK,
            )
            _cleanup(Path(video_path))
            await state.clear()
            return

    elapsed = int(time.monotonic() - t0)

    # Send result
    result_file = FSInputFile(result_path)
    result_size = Path(result_path).stat().st_size / (1024 * 1024)
    await bot.send_video(
        chat_id=callback.message.chat.id,
        video=result_file,
        caption=(
            f"✅ <b>Клип готов!</b>\n\n"
            f"📎 {n} моментов · {fx_str}\n"
            f"⏱ Монтаж: {elapsed} сек · {result_size:.1f}MB\n"
            f"Формат: 9:16 для TikTok"
        ),
        reply_markup=result_kb("tool:clip"),
        supports_streaming=True,
        request_timeout=300,
    )

    _cleanup(Path(video_path))
    _cleanup(result_path)
    if data.get("music_path"):
        _cleanup(Path(data["music_path"]))
    await state.clear()


@router.callback_query(F.data == "mt:cancel")
async def on_cancel(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("video_path"):
        _cleanup(Path(data["video_path"]))
    if data.get("music_path"):
        _cleanup(Path(data["music_path"]))
    await state.clear()
    await callback.message.edit_text("❌ Монтаж отменён.", reply_markup=BACK)
    await callback.answer()


def _cleanup(path):
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}:{s:02d}"
