import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer, FilesPathWrapper
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, BotCommand

from config import settings
from db import init_db
from bot.handlers import start, montage, generate, edit_photo, remove_bg, upscale, video_gen
import bot.keyboards as kb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


class _LocalFilesWrapper(FilesPathWrapper):
    """Map container paths to host bind mount, handling ':' → fullwidth colon on Windows."""

    SERVER_ROOT = "/var/lib/telegram-bot-api"

    def __init__(self, local_data: Path) -> None:
        self.local_data = local_data

    def to_local(self, path: Path | str) -> Path | str:
        s = str(path)
        if s.startswith(self.SERVER_ROOT):
            rel = s[len(self.SERVER_ROOT):].lstrip("/")
            # Docker bind mount on Windows maps ':' to fullwidth colon U+F03A
            if sys.platform == "win32":
                rel = rel.replace(":", "\uf03a")
            return self.local_data / rel
        return path

    def to_server(self, path: Path | str) -> Path | str:
        return path


def create_bot() -> Bot:
    session = None
    if settings.local_bot_api_url:
        server = TelegramAPIServer.from_base(
            settings.local_bot_api_url,
            is_local=True,
            wrap_local_file=_LocalFilesWrapper(settings.local_bot_api_data),
        )
        session = AiohttpSession(api=server)
        log.info("Using Local Bot API: %s", settings.local_bot_api_url)

    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


# Fallback router — catches everything not handled above
fallback_router = Router()


@fallback_router.message(F.photo)
async def fallback_photo(message: Message):
    await message.answer(
        "📷 Вижу фото! Чтобы я мог его обработать,\n"
        "сначала выбери инструмент в меню 👇",
        reply_markup=kb.BACK,
    )


@fallback_router.message(F.sticker)
async def fallback_sticker(message: Message):
    await message.answer(
        "Выбери инструмент в меню 👇",
        reply_markup=kb.BACK,
    )


@fallback_router.message(F.text)
async def fallback_text(message: Message):
    await message.answer(
        "Используй меню для навигации 👇",
        reply_markup=kb.BACK,
    )


@fallback_router.message()
async def fallback_any(message: Message):
    await message.answer(
        "Используй меню 👇",
        reply_markup=kb.BACK,
    )


async def main():
    await init_db()

    bot = create_bot()
    dp = Dispatcher(storage=MemoryStorage())

    # Set bot commands (blue menu button in TG)
    await bot.set_my_commands([
        BotCommand(command="start", description="Главное меню"),
    ])

    # Order matters: start first (nav + callbacks), then feature handlers, fallback last
    dp.include_router(start.router)
    dp.include_router(generate.router)
    dp.include_router(edit_photo.router)
    dp.include_router(remove_bg.router)
    dp.include_router(upscale.router)
    dp.include_router(video_gen.router)
    dp.include_router(montage.router)      # catches F.video + video F.document
    dp.include_router(fallback_router)      # catches everything else

    log.info("VClipAI bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
