"""Live progress tracker — updates a TG message with elapsed time."""

import asyncio
import time
import logging

from aiogram.types import Message

log = logging.getLogger(__name__)


class Progress:
    """
    Periodically updates a status message to show elapsed time.

    Usage:
        status = await message.answer("...")
        async with Progress(status, "🎨 Генерирую", "~15-30 сек") as p:
            result = await some_long_operation()
            # message auto-updates every 10s
    """

    def __init__(
        self,
        msg: Message,
        action: str,
        estimate: str = "",
        interval: int = 10,
    ):
        self.msg = msg
        self.action = action
        self.estimate = estimate
        self.interval = interval
        self._task: asyncio.Task | None = None
        self._start = 0.0

    async def __aenter__(self):
        self._start = time.monotonic()
        text = f"{self.action}..."
        if self.estimate:
            text += f"\n<i>Обычно занимает {self.estimate}</i>"
        try:
            await self.msg.edit_text(text)
        except Exception:
            pass
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *exc):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return False

    @property
    def elapsed(self) -> int:
        return int(time.monotonic() - self._start)

    async def update(self, text: str):
        """Manually update the status text."""
        try:
            await self.msg.edit_text(text)
        except Exception:
            pass

    async def _loop(self):
        while True:
            await asyncio.sleep(self.interval)
            sec = self.elapsed
            elapsed_str = _fmt_elapsed(sec)
            text = f"{self.action}... <b>{elapsed_str}</b>"
            if self.estimate:
                text += f"\n<i>Обычно занимает {self.estimate}</i>"
            try:
                await self.msg.edit_text(text)
            except Exception:
                pass


def _fmt_elapsed(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} сек"
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"
