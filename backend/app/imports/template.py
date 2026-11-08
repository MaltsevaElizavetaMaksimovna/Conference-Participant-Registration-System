"""Шаблон файла для загрузки участников (IM-03): заголовки берутся из словаря `columns.py`."""

import io

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.imports.columns import FIELDS, template_header

SHEET_TITLE = "Участники"


def build_template() -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET_TITLE
    ws.append([template_header(f) for f in FIELDS])
    ws.append([f.example for f in FIELDS])

    head_fill = PatternFill("solid", start_color="DDEBF7")
    for col, spec in enumerate(FIELDS, 1):
        head = ws.cell(row=1, column=col)
        head.font = Font(bold=True)
        head.fill = head_fill
        head.alignment = Alignment(vertical="center", wrap_text=True)
        width = max(len(template_header(spec)), min(len(spec.example), 40)) + 4
        ws.column_dimensions[get_column_letter(col)].width = width
        # весь столбец в текстовом формате: ID вида 00123 или 1E5 Excel не «исправит»
        ws.column_dimensions[get_column_letter(col)].number_format = "@"
        ws.cell(row=2, column=col).number_format = "@"
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
