"""Шаблон файла для загрузки (B1-08, IM-03) и общие утилиты участников."""

import io

import httpx
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.imports.columns import FIELDS, match_header
from app.models.participant import Participant
from app.participants.service import compute_search_norm, is_data_changed
from tests.conftest import LoginAs
from tests.import_files import make_conference, upload_report

URL = "/api/admin/import-template.xlsx"


async def test_template_has_marked_headers_and_example_row(login_as: LoginAs) -> None:
    c = await login_as("imports.run")
    r = await c.get(URL)
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    assert ".xlsx" in r.headers["content-disposition"]

    ws = load_workbook(io.BytesIO(r.content)).active
    assert ws is not None
    header, example = [[c.value for c in row] for row in ws.iter_rows(min_row=1, max_row=2)]
    assert ws.max_row == 2  # пустой, кроме заголовков и примера
    assert header[:6] == [
        "Идентификатор*",
        "Фамилия*",
        "Имя*",
        "Отчество",
        "Должность",
        "Организация",
    ]
    assert [h.rstrip("*") for h in header[6:]] == [
        "Фамилия (EN)",
        "Имя (EN)",
        "Отчество (EN)",
        "Должность (EN)",
        "Организация (EN)",
        "Фото (ссылка)",
    ]
    assert [h.endswith("*") for h in header] == [True] * 3 + [False] * (len(header) - 3)
    assert all(example), "в строке-примере заполнены все столбцы"
    assert example[:3] == ["P-1001", "Иванов", "Пётр"]


async def test_template_headers_are_what_the_parser_expects(login_as: LoginAs) -> None:
    c = await login_as("imports.run")
    ws = load_workbook(io.BytesIO((await c.get(URL)).content)).active
    assert ws is not None
    keys = [match_header(str(cell.value)) for cell in ws[1]]
    assert keys == [f.key for f in FIELDS]


async def test_downloaded_template_loads_back(login_as: LoginAs, db: AsyncSession) -> None:
    c, conf = await login_as("imports.run"), await make_conference(db)
    data = (await c.get(URL)).content
    report = await upload_report(c, conf, "import-template.xlsx", data)
    assert report["summary"] == "Загружено: 1, пропущено: 0"
    p = await db.scalar(select(Participant).where(Participant.conference_id == conf))
    assert p is not None
    assert (p.external_id, p.last_name, p.last_name_en) == ("P-1001", "Иванов", "Ivanov")
    assert p.source_data["photo_url"] == "https://example.com/photos/ivanov.jpg"


async def test_template_permissions(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    assert (await anon.get(URL)).status_code == 401
    other = await login_as("conferences.manage")
    assert (await other.get(URL)).status_code == 403


def test_search_norm_and_data_changed_flag() -> None:
    assert compute_search_norm("Ёлкин", "Пётр", None) == "елкин петр"
    assert compute_search_norm("  Ёлкин ", "Пётр", "Сергеевич") == "елкин петр сергеевич"
    assert is_data_changed([], False) is False
    assert is_data_changed(None) is False
    assert is_data_changed(["position"]) is True
    assert is_data_changed([], True) is True
