"""Действия стойки на PostgreSQL (B2-15)."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import EventType, PrintJobKind
from app.models.participant import BadgeToken
from app.models.printing import PrintJob
from app.participants.schemas import ParticipantCard
from app.printing.schemas import AgentJob
from app.registration.schemas import RegisterOut
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import (
    events,
    make_conference,
    make_participant,
    print_jobs,
    scan,
)
from tests.test_print_queue import _make_template, agent_auth


@pytest.fixture
def settings(database_url: str) -> Settings:
    return Settings(
        env="test", database_url=database_url, public_base_url="https://reg.example.test"
    )


async def test_register_routes_jobs_to_the_staff_printers(
    db: AsyncSession, login_as: LoginAs, devices: Devices, anon: httpx.AsyncClient
) -> None:
    conference = await make_conference(db, badge_type="double")
    front = await _make_template(db, conference.id)
    back = await _make_template(db, conference.id, name="Оборотная", kind="back")
    back.height_mm = Decimal("42")
    conference.front_template_id = front.id
    conference.back_template_id = back.id
    await db.commit()
    queues: list[tuple[int, str]] = []
    for i in range(2):
        participant = await make_participant(db, conference, external_id=f"B24-200{i}")
        staff = await login_as("registration.desk", "stickers.print")
        printer, agent_token = await devices.printer(f"Принтер стойки {i}")
        chosen = await staff.put("/api/auth/me/printer", json={"printer_id": printer.id})
        assert chosen.status_code == 200, chosen.text

        response = await staff.post(f"/api/participants/{participant.id}/register")
        assert response.status_code == 200, response.text
        result = RegisterOut.model_validate_json(response.content)
        assert result.participant.id == participant.id
        assert result.participant.status == "registered"
        registration = result.participant.registration
        assert registration is not None
        assert registration.source == "desk"
        assert registration.user_login == staff.login
        assert registration.terminal_name is None
        (job,) = await print_jobs(db, participant.id)
        assert job.id == result.print_job_id
        assert job.printer_id == printer.id
        assert job.sides == 2
        assert job.created_by_user_id == staff.user_id
        assert job.kind == PrintJobKind.FIRST
        queues.append((job.id, agent_token))

    for job_id, agent_token in queues:
        claimed = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
        assert claimed.status_code == 200, claimed.text
        agent_job = AgentJob.model_validate_json(claimed.content)
        assert agent_job.job_id == job_id
        assert [copy.height_mm for copy in agent_job.copies] == [40, 42]


@pytest.mark.parametrize(
    ("badge_type", "with_sticker", "expected_status", "expected_error"),
    [
        ("single", False, "registered_no_sticker", False),
        ("none", True, "registered_no_sticker", False),
        ("single", True, "registered", True),
    ],
)
async def test_register_without_job(
    db: AsyncSession,
    login_as: LoginAs,
    devices: Devices,
    anon: httpx.AsyncClient,
    badge_type: str,
    with_sticker: bool,
    expected_status: str,
    expected_error: bool,
) -> None:
    conference = await make_conference(db, badge_type=badge_type)
    participant = await make_participant(db, conference, external_id="B24-2001")
    permissions = ["registration.desk"]
    if expected_error:
        permissions.append("stickers.print")
    staff = await login_as(*permissions)
    response = await staff.post(
        f"/api/participants/{participant.id}/register", json={"with_sticker": with_sticker}
    )
    assert response.status_code == 200, response.text
    result = RegisterOut.model_validate_json(response.content)
    assert result.participant.status == expected_status
    assert (
        "sticker_not_printed" in {flag.code for flag in result.participant.flags}
    ) == expected_error
    assert result.print_job_id is None
    assert await print_jobs(db, participant.id) == []

    _, terminal_token = await devices.terminal()
    scanned = await scan(anon, terminal_token, "B24-2001")
    assert scanned["result"] == "already_registered"


async def test_reprint_preserves_qr_and_reports_agent_outcomes(
    db: AsyncSession, login_as: LoginAs, devices: Devices, anon: httpx.AsyncClient
) -> None:
    conference = await make_conference(db)
    template = await _make_template(db, conference.id)
    conference.front_template_id = template.id
    await db.commit()
    participant = await make_participant(db, conference)
    staff = await login_as("registration.desk", "stickers.print", "participants.view")
    url = f"/api/participants/{participant.id}"
    initial = await staff.post(f"{url}/register")
    assert initial.status_code == 200, initial.text
    token_id = await db.scalar(
        select(BadgeToken.id).where(BadgeToken.participant_id == participant.id)
    )
    assert token_id is not None
    no_printer = await staff.post(f"{url}/reprint")
    assert no_printer.status_code == 409, no_printer.text
    assert no_printer.json()["code"] == "printer_not_selected"

    printer, agent_token = await devices.printer()
    chosen = await staff.put("/api/auth/me/printer", json={"printer_id": printer.id})
    assert chosen.status_code == 200, chosen.text
    for ok, count, has_flag in [(False, 0, True), (True, 1, False)]:
        response = await staff.post(f"{url}/reprint")
        assert response.status_code == 200, response.text
        job_id = response.json()["print_job_id"]
        job = await db.get(PrintJob, job_id)
        assert job is not None
        assert job.kind == PrintJobKind.REPRINT
        assert job.badge_token_id == token_id
        assert job.printer_id == printer.id
        claimed = await anon.get("/api/agent/jobs/next?wait=0", headers=agent_auth(agent_token))
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["job_id"] == job_id
        for _ in range(2):
            reported = await anon.post(
                f"/api/agent/jobs/{job_id}/result",
                headers={"Authorization": f"Agent {agent_token}"},
                json={"ok": ok},
            )
            assert reported.status_code == 204, reported.text
        card_response = await staff.get(url)
        assert card_response.status_code == 200, card_response.text
        card = ParticipantCard.model_validate_json(card_response.content)
        assert card.print_count == count
        assert ("sticker_not_printed" in {flag.code for flag in card.flags}) == has_flag
        latest = [event for event in card.events if event.type == "reprint"][-1]
        assert latest.user_login == staff.login
        assert latest.at is not None
    assert len(await events(db, EventType.PRINT_OK, participant.id)) == 1
    assert len(await events(db, EventType.REPRINT, participant.id)) == 2
    assert (
        await db.scalar(select(BadgeToken.id).where(BadgeToken.participant_id == participant.id))
        == token_id
    )


async def test_desk_denies_invalid_requests_without_side_effects(
    db: AsyncSession, login_as: LoginAs, anon: httpx.AsyncClient
) -> None:
    conference = await make_conference(db, badge_type="none")
    other_conference = await make_conference(db, active=False)
    participant = await make_participant(db, conference)
    foreign = await make_participant(db, other_conference)
    staff = await login_as("registration.desk", "stickers.print")
    desk_only = await login_as("registration.desk")
    url = f"/api/participants/{participant.id}"

    requests = [
        (await anon.post(f"{url}/register"), 401, "unauthenticated"),
        (await anon.post(f"{url}/reprint"), 401, "unauthenticated"),
        (
            await staff.post(f"{url}/register", headers={"X-Requested-With": ""}),
            403,
            "csrf_required",
        ),
        (await desk_only.post(f"{url}/reprint"), 403, "forbidden"),
        (await staff.post(f"{url}/reprint"), 409, "not_registered"),
    ]
    for action in ("register", "reprint"):
        response = await staff.post(f"/api/participants/{foreign.id}/{action}")
        requests.append((response, 404, "participant_not_found"))
    for response, status, code in requests:
        assert response.status_code == status, response.text
        assert response.json()["code"] == code
        if code == "not_registered":
            assert response.json()["message"] == "Участник ещё не зарегистрирован"

    assert await db.scalar(select(BadgeToken.id)) is None
    assert await print_jobs(db, participant.id) == []
    assert await events(db, EventType.REGISTERED, participant.id) == []
    registered = await staff.post(f"{url}/register")
    assert registered.status_code == 200, registered.text
    disabled = await staff.post(f"{url}/reprint")
    assert disabled.status_code == 409, disabled.text
    assert disabled.json()["code"] == "no_badge"
    assert await print_jobs(db, participant.id) == []
    assert await events(db, EventType.REPRINT, participant.id) == []


async def test_register_with_sticker_requires_print_permission(
    db: AsyncSession, login_as: LoginAs
) -> None:
    participant = await make_participant(db, await make_conference(db))
    staff = await login_as("registration.desk")
    response = await staff.post(f"/api/participants/{participant.id}/register")
    assert response.status_code == 403, response.text
    assert response.json()["details"]["missing"] == ["stickers.print"]
    assert await print_jobs(db, participant.id) == []
    assert await events(db, EventType.REGISTERED, participant.id) == []
