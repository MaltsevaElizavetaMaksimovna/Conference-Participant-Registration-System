"""Счётчик участников: `GET /api/participants/stats` (B1-10, RG-04)."""

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import Participant
from tests.conftest import LoginAs
from tests.registration_helpers import make_conference, make_participant, utc

URL = "/api/participants/stats"
PARTICIPANTS_URL = "/api/participants"


async def _seed_stats_dataset(db: AsyncSession) -> None:
    conf = await make_conference(db)
    inactive = await make_conference(db, active=False)

    # Активная конференция: 2 registered, 1 registered_no_sticker, 2 not_registered
    await make_participant(db, conf, "ACT-1", registered_at=utc(2026, 11, 20, 9, 0))
    await make_participant(db, conf, "ACT-2", registered_at=utc(2026, 11, 20, 9, 1))
    await make_participant(
        db,
        conf,
        "ACT-3",
        registered_at=utc(2026, 11, 20, 9, 2),
        status="registered_no_sticker",
    )
    await make_participant(db, conf, "ACT-4")
    await make_participant(db, conf, "ACT-5")

    # Неактивная конференция: 3 registered
    await make_participant(db, inactive, "OLD-1", registered_at=utc(2026, 11, 20, 8, 0))
    await make_participant(db, inactive, "OLD-2", registered_at=utc(2026, 11, 20, 8, 1))
    await make_participant(db, inactive, "OLD-3", registered_at=utc(2026, 11, 20, 8, 2))


async def test_active_conference_without_participants(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    await make_conference(db)
    r: httpx.Response = await c.get(URL)
    assert r.status_code == 200, r.text
    assert r.json() == {"registered": 0, "total": 0}


async def test_no_active_conference_with_participant(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    inactive = await make_conference(db, active=False)
    await make_participant(db, inactive, "OLD-1", registered_at=utc(2026, 11, 20, 9, 0))
    r: httpx.Response = await c.get(URL)
    assert r.status_code == 200, r.text
    assert r.json() == {"registered": 0, "total": 0}


async def test_active_and_inactive_conferences_counts(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    await _seed_stats_dataset(db)
    r: httpx.Response = await c.get(URL)
    assert r.status_code == 200, r.text
    assert r.json() == {"registered": 3, "total": 5}


async def test_filter_registered_matches_stats_counter(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    await _seed_stats_dataset(db)

    r_stats: httpx.Response = await c.get(URL)
    assert r_stats.status_code == 200, r_stats.text
    stats = r_stats.json()

    r_reg: httpx.Response = await c.get(
        PARTICIPANTS_URL, params={"filter": "registered", "limit": 200}
    )
    assert r_reg.status_code == 200, r_reg.text
    reg_page = r_reg.json()

    assert reg_page["total"] == stats["registered"]
    assert len(reg_page["items"]) == stats["registered"]
    for item in reg_page["items"]:
        assert item["status"] != "not_registered"

    r_all: httpx.Response = await c.get(PARTICIPANTS_URL, params={"filter": "all"})
    assert r_all.status_code == 200, r_all.text
    all_page = r_all.json()
    assert all_page["total"] == stats["total"]


async def test_registration_increments_stats_counter(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("participants.view")
    conf = await make_conference(db)
    participant = await make_participant(db, conf, "P-1")

    r_before: httpx.Response = await c.get(URL)
    assert r_before.status_code == 200, r_before.text
    stats_before = r_before.json()

    # объект отсоединён от сессии после запроса (см. app_db), поэтому UPDATE напрямую
    await db.execute(
        update(Participant)
        .where(Participant.id == participant.id)
        .values(status="registered", registered_at=utc(2026, 11, 20, 9, 0), reg_source="terminal")
    )
    await db.commit()

    r_after: httpx.Response = await c.get(URL)
    assert r_after.status_code == 200, r_after.text
    stats_after = r_after.json()

    assert stats_after["registered"] == stats_before["registered"] + 1
    assert stats_after["total"] == stats_before["total"]


async def test_stats_forbidden_without_participants_view(login_as: LoginAs) -> None:
    c = await login_as("users.manage")
    r: httpx.Response = await c.get(URL)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "forbidden"
