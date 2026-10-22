"""Разбор файлов участников без БД (B1-05): заголовки, ячейки, CSV и xlsx, защита от «бомб»."""

from datetime import date, datetime, time
from typing import Any

import pytest

from app.imports import readers
from app.imports.columns import (
    FIELDS,
    match_header,
    normalize_header,
    slugify,
    template_header,
    unique_slug,
)
from app.imports.readers import ImportFileError, decode_csv, detect_delimiter, read_table
from app.imports.source import CellError, TableSource, cell_text
from tests.import_files import (
    HEADERS,
    csv_bytes,
    docx_like_bytes,
    people,
    rewrite_zip,
    xlsx_bytes,
)

MAX_ROWS = 5000


def rows_of(name: str, data: bytes) -> list[tuple[int, list[Any]]]:
    return list(read_table(name, data, MAX_ROWS).rows)


# --------------------------------------------------------------------------- заголовки


@pytest.mark.parametrize(
    ("header", "key"),
    [
        ("ID", "external_id"),
        ("id*", "external_id"),
        ("Идентификатор", "external_id"),
        ("  ИДЕНТИФИКАТОР участника ", "external_id"),
        ("Номер участника", "external_id"),
        ("Фамилия", "last_name"),
        ("ФАМИЛИЯ*", "last_name"),
        ("Имя", "first_name"),
        ("Отчество", "middle_name"),
        ("Должность", "position"),
        ("Организация", "organization"),
        ("Компания", "organization"),
        ("Фамилия (EN)", "last_name_en"),
        ("фамилия en", "last_name_en"),
        ("Last name", "last_name_en"),
        ("LAST_NAME", "last_name_en"),
        ("First name", "first_name_en"),
        ("Position (EN)", "position_en"),
        ("Organization", "organization_en"),
        ("Должность (англ.)", "position_en"),
        ("Фото", "photo_url"),
        ("Ссылка на фото", "photo_url"),
        ("Photo URL", "photo_url"),
        ("Секция", None),
        ("Тип участия", None),
        ("", None),
    ],
)
def test_header_synonyms(header: str, key: str | None) -> None:
    assert match_header(header) == key


def test_header_normalization_ignores_case_star_yo_and_spaces() -> None:
    assert normalize_header(" Фёдор  Номер* ") == normalize_header("федорномер")
    assert normalize_header("Ё") == normalize_header("е")


def test_every_template_header_is_recognised_by_the_parser() -> None:
    for spec in FIELDS:
        assert match_header(template_header(spec)) == spec.key
    assert [template_header(f).endswith("*") for f in FIELDS[:3]] == [True] * 3
    assert not any(template_header(f).endswith("*") for f in FIELDS[3:])


def test_slugify() -> None:
    assert slugify("Секция") == "sektsiya"
    assert slugify("Тип участия №2") == "tip_uchastiya_2"
    assert slugify("Hall A / Зал") == "hall_a_zal"
    assert slugify("№") == "field"
    assert unique_slug("Секция", {"sektsiya"}) == "sektsiya_2"
    assert unique_slug("Секция", {"sektsiya", "sektsiya_2"}) == "sektsiya_3"


# --------------------------------------------------------------------------- ячейки


def test_cell_text_numbers_become_strings() -> None:
    assert cell_text(123.0) == "123"
    assert cell_text(123) == "123"
    assert cell_text(1.5) == "1.5"
    assert cell_text(79161234567.0) == "79161234567"
    assert cell_text(None) == ""
    assert cell_text(True) == "TRUE"


def test_cell_text_trims_all_kinds_of_edge_spaces() -> None:
    assert cell_text("  Иванов \t") == "Иванов"
    assert cell_text("\xa0Иванов\xa0") == "Иванов"
    assert cell_text("​Иванов﻿") == "Иванов"
    assert cell_text("Иван  Иванов") == "Иван  Иванов"  # внутри не трогаем


def test_cell_text_dates() -> None:
    assert cell_text(date(2026, 11, 20)) == "20.11.2026"
    assert cell_text(datetime(2026, 11, 20, 9, 5)) == "20.11.2026 09:05"
    assert cell_text(datetime(2026, 11, 20)) == "20.11.2026"
    assert cell_text(time(9, 5)) == "09:05"


def test_id_from_numeric_cell() -> None:
    assert cell_text(123.0, is_id=True) == "123"
    assert cell_text(123456789012345, is_id=True) == "123456789012345"  # 15 цифр ещё точны
    for bad in (1.2345e15, 12345678901234567890, 1.2e20):
        with pytest.raises(CellError):
            cell_text(bad, is_id=True)
    with pytest.raises(CellError):
        cell_text(datetime(2026, 1, 1), is_id=True)


def test_id_from_text_cell() -> None:
    assert cell_text("00123", is_id=True) == "00123"  # ведущие нули сохраняются
    assert cell_text(" B24-1001 ", is_id=True) == "B24-1001"
    assert cell_text("123.0", is_id=True) == "123.0"  # текстовая ячейка xlsx не трогается
    assert cell_text("123.0", is_id=True, text_cells=True) == "123"  # в CSV «123.0» -> «123»
    assert cell_text("00123.0", is_id=True, text_cells=True) == "00123"
    for exp in ("1.2E+15", "1,2e15", "5E10", "1.23E+20"):
        with pytest.raises(CellError, match="экспоненциальной"):
            cell_text(exp, is_id=True)
    # в обычных полях экспонента — просто текст
    assert cell_text("1.2E+15") == "1.2E+15"


# --------------------------------------------------------------------------- файл: тип


def test_unsupported_extensions() -> None:
    for name in ("p.docx", "p.xls", "p.txt", "p", "p.xlsx.exe", "p.pdf"):
        with pytest.raises(ImportFileError, match="Поддерживаются файлы .xlsx и .csv"):
            read_table(name, docx_like_bytes(), MAX_ROWS)


def test_extension_must_match_signature() -> None:
    with pytest.raises(ImportFileError):
        read_table("p.xlsx", csv_bytes(people(1)), MAX_ROWS)
    with pytest.raises(ImportFileError):
        read_table("p.csv", xlsx_bytes(people(1)), MAX_ROWS)
    with pytest.raises(ImportFileError, match="пустой"):
        read_table("p.csv", b"  \r\n ", MAX_ROWS)


def test_docx_renamed_to_xlsx_is_rejected_cleanly() -> None:
    with pytest.raises(ImportFileError, match=r"\.xlsx"):
        read_table("p.xlsx", docx_like_bytes(), MAX_ROWS)
    with pytest.raises(ImportFileError):
        read_table("p.xlsx", b"PK\x03\x04garbage", MAX_ROWS)


# --------------------------------------------------------------------------- CSV


def test_decode_csv_encodings() -> None:
    text = "Фамилия;Имя\r\nЁлкин;Пётр\r\n"
    assert decode_csv(text.encode("utf-8-sig")) == "﻿"[:0] + text
    assert decode_csv(text.encode("utf-8")) == text
    assert decode_csv(text.encode("cp1251")) == text
    assert decode_csv(text.encode("utf-16")) == text
    with pytest.raises(ImportFileError):
        decode_csv(b"\xef\xbb\xbf\xff\xfe\xfa")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-8", "cp1251"])
@pytest.mark.parametrize("delimiter", [";", ",", "\t", "|"])
def test_csv_encoding_and_delimiter_matrix(encoding: str, delimiter: str) -> None:
    data = csv_bytes(people(3), encoding=encoding, delimiter=delimiter)
    table = read_table("p.csv", data, MAX_ROWS)
    assert table.headers == HEADERS
    rows = list(table.rows)
    assert [n for n, _ in rows] == [2, 3, 4]
    assert rows[0][1][1:3] == ["Петров1", "Анна"]


def test_delimiter_prefers_consistent_columns() -> None:
    # запятые внутри текста не должны сбивать разделитель «;»
    text = "Фамилия;Имя;Должность\nИванов;Пётр;Инженер, ведущий\nПетров;Олег;Директор\n"
    assert detect_delimiter(text) == ";"
    assert detect_delimiter("a,b,c\n1,2,3\n") == ","
    assert detect_delimiter("a\tb\n1\t2\n") == "\t"
    assert detect_delimiter("одна колонка\nещё\n") == ";"


def test_csv_sep_line_is_skipped_and_not_counted() -> None:
    data = csv_bytes(people(2), sep_line=True, delimiter="|")
    table = read_table("p.csv", data, MAX_ROWS)
    assert table.headers == HEADERS
    assert [n for n, _ in table.rows] == [2, 3]


def test_csv_quoted_values_and_multiline() -> None:
    rows = [["P-1", 'Иванов "Ваня"', "Пётр", "", "Главный;\nинженер", "ООО"], *people(1, 2)]
    got = rows_of("p.csv", csv_bytes(rows))
    assert got[0][1][1] == 'Иванов "Ваня"'
    assert got[0][1][4] == "Главный;\nинженер"
    assert got[1][0] == 3  # многострочная запись — одна строка


def test_csv_with_only_blank_lines_after_header_and_lf_endings() -> None:
    data = csv_bytes(people(2), line_terminator="\n") + b"\n\n;;;;;\n"
    got = rows_of("p.csv", data)
    assert [n for n, _ in got] == [
        2,
        3,
    ]  # пустые строки в конце отброшены


def test_csv_blank_line_in_the_middle_keeps_numbering() -> None:
    text = "Идентификатор;Фамилия;Имя\r\nP-1;Иванов;Пётр\r\n\r\nP-3;Сидоров;Олег\r\n"
    got = rows_of("p.csv", text.encode("utf-8"))
    assert [n for n, _ in got] == [2, 4]


def test_csv_limits() -> None:
    with pytest.raises(ImportFileError, match="строк"):
        read_table("p.csv", csv_bytes(people(11)), 10)
    wide = [f"c{i}" for i in range(201)]
    with pytest.raises(ImportFileError, match="столбцов"):
        read_table("p.csv", csv_bytes([], headers=wide), MAX_ROWS)
    ok = read_table("p.csv", csv_bytes(people(10)), 10)  # ровно лимит
    assert len(list(ok.rows)) == 10


def test_csv_without_header_row_is_rejected() -> None:
    with pytest.raises(ImportFileError):
        read_table("p.csv", ";;;\r\nP-1;Иванов;Пётр\r\n".encode(), MAX_ROWS)


# --------------------------------------------------------------------------- xlsx


def test_xlsx_basic_and_numbers_keep_types() -> None:
    rows = [[1001, "Иванов", "Пётр", None, None, None], [1002.0, "Петров", "Олег", "", "", ""]]
    got = rows_of("p.xlsx", xlsx_bytes(rows))
    assert [n for n, _ in got] == [2, 3]
    assert got[0][1][0] == 1001
    assert got[0][1][1] == "Иванов"


def test_xlsx_reads_first_visible_sheet() -> None:
    data = xlsx_bytes(people(2), hidden_first=True)
    assert [n for n, _ in rows_of("p.xlsx", data)] == [2, 3]


def test_xlsx_blank_rows_skipped_and_numbering_kept() -> None:
    rows = [*people(1), [None] * 6, *people(1, 3), [None] * 6, [" ", "", None, None, None, None]]
    got = rows_of("p.xlsx", xlsx_bytes(rows))
    assert [n for n, _ in got] == [2, 4]


def test_xlsx_limits() -> None:
    with pytest.raises(ImportFileError, match="строк"):
        read_table("p.xlsx", xlsx_bytes(people(11)), 10)
    with pytest.raises(ImportFileError, match="столбцов"):
        read_table("p.xlsx", xlsx_bytes([], headers=[f"c{i}" for i in range(201)]), MAX_ROWS)


def test_xlsx_zip_bomb_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    data = xlsx_bytes(people(5))
    monkeypatch.setattr(readers, "MAX_UNPACKED_BYTES", 1000)
    with pytest.raises(ImportFileError, match="распакованном"):
        read_table("p.xlsx", data, MAX_ROWS)


def test_xlsx_entity_expansion_is_rejected() -> None:
    import openpyxl

    assert openpyxl.DEFUSEDXML  # defusedxml установлен и подхвачен
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
        b'<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>'
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        b'<row r="1"><c r="A1" t="inlineStr"><is><t>&lol3;</t></is></c></row>'
        b"</sheetData></worksheet>"
    )
    data = rewrite_zip(xlsx_bytes(people(3)), {"xl/worksheets/sheet1.xml": bomb})
    with pytest.raises(ImportFileError):
        read_table("p.xlsx", data, MAX_ROWS)


def test_corrupted_xlsx_is_rejected() -> None:
    data = xlsx_bytes(people(3))
    with pytest.raises(ImportFileError):
        read_table("p.xlsx", data[: len(data) // 2], MAX_ROWS)
    broken = rewrite_zip(data, {"xl/worksheets/sheet1.xml": b"<not-closed"})
    with pytest.raises(ImportFileError):
        read_table("p.xlsx", broken, MAX_ROWS)


# --------------------------------------------------------------------------- таблица -> строки


def source_of(rows: list[list[Any]], headers: list[Any] | None = None) -> TableSource:
    return TableSource(
        read_table("p.xlsx", xlsx_bytes(rows, headers=headers), MAX_ROWS), text_cells=False
    )


def test_unknown_columns_become_extra_fields() -> None:
    src = source_of([[*person_row(), "A", "VIP"]], [*HEADERS, "Секция", "Тип участия"])
    assert src.extra_labels == ["Секция", "Тип участия"]
    (row,) = list(src.rows())
    assert row.extra == {"Секция": "A", "Тип участия": "VIP"}
    assert row.values["last_name"] == "Иванов"
    assert src.fields >= {"external_id", "last_name", "first_name"}
    assert "photo_url" not in src.fields


def person_row() -> list[Any]:
    return ["P-1", "Иванов", "Пётр", "", "", ""]


def test_missing_required_columns_reject_the_file() -> None:
    with pytest.raises(ImportFileError, match="Идентификатор, Имя") as e:
        source_of([["Иванов"]], ["Фамилия"])
    assert e.value.details["reason"] == "missing_columns"
    # английские заголовки означают поля *_en, обязательных русских столбцов в файле нет
    with pytest.raises(ImportFileError, match="Фамилия"):
        source_of([["P-1", "Ivanov", "Petr"]], ["ID", "Last name", "First name"])


def test_duplicate_standard_column_rejects_the_file() -> None:
    with pytest.raises(ImportFileError, match="указан дважды"):
        source_of([["P-1", "Иванов", "Пётр", "Петров"]], ["ID", "Фамилия", "Имя", "фамилия*"])


def test_duplicate_extra_headers_get_distinct_labels() -> None:
    src = source_of([[*person_row(), "A", "B"]], [*HEADERS, "Секция", "секция"])
    assert src.extra_labels == ["Секция", "секция (2)"]


def test_headerless_column_with_data_gives_warning() -> None:
    src = source_of([[*person_row(), "лишнее"]], [*HEADERS, None])
    rows = list(src.rows())
    assert len(rows) == 1
    assert src.warnings == ["Столбец 7 без заголовка не загружен"]


def test_rows_report_bad_ids_and_skip_blank_rows() -> None:
    rows = [
        ["1.2E+15", "Иванов", "Пётр", "", "", ""],
        [None, None, None, None, None, None],
        ["  ", " ", "", "", "", ""],
        [1234567890123456789, "Петров", "Олег", "", "", ""],
        ["P-5", "x" * 1001, "Олег", "", "", ""],
    ]
    out = list(source_of(rows).rows())
    assert [r.number for r in out] == [2, 5, 6]
    assert all(r.error for r in out)
    assert "экспоненциальной" in (out[0].error or "")
    assert "15 цифр" in (out[1].error or "")
    assert "1000" in (out[2].error or "")
