"""Ядро регистрации: единственное место, где меняется статус регистрации (Р-03, B2-04).

`register()` вызывают терминал (`POST /api/terminal/confirm`) и стойка (B2-15).

**Защита от двойной регистрации — условный UPDATE.** Регистрацию получает тот, чей

    UPDATE participant SET status = …, registered_at = clock_timestamp(), …
    WHERE id = :id AND status = 'not_registered' RETURNING …

затронул строку. Второй запрос ждёт блокировку строки до COMMIT первого, заново проверяет
условие (READ COMMITTED) и не находит ни одной строки: он получает `already_registered`.
Никакого «сначала SELECT, потом UPDATE» тут нет, поэтому гонка DP-02 решается самой БД.

Всё происходит в ОДНОЙ транзакции: запись об идемпотентности, UPDATE, событие, код бейджа и
задание печати. Печатать агент начнёт только после COMMIT (NF-05: наклейка выходит только
после того, как сервер подтвердил запись).

**Идемпотентность.** Первым действием в транзакции вставляется строка `idempotency_record` с
ключом `<scope>:<Idempotency-Key>`. Повторный запрос с тем же ключом блокируется на
уникальном индексе до COMMIT первого и получает его сохранённый ответ, а не новую
регистрацию (TR-03). Поэтому три «одновременных» confirm с одним ключом дают один результат.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.tokens import get_or_create_active_token
from app.core.enums import (
    BadgeType,
    EventType,
    ParticipantStatus,
    PrintJobKind,
    PrintJobStatus,
    RegSource,
)
from app.core.errors import AppError
from app.models.conference import Conference
from app.models.device import Terminal
from app.models.participant import EventLog, Participant
from app.models.printing import IdempotencyRecord, PrintJob
from app.models.staff import StaffUser
from app.registration.rescan import record_rescan

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


def _participant_not_found() -> AppError:
    return AppError("participant_not_found", "Участник не найден", 404)


def idempotency_scope(source: RegSource, terminal_id: int | None, user_id: int | None) -> str:
    """Область действия ключа: ключи разных терминалов (и стойки) не пересекаются."""
    if source == RegSource.TERMINAL:
        return f"confirm:{terminal_id}"
    return f"desk:{user_id}"


def _store_key(scope: str, key: str) -> str:
    return f"{scope}:{key}"


def _replay(stored: dict[str, Any], participant_id: int) -> RegistrationResult:
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
        select(IdempotencyRecord.response).where(IdempotencyRecord.key == _store_key(scope, key))
    )
    return _replay(stored, participant_id) if stored else None


async def register(
    session: AsyncSession,
    participant_id: int,
    *,
    source: RegSource,
    terminal_id: int | None,
    user_id: int | None,
    with_sticker: bool,
    printer_id: int | None,
    idempotency_key: str | None = None,
) -> RegistrationResult:
    """Зарегистрировать участника. Транзакцию завершает сама (commit или rollback).

    - `source`/`terminal_id`/`user_id` — где и кем зарегистрирован (терминал или стойка).
    - `with_sticker` — нужна ли наклейка; для конференции «без бейджа» её не бывает никогда
      (статус `registered_no_sticker`, печати нет, ошибки печати нет).
    - `printer_id` — принтер терминала или панели. Наклейка нужна, а принтера нет: регистрация
      всё равно проходит, `sticker_not_printed = true`, задания нет (TR-08).
    - `idempotency_key` — повтор с тем же ключом (в той же области) возвращает сохранённый
      результат и ничего не меняет.

    Уже зарегистрированный участник — не ошибка: результат `already_registered` с данными
    первой регистрации. Нет такого участника: `404 participant_not_found`.
    """
    try:
        return await _register(
            session,
            participant_id,
            source=source,
            terminal_id=terminal_id,
            user_id=user_id,
            with_sticker=with_sticker,
            printer_id=printer_id,
            idempotency_key=idempotency_key,
        )
    except Exception:
        await session.rollback()
        raise


async def _register(
    session: AsyncSession,
    participant_id: int,
    *,
    source: RegSource,
    terminal_id: int | None,
    user_id: int | None,
    with_sticker: bool,
    printer_id: int | None,
    idempotency_key: str | None,
) -> RegistrationResult:
    store_key: str | None = None
    if idempotency_key is not None:
        scope = idempotency_scope(source, terminal_id, user_id)
        store_key = _store_key(scope, idempotency_key)
        # Занимаем ключ первым делом. Параллельный запрос с тем же ключом ждёт здесь
        # конца нашей транзакции и затем получает наш ответ.
        claimed = await session.execute(
            pg_insert(IdempotencyRecord)
            .values(key=store_key, scope=scope, response={})
            .on_conflict_do_nothing(index_elements=[IdempotencyRecord.key])
            .returning(IdempotencyRecord.key)
        )
        if claimed.first() is None:
            stored = await session.scalar(
                select(IdempotencyRecord.response).where(IdempotencyRecord.key == store_key)
            )
            await session.commit()  # нечего сохранять: просто закрываем транзакцию
            if not stored:  # не должно случиться: чужая строка видна только после её COMMIT
                raise AppError("idempotency_conflict", "Повторите запрос", 409)
            return _replay(stored, participant_id)

    info = (
        await session.execute(
            select(Participant.conference_id, Conference.badge_type)
            .join(Conference, Conference.id == Participant.conference_id)
            .where(Participant.id == participant_id)
        )
    ).first()
    if info is None:
        raise _participant_not_found()
    conference_id, badge_type = info.conference_id, info.badge_type

    needs_sticker = with_sticker and badge_type != BadgeType.NONE
    no_printer = needs_sticker and printer_id is None
    status = (
        ParticipantStatus.REGISTERED if needs_sticker else ParticipantStatus.REGISTERED_NO_STICKER
    )

    # --- Ядро: условный UPDATE. Победитель гонки получает строку, остальные — ни одной.
    won = (
        await session.execute(
            update(Participant)
            .where(
                Participant.id == participant_id,
                Participant.status == ParticipantStatus.NOT_REGISTERED,
            )
            .values(
                status=status,
                registered_at=func.clock_timestamp(),
                reg_source=source.value,
                reg_terminal_id=terminal_id,
                reg_user_id=user_id,
                sticker_not_printed=no_printer,
            )
            .returning(Participant.registered_at)
            .execution_options(synchronize_session=False)
        )
    ).first()

    if won is None:
        result = await _already_registered(session, participant_id, badge_type)
        if source == RegSource.TERMINAL and terminal_id is not None:
            # Проигравший гонку терминал: это тоже повторная попытка (DP-01)
            await record_rescan(session, participant_id, conference_id, terminal_id)
    else:
        result = await _after_win(
            session,
            participant_id,
            conference_id=conference_id,
            badge_type=badge_type,
            status=status,
            registered_at=won.registered_at,
            source=source,
            terminal_id=terminal_id,
            user_id=user_id,
            needs_sticker=needs_sticker,
            printer_id=printer_id,
            no_printer=no_printer,
            store_key=store_key,
        )

    if store_key is not None:
        await session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.key == store_key)
            .values(response=result.to_json())
        )
    await session.commit()
    return result


async def _already_registered(
    session: AsyncSession, participant_id: int, badge_type: str
) -> RegistrationResult:
    """Данные первой регистрации (проигравший гонку или повторный запрос)."""
    row = (
        await session.execute(
            select(
                Participant.status,
                Participant.registered_at,
                Participant.reg_source,
                Participant.reg_terminal_id,
                Participant.reg_user_id,
                Participant.sticker_not_printed,
                Terminal.name.label("terminal_name"),
                StaffUser.login.label("user_login"),
            )
            .outerjoin(Terminal, Terminal.id == Participant.reg_terminal_id)
            .outerjoin(StaffUser, StaffUser.id == Participant.reg_user_id)
            .where(Participant.id == participant_id)
        )
    ).first()
    if row is None or row.registered_at is None:  # победитель откатился? в одной транзакции нет
        raise AppError("registration_conflict", "Повторите запрос", 409)
    return RegistrationResult(
        result="already_registered",
        participant_id=participant_id,
        status=row.status,
        registered_at=row.registered_at,
        source=row.reg_source,
        terminal_id=row.reg_terminal_id,
        terminal_name=row.terminal_name,
        user_id=row.reg_user_id,
        user_login=row.user_login,
        print_job_id=None,
        sticker_not_printed=row.sticker_not_printed,
        badge_type=badge_type,
    )


async def _after_win(
    session: AsyncSession,
    participant_id: int,
    *,
    conference_id: int,
    badge_type: str,
    status: str,
    registered_at: datetime,
    source: RegSource,
    terminal_id: int | None,
    user_id: int | None,
    needs_sticker: bool,
    printer_id: int | None,
    no_printer: bool,
    store_key: str | None,
) -> RegistrationResult:
    """Всё, что идёт вместе с успешной регистрацией: событие, код бейджа, задание печати."""
    token = await get_or_create_active_token(session, participant_id)
    sides = 2 if badge_type == BadgeType.DOUBLE else 1
    session.add(
        EventLog(
            conference_id=conference_id,
            participant_id=participant_id,
            type=EventType.REGISTERED,
            terminal_id=terminal_id,
            user_id=user_id,
            payload={
                "source": source.value,
                "status": status,
                "sticker": needs_sticker,
                "sides": sides if needs_sticker else 0,
            },
        )
    )

    job_id: int | None = None
    if needs_sticker and printer_id is not None:
        job = PrintJob(
            conference_id=conference_id,
            participant_id=participant_id,
            badge_token_id=token.id,
            printer_id=printer_id,
            kind=PrintJobKind.FIRST,
            sides=sides,
            status=PrintJobStatus.PENDING,
            idempotency_key=store_key,
            created_by_user_id=user_id,
            created_by_terminal_id=terminal_id,
        )
        session.add(job)
        await session.flush()
        job_id = job.id
    elif no_printer:
        session.add(
            EventLog(
                conference_id=conference_id,
                participant_id=participant_id,
                type=EventType.PRINT_ERROR,
                terminal_id=terminal_id,
                user_id=user_id,
                payload={"reason": "no_printer"},
            )
        )

    terminal_name = user_login = None
    if terminal_id is not None:
        terminal_name = await session.scalar(
            select(Terminal.name).where(Terminal.id == terminal_id)
        )
    if user_id is not None:
        user_login = await session.scalar(select(StaffUser.login).where(StaffUser.id == user_id))

    return RegistrationResult(
        result="registered",
        participant_id=participant_id,
        status=status,
        registered_at=registered_at,
        source=source.value,
        terminal_id=terminal_id,
        terminal_name=terminal_name,
        user_id=user_id,
        user_login=user_login,
        print_job_id=job_id,
        sticker_not_printed=no_printer,
        badge_type=badge_type,
    )
