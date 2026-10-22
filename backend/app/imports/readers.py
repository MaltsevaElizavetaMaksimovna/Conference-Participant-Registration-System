"""Чтение файла участников (.xlsx, .csv) в таблицу «заголовки + строки».

Защита (B1-05): лимит размера файла, тип по расширению и сигнатуре, лимиты строк, столбцов и
распакованного объёма xlsx, `defusedxml` (его openpyxl подхватывает сам, если пакет установлен).
Сами значения не приводятся к тексту здесь: это делает `source.py`, которому нужны типы ячеек.
"""

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePath
from typing import Any

from app.core.errors import AppError

UNSUPPORTED_MESSAGE = "Поддерживаются файлы .xlsx и .csv"
MAX_COLUMNS = 200
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
MAX_ZIP_ENTRIES = 1000
# После стольких пустых строк подряд xlsx считается законченным (Excel хранит «хвост» оформления)
MAX_EMPTY_TAIL = 1000
_DELIMITERS = (";", ",", "\t", "|")
_SEP_LINE = re.compile(r"^sep=(.)\s*$", re.IGNORECASE)
_SAMPLE_ROWS = 10


class ImportFileError(AppError):
    """Файл нельзя прочитать: ничего не загружено (422 `bad_file`)."""

    def __init__(self, message: str, reason: str = "unreadable") -> None:
        super().__init__("bad_file", message, 422, {"reason": reason})


def file_too_large(limit_mb: int) -> AppError:
    return AppError("file_too_large", f"Файл больше {limit_mb} МБ", 413, {"limit_mb": limit_mb})


@dataclass
class RawTable:
    """Заголовки (первая строка) и строки данных: (номер строки файла с 1, значения ячеек)."""

    headers: list[Any]
    rows: Iterator[tuple[int, list[Any]]]


def detect_kind(file_name: str, data: bytes) -> str:
    """`xlsx` или `csv` по расширению и сигнатуре; иначе ImportFileError."""
    ext = PurePath(file_name).suffix.lower()
    if ext not in (".xlsx", ".csv"):
        raise ImportFileError(UNSUPPORTED_MESSAGE, "unsupported_type")
    is_zip = data[:2] == b"PK"
    if ext == ".xlsx" and not is_zip:
        raise ImportFileError("Файл не похож на .xlsx: расширение не соответствует содержимому")
    if ext == ".csv" and is_zip:
        raise ImportFileError("Файл с расширением .csv оказался архивом. Сохраните его как CSV")
    if not data.strip():
        raise ImportFileError("Файл пустой")
    return ext[1:]


def read_table(file_name: str, data: bytes, max_rows: int) -> RawTable:
    """Читает файл целиком (в пределах лимитов). Строки данных — не более `max_rows`."""
    kind = detect_kind(file_name, data)
    table = _read_xlsx(data, max_rows) if kind == "xlsx" else _read_csv(data, max_rows)
    return table


# --------------------------------------------------------------------------- xlsx


def _check_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            infos = zf.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ImportFileError("Файл .xlsx содержит слишком много частей", "zip_bomb")
            if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
                raise ImportFileError("Файл .xlsx слишком велик в распакованном виде", "zip_bomb")
    except zipfile.BadZipFile as e:
        raise ImportFileError("Не удалось прочитать файл .xlsx: он повреждён") from e


def _read_xlsx(data: bytes, max_rows: int) -> RawTable:
    from openpyxl import load_workbook

    _check_zip(data)
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except ImportFileError:
        raise
    except Exception as e:  # openpyxl бросает разные исключения на битых файлах
        raise ImportFileError("Не удалось прочитать файл .xlsx. Проверьте, что это таблица") from e
    try:
        sheets = [ws for ws in wb.worksheets if ws.sheet_state == "visible"]
        if not sheets:
            raise ImportFileError("В файле нет видимых листов")
        try:
            raw = _collect_xlsx_rows(sheets[0], max_rows)
        except ImportFileError:
            raise
        except Exception as e:
            raise ImportFileError(
                "Не удалось прочитать файл .xlsx. Проверьте, что это таблица"
            ) from e
    finally:
        wb.close()
    return _table_from_rows(raw)


def _collect_xlsx_rows(ws: Any, max_rows: int) -> list[tuple[int, list[Any]]]:
    out: list[tuple[int, list[Any]]] = []
    non_empty = 0
    empty_streak = 0
    for number, row in enumerate(ws.iter_rows(values_only=True, max_col=MAX_COLUMNS + 1), 1):
        values = list(row)
        while values and values[-1] is None:
            values.pop()
        if len(values) > MAX_COLUMNS:
            raise ImportFileError(f"Слишком много столбцов (максимум {MAX_COLUMNS})", "too_wide")
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in values):
            empty_streak += 1
            if empty_streak > MAX_EMPTY_TAIL:
                break
            if number > 1:
                continue
        else:
            empty_streak = 0
            non_empty += 1
            if non_empty > max_rows + 1:
                raise ImportFileError(f"Слишком много строк (максимум {max_rows})", "too_long")
        out.append((number, values))
    return out


# --------------------------------------------------------------------------- csv


def decode_csv(data: bytes) -> str:
    """BOM (utf-8-sig, utf-16) -> строгий utf-8 -> cp1251."""
    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError as e:
            raise ImportFileError("Файл с меткой UTF-8 содержит недопустимые символы") from e
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as e:
            raise ImportFileError("Не удалось определить кодировку файла") from e
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1251")
    except UnicodeDecodeError as e:
        raise ImportFileError("Не удалось определить кодировку файла. Сохраните его в UTF-8") from e


def _sample_counts(text: str, delimiter: str) -> list[int]:
    counts: list[int] = []
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if not any(c.strip() for c in row):
                continue
            counts.append(len(row))
            if len(counts) >= _SAMPLE_ROWS:
                break
    except csv.Error:
        return []
    return counts


def detect_delimiter(text: str) -> str:
    """Разделитель из `; , \\t |`, дающий одинаковое число (>1) столбцов в первых строках."""
    best: tuple[int, str] | None = None
    for d in _DELIMITERS:
        counts = _sample_counts(text, d)
        if (
            counts
            and counts[0] > 1
            and len(set(counts)) == 1
            and (best is None or counts[0] > best[0])
        ):
            best = (counts[0], d)
    if best:
        return best[1]
    # Строки разной ширины: берём тот, что лучше режет заголовок
    scored = [(_sample_counts(text, d)[:1] or [0], d) for d in _DELIMITERS]
    top = max(scored, key=lambda s: s[0][0])
    return top[1] if top[0][0] > 1 else ";"


def _read_csv(data: bytes, max_rows: int) -> RawTable:
    text = decode_csv(data)
    delimiter: str | None = None
    first_line, _, rest = text.partition("\n")
    if m := _SEP_LINE.match(first_line.rstrip("\r")):
        delimiter, text = m.group(1), rest
    if delimiter is None:
        delimiter = detect_delimiter(text)
    rows: list[tuple[int, list[Any]]] = []
    non_empty = 0
    try:
        for number, record in enumerate(
            csv.reader(io.StringIO(text, newline=""), delimiter=delimiter), 1
        ):
            if len(record) > MAX_COLUMNS:
                raise ImportFileError(
                    f"Слишком много столбцов (максимум {MAX_COLUMNS})", "too_wide"
                )
            if all(not c.strip() for c in record):
                if number > 1:
                    continue
            else:
                non_empty += 1
                if non_empty > max_rows + 1:
                    raise ImportFileError(f"Слишком много строк (максимум {max_rows})", "too_long")
            rows.append((number, list(record)))
    except csv.Error as e:
        raise ImportFileError(f"Не удалось прочитать файл .csv: {e}") from e
    return _table_from_rows(rows)


def _table_from_rows(rows: list[tuple[int, list[Any]]]) -> RawTable:
    if not rows or rows[0][0] != 1:
        raise ImportFileError("В файле нет строки заголовков")
    headers = rows[0][1]
    if all(h is None or not str(h).strip() for h in headers):
        raise ImportFileError("Первая строка файла должна содержать заголовки столбцов")
    return RawTable(headers=headers, rows=iter(rows[1:]))
