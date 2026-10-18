"""Ограничения схемы БД: уникальность, CHECK, триггер журнала, значения по умолчанию."""

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import BadgeTokenStatus, ChangeSource, ParticipantStatus
from app.core.permissions import Permission
from app.models import (
    BadgeToken,
    ChangeLog,
    Conference,
    LabelTemplate,
    Participant,
    Printer,
    PrintJob,
    Role,
    RolePermission,
    StaffUser,
)


async def make_conference(db: AsyncSession, *, active: bool = False, **kw: Any) -> Conference:
    conf = Conference(
        title=kw.pop("title", "Конференция"),
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 3),
        badge_type="single",
        is_active=active,
        **kw,
    )
    db.add(conf)
    await db.flush()
    return conf


def make_participant(conference_id: int, **kw: Any) -> Participant:
    kw.setdefault("last_name", "Иванов")
    kw.setdefault("first_name", "Иван")
    kw.setdefault("search_norm", "иванов иван")
    return Participant(conference_id=conference_id, **kw)


async def make_role_and_user(db: AsyncSession, login: str = "admin") -> StaffUser:
    role = Role(name=f"Роль {login}")
    db.add(role)
    await db.flush()
    user = StaffUser(full_name="Тест", login=login, password_hash="x", role_id=role.id)
    db.add(user)
    await db.flush()
    return user


async def test_only_one_active_conference(db: AsyncSession) -> None:
    await make_conference(db, active=True)
    await make_conference(db, active=False, title="Архив 1")
    await make_conference(db, active=False, title="Архив 2")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await make_conference(db, active=True, title="Вторая активная")


async def test_active_conference_can_be_switched(db: AsyncSession) -> None:
    first = await make_conference(db, active=True)
    second = await make_conference(db, title="Следующая")
    first.is_active = False
    await db.flush()
    second.is_active = True
    await db.flush()


async def test_external_id_unique_within_conference(db: AsyncSession) -> None:
    c1 = await make_conference(db, title="К1")
    c2 = await make_conference(db, title="К2")
    db.add(make_participant(c1.id, external_id="B24-1"))
    db.add(make_participant(c2.id, external_id="B24-1"))  # в другой конференции — можно
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(make_participant(c1.id, external_id="B24-1"))


async def test_null_external_id_allowed_many_times(db: AsyncSession) -> None:
    conf = await make_conference(db)
    db.add_all([make_participant(conf.id), make_participant(conf.id)])
    await db.flush()


async def test_participant_defaults(db: AsyncSession) -> None:
    conf = await make_conference(db)
    p = make_participant(conf.id)
    db.add(p)
    await db.flush()
    await db.refresh(p)
    assert p.status == ParticipantStatus.NOT_REGISTERED
    assert p.registered_at is None
    assert p.extra == {} and p.source_data == {}
    assert p.manual_fields == []
    assert (p.print_count, p.rescan_count) == (0, 0)
    assert p.is_manual_added is False and p.sticker_not_printed is False
    assert p.created_at is not None and p.updated_at is not None


async def test_registered_requires_registered_at(db: AsyncSession) -> None:
    conf = await make_conference(db)
    for status in (ParticipantStatus.REGISTERED, ParticipantStatus.REGISTERED_NO_STICKER):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(make_participant(conf.id, status=status))
    # и наоборот: время регистрации у «не зарегистрирован»
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(make_participant(conf.id, registered_at=datetime.now(UTC)))
    db.add(
        make_participant(
            conf.id,
            status=ParticipantStatus.REGISTERED,
            registered_at=datetime.now(UTC),
            reg_source="desk",
        )
    )
    await db.flush()


@pytest.mark.parametrize("kw", [{"status": "unknown"}, {"reg_source": "web"}])
async def test_participant_enum_checks(db: AsyncSession, kw: dict[str, Any]) -> None:
    conf = await make_conference(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(make_participant(conf.id, **kw))


async def test_invalid_badge_type_rejected(db: AsyncSession) -> None:
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                Conference(
                    title="X",
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 2),
                    badge_type="triple",
                )
            )


async def test_one_active_badge_token_per_participant(db: AsyncSession) -> None:
    conf = await make_conference(db)
    p = make_participant(conf.id)
    other = make_participant(conf.id)
    db.add_all([p, other])
    await db.flush()
    first = BadgeToken(participant_id=p.id, token="t-1")
    db.add(first)
    db.add(BadgeToken(participant_id=other.id, token="t-other"))  # у другого участника — можно
    await db.flush()

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(BadgeToken(participant_id=p.id, token="t-2"))

    first.status = BadgeTokenStatus.REVOKED
    first.revoked_at = datetime.now(UTC)
    await db.flush()
    db.add(BadgeToken(participant_id=p.id, token="t-2"))
    await db.flush()
    # отозванных может быть сколько угодно
    db.add(BadgeToken(participant_id=p.id, token="t-3", status=BadgeTokenStatus.REVOKED))
    await db.flush()


async def test_badge_token_value_is_unique(db: AsyncSession) -> None:
    conf = await make_conference(db)
    a, b = make_participant(conf.id), make_participant(conf.id)
    db.add_all([a, b])
    await db.flush()
    db.add(BadgeToken(participant_id=a.id, token="same"))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(BadgeToken(participant_id=b.id, token="same"))


async def test_change_log_is_append_only(db: AsyncSession) -> None:
    conf = await make_conference(db)
    p = make_participant(conf.id)
    db.add(p)
    await db.flush()
    db.add(
        ChangeLog(
            participant_id=p.id,
            field="last_name",
            old_value="Иванов",
            new_value="Петров",
            source=ChangeSource.MANUAL,
        )
    )
    await db.flush()  # вставка разрешена

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(update(ChangeLog).values(new_value="Сидоров"))
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(delete(ChangeLog))
    assert await db.scalar(select(ChangeLog.new_value)) == "Петров"


async def test_change_log_source_check(db: AsyncSession) -> None:
    conf = await make_conference(db)
    p = make_participant(conf.id)
    db.add(p)
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(ChangeLog(participant_id=p.id, field="x", source="robot"))


async def test_login_unique_case_insensitive(db: AsyncSession) -> None:
    user = await make_role_and_user(db, "Ivanov")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                StaffUser(
                    full_name="Двойник", login="IVANOV", password_hash="x", role_id=user.role_id
                )
            )
    db.add(StaffUser(full_name="Другой", login="petrov", password_hash="x", role_id=user.role_id))
    await db.flush()


async def test_role_permission_check_and_cascade(db: AsyncSession) -> None:
    role = Role(name="Тестовая")
    db.add(role)
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(RolePermission(role_id=role.id, permission="nuke.everything"))
    db.add(RolePermission(role_id=role.id, permission=Permission.PARTICIPANTS_VIEW))
    await db.flush()
    with pytest.raises(IntegrityError):  # PK (role_id, permission)
        async with db.begin_nested():
            db.add(RolePermission(role_id=role.id, permission=Permission.PARTICIPANTS_VIEW))

    await db.execute(delete(Role).where(Role.id == role.id))
    assert await db.scalar(select(RolePermission.role_id)) is None


async def test_role_with_users_cannot_be_deleted(db: AsyncSession) -> None:
    user = await make_role_and_user(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(delete(Role).where(Role.id == user.role_id))


async def test_label_template_defaults_and_cyclic_fk(db: AsyncSession) -> None:
    conf = await make_conference(db)
    tpl = LabelTemplate(
        conference_id=conf.id,
        name="Лицевая",
        kind="front",
        width_mm=Decimal("58"),
        height_mm=Decimal("40"),
    )
    db.add(tpl)
    await db.flush()
    await db.refresh(tpl)
    assert tpl.gap_mm == Decimal("2.00")
    assert tpl.elements == []
    assert tpl.version == 1

    conf.front_template_id = tpl.id  # циклическая ссылка conference -> label_template
    await db.flush()
    with pytest.raises(IntegrityError):  # шаблон, на который ссылается конференция, не удалить
        async with db.begin_nested():
            await db.execute(delete(LabelTemplate))

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(
                LabelTemplate(conference_id=conf.id, name="X", kind="side", width_mm=1, height_mm=1)
            )


async def test_printer_calibration_defaults_and_checks(db: AsyncSession) -> None:
    printer = Printer(name="П1")
    db.add(printer)
    await db.flush()
    await db.refresh(printer)
    assert printer.offset_x_mm == Decimal("0") and printer.offset_y_mm == Decimal("0")
    assert (printer.density, printer.speed, printer.dpi) == (10, 3, 203)

    printer.offset_x_mm = Decimal("-2.00")  # сдвиг влево может быть отрицательным
    printer.density, printer.speed = 15, 6
    await db.flush()

    for bad in ({"density": 16}, {"density": -1}, {"speed": 0}, {"speed": 7}):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(Printer(name=f"bad-{bad}", **bad))


async def test_print_job_sides_check(db: AsyncSession) -> None:
    conf = await make_conference(db)
    printer = Printer(name="П1")
    db.add(printer)
    await db.flush()
    db.add(PrintJob(conference_id=conf.id, printer_id=printer.id, kind="test", sides=2))
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(PrintJob(conference_id=conf.id, printer_id=printer.id, kind="test", sides=3))


async def test_print_job_idempotency_key_unique(db: AsyncSession) -> None:
    conf = await make_conference(db)
    printer = Printer(name="П1")
    db.add(printer)
    await db.flush()

    def job(key: str | None) -> PrintJob:
        return PrintJob(
            conference_id=conf.id,
            printer_id=printer.id,
            kind="first",
            sides=1,
            idempotency_key=key,
        )

    db.add_all([job(None), job(None), job("k")])
    await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(job("k"))


async def test_session_isolation(db: AsyncSession) -> None:
    # фикстура db откатывает данные: из других тестов ничего не видно
    assert await db.scalar(text("SELECT count(*) FROM conference")) == 0
    assert await db.scalar(text("SELECT count(*) FROM participant")) == 0
