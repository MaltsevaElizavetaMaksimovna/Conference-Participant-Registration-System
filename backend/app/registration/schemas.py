"""Схемы действий на стойке (RG-05, RG-08, RG-09, QR-03, TR-08)."""

from pydantic import BaseModel, Field

from app.api.common import PrintJobStatus
from app.participants.schemas import ParticipantCard


class RegisterIn(BaseModel):
    with_sticker: bool = Field(
        default=True,
        description="`false` — зарегистрировать без наклейки (статус `registered_no_sticker`)",
    )


class RegisterOut(BaseModel):
    participant: ParticipantCard = Field(description="Карточка после регистрации")
    print_job_id: int | None = Field(
        description="Задание печати; null, если `with_sticker=false`", examples=[501]
    )


class PrintJobOut(BaseModel):
    id: int = Field(examples=[501])
    status: PrintJobStatus = Field(description="pending → sent → done | error")
    error: str | None = Field(description="Причина, если status=error", examples=[None])
