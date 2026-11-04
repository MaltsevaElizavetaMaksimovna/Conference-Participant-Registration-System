"""Раздача событий панели: одно `LISTEN regsys_events` на процесс (B1-11, RG-04, NF-01).

Источник — `pg_notify` из транзакций регистрации, печати и правок (`app.eventlog.notify`): событие
приходит только после COMMIT. На каждое `participant_updated` активной конференции хаб читает
актуальные статус и пометки участника и свежий счётчик и кладёт готовые SSE-сообщения в очереди
всех подписчиков. Соединение поднимается при первом подписчике и восстанавливается после обрыва.
"""

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import psycopg
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.eventlog.notify import EVENTS_CHANNEL, PARTICIPANT_UPDATED
from app.models.conference import Conference
from app.models.participant import Participant
from app.participants.search import participant_stats
from app.participants.service import participant_flags
from app.realtime.schemas import (
    PARTICIPANT_UPDATED_EVENT,
    STATS_EVENT,
    ParticipantUpdatedEvent,
    StatsEvent,
)

log = logging.getLogger("app.realtime")

KEEPALIVE = ": keep-alive\n\n"


def sse_message(event: str, data: BaseModel) -> str:
    return f"event: {event}\ndata: {data.model_dump_json()}\n\n"


def psycopg_conninfo(database_url: str) -> str:
    """URL SQLAlchemy (`postgresql+psycopg://…`) -> строка подключения psycopg."""
    url = make_url(database_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


async def stats_message(session: AsyncSession) -> str:
    stats = await participant_stats(session)
    return sse_message(STATS_EVENT, StatsEvent(registered=stats.registered, total=stats.total))


def _participant_id(payload: str) -> int | None:
    """id участника из `participant_updated`; всё остальное — None."""
    try:
        data: Any = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("type") != PARTICIPANT_UPDATED:
        return None
    pid = data.get("id")
    return pid if isinstance(pid, int) and not isinstance(pid, bool) else None


class EventHub:
    def __init__(
        self,
        conninfo: str,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        reconnect_s: float = 1.0,
        queue_size: int = 100,
    ) -> None:
        self._conninfo = conninfo
        self._sessionmaker = sessionmaker
        self._reconnect_s = reconnect_s
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[str]] = set()
        self._task: asyncio.Task[None] | None = None
        self._listening = asyncio.Event()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[str]]:
        """Очередь готовых SSE-сообщений на время подключения клиента."""
        queue: asyncio.Queue[str] = asyncio.Queue(self._queue_size)
        self._subscribers.add(queue)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="realtime-listen")
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)

    async def wait_listening(self, timeout_s: float) -> bool:
        """Дождаться, пока LISTEN установлен (события после этого не теряются)."""
        try:
            await asyncio.wait_for(self._listening.wait(), timeout_s)
        except TimeoutError:
            return False
        return True

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._listening.clear()

    async def _run(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._conninfo, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {EVENTS_CHANNEL}")
                    self._listening.set()
                    async for notify in conn.notifies():
                        await self._handle(notify.payload)
            except (psycopg.Error, OSError) as e:
                log.warning("LISTEN %s прервано: %s", EVENTS_CHANNEL, type(e).__name__)
            finally:
                self._listening.clear()
            await asyncio.sleep(self._reconnect_s)

    async def _handle(self, payload: str) -> None:
        participant_id = _participant_id(payload)
        if participant_id is None:
            return
        try:
            async with self._sessionmaker() as session:
                p = await session.scalar(
                    select(Participant)
                    .join(Conference, Conference.id == Participant.conference_id)
                    .where(Participant.id == participant_id, Conference.is_active)
                )
                if p is None:
                    return
                updated = ParticipantUpdatedEvent(
                    id=p.id,
                    status=p.status,  # type: ignore[arg-type]
                    flags=participant_flags(p),
                )
                stats = await stats_message(session)
        except Exception:
            log.exception("Событие участника %s не разослано", participant_id)
            return
        self._broadcast(sse_message(PARTICIPANT_UPDATED_EVENT, updated))
        self._broadcast(stats)

    def _broadcast(self, message: str) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # медленный клиент: теряет самое старое, свежий stats всё равно придёт
                queue.get_nowait()
            queue.put_nowait(message)
