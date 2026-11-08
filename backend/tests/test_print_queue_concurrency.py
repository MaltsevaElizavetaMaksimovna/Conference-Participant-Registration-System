"""B2-11: гонки очереди печати на НАСТОЯЩИХ коммитах.

- `FOR UPDATE SKIP LOCKED`: одновременные запросы агента разбирают задания без повторов;
- ответ агента и просрочка задания не применяются дважды (условный UPDATE).

Откатываемая фикстура `db` здесь не годится: все запросы шли бы через одно соединение.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.models.device import Printer
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.printing.queue import claim_next, expire_stale, finish_job
from app.printing.schemas import AgentJobCopy
from tests.test_registration_concurrency import World

ROUNDS = 10


@pytest.fixture
async def world(database_url: str) -> AsyncIterator[World]:
    engine = create_async_engine(database_url, pool_size=10, max_overflow=10)
    w = World(async_sessionmaker(engine, expire_on_commit=False))
    try:
        await w.setup()
        yield w
    finally:
        try:
            await w.cleanup()
        finally:
            await engine.dispose()


async def no_render(
    session: AsyncSession, settings: Settings, job: PrintJob, printer: Printer
) -> list[AgentJobCopy]:
    """Рендер здесь не проверяется: только блокировки."""
    await asyncio.sleep(0.05)  # держим блокировку, пока соседний запрос ищет задание
    return []


async def add_jobs(world: World, count: int) -> list[int]:
    ids = []
    async with world.sessionmaker() as s:
        for _ in range(count):
            pid = await world.new_participant()
            job = PrintJob(
                conference_id=world.conference_id,
                participant_id=pid,
                printer_id=world.printer_ids[0],
                kind="first",
                sides=1,
            )
            s.add(job)
            await s.flush()
            ids.append(job.id)
        await s.commit()
    return ids


async def claim(world: World, settings: Settings) -> int | None:
    async with world.sessionmaker() as s:
        printer = await s.get(Printer, world.printer_ids[0])
        assert printer is not None
        job = await claim_next(s, settings, printer, no_render)
        return job.job_id if job else None


async def test_parallel_claims_never_share_a_job(world: World, settings: Settings) -> None:
    for _ in range(ROUNDS):
        ids = await add_jobs(world, 3)

        got = await asyncio.gather(*(claim(world, settings) for _ in range(5)))

        claimed = [j for j in got if j is not None]
        assert sorted(claimed) == sorted(ids)  # каждое задание ровно одному запросу
        async with world.sessionmaker() as s:
            attempts = await s.scalars(select(PrintJob.attempts).where(PrintJob.id.in_(ids)))
            assert set(attempts) == {1}


async def test_result_and_expiry_apply_once(world: World, settings: Settings) -> None:
    for _ in range(ROUNDS):
        [job_id] = await add_jobs(world, 1)
        assert await claim(world, settings) == job_id
        async with world.sessionmaker() as s:
            await s.execute(
                update(PrintJob)
                .where(PrintJob.id == job_id)
                .values(sent_at=func.now() - timedelta(seconds=120))
            )
            await s.commit()

        async def fail(job_id: int = job_id) -> None:
            async with world.sessionmaker() as s:
                await finish_job(s, world.printer_ids[0], job_id, False, "Нет ленты")

        async def expire() -> None:
            async with world.sessionmaker() as s:
                await expire_stale(s, settings, world.printer_ids[0])

        await asyncio.gather(fail(), expire())

        async with world.sessionmaker() as s:
            job = (await s.execute(select(PrintJob).where(PrintJob.id == job_id))).scalar_one()
            assert job.status == "error"
            assert job.error in ("Нет ленты", "timeout")
            errors = await s.scalar(
                select(func.count())
                .select_from(EventLog)
                .where(
                    EventLog.participant_id == job.participant_id, EventLog.type == "print_error"
                )
            )
            assert errors == 1  # итог применён ровно один раз
            flagged = await s.scalar(
                select(Participant.sticker_not_printed).where(Participant.id == job.participant_id)
            )
            assert flagged is True


async def test_repeated_ok_counts_one_print(world: World, settings: Settings) -> None:
    [job_id] = await add_jobs(world, 1)
    assert await claim(world, settings) == job_id

    async def ok() -> None:
        async with world.sessionmaker() as s:
            await finish_job(s, world.printer_ids[0], job_id, True, None)

    await asyncio.gather(*(ok() for _ in range(5)))  # агент повторил ответ после обрыва

    async with world.sessionmaker() as s:
        pid = await s.scalar(select(PrintJob.participant_id).where(PrintJob.id == job_id))
        count = await s.scalar(select(Participant.print_count).where(Participant.id == pid))
        assert count == 1
