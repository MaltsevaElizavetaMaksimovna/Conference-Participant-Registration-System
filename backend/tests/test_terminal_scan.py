"""POST /api/terminal/scan (B2-03): TR-01, TR-02, TR-07, DP-01."""

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Devices
from tests.registration_helpers import (
    ALREADY_SUFFIX,
    NOT_FOUND,
    events,
    make_conference,
    make_participant,
    scan,
    to_russian_layout,
    utc,
)

LINK = "https://invite.example.ru/event?id={}"


async def test_found_shows_print_spelling(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    _, token = await devices.terminal()

    data = await scan(db_client, token, LINK.format("B24-1001"))

    assert data["result"] == "found"
    assert data["participant"] == {
        "id": p.id,
        "full_name": "Иванов Пётр Сергеевич",
        "position": "Инженер",
        "organization": "ООО Ромашка",
    }
    assert data["scan_id"]
    # скан участника ничего не меняет
    await db.refresh(p)
    assert (p.status, p.rescan_count, p.registered_at) == ("not_registered", 0, None)
    assert await events(db, "scan_not_found") == []


async def test_empty_position_and_organization_are_not_specified(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-02: «не указано», регистрация при этом возможна."""
    conference = await make_conference(db)
    await make_participant(db, conference, "X1", position=None, organization="  ", middle_name=None)
    _, token = await devices.terminal()

    data = await scan(db_client, token, "X1")

    assert data["result"] == "found"
    assert data["participant"]["full_name"] == "Иванов Пётр"
    assert data["participant"]["position"] == "не указано"
    assert data["participant"]["organization"] == "не указано"


async def test_other_conference_code_is_not_found(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-01: поиск только в активной конференции."""
    old = await make_conference(db, active=False, title="Прошлогодняя")
    await make_participant(db, old, "OLD-1")
    active = await make_conference(db)
    await make_participant(db, active, "NEW-1")
    _, token = await devices.terminal()

    assert (await scan(db_client, token, LINK.format("OLD-1")))["result"] == "not_found"
    assert (await scan(db_client, token, LINK.format("NEW-1")))["result"] == "found"


async def test_no_active_conference_is_not_found(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    old = await make_conference(db, active=False)
    await make_participant(db, old, "OLD-1")
    _, token = await devices.terminal()

    data = await scan(db_client, token, "OLD-1")

    assert data == {"result": "not_found", "message": NOT_FOUND}


async def test_not_found_is_logged_and_nothing_changes(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-07: время, терминал и считанный код — в журнале."""
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    terminal, token = await devices.terminal()

    data = await scan(db_client, token, LINK.format("NO-SUCH"))

    assert data == {"result": "not_found", "message": NOT_FOUND}
    (event,) = await events(db, "scan_not_found")
    assert event.raw_code == LINK.format("NO-SUCH")
    assert event.terminal_id == terminal.id
    assert event.conference_id == conference.id
    assert event.created_at is not None
    await db.refresh(p)
    assert (p.status, p.rescan_count) == ("not_registered", 0)


async def test_link_without_id_is_not_found(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    await make_participant(db, conference, "B24-1001")
    _, token = await devices.terminal()

    for raw in ("https://invite.example.ru/", "https://invite.example.ru", "ftp://x/y", "!!"):
        assert (await scan(db_client, token, raw))["result"] == "not_found", raw
    assert len(await events(db, "scan_not_found")) == 4


async def test_badge_sticker_qr_is_not_found(
    app: FastAPI, db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-07: QR с наклейки не регистрирует, даже если токен совпал бы с каким-то ID."""
    app.state.settings = app.state.settings.model_copy(
        update={"public_base_url": "https://reg.example.ru"}
    )
    conference = await make_conference(db)
    await make_participant(db, conference, "Zk3x9QnS7Vb2LmT4")
    _, token = await devices.terminal()

    data = await scan(db_client, token, "https://reg.example.ru/p/Zk3x9QnS7Vb2LmT4")

    assert data["result"] == "not_found"
    assert len(await events(db, "scan_not_found")) == 1


async def test_russian_layout_is_fixed(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "A1b2")
    _, token = await devices.terminal()
    raw = to_russian_layout(LINK.format("A1b2"))
    assert raw != LINK.format("A1b2")

    data = await scan(db_client, token, raw)

    assert data["result"] == "found"
    assert data["participant"]["id"] == p.id


async def test_trailing_enter_and_spaces_are_ignored(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    await make_participant(db, conference, "B24-1001")
    _, token = await devices.terminal()

    assert (await scan(db_client, token, "  B24-1001\r\n"))["result"] == "found"


async def test_capslock_matches_when_unique(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "Ab-12")
    _, token = await devices.terminal()

    data = await scan(db_client, token, "aB-12")

    assert data["result"] == "found"
    assert data["participant"]["id"] == p.id


async def test_case_insensitive_match_must_be_unique(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    low = await make_participant(db, conference, "ab-12", last_name="Первый")
    up = await make_participant(db, conference, "Ab-12", last_name="Второй")
    _, token = await devices.terminal()

    # точное совпадение всегда главнее
    assert (await scan(db_client, token, "ab-12"))["participant"]["id"] == low.id
    assert (await scan(db_client, token, "Ab-12"))["participant"]["id"] == up.id
    # а «AB-12» подходит обоим без учёта регистра: выбирать нельзя
    assert (await scan(db_client, token, "AB-12"))["result"] == "not_found"


async def test_conference_regex_overrides_default(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db, invite_id_regex=r"/guest/([A-Z0-9]+)/ticket")
    p = await make_participant(db, conference, "Q9Z8")
    _, token = await devices.terminal()

    data = await scan(db_client, token, "https://x.example/guest/Q9Z8/ticket?id=WRONG")

    assert data["result"] == "found"
    assert data["participant"]["id"] == p.id


async def test_already_registered_message_and_attempt_is_saved(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """DP-01: время в часовом поясе мероприятия (Томск, UTC+7), попытка — в карточке."""
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001", registered_at=utc(2026, 11, 20, 2, 15))
    terminal, token = await devices.terminal()

    data = await scan(db_client, token, "B24-1001")

    assert data == {
        "result": "already_registered",
        "message": "Вы уже зарегистрированы (20.11, 09:15)" + ALREADY_SUFFIX,
    }
    assert "scan_id" not in data
    await scan(db_client, token, "B24-1001")
    await db.refresh(p)
    assert p.rescan_count == 2
    rescans = await events(db, "scan_rescan", p.id)
    assert [e.terminal_id for e in rescans] == [terminal.id, terminal.id]
    assert p.status == "registered"  # статус не тронут


async def test_registered_without_sticker_also_gets_warning(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(
        db,
        conference,
        "B24-1001",
        registered_at=utc(2026, 11, 20, 20, 5),
        status="registered_no_sticker",
    )
    _, token = await devices.terminal()

    data = await scan(db_client, token, "B24-1001")

    assert data["result"] == "already_registered"
    assert data["message"].startswith("Вы уже зарегистрированы (21.11, 03:05)")  # 20:05 UTC = 03:05
    await db.refresh(p)
    assert p.rescan_count == 1


async def test_timezone_is_configurable(
    app: FastAPI, db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    app.state.settings = app.state.settings.model_copy(update={"timezone": "Europe/Moscow"})
    conference = await make_conference(db)
    await make_participant(db, conference, "B24-1001", registered_at=utc(2026, 11, 20, 2, 15))
    _, token = await devices.terminal()

    data = await scan(db_client, token, "B24-1001")

    assert "(20.11, 05:15)" in data["message"]


async def test_scan_of_registered_participant_from_other_conference_changes_nothing(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    old = await make_conference(db, active=False)
    p = await make_participant(db, old, "OLD", registered_at=utc(2026, 1, 1))
    await make_conference(db)
    _, token = await devices.terminal()

    assert (await scan(db_client, token, "OLD"))["result"] == "not_found"
    await db.refresh(p)
    assert p.rescan_count == 0
    assert await events(db, "scan_rescan") == []
