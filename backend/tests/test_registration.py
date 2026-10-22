"""Ядро регистрации и POST /api/terminal/confirm (B2-04): TR-03, TR-04, TR-05, TR-09, DP-01."""

import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.tokens import get_or_create_active_token, new_badge_token
from app.core.enums import RegSource
from app.core.errors import AppError
from app.models.participant import BadgeToken, Participant
from app.models.printing import IdempotencyRecord
from app.registration.service import register
from app.terminals.scan_id import issue_scan_id
from tests.conftest import Devices
from tests.registration_helpers import (
    ALREADY_SUFFIX,
    NO_BADGE,
    NOT_FOUND,
    PRINTING,
    STICKER_FAILED,
    auth,
    confirm,
    events,
    make_conference,
    make_participant,
    print_jobs,
    scan,
    scan_and_get_id,
    utc,
)


async def _reload(db: AsyncSession, p: Participant) -> Participant:
    await db.refresh(p)
    return p


# ------------------------------------------------------------- register() напрямую


async def _terminal_register(
    db: AsyncSession, p: Participant, terminal_id: int, printer_id: int | None, **kw: object
) -> object:
    return await register(
        db,
        p.id,
        source=RegSource.TERMINAL,
        terminal_id=terminal_id,
        user_id=None,
        with_sticker=bool(kw.pop("with_sticker", True)),
        printer_id=printer_id,
        **kw,  # type: ignore[arg-type]
    )


async def test_register_single_sided(db: AsyncSession, devices: Devices) -> None:
    conference = await make_conference(db, badge_type="single")
    p = await make_participant(db, conference)
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal(printer=printer)

    before = datetime.now(UTC) - timedelta(seconds=2)
    result = await _terminal_register(db, p, terminal.id, printer.id)

    assert result.result == "registered"  # type: ignore[attr-defined]
    await _reload(db, p)
    assert p.status == "registered"
    assert p.reg_source == "terminal"
    assert p.reg_terminal_id == terminal.id
    assert p.reg_user_id is None
    assert p.sticker_not_printed is False
    assert before <= p.registered_at <= datetime.now(UTC) + timedelta(seconds=2)  # type: ignore[operator]
    (job,) = await print_jobs(db, p.id)
    assert (job.kind, job.sides, job.status, job.printer_id) == ("first", 1, "pending", printer.id)
    assert job.created_by_terminal_id == terminal.id
    assert result.print_job_id == job.id  # type: ignore[attr-defined]
    (event,) = await events(db, "registered", p.id)
    assert event.terminal_id == terminal.id


async def test_register_double_sided_is_one_job_with_two_sides(
    db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db, badge_type="double")
    p = await make_participant(db, conference)
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal(printer=printer)

    await _terminal_register(db, p, terminal.id, printer.id)

    (job,) = await print_jobs(db, p.id)
    assert job.sides == 2


async def test_no_badge_conference_registers_without_sticker_even_without_printer(
    db: AsyncSession, devices: Devices
) -> None:
    """TR-09: статус «без наклейки», печати нет и ошибки печати нет."""
    conference = await make_conference(db, badge_type="none")
    p = await make_participant(db, conference)
    terminal, _ = await devices.terminal()  # принтер не привязан

    result = await _terminal_register(db, p, terminal.id, None)

    await _reload(db, p)
    assert (p.status, p.sticker_not_printed) == ("registered_no_sticker", False)
    assert result.print_job_id is None  # type: ignore[attr-defined]
    assert await print_jobs(db, p.id) == []
    assert await events(db, "print_error", p.id) == []


async def test_missing_printer_registers_but_flags_sticker_not_printed(
    db: AsyncSession, devices: Devices
) -> None:
    """TR-08: регистрация остаётся в силе, даже если печатать некуда."""
    conference = await make_conference(db)
    p = await make_participant(db, conference)
    terminal, _ = await devices.terminal()

    result = await _terminal_register(db, p, terminal.id, None)

    await _reload(db, p)
    assert (p.status, p.sticker_not_printed) == ("registered", True)
    assert result.print_job_id is None  # type: ignore[attr-defined]
    assert await print_jobs(db, p.id) == []
    (event,) = await events(db, "print_error", p.id)
    assert event.payload == {"reason": "no_printer"}


async def test_desk_registration_without_sticker(db: AsyncSession, devices: Devices) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference)
    printer, _ = await devices.printer()

    result = await register(
        db,
        p.id,
        source=RegSource.DESK,
        terminal_id=None,
        user_id=None,
        with_sticker=False,
        printer_id=printer.id,
    )

    await _reload(db, p)
    assert (p.status, p.reg_source, p.sticker_not_printed) == (
        "registered_no_sticker",
        "desk",
        False,
    )
    assert result.print_job_id is None
    assert await print_jobs(db, p.id) == []


async def test_second_register_returns_first_registration_and_changes_nothing(
    db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference)
    printer, _ = await devices.printer()
    first_terminal, _ = await devices.terminal("Терминал А", printer=printer)
    second_terminal, _ = await devices.terminal("Терминал Б", printer=printer)

    first = await _terminal_register(db, p, first_terminal.id, printer.id)
    second = await _terminal_register(db, p, second_terminal.id, printer.id)

    assert second.result == "already_registered"  # type: ignore[attr-defined]
    assert second.registered_at == first.registered_at  # type: ignore[attr-defined]
    assert second.terminal_name == "Терминал А"  # type: ignore[attr-defined]
    assert second.print_job_id is None  # type: ignore[attr-defined]
    await _reload(db, p)
    assert p.reg_terminal_id == first_terminal.id
    assert len(await print_jobs(db, p.id)) == 1
    assert len(await events(db, "registered", p.id)) == 1
    # проигравший терминал — это повторная попытка (DP-01)
    assert p.rescan_count == 1
    (rescan,) = await events(db, "scan_rescan", p.id)
    assert rescan.terminal_id == second_terminal.id


async def test_register_unknown_participant(db: AsyncSession) -> None:
    with pytest.raises(AppError) as exc:
        await register(
            db,
            999_999,
            source=RegSource.DESK,
            terminal_id=None,
            user_id=None,
            with_sticker=True,
            printer_id=None,
            idempotency_key="k",
        )
    assert exc.value.code == "participant_not_found"
    assert exc.value.status_code == 404
    # ключ не остался занятым: откат вместе с транзакцией
    assert await db.scalar(select(func.count()).select_from(IdempotencyRecord)) == 0


# ----------------------------------------------------------------- идемпотентность


async def test_same_key_three_times_gives_one_registration_and_one_job(
    db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference)
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal(printer=printer)

    results = [
        await _terminal_register(db, p, terminal.id, printer.id, idempotency_key="key-1")
        for _ in range(3)
    ]

    assert results[0] == results[1] == results[2]
    assert results[0].result == "registered"  # type: ignore[attr-defined]
    assert len(await print_jobs(db, p.id)) == 1
    assert len(await events(db, "registered", p.id)) == 1
    await _reload(db, p)
    assert p.rescan_count == 0  # повтор по ключу — не «повторная попытка»
    record = await db.get(IdempotencyRecord, f"confirm:{terminal.id}:key-1")
    assert record is not None
    assert record.scope == f"confirm:{terminal.id}"


async def test_same_key_for_another_participant_is_rejected(
    db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    a = await make_participant(db, conference, "A")
    b = await make_participant(db, conference, "B")
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal(printer=printer)
    await _terminal_register(db, a, terminal.id, printer.id, idempotency_key="key-1")

    with pytest.raises(AppError) as exc:
        await _terminal_register(db, b, terminal.id, printer.id, idempotency_key="key-1")

    assert exc.value.code == "idempotency_key_reused"
    await _reload(db, b)
    assert b.status == "not_registered"


async def test_same_key_on_different_terminals_does_not_collide(
    db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    a = await make_participant(db, conference, "A")
    b = await make_participant(db, conference, "B")
    printer, _ = await devices.printer()
    t1, _ = await devices.terminal(printer=printer)
    t2, _ = await devices.terminal(printer=printer)

    r1 = await _terminal_register(db, a, t1.id, printer.id, idempotency_key="same")
    r2 = await _terminal_register(db, b, t2.id, printer.id, idempotency_key="same")

    assert (r1.result, r2.result) == ("registered", "registered")  # type: ignore[attr-defined]


# --------------------------------------------------------------------- код бейджа


async def test_registration_creates_random_badge_token(db: AsyncSession, devices: Devices) -> None:
    """QR-01: код отдельный от ID приглашения, случайный, >= 128 бит; при повторе тот же."""
    conference = await make_conference(db)
    a = await make_participant(db, conference, "A")
    b = await make_participant(db, conference, "B")
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal(printer=printer)
    await _terminal_register(db, a, terminal.id, printer.id)
    await _terminal_register(db, b, terminal.id, printer.id)

    tokens = {
        p.id: (await db.scalars(select(BadgeToken).where(BadgeToken.participant_id == p.id))).all()
        for p in (a, b)
    }
    (ta,), (tb,) = tokens[a.id], tokens[b.id]
    assert ta.status == "active"
    assert ta.token != tb.token
    assert ta.token != a.external_id
    assert len(ta.token) >= 22  # 16 байт в base64url
    (job,) = await print_jobs(db, a.id)
    assert job.badge_token_id == ta.id
    # повторная печать берёт тот же токен
    again = await get_or_create_active_token(db, a.id)
    assert again.id == ta.id
    assert new_badge_token() != new_badge_token()


# --------------------------------------------------------------- POST /terminal/confirm


async def test_full_flow_scan_then_confirm(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-05: дата-время и терминал записаны; наклейка — задание на принтер терминала (TR-04)."""
    conference = await make_conference(db, badge_type="single")
    p = await make_participant(db, conference, "B24-1001")
    printer1, _ = await devices.printer("Принтер 1")
    printer2, _ = await devices.printer("Принтер 2")
    terminal1, _ = await devices.terminal("Терминал 1", printer=printer1)
    terminal2, token2 = await devices.terminal("Терминал 2", printer=printer2)
    pid, scan_id = await scan_and_get_id(db_client, token2, "B24-1001")

    r = await confirm(db_client, token2, pid, scan_id)

    assert r.status_code == 200, r.text
    body = r.json()
    (job,) = await print_jobs(db, p.id)
    assert body == {"result": "registered", "print_job_id": job.id, "message": PRINTING}
    assert job.printer_id == printer2.id  # на принтер ТОГО терминала, где нажали
    await _reload(db, p)
    assert p.status == "registered"
    assert p.registered_at is not None
    assert p.reg_terminal_id == terminal2.id
    assert p.reg_terminal_id != terminal1.id


async def test_confirm_no_badge_message_and_no_print(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-09."""
    conference = await make_conference(db, badge_type="none")
    p = await make_participant(db, conference, "B24-1001")
    _, token = await devices.terminal()  # без принтера
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")

    r = await confirm(db_client, token, pid, scan_id)

    assert r.json() == {"result": "registered", "print_job_id": None, "message": NO_BADGE}
    await _reload(db, p)
    assert p.status == "registered_no_sticker"
    assert await print_jobs(db, p.id) == []
    # повторный скан — как у любого зарегистрированного
    again = await db_client.post(
        "/api/terminal/scan", headers=auth(token), json={"raw": "B24-1001"}
    )
    assert again.json()["result"] == "already_registered"


async def test_confirm_without_printer_keeps_registration(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-08: регистрация остаётся, участнику — отправить к стойке."""
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    _, token = await devices.terminal()
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")

    r = await confirm(db_client, token, pid, scan_id)

    assert r.json() == {"result": "registered", "print_job_id": None, "message": STICKER_FAILED}
    await _reload(db, p)
    assert (p.status, p.sticker_not_printed) == ("registered", True)


async def test_confirm_double_sided_creates_single_job_with_two_sides(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db, badge_type="double")
    p = await make_participant(db, conference, "B24-1001")
    printer, _ = await devices.printer()
    _, token = await devices.terminal(printer=printer)
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")

    await confirm(db_client, token, pid, scan_id)

    (job,) = await print_jobs(db, p.id)
    assert job.sides == 2


async def test_triple_confirm_with_same_key_is_one_registration(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """TR-03: повторные нажатия — одна регистрация, одна наклейка, одинаковые ответы."""
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    printer, _ = await devices.printer()
    _, token = await devices.terminal(printer=printer)
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")

    responses = [await confirm(db_client, token, pid, scan_id, key="ui-key") for _ in range(3)]

    assert [r.status_code for r in responses] == [200, 200, 200]
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert responses[0].json()["result"] == "registered"
    assert len(await print_jobs(db, p.id)) == 1
    assert len(await events(db, "registered", p.id)) == 1
    await _reload(db, p)
    assert p.rescan_count == 0


async def test_retry_with_same_key_after_scan_id_expired_returns_stored_answer(
    app: FastAPI, db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    printer, _ = await devices.printer()
    terminal, token = await devices.terminal(printer=printer)
    pid, scan_id = await scan_and_get_id(db_client, token, "B24-1001")
    first = await confirm(db_client, token, pid, scan_id, key="k")
    stale = issue_scan_id(app.state.settings.secret_key, terminal.id, pid, now=time.time() - 3600)

    again = await confirm(db_client, token, pid, stale, key="k")

    assert again.status_code == 200
    assert again.json() == first.json()
    assert len(await print_jobs(db, p.id)) == 1


async def test_idempotency_key_is_required(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    _, token = await devices.terminal()
    r = await db_client.post(
        "/api/terminal/confirm", headers=auth(token), json={"participant_id": 1, "scan_id": "x"}
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


@pytest.mark.parametrize("kind", ["garbage", "other_terminal", "other_participant", "expired"])
async def test_bad_scan_id_is_rejected_with_409(
    kind: str,
    app: FastAPI,
    db_client: httpx.AsyncClient,
    db: AsyncSession,
    devices: Devices,
) -> None:
    conference = await make_conference(db)
    a = await make_participant(db, conference, "A")
    b = await make_participant(db, conference, "B")
    printer, _ = await devices.printer()
    terminal, token = await devices.terminal(printer=printer)
    other, other_token = await devices.terminal(printer=printer)
    secret = app.state.settings.secret_key
    scan_id = {
        "garbage": "scan_1.2.3.zzz",
        "other_terminal": issue_scan_id(secret, other.id, a.id),
        "other_participant": issue_scan_id(secret, terminal.id, b.id),
        "expired": issue_scan_id(secret, terminal.id, a.id, now=time.time() - 3600),
    }[kind]

    r = await confirm(db_client, token, a.id, scan_id)

    assert r.status_code == 409
    assert r.json()["code"] == "scan_expired"
    assert r.json()["message"] == "Отсканируйте код ещё раз"
    await _reload(db, a)
    assert a.status == "not_registered"
    assert await print_jobs(db, a.id) == []
    del other_token


async def test_forged_scan_id_signature_is_rejected(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    conference = await make_conference(db)
    p = await make_participant(db, conference, "A")
    terminal, token = await devices.terminal()
    forged = issue_scan_id("не-тот-ключ", terminal.id, p.id)

    r = await confirm(db_client, token, p.id, forged)

    assert r.status_code == 409


async def test_confirm_participant_of_inactive_conference_is_404(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices, app: FastAPI
) -> None:
    old = await make_conference(db, active=False)
    p = await make_participant(db, old, "OLD")
    terminal, token = await devices.terminal()
    scan_id = issue_scan_id(app.state.settings.secret_key, terminal.id, p.id)

    r = await confirm(db_client, token, p.id, scan_id)

    assert r.status_code == 404
    assert r.json()["code"] == "participant_not_found"
    assert r.json()["message"] == NOT_FOUND
    await _reload(db, p)
    assert p.status == "not_registered"


async def test_confirm_for_already_registered_is_a_warning_not_an_error(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """DP-01 / DP-02 между двумя терминалами: второй видит предупреждение, наклейка одна."""
    conference = await make_conference(db)
    p = await make_participant(db, conference, "B24-1001")
    printer1, _ = await devices.printer()
    printer2, _ = await devices.printer()
    _, token1 = await devices.terminal(printer=printer1)
    t2, token2 = await devices.terminal(printer=printer2)
    pid, scan1 = await scan_and_get_id(db_client, token1, "B24-1001")
    _, scan2 = await scan_and_get_id(db_client, token2, "B24-1001")  # оба увидели «found»

    first = await confirm(db_client, token1, pid, scan1, key="a")
    second = await confirm(db_client, token2, pid, scan2, key="b")

    assert first.json()["result"] == "registered"
    assert second.status_code == 200
    body = second.json()
    assert body["result"] == "already_registered"
    assert body["print_job_id"] is None
    assert body["message"].startswith("Вы уже зарегистрированы (")
    assert body["message"].endswith(ALREADY_SUFFIX)
    (job,) = await print_jobs(db, p.id)
    assert job.printer_id == printer1.id
    await _reload(db, p)
    assert p.rescan_count == 1
    (rescan,) = await events(db, "scan_rescan", p.id)
    assert rescan.terminal_id == t2.id


async def test_registered_by_desk_is_protected_from_terminal(
    app: FastAPI, db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    """DP-01 для зарегистрированных регистратором, в том числе без наклейки."""
    conference = await make_conference(db)
    p = await make_participant(
        db,
        conference,
        "B24-1001",
        registered_at=utc(2026, 11, 20, 2, 15),
        status="registered_no_sticker",
    )
    printer, _ = await devices.printer()
    terminal, token = await devices.terminal(printer=printer)
    data = await scan(db_client, token, "B24-1001")
    assert data["result"] == "already_registered"
    scan_id = issue_scan_id(app.state.settings.secret_key, terminal.id, p.id)

    r = await confirm(db_client, token, p.id, scan_id)

    assert r.json()["result"] == "already_registered"
    assert await print_jobs(db, p.id) == []
    await _reload(db, p)
    assert p.status == "registered_no_sticker"
