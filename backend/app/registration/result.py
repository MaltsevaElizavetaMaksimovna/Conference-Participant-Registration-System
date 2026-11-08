"""Итог регистрации и повтор ответа по `Idempotency-Key` (TR-03)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import RegSource
from app.core.errors import AppError
from app.models.printing import IdempotencyRecord

Outcome = Literal["registered", "already_registered"]


@dataclass(frozen=True)
class RegistrationResult:
    """Итог `register()`; сохраняется в `idempotency_record.response` и восстанавливается."""

    result: Outcome
    participant_id: int
    status: str
    registered_at: datetime
    # Данные регистрации: у `registered` — только что записанные, у `already_registered` —
    # первой регистрации (кто и где зарегистрировал раньше)
    source: str | None
    terminal_id: int | None
    terminal_name: str | None
    user_id: int | None
    user_login: str | None
    print_job_id: int | None
    sticker_not_printed: bool
    badge_type: str

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {f: getattr(self, f) for f in self.__dataclass_fields__}
        data["registered_at"] = self.registered_at.isoformat()
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "RegistrationResult":
        fields = {f: data[f] for f in cls.__dataclass_fields__}
        fields["registered_at"] = datetime.fromisoformat(fields["registered_at"])
        return cls(**fields)


def idempotency_scope(source: RegSource, terminal_id: int | None, user_id: int | None) -> str:
    """Область действия ключа: ключи разных терминалов (и стойки) не пересекаются."""
    if source == RegSource.TERMINAL:
        return f"confirm:{terminal_id}"
    return f"desk:{user_id}"


def make_store_key(scope: str, key: str) -> str:
    return f"{scope}:{key}"


def replay_stored(stored: dict[str, Any], participant_id: int) -> RegistrationResult:
    result = RegistrationResult.from_json(stored)
    if result.participant_id != participant_id:
        raise AppError(
            "idempotency_key_reused",
            "Этот ключ идемпотентности уже использован для другого участника",
            409,
        )
    return result


async def find_replay(
    session: AsyncSession, scope: str, key: str, participant_id: int
) -> RegistrationResult | None:
    """Сохранённый ответ на запрос с этим ключом, если он уже обработан (иначе None)."""
    stored = await session.scalar(
        select(IdempotencyRecord.response).where(
            IdempotencyRecord.key == make_store_key(scope, key)
        )
    )
    return replay_stored(stored, participant_id) if stored else None
