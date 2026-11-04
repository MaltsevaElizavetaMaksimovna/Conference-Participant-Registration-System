"""Поток SSE одного клиента (B1-11): снимок `stats`, затем события хаба и keep-alive.

Сначала подписка и ожидание LISTEN, потом снимок счётчика: изменение, случившееся между ними,
придёт событием, а не потеряется. Разрыв соединения отменяет генератор, подписка снимается.
"""

import asyncio
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.realtime.hub import KEEPALIVE, EventHub, stats_message

# Сколько ждать LISTEN перед снимком; дольше — отдаём снимок без гарантии (переподключится сам)
LISTEN_WAIT_S = 2.0


async def event_stream(
    hub: EventHub,
    sessionmaker: async_sessionmaker[AsyncSession],
    keepalive_s: float,
) -> AsyncIterator[str]:
    async with hub.subscribe() as queue:
        await hub.wait_listening(LISTEN_WAIT_S)
        async with sessionmaker() as session:
            yield await stats_message(session)
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), keepalive_s)
            except TimeoutError:
                yield KEEPALIVE
