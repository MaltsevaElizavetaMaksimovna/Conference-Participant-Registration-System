"""POST /api/terminal/report-error (B2-05): ER-01."""

import time
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.terminals.scan_id import issue_scan_id
from tests.conftest import Devices
from tests.registration_helpers import (
    ALREADY_SUFFIX,
    ERROR_REPORTED,
    NOT_FOUND,
    PRINTING,
    confirm,
    events,
    make_conference,
    make_participant,
    print_jobs,
    report_error,
    scan_and_get_id,
    utc,
)


async def test_report_error_marks_participant_without_registering(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    printer, _ = await devices.printer()
    terminal, token = await devices.terminal(printer=printer)
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")
    before = datetime.now(UTC) - timedelta(seconds=2)

    r = await report_error(db_client, token, pid, scan_id)

    assert r.status_code == 200, r.text
    assert r.json() == {"message": ERROR_REPORTED}
    await db.refresh(p)
    assert p.status == "not_registered"
    assert p.registered_at is None
    assert p.error_reported_at is not None
    assert before <= p.error_reported_at <= datetime.now(UTC) + timedelta(seconds=2)
    assert await print_jobs(db, p.id) == []
    (event,) = await events(db, "error_reported", p.id)
    assert event.terminal_id == terminal.id
    assert event.conference_id == conference.id


async def test_after_error_participant_can_scan_again_and_register(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    printer, _ = await devices.printer()
    _, token = await devices.terminal(printer=printer)
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")
    await report_error(db_client, token, pid, scan_id)

    # сотрудник поправил данные, участник сканирует снова
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")
    r = await confirm(db_client, token, pid, scan_id)

    assert r.json()["result"] == "registered"
    assert r.json()["message"] == PRINTING
    await db.refresh(p)
    assert p.status == "registered"
    assert p.error_reported_at is not None  # пометка остаётся для сотрудника
    assert len(await print_jobs(db, p.id)) == 1


async def test_report_error_on_registered_changes_nothing_and_shows_dp01(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices, app: FastAPI
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001", registered_at=utc(2026, 11, 20, 2, 15))
    terminal, token = await devices.terminal()
    scan_id = issue_scan_id(app.state.settings.secret_key, terminal.id, p.id)

    r = await report_error(db_client, token, p.id, scan_id)

    assert r.status_code == 200
    assert r.json() == {"message": "Вы уже зарегистрированы (20.11, 09:15)" + ALREADY_SUFFIX}
    await db.refresh(p)
    assert p.error_reported_at is None
    assert p.rescan_count == 0
    assert await events(db, "error_reported", p.id) == []
    assert p.status == "registered"


async def test_report_error_requires_valid_scan_id(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices, app: FastAPI
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    terminal, token = await devices.terminal()
    secret = app.state.settings.secret_key

    for scan_id in (
        "nonsense",
        issue_scan_id(secret, terminal.id + 1, p.id),
        issue_scan_id(secret, terminal.id, p.id, now=time.time() - 3600),
    ):
        r = await report_error(db_client, token, p.id, scan_id)
        assert r.status_code == 409
        assert r.json()["code"] == "scan_expired"
    await db.refresh(p)
    assert p.error_reported_at is None


async def test_report_error_for_participant_of_inactive_conference(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices, app: FastAPI
) -> None:
    old = await make_conference(db, active=False)
    p = await make_participant(db, old, "OLD")
    terminal, token = await devices.terminal()
    scan_id = issue_scan_id(app.state.settings.secret_key, terminal.id, p.id)

    r = await report_error(db_client, token, p.id, scan_id)

    assert r.status_code == 404
    assert r.json()["message"] == NOT_FOUND
    await db.refresh(p)
    assert p.error_reported_at is None


async def test_report_error_requires_terminal_token(db_client: httpx.AsyncClient) -> None:
    r = await db_client.post(
        "/api/terminal/report-error", json={"participant_id": 1, "scan_id": "x"}
    )
    assert r.status_code == 401
