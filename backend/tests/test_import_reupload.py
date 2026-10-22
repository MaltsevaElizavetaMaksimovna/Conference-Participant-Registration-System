"""Повторная загрузка (B1-07, IM-02): обновление по ID, ручные правки, регистрации, пропавшие."""

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import ChangeLog, Participant
from tests.conftest import LoginAs, StaffClient
from tests.import_files import (
    HEADERS,
    csv_bytes,
    make_conference,
    people,
    person,
    upload_report,
    xlsx_bytes,
)

STATE = (
    "status",
    "registered_at",
    "reg_source",
    "print_count",
    "rescan_count",
    "error_reported_at",
    "sticker_not_printed",
)


async def load(db: AsyncSession, conf: int) -> dict[str, Participant]:
    db.expunge_all()
    rows = await db.scalars(select(Participant).where(Participant.conference_id == conf))
    return {p.external_id: p for p in rows if p.external_id}


def state(p: Participant) -> tuple[Any, ...]:
    return tuple(getattr(p, f) for f in STATE)


async def changes(db: AsyncSession, conf: int) -> list[ChangeLog]:
    db.expunge_all()
    rows = await db.scalars(
        select(ChangeLog)
        .join(Participant, Participant.id == ChangeLog.participant_id)
        .where(Participant.conference_id == conf)
        .order_by(ChangeLog.id)
    )
    return list(rows)


async def setup(login_as: LoginAs, db: AsyncSession, n: int = 10) -> tuple[StaffClient, int]:
    c = await login_as("imports.run")
    conf = await make_conference(db)
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(people(n)))
    assert report["loaded"] == n
    return c, conf


async def test_same_file_twice_changes_nothing(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await setup(login_as, db)
    before = await load(db, conf)
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(people(10)))
    assert (report["loaded"], report["updated"], report["unchanged"]) == (0, 0, 10)
    assert report["conflicts"] == [] and report["missing"] == [] and report["errors"] == []
    assert report["summary"] == "Загружено: 0, пропущено: 0, без изменений: 10"
    assert await changes(db, conf) == []
    assert {k: v.id for k, v in (await load(db, conf)).items()} == {
        k: v.id for k, v in before.items()
    }


async def test_registrations_survive_reupload_and_data_updates(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db)
    # 5 участников уже зарегистрированы (статус выставляем напрямую в БД)
    await db.execute(
        update(Participant)
        .where(
            Participant.conference_id == conf,
            Participant.external_id.in_([f"P-{i}" for i in range(1, 6)]),
        )
        .values(
            status="registered",
            registered_at=func.now(),
            reg_source="desk",
            print_count=1,
            rescan_count=2,
            error_reported_at=func.now(),
        )
    )
    await db.execute(
        update(Participant)
        .where(Participant.conference_id == conf, Participant.external_id == "P-6")
        .values(status="registered_no_sticker", registered_at=func.now(), sticker_not_printed=True)
    )
    p1 = (await load(db, conf))["P-1"]
    db.add(
        ChangeLog(
            participant_id=p1.id,
            field="organization",
            old_value="Старая",
            new_value=p1.organization,
            source="manual",
        )
    )
    await db.commit()
    before = {k: state(v) for k, v in (await load(db, conf)).items()}

    # P-1..P-3 сменили организацию (P-1, P-2 зарегистрированы), P-4 фамилию, +2 новых
    new_rows = people(10)
    for i in (0, 1, 2):
        new_rows[i][5] = f"Новая организация {i}"
    new_rows[3][1] = "Ёжиков"
    new_rows += people(2, 11)
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(new_rows))

    assert report["summary"] == "Загружено: 2, пропущено: 0, обновлено: 4, без изменений: 6"
    assert (report["loaded"], report["updated"], report["unchanged"]) == (2, 4, 6)
    after = await load(db, conf)
    assert len(after) == 12
    # регистрации, пометки и счётчики не сброшены
    assert {k: state(after[k]) for k in before} == before
    assert after["P-1"].status == "registered"
    assert after["P-6"].sticker_not_printed is True
    # данные обновились, search_norm пересчитан только где менялось ФИО
    assert after["P-1"].organization == "Новая организация 0"
    assert after["P-4"].last_name == "Ёжиков"
    assert after["P-4"].search_norm.startswith("ежиков ")
    assert after["P-11"].status == "not_registered"
    # старая запись истории осталась, новые — только по изменённым полям
    log = await changes(db, conf)
    manual = [x for x in log if x.source == "manual"]
    imported = [x for x in log if x.source == "import"]
    assert len(manual) == 1 and manual[0].old_value == "Старая"
    assert sorted((x.field, x.old_value, x.new_value) for x in imported) == sorted(
        [
            ("organization", "ООО Ромашка 1", "Новая организация 0"),
            ("organization", "ООО Ромашка 2", "Новая организация 1"),
            ("organization", "ООО Ромашка 3", "Новая организация 2"),
            ("last_name", before_name(4), "Ёжиков"),
        ]
    )
    batch_ids = {x.import_batch_id for x in imported}
    assert len(batch_ids) == 1 and None not in batch_ids
    assert {x.user_id for x in imported} == {c.user_id}


def before_name(i: int) -> str:
    return str(person(i)[1])


async def test_manual_fields_are_not_overwritten_and_conflicts_reported(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db)
    got = await load(db, conf)
    p3, p4 = got["P-3"], got["P-4"]
    await db.execute(
        update(Participant)
        .where(Participant.id == p3.id)
        .values(position="Директор", organization="Исправлено", manual_fields=["position"])
    )
    # P-4: исправление совпадает с тем, что в файле, — расхождения нет
    await db.execute(
        update(Participant)
        .where(Participant.id == p4.id)
        .values(position="Ведущий инженер", manual_fields=["position"])
    )
    await db.commit()

    rows = people(10)
    rows[2][4] = "Инженер"  # P-3: в файле старая должность
    rows[2][5] = "Файловая организация"  # не ручное поле — обновится
    rows[3][4] = "Ведущий инженер"
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))

    assert report["conflicts"] == [
        {
            "participant_id": p3.id,
            "external_id": "P-3",
            "field": "position",
            "system_value": "Директор",
            "file_value": "Инженер",
        }
    ]
    assert report["updated"] == 1
    after = await load(db, conf)
    assert after["P-3"].position == "Директор"  # ручная правка сохранена
    assert after["P-3"].organization == "Файловая организация"
    assert after["P-3"].manual_fields == ["position"]
    assert after["P-3"].source_data["position"] == "Инженер"  # последнее значение из файла
    assert after["P-4"].position == "Ведущий инженер"
    log = await changes(db, conf)
    assert [(x.field, x.new_value) for x in log] == [("organization", "Файловая организация")]

    # вторая загрузка снова показывает то же расхождение
    again = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))
    assert len(again["conflicts"]) == 1 and again["updated"] == 0


async def test_participants_missing_from_the_new_file_stay_and_are_listed(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db)
    # участник, добавленный регистратором вручную (без ID), в список «нет в файле» не входит
    db.add(
        Participant(
            conference_id=conf,
            external_id=None,
            last_name="Ручной",
            first_name="Иван",
            search_norm="ручной иван",
            is_manual_added=True,
        )
    )
    await db.commit()
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(people(7)))
    before = await load(db, conf)

    def name(key: str) -> str:
        p = before[key]
        return f"{p.last_name} {p.first_name} {p.middle_name}"

    assert [(m["external_id"], m["full_name"]) for m in report["missing"]] == [
        (key, name(key)) for key in ("P-8", "P-9", "P-10")
    ]
    assert report["missing"][0]["participant_id"] == before["P-8"].id
    assert report["summary"] == "Загружено: 0, пропущено: 0, без изменений: 7, нет в файле: 3"
    assert len(before) == 10  # никто не удалён
    manual = await db.scalar(
        select(func.count()).select_from(Participant).where(Participant.external_id.is_(None))
    )
    assert manual == 1


async def test_row_with_invalid_data_does_not_make_participant_missing(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db, 3)
    rows = people(3)
    rows[1][1] = ""  # P-2: нет фамилии -> строка пропущена, но участник в файле есть
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))
    assert report["skipped"] == 1
    assert report["missing"] == []
    assert (await load(db, conf))["P-2"].last_name == person(2)[1]  # прежние данные целы


async def test_missing_columns_do_not_clear_data_but_blank_cells_do(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db, 3)
    # в новом файле нет столбцов «Должность» и «Организация»: поля не трогаем
    headers = ["Идентификатор", "Фамилия", "Имя"]
    rows = [row[:3] for row in people(3)]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert report["unchanged"] == 3
    got = await load(db, conf)
    assert got["P-1"].position == "Инженер" and got["P-1"].organization == "ООО Ромашка 1"
    # пустая ячейка в существующем столбце очищает поле (и пишется в историю)
    rows = people(3)
    rows[0][4] = ""
    report = await upload_report(c, conf, "p.csv", csv_bytes(rows))
    assert report["updated"] == 1
    assert (await load(db, conf))["P-1"].position is None
    log = await changes(db, conf)
    assert [(x.field, x.old_value, x.new_value) for x in log] == [("position", "Инженер", None)]


async def test_extra_fields_on_reupload(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await setup(login_as, db, 3)
    headers = [*HEADERS, "Секция"]
    first = [[*row, "A"] for row in people(3)]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(first, headers=headers))
    assert report["updated"] == 3  # доп. поле появилось у существующих участников
    assert (await load(db, conf))["P-1"].extra == {"sektsiya": "A"}

    second = [[*row, "Б" if i == 0 else "A"] for i, row in enumerate(people(3))]
    report = await upload_report(
        c, conf, "p.xlsx", xlsx_bytes(second, headers=[*HEADERS[:-1], "Организация", "секция"])
    )
    # заголовок «секция» распознан как то же самое поле (без учёта регистра)
    assert report["updated"] == 1
    got = await load(db, conf)
    assert got["P-1"].extra == {"sektsiya": "Б"}
    log = [x for x in await changes(db, conf) if x.new_value == "Б"]
    assert [(x.field, x.old_value) for x in log] == [("extra.sektsiya", "A")]
    from app.models.conference import ExtraFieldDef

    defs = list(await db.scalars(select(ExtraFieldDef).where(ExtraFieldDef.conference_id == conf)))
    assert [(d.key, d.label) for d in defs] == [("sektsiya", "Секция")]


async def test_photo_link_change_counts_as_update_but_is_not_logged(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await setup(login_as, db, 2)
    headers = [*HEADERS, "Фото"]
    rows = [[*row, f"https://x.ru/{row[0]}.jpg"] for row in people(2)]
    assert (await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers)))[
        "updated"
    ] == 2
    rows[0][6] = "https://x.ru/new.jpg"
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert (report["updated"], report["unchanged"]) == (1, 1)
    got = await load(db, conf)
    assert got["P-1"].source_data["photo_url"] == "https://x.ru/new.jpg"
    assert await changes(db, conf) == []
