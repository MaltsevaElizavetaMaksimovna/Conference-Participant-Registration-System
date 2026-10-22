"""Журнал событий: `GET /api/admin/events` (S-02)."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import EventLog
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import make_conference, make_participant

URL = "/api/admin/events"


def at(minutes: int) -> datetime:
    return datetime(2026, 11, 20, 9, 0, tzinfo=UTC) + timedelta(minutes=minutes)


async def test_events_of_active_conference_newest_first(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.view")
    conf, old = await make_conference(db), await make_conference(db, active=False)
    p = await make_participant(db, conf, "B24-1001")
    other = await make_participant(
        db, conf, "B24-1002", last_name="Петрова", first_name="Анна", middle_name=None
    )
    terminal, _ = await devices.terminal("Терминал 7")
    db.add_all(
        [
            EventLog(
                conference_id=conf.id,
                type="registered",
                participant_id=p.id,
                terminal_id=terminal.id,
                created_at=at(1),
                payload={"with_sticker": True},
            ),
            EventLog(
                conference_id=conf.id,
                type="scan_not_found",
                raw_code="ZZZ",
                terminal_id=terminal.id,
                created_at=at(2),
            ),
            EventLog(
                conference_id=conf.id,
                type="reprint",
                participant_id=other.id,
                user_id=c.user_id,
                created_at=at(3),
            ),
            EventLog(conference_id=old.id, type="registered", created_at=at(4)),
        ]
    )
    await db.commit()

    r = await c.get(URL)
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 3
    assert [e["type"] for e in page["items"]] == ["reprint", "scan_not_found", "registered"]
    reprint, not_found, registered = page["items"]
    assert set(reprint) == {
        "id",
        "type",
        "at",
        "participant_id",
        "participant_name",
        "terminal_name",
        "user_login",
        "raw_code",
        "payload",
    }
    assert reprint["participant_name"] == "Петрова Анна"
    assert reprint["user_login"] == c.login
    assert reprint["terminal_name"] is None
    assert not_found["participant_id"] is None
    assert not_found["participant_name"] is None
    assert not_found["raw_code"] == "ZZZ"
    assert not_found["terminal_name"] == "Терминал 7"
    assert registered["participant_name"] == "Иванов Пётр Сергеевич"
    assert registered["payload"] == {"with_sticker": True}
    assert registered["at"].startswith("2026-11-20T09:01:00")


async def test_filters_and_pagination(
    login_as: LoginAs, db: AsyncSession, devices: Devices
) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    p = await make_participant(db, conf, "B24-1001")
    t1, _ = await devices.terminal()
    t2, _ = await devices.terminal()
    db.add_all(
        [
            EventLog(
                conference_id=conf.id,
                type="scan_rescan",
                participant_id=p.id,
                terminal_id=t1.id,
                created_at=at(1),
            ),
            EventLog(
                conference_id=conf.id,
                type="scan_rescan",
                participant_id=p.id,
                terminal_id=t2.id,
                created_at=at(2),
            ),
            EventLog(
                conference_id=conf.id, type="scan_not_found", terminal_id=t2.id, created_at=at(3)
            ),
        ]
    )
    await db.commit()

    async def total(**params: object) -> int:
        r = await c.get(URL, params=params)
        assert r.status_code == 200, r.text
        value: int = r.json()["total"]
        return value

    assert await total(type="scan_rescan") == 2
    assert await total(participant_id=p.id) == 2
    assert await total(terminal_id=t2.id) == 2
    assert await total(terminal_id=t2.id, type="scan_rescan") == 1
    assert await total(type="registered") == 0

    page = (await c.get(URL, params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 3
    assert [e["type"] for e in page["items"]] == ["scan_rescan"]

    bad = await c.get(URL, params={"type": "teleport"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation_error"


async def test_no_active_conference_gives_empty_list(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db, active=False)
    db.add(EventLog(conference_id=conf.id, type="registered", created_at=at(1)))
    await db.commit()
    assert (await c.get(URL)).json() == {"items": [], "total": 0}


async def test_permissions(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    assert (await (await login_as("imports.run")).get(URL)).status_code == 403
    assert (await anon.get(URL)).status_code == 401
