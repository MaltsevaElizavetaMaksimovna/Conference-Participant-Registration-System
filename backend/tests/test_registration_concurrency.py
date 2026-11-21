"""DP-02: гонки регистрации на НАСТОЯЩИХ коммитах (B2-04).

Эти тесты не используют откатываемую фикстуру `db`: каждая сторона гонки работает в своей
сессии и своём соединении, данные коммитятся, а в конце удаляются. Откатываемая транзакция
скрыла бы гонку: все запросы шли бы через одно соединение по очереди.

Проверка заказчика: повторить 20 раз и ни разу не получить двух наклеек. Здесь:
- 20 раундов «два терминала одновременно» (вызов `register()`),
- 20 раундов «терминал против стойки»,
- по 20 раундов с двумя и десятью одновременными confirm по HTTP,
- одинаковый `Idempotency-Key` в трёх параллельных confirm.

Если убрать из UPDATE условие `AND status = 'not_registered'`, эти тесты падают
(проверено вручную при сдаче задачи).
"""

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.enums import RegSource
from app.core.text import normalize_search
from app.models.conference import Conference
from app.models.device import Printer, Terminal
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.models.staff import Role, StaffUser
from app.registration.result import RegistrationResult
from app.registration.service import register
from app.terminals.tokens import TERMINAL_PREFIX, generate_token, hash_token
from tests.registration_helpers import confirm, scan_and_get_id

ROUNDS = 20

Call = Callable[[AsyncSession], Awaitable[RegistrationResult]]


@dataclass
class World:
    """Закоммиченные данные одного теста: активная конференция, два принтера и терминала."""

    sessionmaker: async_sessionmaker[AsyncSession]
    conference_id: int = 0
    printer_ids: list[int] = field(default_factory=list)
    terminal_ids: list[int] = field(default_factory=list)
    terminal_tokens: list[str] = field(default_factory=list)
    user_id: int = 0
    role_id: int = 0
    participant_ids: list[int] = field(default_factory=list)

    async def setup(self, badge_type: str = "single") -> None:
        tag = uuid.uuid4().hex[:8]
        async with self.sessionmaker() as s:
            conference = Conference(
                title=f"Гонки {tag}",
                date_from=date.today(),
                date_to=date.today(),
                badge_type=badge_type,
                is_active=True,
            )
            s.add(conference)
            role = Role(name=f"race-role-{tag}")
            s.add(role)
            await s.flush()
            user = StaffUser(
                full_name="Гонщик",
                login=f"race-{tag}",
                password_hash="x",
                role_id=role.id,
            )
            s.add(user)
            printers = [Printer(name=f"race-printer-{tag}-{i}") for i in (1, 2)]
            s.add_all(printers)
            await s.flush()
            terminals = []
            for i, printer in enumerate(printers, 1):
                token = generate_token(TERMINAL_PREFIX)
                terminals.append(
                    Terminal(
                        name=f"race-terminal-{tag}-{i}",
                        token_hash=hash_token(token),
                        printer_id=printer.id,
                    )
                )
                self.terminal_tokens.append(token)
            s.add_all(terminals)
            await s.flush()
            self.conference_id = conference.id
            self.role_id, self.user_id = role.id, user.id
            self.printer_ids = [p.id for p in printers]
            self.terminal_ids = [t.id for t in terminals]
            await s.commit()

    async def new_participant(self, external_id: str | None = None) -> int:
        async with self.sessionmaker() as s:
            p = Participant(
                conference_id=self.conference_id,
                external_id=external_id or f"R-{uuid.uuid4().hex[:10]}",
                last_name="Гонкин",
                first_name="Иван",
                search_norm=normalize_search("Гонкин Иван"),
            )
            s.add(p)
            await s.commit()
            self.participant_ids.append(p.id)
            return p.id

    async def external_id(self, participant_id: int) -> str:
        async with self.sessionmaker() as s:
            value = await s.scalar(
                select(Participant.external_id).where(Participant.id == participant_id)
            )
            assert value is not None
            return value

    async def snapshot(self, participant_id: int) -> dict[str, Any]:
        async with self.sessionmaker() as s:
            p = (
                await s.execute(
                    select(
                        Participant.status,
                        Participant.reg_source,
                        Participant.reg_terminal_id,
                        Participant.reg_user_id,
                        Participant.rescan_count,
                    ).where(Participant.id == participant_id)
                )
            ).one()
            jobs = (
                await s.execute(
                    select(PrintJob.id, PrintJob.printer_id).where(
                        PrintJob.participant_id == participant_id
                    )
                )
            ).all()
            registered_events = await s.scalar(
                select(func.count())
                .select_from(EventLog)
                .where(EventLog.participant_id == participant_id, EventLog.type == "registered")
            )
            return {
                "status": p.status,
                "reg_source": p.reg_source,
                "reg_terminal_id": p.reg_terminal_id,
                "reg_user_id": p.reg_user_id,
                "rescan_count": p.rescan_count,
                "jobs": [(j.id, j.printer_id) for j in jobs],
                "registered_events": registered_events,
            }

    async def cleanup(self) -> None:
        async with self.sessionmaker() as s:
            c = {"c": self.conference_id}
            ids = {"t": self.terminal_ids or [0], "u": [self.user_id], "p": self.printer_ids or [0]}
            participants = "SELECT id FROM participant WHERE conference_id = :c"
            statements = [
                "DELETE FROM print_job WHERE conference_id = :c",
                "DELETE FROM idempotency_record WHERE scope = ANY(:scopes)",
                f"DELETE FROM badge_token WHERE participant_id IN ({participants})",
                "DELETE FROM event_log WHERE conference_id = :c OR terminal_id = ANY(:t)",
                "DELETE FROM participant WHERE conference_id = :c",
                "DELETE FROM terminal WHERE id = ANY(:t)",
                "DELETE FROM printer WHERE id = ANY(:p)",
                "DELETE FROM staff_user WHERE id = ANY(:u)",
                "DELETE FROM role WHERE id = :r",
                "DELETE FROM conference WHERE id = :c",
            ]
            scopes = [f"confirm:{t}" for t in self.terminal_ids] + [f"desk:{self.user_id}"]
            params = {**c, **ids, "scopes": scopes, "r": self.role_id}
            for sql in statements:
                wanted = {k: v for k, v in params.items() if f":{k}" in sql}
                await s.execute(text(sql), wanted)
            await s.commit()


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


async def race(world: World, calls: list[Call]) -> list[RegistrationResult]:
    """Запустить вызовы одновременно: у каждого своя сессия, старт — по общему барьеру."""
    barrier = asyncio.Barrier(len(calls))

    async def run(call: Call) -> RegistrationResult:
        async with world.sessionmaker() as s:
            await s.execute(text("SELECT 1"))  # соединение уже занято и прогрето
            await barrier.wait()
            return await call(s)

    return list(await asyncio.gather(*(run(c) for c in calls)))


def terminal_call(world: World, index: int, participant_id: int) -> Call:
    async def call(s: AsyncSession) -> RegistrationResult:
        return await register(
            s,
            participant_id,
            source=RegSource.TERMINAL,
            terminal_id=world.terminal_ids[index],
            user_id=None,
            with_sticker=True,
            printer_id=world.printer_ids[index],
        )

    return call


def desk_call(world: World, participant_id: int) -> Call:
    async def call(s: AsyncSession) -> RegistrationResult:
        return await register(
            s,
            participant_id,
            source=RegSource.DESK,
            terminal_id=None,
            user_id=world.user_id,
            with_sticker=True,
            printer_id=world.printer_ids[0],
        )

    return call


# ------------------------------------------------------------------ register() против register()


async def test_two_terminals_at_once_exactly_one_registration(world: World) -> None:
    for _ in range(ROUNDS):
        pid = await world.new_participant()

        results = await race(world, [terminal_call(world, 0, pid), terminal_call(world, 1, pid)])

        assert sorted(r.result for r in results) == ["already_registered", "registered"]
        winner = next(r for r in results if r.result == "registered")
        loser = next(r for r in results if r.result == "already_registered")
        snap = await world.snapshot(pid)
        assert snap["status"] == "registered"
        assert len(snap["jobs"]) == 1, snap  # ровно одна наклейка
        assert snap["registered_events"] == 1
        assert snap["reg_terminal_id"] == winner.terminal_id
        assert snap["jobs"][0][0] == winner.print_job_id
        assert loser.print_job_id is None
        # проигравший видит данные первой регистрации и считается повторной попыткой
        assert loser.registered_at == winner.registered_at
        assert loser.terminal_id == winner.terminal_id
        assert snap["rescan_count"] == 1


async def test_terminal_against_desk_exactly_one_registration(world: World) -> None:
    sources = set()
    for i in range(ROUNDS):
        pid = await world.new_participant()
        calls = [terminal_call(world, 0, pid), desk_call(world, pid)]
        if i % 2:  # порядок запуска не должен влиять на исход
            calls.reverse()

        results = await race(world, calls)

        assert sorted(r.result for r in results) == ["already_registered", "registered"]
        winner = next(r for r in results if r.result == "registered")
        snap = await world.snapshot(pid)
        assert len(snap["jobs"]) == 1, snap
        assert snap["registered_events"] == 1
        assert snap["reg_source"] == winner.source
        assert snap["jobs"][0][0] == winner.print_job_id
        if winner.source == "desk":
            assert (snap["reg_user_id"], snap["reg_terminal_id"]) == (world.user_id, None)
            assert snap["rescan_count"] == 1  # проиграл терминал: это повторная попытка
        else:
            assert snap["reg_terminal_id"] == world.terminal_ids[0]
            assert snap["rescan_count"] == 0  # стойке попытки не считаем, она получает отказ
        sources.add(winner.source)
    # (не требуем, чтобы побеждали обе стороны: это дело планировщика, а не проверки)
    assert sources <= {"desk", "terminal"}


async def test_many_parallel_attempts_still_one_registration(world: World) -> None:
    """Не только пара: пять одновременных попыток с двух терминалов и стойки."""
    for _ in range(5):
        pid = await world.new_participant()
        calls = [
            terminal_call(world, 0, pid),
            terminal_call(world, 1, pid),
            desk_call(world, pid),
            terminal_call(world, 0, pid),
            terminal_call(world, 1, pid),
        ]

        results = await race(world, calls)

        assert [r.result for r in results].count("registered") == 1
        snap = await world.snapshot(pid)
        assert len(snap["jobs"]) == 1
        assert snap["registered_events"] == 1


async def test_parallel_same_idempotency_key_returns_one_answer(world: World) -> None:
    for _ in range(ROUNDS):
        pid = await world.new_participant()

        def keyed(key: str, participant_id: int = pid) -> Call:
            async def call(s: AsyncSession) -> RegistrationResult:
                return await register(
                    s,
                    participant_id,
                    source=RegSource.TERMINAL,
                    terminal_id=world.terminal_ids[0],
                    user_id=None,
                    with_sticker=True,
                    printer_id=world.printer_ids[0],
                    idempotency_key=key,
                )

            return call

        results = await race(world, [keyed(f"one-key-{pid}")] * 3)

        assert results[0] == results[1] == results[2]
        assert results[0].result == "registered"
        snap = await world.snapshot(pid)
        assert len(snap["jobs"]) == 1
        assert snap["rescan_count"] == 0  # повторы по ключу — не повторные попытки


# ---------------------------------------------------------------------------- через HTTP


@pytest.mark.parametrize("attempts", [2, 10])
async def test_parallel_confirms_from_two_terminals_over_http(
    world: World, client: httpx.AsyncClient, attempts: int
) -> None:
    async def send(barrier: asyncio.Barrier, token: str, pid: int, scan_id: str) -> httpx.Response:
        await barrier.wait()
        return await confirm(client, token, pid, scan_id, key=uuid.uuid4().hex)

    for round_number in range(1, ROUNDS + 1):
        pid = await world.new_participant()
        raw = await world.external_id(pid)
        scans = [await scan_and_get_id(client, token, raw) for token in world.terminal_tokens]
        assert all(participant_id == pid for participant_id, _ in scans)
        barrier = asyncio.Barrier(attempts)

        indices = [i % len(scans) for i in range(attempts)]
        responses = await asyncio.wait_for(
            asyncio.gather(
                *(send(barrier, world.terminal_tokens[i], pid, scans[i][1]) for i in indices)
            ),
            30,
        )
        assert all(r.status_code == 200 for r in responses), (
            round_number,
            [(r.status_code, r.text) for r in responses],
        )
        bodies = [response.json() for response in responses]
        assert sorted(body["result"] for body in bodies) == [
            *(["already_registered"] * (attempts - 1)),
            "registered",
        ], (round_number, bodies)
        winner = next(i for i, body in enumerate(bodies) if body["result"] == "registered")
        for i, body in enumerate(bodies):
            if i != winner:
                assert body["print_job_id"] is None
                assert body["message"].startswith("Вы уже зарегистрированы (")

        winner_terminal = indices[winner]
        snap = await world.snapshot(pid)
        assert snap["status"] == "registered"
        assert snap["registered_events"] == 1, (round_number, snap)
        assert snap["reg_terminal_id"] == world.terminal_ids[winner_terminal]
        assert snap["jobs"] == [
            (bodies[winner]["print_job_id"], world.printer_ids[winner_terminal])
        ], (round_number, snap)


async def test_triple_parallel_confirm_with_same_key_over_http(
    world: World, client: httpx.AsyncClient
) -> None:
    for _ in range(10):
        pid = await world.new_participant()
        token = world.terminal_tokens[0]
        _, scan_id = await scan_and_get_id(client, token, await world.external_id(pid))

        responses = await asyncio.gather(
            *(confirm(client, token, pid, scan_id, key=f"double-click-{pid}") for _ in range(3))
        )

        assert [r.status_code for r in responses] == [200, 200, 200]
        assert responses[0].json() == responses[1].json() == responses[2].json()
        assert responses[0].json()["result"] == "registered"
        snap = await world.snapshot(pid)
        assert len(snap["jobs"]) == 1
        assert snap["registered_events"] == 1
