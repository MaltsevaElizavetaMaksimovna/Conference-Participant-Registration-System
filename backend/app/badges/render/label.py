"""Наклейка по шаблону → 1-битное изображение 203 dpi (PR-01, PR-03, QR-01).

Проверено на XP-360B (S-04): картинка уходит без инверсии, бинаризация порогом 128 без
дизеринга, QR — целыми точками с тихой зоной 2 модуля. Каждый элемент рисуется в своей
рамке и обрезается по ней, поэтому ничего не выходит за рамку элемента и край наклейки.
"""

import io
from dataclasses import dataclass, field

import segno
from PIL import Image, ImageDraw

from app.badges.render.data import LabelData
from app.badges.render.text_fit import fit_text
from app.templates.schemas import TemplateElement, TemplateIn

DPI = 203
MM_PER_INCH = 25.4
THRESHOLD = 128
QR_QUIET_MODULES = 2
QR_ERROR = "m"
WHITE, BLACK = 255, 0


@dataclass(frozen=True)
class Overflow:
    """Значение не поместилось даже минимальным кеглем (PR-03)."""

    element: int
    field: str
    value: str


@dataclass(frozen=True)
class RenderResult:
    image: Image.Image  # режим "1", размер наклейки в точках
    overflow: list[Overflow] = field(default_factory=list)


def dots(mm: float, dpi: int = DPI) -> int:
    return round(mm * dpi / MM_PER_INCH)


def _element_text(el: TemplateElement, data: LabelData) -> str:
    if el.type == "text":
        return el.text or ""
    return data.value(el.field or "")


def _draw_text(box: Image.Image, el: TemplateElement, text: str, dpi: int) -> bool:
    """Текст в рамке; True — не поместился (overflow)."""
    fitted = fit_text(
        text,
        box.width,
        box.height,
        font_size=el.font_size,
        min_font_size=el.min_font_size,
        max_lines=el.max_lines,
        bold=el.bold,
        dpi=dpi,
    )
    d = ImageDraw.Draw(box)
    y = 0
    for line in fitted.lines:
        w = fitted.font.getlength(line)
        if el.align == "center":
            x = (box.width - w) / 2
        elif el.align == "right":
            x = box.width - w
        else:
            x = 0
        d.text((round(x), y), line, font=fitted.font, fill=BLACK)
        y += fitted.line_height
    return fitted.overflow


def _draw_qr(box: Image.Image, url: str) -> None:
    """QR по центру рамки, модуль — целое число точек (не больше рамки)."""
    matrix = segno.make(url, error=QR_ERROR, boost_error=False).matrix
    n = len(matrix) + 2 * QR_QUIET_MODULES
    module = min(box.width, box.height) // n
    if module < 1:
        return  # рамка меньше QR в точку на модуль: нечитаемо, не рисуем
    side = n * module
    x0, y0 = (box.width - side) // 2, (box.height - side) // 2
    d = ImageDraw.Draw(box)
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                px = x0 + (c + QR_QUIET_MODULES) * module
                py = y0 + (r + QR_QUIET_MODULES) * module
                d.rectangle([px, py, px + module - 1, py + module - 1], fill=BLACK)


def render_label(spec: TemplateIn, data: LabelData, dpi: int = DPI) -> RenderResult:
    """Нарисовать наклейку. Пустые поля не печатаются; QR без ссылки не рисуется."""
    canvas = Image.new("L", (dots(spec.width_mm, dpi), dots(spec.height_mm, dpi)), WHITE)
    overflow: list[Overflow] = []
    for i, el in enumerate(spec.elements):
        x, y = dots(el.x_mm, dpi), dots(el.y_mm, dpi)
        w = min(dots(el.w_mm, dpi), canvas.width - x)
        h = min(dots(el.h_mm, dpi), canvas.height - y)
        if w <= 0 or h <= 0:
            continue
        box = Image.new("L", (w, h), WHITE)
        if el.type == "qr":
            if data.profile_url:
                _draw_qr(box, data.profile_url)
        else:
            text = _element_text(el, data)
            if text and _draw_text(box, el, text, dpi):
                overflow.append(Overflow(i, el.field or "text", text))
        canvas.paste(box, (x, y))
    bw = canvas.point(lambda p: WHITE if p >= THRESHOLD else BLACK, mode="L")
    return RenderResult(bw.convert("1", dither=Image.Dither.NONE), overflow)


def to_png(image: Image.Image, dpi: int = DPI) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", dpi=(dpi, dpi))
    return buf.getvalue()
