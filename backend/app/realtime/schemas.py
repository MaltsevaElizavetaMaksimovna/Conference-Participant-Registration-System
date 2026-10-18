"""Данные событий SSE `/api/events/stream` (RG-04, NF-01).

Формат потока: `event: <тип>\\ndata: <JSON>\\n\\n`, строки `: keep-alive` — комментарии.
"""

from pydantic import BaseModel, Field

from app.participants.schemas import ParticipantShort


class StatsEvent(BaseModel):
    """`event: stats` — приходит сразу при подключении и после каждой регистрации."""

    registered: int = Field(examples=[120])
    total: int = Field(examples=[300])


class ParticipantUpdatedEvent(BaseModel):
    """`event: participant_updated` — изменился статус, пометки или данные участника."""

    participant: ParticipantShort
