"""Реалтайм: хаб `LISTEN regsys_events` и поток `GET /api/events/stream` (B1-11, RG-04, NF-01).

Тесты на НАСТОЯЩИХ коммитах (NOTIFY доставляется только после COMMIT), данные — `World`.
Поток бесконечный, поэтому эндпоинт вызывается напрямую через ASGI: тело читается по кускам,
разрыв клиента — сообщение `http.disconnect`.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.auth.deps import CurrentStaff, get_current_staff
from app.core.enums import RegSource
from app.core.permissions import Permission
from app.eventlog.notify import EVENTS_CHANNEL, participant_updated_payload
from app.participants.editing import update_participant
from app.realtime.hub import KEEPALIVE, EventHub, psycopg_conninfo
from app.realtime.stream import event_stream
from app.registration.service import register
from tests.test_registration_concurrency import World

# NF-01: изменение видно в панели не позже 5 с; в тестах события приходят за миллисекунды
WAIT_S = 3.0


@pytest.fixture
async def world(database_url: str) -> AsyncIterator[World]:
    engine = create_async_engine(database_url)
    w = World(async_sessionmaker(engine, expire_on_commit=False))
    try:
        await w.setup()
        yield w
    finally:
        try:
            async with w.sessionmaker() as s:
                # change_log защищён от DELETE триггером: на время очистки триггеры отключены
                await s.execute(text("SET LOCAL session_replication_role = replica"))
                await s.execute(
                    text(
                        "DELETE FROM change_log WHERE participant_id IN "
                        "(SELECT id FROM participant WHERE conference_id = :c)"
                    ),
                    {"c": w.conference_id},
                )
                await s.commit()
            await w.cleanup()
        finally:
            await engine.dispose()


@pytest.fixture
async def hub(database_url: str, world: World) -> AsyncIterator[EventHub]:
    h = EventHub(psycopg_conninfo(database_url), world.sessionmaker, reconnect_s=0.1)
    try:
        yield h
    finally:
        await h.stop()


def parse(message: str) -> tuple[str, dict[str, Any]]:
    """`event: X\\ndata: {...}\\n\\n` -> (X, данные)."""
    assert message.endswith("\n\n"), message
    lines = message.strip("\n").split("\n")
    assert lines[0].startswith("event: ") and lines[1].startswith("data: "), message
    return lines[0].removeprefix("event: "), json.loads(lines[1].removeprefix("data: "))


async def take(queue: asyncio.Queue[str], n: int) -> list[tuple[str, dict[str, Any]]]:
    return [parse(await asyncio.wait_for(queue.get(), WAIT_S)) for _ in range(n)]


async def register_on_terminal(world: World, participant_id: int) -> None:
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


def staff_of(world: World) -> CurrentStaff:
    return CurrentStaff(
        user_id=world.user_id,
        login="race",
        full_name="Гонщик",
        role_id=world.role_id,
        permissions=frozenset(Permission),
        session_id="test",
    )


async def notify_raw(database_url: str, *payloads: str) -> None:
    async with await psycopg.AsyncConnection.connect(
        psycopg_conninfo(database_url), autocommit=True
    ) as conn:
        for payload in payloads:
            await conn.execute("SELECT pg_notify(%s, %s)", (EVENTS_CHANNEL, payload))


# ---------------------------------------------------------------- хаб


async def test_registration_sends_participant_updated_then_stats(
    world: World, hub: EventHub
) -> None:
    pid = await world.new_participant()
    await world.new_participant()
    async with hub.subscribe() as queue:
        assert await hub.wait_listening(WAIT_S)
        await register_on_terminal(world, pid)

        assert await take(queue, 2) == [
            ("participant_updated", {"id": pid, "status": "registered", "flags": []}),
            ("stats", {"registered": 1, "total": 2}),
        ]


async def test_edit_sends_event_with_data_changed(world: World, hub: EventHub) -> None:
    pid = await world.new_participant()
    async with hub.subscribe() as queue:
        assert await hub.wait_listening(WAIT_S)
        async with world.sessionmaker() as s:
            changed = await update_participant(
                s, pid, {"organization": "ООО Новая"}, staff_of(world)
            )
        assert changed == ["organization"]

        assert await take(queue, 2) == [
            (
                "participant_updated",
                {"id": pid, "status": "not_registered", "flags": ["data_changed"]},
            ),
            ("stats", {"registered": 0, "total": 1}),
        ]


async def test_garbage_and_unknown_participants_are_ignored(
    world: World, hub: EventHub, database_url: str
) -> None:
    pid = await world.new_participant()
    async with hub.subscribe() as queue:
        assert await hub.wait_listening(WAIT_S)
        await notify_raw(
            database_url,
            "не json",
            "[1, 2]",
            json.dumps({"type": "something_else", "id": pid}),
            json.dumps({"type": "participant_updated", "id": "17"}),
            json.dumps({"type": "participant_updated", "id": True}),
            participant_updated_payload(0, world.conference_id),
            participant_updated_payload(pid, world.conference_id),
        )
        event, data = (await take(queue, 1))[0]
        assert (event, data["id"]) == ("participant_updated", pid)
        assert (await take(queue, 1))[0][0] == "stats"
        assert queue.empty()


async def test_every_subscriber_gets_events_and_unsubscribes(world: World, hub: EventHub) -> None:
    pid = await world.new_participant()
    async with hub.subscribe() as first, hub.subscribe() as second:
        assert hub.subscriber_count == 2
        assert await hub.wait_listening(WAIT_S)
        await register_on_terminal(world, pid)
        assert await take(first, 2) == await take(second, 2)
    assert hub.subscriber_count == 0


async def test_slow_subscriber_drops_oldest(world: World, database_url: str) -> None:
    small = EventHub(psycopg_conninfo(database_url), world.sessionmaker, queue_size=2)
    pids = [await world.new_participant() for _ in range(2)]
    try:
        async with small.subscribe() as queue:
            assert await small.wait_listening(WAIT_S)
            for pid in pids:
                await register_on_terminal(world, pid)
            await asyncio.sleep(0.5)
            # 4 сообщения в очередь на 2: остались последние — событие второго и итоговый stats
            assert await take(queue, 2) == [
                ("participant_updated", {"id": pids[1], "status": "registered", "flags": []}),
                ("stats", {"registered": 2, "total": 2}),
            ]
    finally:
        await small.stop()


async def test_hub_reconnects_after_connection_loss(
    world: World, hub: EventHub, database_url: str
) -> None:
    pid = await world.new_participant()
    async with hub.subscribe() as queue:
        assert await hub.wait_listening(WAIT_S)
        async with await psycopg.AsyncConnection.connect(
            psycopg_conninfo(database_url), autocommit=True
        ) as conn:
            await conn.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE query = %s AND pid <> pg_backend_pid()",
                (f"LISTEN {EVENTS_CHANNEL}",),
            )
        await asyncio.sleep(0.5)  # обрыв замечен, прошла пауза переподключения
        assert await hub.wait_listening(WAIT_S)

        await register_on_terminal(world, pid)
        assert (await take(queue, 1))[0] == (
            "participant_updated",
            {"id": pid, "status": "registered", "flags": []},
        )


# ---------------------------------------------------------------- поток одного клиента


async def test_stream_starts_with_stats_then_keepalive_and_events(
    world: World, hub: EventHub
) -> None:
    pid = await world.new_participant()
    stream = event_stream(hub, world.sessionmaker, keepalive_s=0.2)
    try:
        assert parse(await anext(stream)) == ("stats", {"registered": 0, "total": 1})
        assert await anext(stream) == KEEPALIVE

        await register_on_terminal(world, pid)
        messages: list[str] = []
        while len(messages) < 2:
            message = await asyncio.wait_for(anext(stream), WAIT_S)
            if message != KEEPALIVE:
                messages.append(message)
        assert [parse(m)[0] for m in messages] == ["participant_updated", "stats"]
        assert parse(messages[1])[1] == {"registered": 1, "total": 1}
    finally:
        await stream.aclose()
    assert hub.subscriber_count == 0


# ---------------------------------------------------------------- эндпоинт через ASGI


class AsgiStream:
    """Запрос к ASGI-приложению с телом по кускам; `close()` — клиент оборвал соединение."""

    def __init__(self, app: FastAPI, path: str) -> None:
        self.start: dict[str, Any] = {}
        self.chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._disconnected = asyncio.Event()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test")],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }
        self.task = asyncio.create_task(app(scope, self._receive, self._send))

    async def _receive(self) -> dict[str, Any]:
        await self._disconnected.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.start = message
        elif message["type"] == "http.response.body" and message.get("body"):
            await self.chunks.put(message["body"])

    async def next_event(self) -> tuple[str, dict[str, Any]]:
        """Следующее событие, keep-alive пропускается."""
        while True:
            chunk = (await asyncio.wait_for(self.chunks.get(), WAIT_S)).decode()
            if chunk != KEEPALIVE:
                return parse(chunk)

    async def close(self) -> None:
        self._disconnected.set()
        await asyncio.wait_for(self.task, WAIT_S)


async def test_endpoint_streams_events_until_client_disconnects(app: FastAPI, world: World) -> None:
    async def viewer() -> CurrentStaff:
        return staff_of(world)

    app.dependency_overrides[get_current_staff] = viewer
    hub: EventHub = app.state.event_hub
    pid = await world.new_participant()
    stream = AsgiStream(app, "/api/events/stream")
    try:
        assert await stream.next_event() == ("stats", {"registered": 0, "total": 1})
        headers = {k.decode(): v.decode() for k, v in stream.start["headers"]}
        assert stream.start["status"] == 200
        assert headers["content-type"].startswith("text/event-stream")
        assert headers["cache-control"] == "no-cache"
        assert headers["x-accel-buffering"] == "no"
        assert hub.subscriber_count == 1

        await register_on_terminal(world, pid)
        assert await stream.next_event() == (
            "participant_updated",
            {"id": pid, "status": "registered", "flags": []},
        )
        assert await stream.next_event() == ("stats", {"registered": 1, "total": 1})
    finally:
        await stream.close()
        await hub.stop()
    assert hub.subscriber_count == 0
