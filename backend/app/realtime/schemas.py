"""Данные событий SSE `/api/events/stream` (RG-04, NF-01).

Формат потока: `event: <имя>\ndata: <JSON>\n\n`, строки `: keep-alive` — комментарии.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.participants.schemas import ParticipantFlag, ParticipantStatus

# Имена событий потока (поле `event:`). Новые имена в v1.x добавляются, старые не меняются.
STATS_EVENT = "stats"
PARTICIPANT_UPDATED_EVENT = "participant_updated"
EVENT_NAMES: tuple[str, ...] = (STATS_EVENT, PARTICIPANT_UPDATED_EVENT)


class StatsEvent(BaseModel):
    """`event: stats` — приходит сразу при подключении и после каждой регистрации."""

    registered: int = Field(description="Сколько участников зарегистрировано", examples=[120])
    total: int = Field(description="Сколько участников в активной конференции", examples=[300])


class ParticipantUpdatedEvent(BaseModel):
    """`event: participant_updated` — изменился статус, пометки или данные участника.

    Содержит только то, что нужно, чтобы обновить строку списка; ФИО и прочее при
    необходимости фронт перечитывает через `GET /api/participants/{id}`.
    """

    id: int = Field(description="Идентификатор участника", examples=[17])
    status: ParticipantStatus = Field(description="Актуальный статус регистрации")
    flags: list[ParticipantFlag] = Field(
        description="Актуальные пометки (полный список, не изменения)", examples=[["data_changed"]]
    )


SseEventName = Literal["stats", "participant_updated"]
