"""Импорт участников из .xlsx/.csv через API (B1-05, IM-01) и производительность (NF-01)."""

import time
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports import service
from app.models.conference import ExtraFieldDef
from app.models.imports import ImportBatch
from app.models.participant import Participant
from tests.conftest import LoginAs, StaffClient
from tests.import_files import (
    HEADERS,
    csv_bytes,
    docx_like_bytes,
    make_conference,
    people,
    person,
    upload,
    upload_report,
    xlsx_bytes,
)


async def importer(login_as: LoginAs) -> StaffClient:
    return await login_as("imports.run")


async def participants(db: AsyncSession, conference_id: int) -> dict[str, Participant]:
    db.expunge_all()
    rows = await db.scalars(select(Participant).where(Participant.conference_id == conference_id))
    return {p.external_id: p for p in rows if p.external_id}


async def count(db: AsyncSession, model: Any) -> int:
    return await db.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------------- проверки IM-01


async def test_300_rows_load_without_errors(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    r = await upload(c, conf, "participants.xlsx", xlsx_bytes(people(300)))
    assert r.status_code == 202
    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{r.json()['batch_id']}")).json()
    assert report["summary"] == "Загружено: 300, пропущено: 0"
    assert (report["loaded"], report["skipped"], report["updated"], report["total_rows"]) == (
        300,
        0,
        0,
        300,
    )
    assert report["status"] == "done"
    assert report["errors"] == []
    assert report["file_name"] == "participants.xlsx"
    assert report["finished_at"] is not None
    assert await count(db, Participant) == 300

    batch = await db.get(ImportBatch, r.json()["batch_id"])
    assert batch is not None
    assert batch.status == "done"
    assert batch.source == "file"
    assert batch.file_sha256 and len(batch.file_sha256) == 64
    assert batch.user_id == c.user_id


async def test_participant_fields_and_search_norm(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [["P-1", "  Ёлкин ", " Пётр", "Сергеевич ", "\xa0Инженер", "ООО Ромашка"]]
    await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))
    p = (await participants(db, conf))["P-1"]
    assert (p.last_name, p.first_name, p.middle_name) == ("Ёлкин", "Пётр", "Сергеевич")
    assert p.position == "Инженер"
    assert p.organization == "ООО Ромашка"
    assert p.search_norm == "елкин петр сергеевич"
    assert p.status == "not_registered"
    assert p.manual_fields == []
    assert p.last_name_en is None
    assert p.extra == {}


async def test_non_xlsx_non_csv_is_rejected_and_nothing_is_loaded(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    for name in ("participants.docx", "p.xls", "p.txt", "noext"):
        r = await upload(c, conf, name, docx_like_bytes())
        assert r.status_code == 422, name
        assert r.json()["code"] == "bad_file"
        assert r.json()["message"] == "Поддерживаются файлы .xlsx и .csv"
    assert await count(db, Participant) == 0
    assert await count(db, ImportBatch) == 0


async def test_fake_xlsx_and_garbage_are_rejected(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    for name, data in (
        ("a.xlsx", docx_like_bytes()),
        ("b.xlsx", b"just text"),
        ("c.csv", xlsx_bytes(people(2))),
        ("d.csv", b""),
    ):
        r = await upload(c, conf, name, data)
        assert r.status_code == 422, name
        assert r.json()["code"] == "bad_file"
    assert await count(db, Participant) == 0


async def test_extra_column_becomes_extra_field(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [[*person(i), "A" if i % 2 else "Б", "VIP" if i == 1 else ""] for i in range(1, 5)]
    headers = [*HEADERS, "Секция", "Тип участия"]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows, headers=headers))
    assert report["loaded"] == 4
    defs = list(
        await db.scalars(
            select(ExtraFieldDef).where(ExtraFieldDef.conference_id == conf).order_by("sort_order")
        )
    )
    assert [(d.key, d.label) for d in defs] == [
        ("sektsiya", "Секция"),
        ("tip_uchastiya", "Тип участия"),
    ]
    got = await participants(db, conf)
    assert got["P-1"].extra == {"sektsiya": "A", "tip_uchastiya": "VIP"}
    assert got["P-2"].extra == {"sektsiya": "Б"}  # пустое значение не хранится
    assert got["P-1"].source_data["extra.sektsiya"] == "A"


async def test_synonyms_english_columns_and_photo_link(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    headers = [
        "ID*",
        "фамилия",
        "ИМЯ",
        "Last name",
        "First name",
        "Position (EN)",
        "Ссылка на фото",
    ]
    rows = [["B24-7", "Иванов", "Пётр", "Ivanov", "Petr", "Engineer", " https://x.ru/a.jpg "]]
    report = await upload_report(c, conf, "p.csv", csv_bytes(rows, headers=headers))
    assert report["loaded"] == 1
    p = (await participants(db, conf))["B24-7"]
    assert (p.last_name_en, p.first_name_en, p.position_en) == ("Ivanov", "Petr", "Engineer")
    assert p.position is None
    # ссылка только сохраняется (скачивает B1-06), в участнике фото нет
    assert p.source_data["photo_url"] == "https://x.ru/a.jpg"
    assert p.photo_path is None


async def test_rows_without_required_fields_are_skipped_with_reason(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [
        person(1),
        ["P-2", "", "Анна", "", "", ""],  # строка 3
        ["P-3", "Петров", None, "", "", ""],  # строка 4
        ["", "Сидоров", "Олег", "", "", ""],  # строка 5
        ["P-6", "  ", "  ", "", "", ""],  # строка 6
        ["", "", "", "", "", ""],  # строка 7: пустая, молча
        person(8),
    ]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))
    assert report["loaded"] == 2
    assert report["skipped"] == 4
    assert report["total_rows"] == 6
    assert report["summary"] == "Загружено: 2, пропущено: 4"
    assert [(e["row"], e["reason"], e["message"]) for e in report["errors"]] == [
        (3, "не указана фамилия", "Строка 3: не указана фамилия"),
        (4, "не указано имя", "Строка 4: не указано имя"),
        (5, "не указан идентификатор", "Строка 5: не указан идентификатор"),
        (6, "не указаны: фамилия, имя", "Строка 6: не указаны: фамилия, имя"),
    ]
    assert set(await participants(db, conf)) == {"P-1", "P-8"}


async def test_duplicate_ids_first_row_wins(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [
        ["P-1", "Первый", "Иван", "", "", ""],
        ["P-2", "Другой", "Олег", "", "", ""],
        ["P-1", "Второй", "Иван", "", "", ""],
        ["P-1", "Третий", "Иван", "", "", ""],
    ]
    report = await upload_report(c, conf, "p.csv", csv_bytes(rows))
    assert report["loaded"] == 2
    assert [e["row"] for e in report["errors"]] == [4, 5]
    assert "повторяется идентификатор P-1" in report["errors"][0]["reason"]
    assert "строка 2" in report["errors"][0]["reason"]
    assert (await participants(db, conf))["P-1"].last_name == "Первый"


async def test_invalid_row_does_not_shadow_a_later_valid_duplicate(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [["P-1", "", "Иван", "", "", ""], ["P-1", "Иванов", "Иван", "", "", ""]]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows))
    assert (report["loaded"], report["skipped"]) == (1, 1)
    assert report["errors"][0]["row"] == 2


# --------------------------------------------------------------------------- вид идентификатора


async def test_id_shapes_from_excel(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [
        [123.0, "Числовой", "А", "", "", ""],  # 123.0 -> "123"
        ["00456", "Текстовый", "Б", "", "", ""],  # ведущие нули из текстовой ячейки
        [789, "Целый", "В", "", "", ""],
        ["1.2E+15", "Экспонента", "Г", "", "", ""],  # испорчено Excel
        [1.2345678901234568e18, "Длинный", "Д", "", "", ""],  # >15 цифр из числа
        ["12345678901234567890", "Текстом", "Е", "", "", ""],  # длинный, но текстом — можно
    ]
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(rows, text_columns=[]))
    got = await participants(db, conf)
    assert set(got) == {"123", "00456", "789", "12345678901234567890"}
    assert [e["row"] for e in report["errors"]] == [5, 6]
    assert "экспоненциальной" in report["errors"][0]["reason"]
    assert "15 цифр" in report["errors"][1]["reason"]


async def test_id_shapes_from_csv(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [
        ["123.0", "Один", "А", "", "", ""],
        ["00789", "Два", "Б", "", "", ""],
        ["1,2E+15", "Три", "В", "", "", ""],
    ]
    report = await upload_report(c, conf, "p.csv", csv_bytes(rows))
    assert set(await participants(db, conf)) == {"123", "00789"}
    assert [e["row"] for e in report["errors"]] == [4]


async def test_trailing_blank_rows_are_ignored_silently(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    blanks: list[list[Any]] = [[None] * 6, ["", " ", "", "", "", ""]] * 3
    xlsx = await upload_report(c, conf, "p.xlsx", xlsx_bytes([*people(3), *blanks]))
    assert (xlsx["loaded"], xlsx["skipped"], xlsx["total_rows"]) == (3, 0, 3)
    conf2 = await make_conference(db, "Вторая")
    data = csv_bytes(people(3)) + b";;;;;\r\n\r\n   \r\n"
    csv = await upload_report(c, conf2, "p.csv", data)
    assert (csv["loaded"], csv["skipped"], csv["total_rows"]) == (3, 0, 3)


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "cp1251"])
@pytest.mark.parametrize("delimiter", [";", ","])
async def test_csv_encodings_and_delimiters(
    login_as: LoginAs, db: AsyncSession, encoding: str, delimiter: str
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [["P-1", "Ёлкин", "Пётр", "", "Главный, инженер", 'ООО "Ромашка"'], *people(2, 2)]
    report = await upload_report(
        c, conf, "p.csv", csv_bytes(rows, encoding=encoding, delimiter=delimiter)
    )
    assert report["summary"] == "Загружено: 3, пропущено: 0"
    p = (await participants(db, conf))["P-1"]
    assert (p.last_name, p.position, p.organization) == (
        "Ёлкин",
        "Главный, инженер",
        'ООО "Ромашка"',
    )


async def test_csv_with_sep_line_and_excel_style_file(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    data = csv_bytes(people(3), sep_line=True, delimiter=";", encoding="cp1251")
    report = await upload_report(c, conf, "p.CSV", data)  # расширение в любом регистре
    assert report["loaded"] == 3


async def test_hidden_first_sheet_is_skipped(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    report = await upload_report(c, conf, "p.xlsx", xlsx_bytes(people(4), hidden_first=True))
    assert report["loaded"] == 4


# --------------------------------------------------------------------------- ошибки файла и запроса


async def test_missing_required_columns(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    r = await upload(c, conf, "p.xlsx", xlsx_bytes([["Иванов"]], headers=["Фамилия"]))
    assert r.status_code == 422
    assert r.json()["code"] == "bad_file"
    assert r.json()["message"] == "В файле нет обязательных столбцов: Идентификатор, Имя"
    assert await count(db, Participant) == 0


async def test_file_too_large(login_as: LoginAs, db: AsyncSession, app_db: FastAPI) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    app_db.state.settings = app_db.state.settings.model_copy(update={"import_max_file_mb": 1})
    big = csv_bytes(people(30000))
    assert len(big) > 1024 * 1024
    r = await upload(c, conf, "big.csv", big)
    assert r.status_code == 413
    assert r.json()["code"] == "file_too_large"
    assert await count(db, Participant) == 0
    assert await count(db, ImportBatch) == 0


async def test_too_many_rows(login_as: LoginAs, db: AsyncSession, app_db: FastAPI) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    app_db.state.settings = app_db.state.settings.model_copy(update={"import_max_rows": 50})
    assert (await upload(c, conf, "ok.xlsx", xlsx_bytes(people(50)))).status_code == 202
    r = await upload(c, conf, "big.xlsx", xlsx_bytes(people(51)))
    assert r.status_code == 422
    assert r.json()["code"] == "bad_file"
    assert await count(db, Participant) == 50


async def test_unknown_conference_and_missing_file(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    r = await upload(c, 999999, "p.xlsx", xlsx_bytes(people(1)))
    assert r.status_code == 404
    assert r.json()["code"] == "conference_not_found"
    r = await c.post(f"/api/admin/conferences/{conf}/imports", data={"x": "y"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_report_is_scoped_to_the_conference(login_as: LoginAs, db: AsyncSession) -> None:
    c = await importer(login_as)
    conf, other = await make_conference(db), await make_conference(db, "Другая")
    r = await upload(c, conf, "p.xlsx", xlsx_bytes(people(1)))
    batch = r.json()["batch_id"]
    assert (await c.get(f"/api/admin/conferences/{conf}/imports/{batch}")).status_code == 200
    miss = await c.get(f"/api/admin/conferences/{other}/imports/{batch}")
    assert miss.status_code == 404
    assert miss.json()["code"] == "import_not_found"
    assert (await c.get(f"/api/admin/conferences/{conf}/imports/999999")).status_code == 404


async def test_failed_import_rolls_back_everything(
    login_as: LoginAs, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, conf = await importer(login_as), await make_conference(db)

    async def boom(*_: Any, **__: Any) -> None:
        raise RuntimeError("сбой в конце загрузки")

    monkeypatch.setattr(service, "_collect_missing", boom)
    r = await upload(c, conf, "p.xlsx", xlsx_bytes(people(20)))
    assert r.status_code == 500
    assert r.json()["code"] == "import_failed"
    assert await count(db, Participant) == 0  # транзакция откатилась целиком
    assert await count(db, ExtraFieldDef) == 0
    batch = await db.get(ImportBatch, r.json()["details"]["batch_id"], populate_existing=True)
    assert batch is not None
    assert batch.status == "failed"
    report = await c.get(f"/api/admin/conferences/{conf}/imports/{batch.id}")
    assert report.json()["status"] == "failed"


async def test_same_ids_in_different_conferences_are_independent(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await importer(login_as)
    first, second = await make_conference(db), await make_conference(db, "Вторая")
    one = await upload_report(c, first, "p.xlsx", xlsx_bytes(people(5)))
    two = await upload_report(c, second, "p.xlsx", xlsx_bytes(people(5)))
    assert (one["loaded"], two["loaded"]) == (5, 5)
    assert len(await participants(db, first)) == len(await participants(db, second)) == 5


# --------------------------------------------------------------------------- права


async def test_permissions(login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession) -> None:
    conf = await make_conference(db)
    data = xlsx_bytes(people(1))
    denied = await login_as("conferences.manage", "participants.view")
    r = await upload(denied, conf, "p.xlsx", data)
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
    assert (await denied.get(f"/api/admin/conferences/{conf}/imports/1")).status_code == 403
    assert (await upload(anon, conf, "p.xlsx", data)).status_code == 401
    assert await count(db, Participant) == 0
    # без CSRF-заголовка нельзя, даже с правом
    c = await importer(login_as)
    del c.headers["X-Requested-With"]
    r = await upload(c, conf, "p.xlsx", data)
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_required"


# --------------------------------------------------------------------------- NF-01


@pytest.mark.parametrize("kind", ["xlsx", "csv"])
async def test_1000_rows_load_within_10_seconds(
    login_as: LoginAs, db: AsyncSession, kind: str
) -> None:
    c, conf = await importer(login_as), await make_conference(db)
    rows = [[*person(i), "A", "https://example.com/p.jpg"] for i in range(1, 1001)]
    headers = [*HEADERS, "Секция", "Фото"]
    data = xlsx_bytes(rows, headers=headers) if kind == "xlsx" else csv_bytes(rows, headers=headers)

    started = time.perf_counter()
    r = await upload(c, conf, f"p.{kind}", data)
    report = (await c.get(f"/api/admin/conferences/{conf}/imports/{r.json()['batch_id']}")).json()
    first = time.perf_counter() - started
    assert report["summary"] == "Загружено: 1000, пропущено: 0"
    assert first < 10, f"{first:.1f} с"

    # повторная загрузка (обновление 1000 существующих) тоже укладывается
    changed = [[*row[:5], f"{row[5]} (новое)", *row[6:]] for row in rows]
    started = time.perf_counter()
    again = await upload_report(
        c,
        conf,
        f"p.{kind}",
        xlsx_bytes(changed, headers=headers)
        if kind == "xlsx"
        else csv_bytes(changed, headers=headers),
    )
    second = time.perf_counter() - started
    assert again["updated"] == 1000
    assert second < 10, f"{second:.1f} с"
    print(f"\n{kind}: загрузка {first:.2f} с, обновление {second:.2f} с")
