import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EventType
from app.models.participant import Participant
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import (
    auth,
    events,
    make_conference,
    make_participant,
    print_jobs,
    scan_and_get_id,
)


@pytest.mark.parametrize("operation", ["confirm", "report-error"])
async def test_scan_is_bound_to_terminal_and_participant(
    anon: httpx.AsyncClient,
    login_as: LoginAs,
    db: AsyncSession,
    devices: Devices,
    operation: str,
) -> None:
    conference = await make_conference(db)
    scanned = await make_participant(db, conference, "B24-1001")
    other = await make_participant(db, conference, "B24-1002")
    printer, agent_token = await devices.printer()
    _, owner_token = await devices.terminal(printer=printer)
    _, other_token = await devices.terminal(printer=printer)
    staff = await login_as("registration.desk", "stickers.print")
    participant_id, scan_id = await scan_and_get_id(anon, owner_token, "B24-1001")
    assert participant_id == scanned.id

    path = f"/api/terminal/{operation}"
    key = {"Idempotency-Key": "scan-binding-test"}
    body = {"participant_id": scanned.id, "scan_id": scan_id}
    for client, headers in (
        (anon, {}),
        (staff, {}),
        (anon, {"Authorization": f"Agent {agent_token}"}),
    ):
        response = await client.post(path, headers={**headers, **key}, json=body)
        assert response.status_code == 401, response.text
        assert response.json()["code"] == "invalid_device_token"

    for token, target_id in ((other_token, scanned.id), (owner_token, other.id)):
        response = await anon.post(
            path,
            headers={**auth(token), **key},
            json={**body, "participant_id": target_id},
        )
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "scan_expired"

    for denied_id in (scanned.id, other.id):
        participant = await db.get(Participant, denied_id)
        assert participant is not None
        assert participant.status == "not_registered"
        assert participant.registered_at is None
        assert participant.error_reported_at is None
        assert not await print_jobs(db, participant.id)
        assert not await events(db, EventType.ERROR_REPORTED, participant.id)

    response = await anon.post(path, headers={**auth(owner_token), **key}, json=body)
    assert response.status_code == 200, response.text
    registered = await db.get(Participant, scanned.id)
    assert registered is not None
    if operation == "confirm":
        assert registered.status == "registered"
        (job,) = await print_jobs(db, scanned.id)
        assert job.printer_id == printer.id
    else:
        assert registered.status == "not_registered"
        assert registered.error_reported_at is not None
        assert len(await events(db, EventType.ERROR_REPORTED, scanned.id)) == 1
        assert not await print_jobs(db, scanned.id)


async def test_agent_rejects_staff_cookie_without_agent_credentials(
    login_as: LoginAs, devices: Devices
) -> None:
    staff = await login_as("devices.manage")
    _, token = await devices.printer()
    payload = {"printer_status": "ready"}
    response = await staff.post("/api/agent/heartbeat", json=payload)
    assert response.status_code == 401, response.text
    assert response.json()["code"] == "invalid_device_token"

    response = await staff.post(
        "/api/agent/heartbeat", json=payload, headers={"Authorization": f"Agent {token}"}
    )
    assert response.status_code == 204, response.text
