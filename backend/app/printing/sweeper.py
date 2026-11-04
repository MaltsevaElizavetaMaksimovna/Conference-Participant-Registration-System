"""Фоновая пометка просроченных заданий печати (B2-11, TR-08).

Агент сам помечает просрочку своего принтера при каждом опросе, но выключенный агент не
опрашивает. Тогда задание терминала так и висело бы `pending`, а пометка «Наклейка не
напечатана» не появилась бы. Поэтому сервер раз в `RS_PRINT_SWEEP_INTERVAL_S` секунд
проверяет очередь сам.
"""

import asyncio
import logging
from contextlib import suppress

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.printing.queue import expire_stale

log = logging.getLogger(__name__)


class PrintSweeper:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self._sessionmaker = sessionmaker
        self._settings = settings
        self._task: asyncio.Task[None] | None = None

    async def sweep_once(self) -> int:
        async with self._sessionmaker() as session:
            return await expire_stale(session, self._settings)

    async def _run(self) -> None:
        while True:
            try:
                await self.sweep_once()
            except Exception:  # БД недоступна и т. п.: пробуем на следующем круге
                log.exception("Не удалось пометить просроченные задания печати")
            await asyncio.sleep(self._settings.print_sweep_interval_s)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="print-sweeper")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None
