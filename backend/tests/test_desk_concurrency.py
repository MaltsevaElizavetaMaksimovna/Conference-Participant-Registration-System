"""Гонки B2-15 через независимые подключения к PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from app.auth.deps import CurrentStaff, get_current_staff
from app.core.enums import EventType
from app.core.permissions import Permission
from app.models.conference import Conference
from app.models.device import Terminal
from app.models.staff import StaffUser
from app.registration import desk
from tests.registration_helpers import confirm, events, print_jobs, scan_and_get_id
from tests.test_registration_concurrency import World


@pytest.fixture
async def desk_world(app: FastAPI) -> AsyncIterator[tuple[World, str]]:
    world = World(app.state.sessionmaker)
    await world.setup()
    try:
        async with world.sessionmaker() as db:
            user = await db.get(StaffUser, world.user_id)
            assert user is not None
            user.panel_printer_id = world.printer_ids[1]
            staff = CurrentStaff(
                user_id=user.id,
                login=user.login,
                full_name=user.full_name,
                role_id=user.role_id,
                permissions=frozenset({Permission.REGISTRATION_DESK, Permission.STICKERS_PRINT}),
                session_id="desk-race",
            )
            await db.commit()

        app.dependency_overrides[get_current_staff] = lambda: staff
        yield world, staff.login
    finally:
        app.dependency_overrides.pop(get_current_staff, None)
        async with world.sessionmaker() as db:
            await db.execute(
                update(StaffUser).where(StaffUser.id == world.user_id).values(panel_printer_id=None)
            )
            await db.commit()
        await world.cleanup()


async def test_desk_and_terminal_register_once(
    desk_world: tuple[World, str], client: httpx.AsyncClient
) -> None:
    world, login = desk_world
    pid = await world.new_participant()
    token = world.terminal_tokens[0]
    _, scan_id = await scan_and_get_id(client, token, await world.external_id(pid))
    url = f"/api/participants/{pid}/register"

    desk_response, kiosk = await asyncio.gather(
        client.post(url), confirm(client, token, pid, scan_id)
    )
    assert kiosk.status_code == 200, kiosk.text
    repeat = await client.post(url)
    assert repeat.status_code == 409, repeat.text
    assert repeat.json()["code"] == "already_registered"
    details = repeat.json()["details"]
    snapshot = await world.snapshot(pid)
    assert snapshot["registered_events"] == 1
    assert len(snapshot["jobs"]) == 1

    if desk_response.status_code == 200:
        assert kiosk.json()["result"] == "already_registered"
        assert details["source"] == "desk"
        assert details["user_login"] == login
        assert details["terminal_name"] is None
        registration = desk_response.json()["participant"]["registration"]
        assert datetime.fromisoformat(details["registered_at"]) == datetime.fromisoformat(
            registration["at"]
        )
        assert snapshot["jobs"] == [(desk_response.json()["print_job_id"], world.printer_ids[1])]
    else:
        assert desk_response.status_code == 409, desk_response.text
        assert kiosk.json()["result"] == "registered"
        assert desk_response.json() == repeat.json()
        assert details["source"] == "terminal"
        async with world.sessionmaker() as db:
            terminal = await db.get(Terminal, world.terminal_ids[0])
            assert terminal is not None
            assert details["terminal_name"] == terminal.name
        assert details["user_login"] is None
        assert details["registered_at"]
        assert snapshot["jobs"] == [(kiosk.json()["print_job_id"], world.printer_ids[0])]


async def test_parallel_reprints_with_same_key(
    desk_world: tuple[World, str], client: httpx.AsyncClient
) -> None:
    world, _ = desk_world
    pid = await world.new_participant()
    url = f"/api/participants/{pid}"
    registered = await client.post(f"{url}/register", json={"with_sticker": False})
    assert registered.status_code == 200, registered.text

    headers = {"Idempotency-Key": "one-press"}
    first, second = await asyncio.gather(
        client.post(f"{url}/reprint", headers=headers),
        client.post(f"{url}/reprint", headers=headers),
    )
    assert first.status_code == second.status_code == 200, (first.text, second.text)
    assert first.json() == second.json()
    async with world.sessionmaker() as db:
        [job] = await print_jobs(db, pid)
        assert job.id == first.json()["print_job_id"]
        assert len(await events(db, EventType.REPRINT, pid)) == 1


async def test_register_holds_conference_lock_until_card_is_built(
    desk_world: tuple[World, str], client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, _ = desk_world
    pid = await world.new_participant()
    card_started = asyncio.Event()
    continue_card = asyncio.Event()
    get_card = desk.get_card

    async def delayed_card(*args, **kwargs):
        card_started.set()
        await continue_card.wait()
        return await get_card(*args, **kwargs)

    monkeypatch.setattr(desk, "get_card", delayed_card)
    registration = asyncio.create_task(client.post(f"/api/participants/{pid}/register"))
    try:
        await asyncio.wait_for(card_started.wait(), timeout=5)
        async with world.sessionmaker() as db:
            with pytest.raises(OperationalError) as error:
                await db.execute(
                    select(Conference.id)
                    .where(Conference.id == world.conference_id)
                    .with_for_update(nowait=True)
                )
            assert getattr(error.value.orig, "sqlstate", None) == "55P03"
    finally:
        continue_card.set()
        response = await registration
    assert response.status_code == 200, response.text
