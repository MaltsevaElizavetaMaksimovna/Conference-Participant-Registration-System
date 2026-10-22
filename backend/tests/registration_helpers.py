"""Общие хелперы тестов регистрации (B2-03..05): данные напрямую через модели и вызовы API."""

from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.text import normalize_search
from app.models.conference import Conference
from app.models.participant import EventLog, Participant
from app.models.printing import PrintJob
from app.terminals.scan_code import RU_TO_US

NOT_FOUND = "Участник не найден. Обратитесь к стойке регистрации"
PRINTING = "Заберите наклейку и подойдите к стойке регистрации за бейджем"
NO_BADGE = "Вы зарегистрированы. Добро пожаловать на конференцию!"
STICKER_FAILED = (
    "Вы зарегистрированы, но наклейку напечатать не удалось. Обратитесь к стойке регистрации"
)
ERROR_REPORTED = "Подойдите к стойке регистрации — сотрудник исправит данные"
ALREADY_SUFFIX = ". Если вы не получили бейдж — обратитесь к стойке регистрации"

# Обратная раскладка US -> ЙЦУКЕН: так строку «напечатал» бы сканер в русской раскладке
US_TO_RU = {us: chr(ru) for ru, us in RU_TO_US.items()}


def to_russian_layout(s: str) -> str:
    return "".join(US_TO_RU.get(ch, ch) for ch in s)


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Terminal {token}"}


async def make_conference(
    db: AsyncSession,
    *,
    badge_type: str = "single",
    active: bool = True,
    invite_id_regex: str | None = None,
    title: str = "Тестовая конференция",
) -> Conference:
    conference = Conference(
        title=title,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 21),
        badge_type=badge_type,
        is_active=active,
        invite_id_regex=invite_id_regex,
    )
    db.add(conference)
    await db.commit()
    return conference


async def make_participant(
    db: AsyncSession,
    conference: Conference,
    external_id: str | None = "B24-1001",
    *,
    last_name: str = "Иванов",
    first_name: str = "Пётр",
    middle_name: str | None = "Сергеевич",
    position: str | None = "Инженер",
    organization: str | None = "ООО Ромашка",
    registered_at: datetime | None = None,
    status: str | None = None,
) -> Participant:
    fields: dict[str, Any] = {}
    if registered_at is not None:
        fields["registered_at"] = registered_at
        fields["status"] = status or "registered"
        fields["reg_source"] = "terminal"
    participant = Participant(
        conference_id=conference.id,
        external_id=external_id,
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        position=position,
        organization=organization,
        search_norm=normalize_search(f"{last_name} {first_name} {middle_name or ''}"),
        **fields,
    )
    db.add(participant)
    await db.commit()
    return participant


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


async def scan(client: httpx.AsyncClient, token: str, raw: str) -> dict[str, Any]:
    r = await client.post("/api/terminal/scan", headers=auth(token), json={"raw": raw})
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    return data


async def confirm(
    client: httpx.AsyncClient,
    token: str,
    participant_id: int,
    scan_id: str,
    key: str = "key-1",
) -> httpx.Response:
    return await client.post(
        "/api/terminal/confirm",
        headers={**auth(token), "Idempotency-Key": key},
        json={"participant_id": participant_id, "scan_id": scan_id},
    )


async def report_error(
    client: httpx.AsyncClient, token: str, participant_id: int, scan_id: str
) -> httpx.Response:
    return await client.post(
        "/api/terminal/report-error",
        headers=auth(token),
        json={"participant_id": participant_id, "scan_id": scan_id},
    )


async def scan_and_get_id(client: httpx.AsyncClient, token: str, raw: str) -> tuple[int, str]:
    """Скан, который должен найти участника: (participant_id, scan_id)."""
    data = await scan(client, token, raw)
    assert data["result"] == "found", data
    return data["participant"]["id"], data["scan_id"]


async def events(db: AsyncSession, event_type: str, participant_id: int | None = None) -> list[Any]:
    query = select(EventLog).where(EventLog.type == event_type).order_by(EventLog.id)
    if participant_id is not None:
        query = query.where(EventLog.participant_id == participant_id)
    return list((await db.scalars(query.execution_options(populate_existing=True))).all())


async def print_jobs(db: AsyncSession, participant_id: int) -> list[PrintJob]:
    query = (
        select(PrintJob)
        .where(PrintJob.participant_id == participant_id)
        .order_by(PrintJob.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(query)).all())
