"""B2-04a: события `participant_updated` через `NOTIFY regsys_events` (RG-04, NF-01).

Тесты работают на НАСТОЯЩИХ коммитах (как `test_registration_concurrency`): откатываемая
фикстура `db` никогда не делает COMMIT, и слушатель ничего бы не получил. Слушатель —
отдельное соединение с `LISTEN regsys_events`; чужие события отсекаются по конференции.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.enums import PrintJobKind, PrintJobStatus, RegSource
from app.eventlog.notify import EVENTS_CHANNEL, notify_participant_updated
from app.models.printing import PrintJob
from app.printing.jobs import set_job_status
from app.registration.service import register
from tests.test_registration_concurrency import World

# Сколько ждать событий: после COMMIT они приходят за миллисекунды
WAIT_S = 1.0


@pytest.fixture
async def world(database_url: str) -> AsyncIterator[World]:
    engine = create_async_engine(database_url)
    w = World(async_sessionmaker(engine, expire_on_commit=False))
    try:
        await w.setup()
        yield w
    finally:
        try:
            await w.cleanup()
        finally:
            await engine.dispose()


class Listener:
    def __init__(self, conn: psycopg.AsyncConnection[Any], conference_id: int) -> None:
        self._conn = conn
        self._conference_id = conference_id

    async def events(self, wait_s: float = WAIT_S) -> list[dict[str, Any]]:
        """Все события этой конференции, пришедшие за `wait_s` секунд."""
        got = []
        async for n in self._conn.notifies(timeout=wait_s):
            assert n.channel == EVENTS_CHANNEL
            data = json.loads(n.payload)
            if data.get("conference_id") == self._conference_id:
                got.append(data)
        return got


@pytest.fixture
async def listener(database_url: str, world: World) -> AsyncIterator[Listener]:
    conninfo = make_url(database_url).set(drivername="postgresql")
    conn = await psycopg.AsyncConnection.connect(
        conninfo.render_as_string(hide_password=False), autocommit=True
    )
    try:
        await conn.execute(f"LISTEN {EVENTS_CHANNEL}")
        yield Listener(conn, world.conference_id)
    finally:
        await conn.close()


def expected(world: World, participant_id: int) -> dict[str, Any]:
    return {
        "type": "participant_updated",
        "id": participant_id,
        "conference_id": world.conference_id,
    }


async def register_on_terminal(world: World, participant_id: int) -> int | None:
    async with world.sessionmaker() as s:
        result = await register(
            s,
            participant_id,
            source=RegSource.TERMINAL,
            terminal_id=world.terminal_ids[0],
            user_id=None,
            with_sticker=True,
            printer_id=world.printer_ids[0],
        )
    assert result.result == "registered"
    return result.print_job_id


async def test_registration_sends_event_after_commit(world: World, listener: Listener) -> None:
    pid = await world.new_participant()

    await register_on_terminal(world, pid)

    assert await listener.events() == [expected(world, pid)]


async def test_desk_registration_without_sticker_sends_event(
    world: World, listener: Listener
) -> None:
    pid = await world.new_participant()

    async with world.sessionmaker() as s:
        await register(
            s,
            pid,
            source=RegSource.DESK,
            terminal_id=None,
            user_id=world.user_id,
            with_sticker=False,
            printer_id=None,
        )

    assert await listener.events() == [expected(world, pid)]


async def test_repeat_registration_sends_nothing(world: World, listener: Listener) -> None:
    pid = await world.new_participant()
    await register_on_terminal(world, pid)
    assert len(await listener.events()) == 1

    async with world.sessionmaker() as s:
        again = await register(
            s,
            pid,
            source=RegSource.TERMINAL,
            terminal_id=world.terminal_ids[1],
            user_id=None,
            with_sticker=True,
            printer_id=world.printer_ids[1],
        )

    assert again.result == "already_registered"
    assert await listener.events() == []  # статус и пометки не изменились


async def test_event_is_delivered_only_on_commit(world: World, listener: Listener) -> None:
    pid = await world.new_participant()

    async with world.sessionmaker() as s:
        await notify_participant_updated(s, pid, world.conference_id)
        assert await listener.events(0.3) == []  # транзакция ещё открыта
        await s.commit()

    assert await listener.events() == [expected(world, pid)]


async def test_rolled_back_change_sends_nothing(world: World, listener: Listener) -> None:
    pid = await world.new_participant()

    async with world.sessionmaker() as s:
        await notify_participant_updated(s, pid, world.conference_id)
        await s.rollback()

    assert await listener.events() == []


async def test_print_job_status_change_sends_event(world: World, listener: Listener) -> None:
    pid = await world.new_participant()
    job_id = await register_on_terminal(world, pid)
    assert job_id is not None
    await listener.events()  # событие самой регистрации

    for status in (PrintJobStatus.SENT, PrintJobStatus.DONE):
        async with world.sessionmaker() as s:
            assert await set_job_status(s, job_id, status)
            await s.commit()
        assert await listener.events() == [expected(world, pid)], status

    async with world.sessionmaker() as s:
        job = (await s.execute(select(PrintJob).where(PrintJob.id == job_id))).scalar_one()
    assert job.status == "done"
    assert job.sent_at is not None
    assert job.done_at is not None


async def test_print_job_error_keeps_message(world: World, listener: Listener) -> None:
    pid = await world.new_participant()
    job_id = await register_on_terminal(world, pid)
    assert job_id is not None
    await listener.events()

    async with world.sessionmaker() as s:
        await set_job_status(s, job_id, PrintJobStatus.ERROR, error="timeout")
        await s.commit()
        job = (await s.execute(select(PrintJob).where(PrintJob.id == job_id))).scalar_one()

    assert (job.status, job.error) == ("error", "timeout")
    assert job.done_at is not None
    assert await listener.events() == [expected(world, pid)]


async def test_test_print_job_sends_nothing(world: World, listener: Listener) -> None:
    async with world.sessionmaker() as s:
        job = PrintJob(
            conference_id=world.conference_id,
            printer_id=world.printer_ids[0],
            kind=PrintJobKind.TEST,
            sides=1,
        )
        s.add(job)
        await s.commit()
        assert await set_job_status(s, job.id, PrintJobStatus.DONE)
        await s.commit()

    assert await listener.events() == []  # у пробной печати нет участника


async def test_unknown_print_job(world: World) -> None:
    async with world.sessionmaker() as s:
        assert not await set_job_status(s, 0, PrintJobStatus.DONE)
