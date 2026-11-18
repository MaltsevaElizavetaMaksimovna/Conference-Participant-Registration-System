"""Повтор запроса на печать с ключом идемпотентности (B2-15)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import EventType
from tests.conftest import Devices, LoginAs
from tests.registration_helpers import events, make_conference, make_participant, print_jobs


async def test_reprint_replays_same_key_and_accepts_new_press(
    db: AsyncSession, login_as: LoginAs, devices: Devices
) -> None:
    conference = await make_conference(db)
    participant = await make_participant(db, conference)
    staff = await login_as("registration.desk", "stickers.print")
    printer, _ = await devices.printer()
    chosen = await staff.put("/api/auth/me/printer", json={"printer_id": printer.id})
    assert chosen.status_code == 200, chosen.text
    url = f"/api/participants/{participant.id}"
    registered = await staff.post(f"{url}/register", json={"with_sticker": False})
    assert registered.status_code == 200, registered.text

    first = await staff.post(f"{url}/reprint", headers={"Idempotency-Key": "first-click"})
    assert first.status_code == 200, first.text
    original = first.json()["print_job_id"]

    # Повтор одного запроса возвращает задание, даже если принтер панели уже сменили.
    next_printer, _ = await devices.printer("Другой принтер")
    chosen = await staff.put("/api/auth/me/printer", json={"printer_id": next_printer.id})
    assert chosen.status_code == 200, chosen.text
    replay = await staff.post(f"{url}/reprint", headers={"Idempotency-Key": "first-click"})
    assert replay.status_code == 200, replay.text
    assert replay.json()["print_job_id"] == original

    fresh = await staff.post(f"{url}/reprint", headers={"Idempotency-Key": "second-click"})
    assert fresh.status_code == 200, fresh.text
    legacy = await staff.post(f"{url}/reprint")
    assert legacy.status_code == 200, legacy.text

    jobs = await print_jobs(db, participant.id)
    assert [job.id for job in jobs] == [
        original,
        fresh.json()["print_job_id"],
        legacy.json()["print_job_id"],
    ]
    assert [job.printer_id for job in jobs] == [printer.id, next_printer.id, next_printer.id]
    assert len(await events(db, EventType.REPRINT, participant.id)) == 3
