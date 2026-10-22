"""Источник участников: нормализованные строки `(номер, значения)` независимо от происхождения.

`ParticipantSource` — общий интерфейс: файл (`TableSource`) сегодня, Битрикс24 (B1-16) позже.
Конвейер импорта (`service.py`) знает только про него.
"""

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Protocol

from app.imports.columns import FIELD_BY_KEY, REQUIRED_KEYS, match_header
from app.imports.readers import ImportFileError, RawTable

MAX_VALUE_LEN = 1000
MAX_ID_LEN = 200
MAX_LABEL_LEN = 200
# Целое число в числовой ячейке теряет точность после 15 цифр (двойная точность Excel)
MAX_SAFE_ID_DIGITS = 15

_EDGE = r"[\s​-‍⁠﻿]"
_EDGE_RE = re.compile(rf"^{_EDGE}+|{_EDGE}+$")
_EXPONENT = re.compile(r"^[+-]?\d+(?:[.,]\d+)?[eEеЕ][+-]?\d+$")
_INT_FLOAT = re.compile(r"^(\d+)[.,]0+$")


@dataclass(frozen=True, slots=True)
class SourceRow:
    number: int  # номер строки в источнике (для файла: как в Excel, заголовки — строка 1)
    values: dict[str, str] = field(default_factory=dict)  # поле участника -> значение ("" = пусто)
    extra: dict[str, str] = field(default_factory=dict)  # заголовок доп. столбца -> значение
    error: str | None = None  # строка непригодна (например, ID испорчен Excel)


class ParticipantSource(Protocol):
    """Откуда берутся участники."""

    @property
    def fields(self) -> frozenset[str]:
        """Какие стандартные поля источник отдаёт (по ним решается, что обновлять)."""

    @property
    def extra_labels(self) -> list[str]:
        """Заголовки дополнительных полей в порядке источника."""

    @property
    def warnings(self) -> list[str]:
        """Замечания источника; полны после полного обхода `rows()`."""

    def rows(self) -> Iterator[SourceRow]:
        """Непустые строки; полностью пустые источник пропускает молча."""


class CellError(Exception):
    """Значение ячейки нельзя использовать (текст — причина для отчёта)."""


def strip_value(s: str) -> str:
    """Пробелы по краям (в т.ч. неразрывные и нулевой ширины) удаляются."""
    return _EDGE_RE.sub("", s)


def cell_text(value: Any, *, is_id: bool = False, text_cells: bool = False) -> str:
    """Любая ячейка -> строка. `is_id`: строгие правила для идентификатора.

    `text_cells=True` (CSV): все значения уже текст, поэтому «123.0» у ID приводится к «123».
    """
    if value is None:
        return ""
    if isinstance(value, str):
        s = strip_value(value)
        if is_id and s:
            if _EXPONENT.match(s):
                raise CellError(
                    f"идентификатор «{s}» записан в экспоненциальной форме: Excel испортил "
                    "значение, задайте столбцу текстовый формат"
                )
            if text_cells and (m := _INT_FLOAT.match(s)):
                return m.group(1)
        return s
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        if is_id and len(str(abs(value))) > MAX_SAFE_ID_DIGITS:
            raise CellError(_long_id(str(value)))
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return ""
        if value.is_integer():
            if is_id and abs(value) >= 10**MAX_SAFE_ID_DIGITS:
                raise CellError(_long_id(f"{value:.0f}"))
            return str(int(value))
        text = repr(value)
        if "e" in text:
            if is_id:
                raise CellError(f"идентификатор «{text}» записан в экспоненциальной форме")
            return f"{value:f}".rstrip("0")
        return text
    if isinstance(value, datetime | date | time):
        if is_id:
            raise CellError("идентификатор записан как дата или время: задайте текстовый формат")
        if isinstance(value, datetime):
            has_time = value.time() != time(0)
            return value.strftime("%d.%m.%Y %H:%M" if has_time else "%d.%m.%Y")
        if isinstance(value, date):
            return value.strftime("%d.%m.%Y")
        return value.strftime("%H:%M")
    return strip_value(str(value))


def _long_id(digits: str) -> str:
    return (
        f"идентификатор из числовой ячейки длиннее {MAX_SAFE_ID_DIGITS} цифр ({digits}): "
        "Excel мог его исказить, задайте столбцу текстовый формат"
    )


@dataclass(frozen=True, slots=True)
class _Column:
    index: int
    key: str | None  # стандартное поле
    label: str | None  # заголовок доп. поля


class TableSource:
    """Табличный файл: первая строка — заголовки, неизвестные столбцы — доп. поля."""

    def __init__(self, table: RawTable, *, text_cells: bool) -> None:
        self._table = table
        self._text_cells = text_cells
        self._columns: list[_Column] = []
        self._warnings: list[str] = []
        self._headerless: set[int] = set()  # столбцы без заголовка, в которых есть данные
        self._mapped: set[int] = set()
        self._map_headers(table.headers)

    def _map_headers(self, headers: list[Any]) -> None:
        seen_keys: dict[str, str] = {}
        seen_labels: set[str] = set()
        for index, raw in enumerate(headers):
            header = strip_value(str(raw)) if raw is not None else ""
            if not header.strip("*"):
                continue
            self._mapped.add(index)
            if key := match_header(header):
                if key in seen_keys:
                    raise ImportFileError(
                        f"Столбец «{FIELD_BY_KEY[key].title}» указан дважды: "
                        f"«{seen_keys[key]}» и «{header}»",
                        "duplicate_column",
                    )
                seen_keys[key] = header
                self._columns.append(_Column(index, key, None))
                continue
            label = header[:MAX_LABEL_LEN]
            unique, n = label, 2
            while unique.casefold() in seen_labels:
                unique = f"{label} ({n})"
                n += 1
            seen_labels.add(unique.casefold())
            self._columns.append(_Column(index, None, unique))
        missing = [FIELD_BY_KEY[k].title for k in REQUIRED_KEYS if k not in seen_keys]
        if missing:
            raise ImportFileError(
                "В файле нет обязательных столбцов: " + ", ".join(missing),
                "missing_columns",
            )
        self._fields = frozenset(seen_keys)

    @property
    def fields(self) -> frozenset[str]:
        return self._fields

    @property
    def extra_labels(self) -> list[str]:
        return [c.label for c in self._columns if c.label]

    @property
    def warnings(self) -> list[str]:
        out = list(self._warnings)
        out.extend(f"Столбец {i + 1} без заголовка не загружен" for i in sorted(self._headerless))
        return out

    def rows(self) -> Iterator[SourceRow]:
        for number, cells in self._table.rows:
            row = self._convert(number, cells)
            if row is not None:
                yield row

    def _convert(self, number: int, cells: list[Any]) -> SourceRow | None:
        values: dict[str, str] = {}
        extra: dict[str, str] = {}
        error: str | None = None
        for col in self._columns:
            raw = cells[col.index] if col.index < len(cells) else None
            is_id = col.key == "external_id"
            try:
                text = cell_text(raw, is_id=is_id, text_cells=self._text_cells)
            except CellError as e:
                text, error = "", error or str(e)
            limit = MAX_ID_LEN if is_id else MAX_VALUE_LEN
            if len(text) > limit:
                title = FIELD_BY_KEY[col.key].title if col.key else col.label
                error = error or f"значение в столбце «{title}» длиннее {limit} символов"
                text = ""
            if col.key:
                values[col.key] = text
            elif col.label:
                extra[col.label] = text
        for index, raw in enumerate(cells):
            if index not in self._mapped and index not in self._headerless and cell_text(raw):
                self._headerless.add(index)
        # Ошибка в ячейке делает строку непустой, даже если остальное пусто
        if error is None and not any(values.values()) and not any(extra.values()):
            return None
        return SourceRow(number=number, values=values, extra=extra, error=error)
