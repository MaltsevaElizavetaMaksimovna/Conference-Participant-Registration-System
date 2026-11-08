"""Генерация тестовых файлов участников (.xlsx и .csv в разных кодировках и разделителях)."""

import csv
import io
import zipfile
from collections.abc import Sequence
from datetime import date
from typing import Any

import httpx
from openpyxl import Workbook
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import Conference

HEADERS = ["Идентификатор", "Фамилия", "Имя", "Отчество", "Должность", "Организация"]

_LAST = ["Иванов", "Петров", "Сидорова", "Козлов", "Смирнова", "Фёдоров", "Ёлкин", "Орлова"]
_FIRST = ["Пётр", "Анна", "Олег", "Мария", "Иван", "Елена", "Сергей", "Ольга"]


def person(i: int) -> list[Any]:
    """Строка участника №i (идентификатор `P-<i>`), столбцы как в HEADERS."""
    return [
        f"P-{i}",
        f"{_LAST[i % len(_LAST)]}{i}",
        _FIRST[i % len(_FIRST)],
        "Сергеевич",
        "Инженер",
        f"ООО Ромашка {i % 10}",
    ]


def people(n: int, start: int = 1) -> list[list[Any]]:
    return [person(i) for i in range(start, start + n)]


def xlsx_bytes(
    rows: Sequence[Sequence[Any]],
    *,
    headers: Sequence[Any] | None = None,
    sheet_title: str = "Участники",
    hidden_first: bool = False,
    text_columns: Sequence[int] = (),
) -> bytes:
    """Книга; `headers=None` — HEADERS; `text_columns` — столбцы (с 0) в текстовом формате."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = sheet_title
    ws.append(list(HEADERS if headers is None else headers))
    for row in rows:
        ws.append(list(row))
    for col in text_columns:
        for r in range(2, len(rows) + 2):
            ws.cell(row=r, column=col + 1).number_format = "@"
    if hidden_first:
        visible = wb.create_sheet("Видимый")
        visible.append(list(HEADERS if headers is None else headers))
        for row in rows:
            visible.append(list(row))
        ws.sheet_state = "hidden"
        wb.active = 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def csv_bytes(
    rows: Sequence[Sequence[Any]],
    *,
    headers: Sequence[Any] | None = None,
    encoding: str = "utf-8-sig",
    delimiter: str = ";",
    sep_line: bool = False,
    line_terminator: str = "\r\n",
) -> bytes:
    buf = io.StringIO(newline="")
    if sep_line:
        buf.write(f"sep={delimiter}{line_terminator}")
    writer = csv.writer(buf, delimiter=delimiter, lineterminator=line_terminator)
    writer.writerow(HEADERS if headers is None else headers)
    writer.writerows(rows)
    return buf.getvalue().encode(encoding)


def docx_like_bytes() -> bytes:
    """Zip с содержимым как у .docx (для проверки расширения и разбора чужого архива)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def rewrite_zip(data: bytes, replacements: dict[str, bytes]) -> bytes:
    """Копия xlsx, где указанные части заменены (для файлов с вредным XML)."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            dst.writestr(info.filename, replacements.get(info.filename, src.read(info)))
    return out.getvalue()


# ------------------------------------------------------------------ помощники для API-тестов


async def make_conference(db: AsyncSession, title: str = "Конференция") -> int:
    conf = Conference(
        title=title, date_from=date(2026, 11, 20), date_to=date(2026, 11, 21), badge_type="single"
    )
    db.add(conf)
    await db.commit()
    return conf.id


async def upload(
    client: httpx.AsyncClient, conference_id: int, name: str, data: bytes
) -> httpx.Response:
    return await client.post(
        f"/api/admin/conferences/{conference_id}/imports",
        files={"file": (name, data, "application/octet-stream")},
    )


async def upload_report(
    client: httpx.AsyncClient, conference_id: int, name: str, data: bytes
) -> dict[str, Any]:
    """Загружает файл (ждёт 202) и возвращает отчёт."""
    r = await upload(client, conference_id, name, data)
    assert r.status_code == 202, r.text
    report = await client.get(
        f"/api/admin/conferences/{conference_id}/imports/{r.json()['batch_id']}"
    )
    assert report.status_code == 200, report.text
    body: dict[str, Any] = report.json()
    return body
