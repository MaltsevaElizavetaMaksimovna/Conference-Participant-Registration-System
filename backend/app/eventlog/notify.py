"""События для реалтайма панели через PostgreSQL `NOTIFY` (B2-04a, RG-04, NF-01).

`pg_notify` выполняется внутри транзакции изменения: слушатели `LISTEN regsys_events`
получают событие только после COMMIT, а при откате — не получают вовсе. Поэтому панель
не увидит регистрацию, которая не записалась.

Формат: `{"type":"participant_updated","id":<participant_id>,"conference_id":<id>}`.
Одинаковые события одной транзакции PostgreSQL доставляет один раз.
"""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

EVENTS_CHANNEL = "regsys_events"
PARTICIPANT_UPDATED = "participant_updated"


def participant_updated_payload(participant_id: int, conference_id: int) -> str:
    data = {"type": PARTICIPANT_UPDATED, "id": participant_id, "conference_id": conference_id}
    return json.dumps(data, separators=(",", ":"))


async def notify_participant_updated(
    session: AsyncSession, participant_id: int, conference_id: int
) -> None:
    """Поставить событие `participant_updated` в текущую транзакцию. Без commit."""
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {
            "channel": EVENTS_CHANNEL,
            "payload": participant_updated_payload(participant_id, conference_id),
        },
    )
