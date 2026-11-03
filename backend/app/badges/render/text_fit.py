"""Длинные значения в рамке элемента (PR-03).

Порядок: перенос по словам (и после дефиса) → не больше `max_lines` строк → уменьшение
кегля шагом 0.5 pt до `min_font_size`. Если не помещается и так, слова рвутся по символам,
лишние строки отбрасываются, последняя заканчивается «…», а результат помечается `overflow`
(такие участники попадают в список при сохранении шаблона, B2-09).
"""

import re
from dataclasses import dataclass

from PIL import ImageFont

from app.badges.render.fonts import font

LINE_SPACING = 1.12
PT_STEP = 0.5
ELLIPSIS = "…"

# Токен: (текст, приклеен к предыдущему без пробела) — часть слова после дефиса
Token = tuple[str, bool]


@dataclass(frozen=True)
class FittedText:
    lines: list[str]
    font: ImageFont.FreeTypeFont
    pt: float
    line_height: int
    overflow: bool


def tokens(text: str) -> list[Token]:
    """Слова, разбитые после дефисов: «Петров-Водкин» можно перенести после дефиса."""
    result: list[Token] = []
    for word in text.split():
        for i, part in enumerate(re.findall(r"[^-]+-?|-", word)):
            result.append((part, i > 0))
    return result


def _split_chars(text: str, f: ImageFont.FreeTypeFont, width: int) -> list[str]:
    pieces, buf = [], ""
    for ch in text:
        if buf and f.getlength(buf + ch) > width:
            pieces.append(buf)
            buf = ""
        buf += ch
    pieces.append(buf)
    return pieces


def wrap(
    toks: list[Token], f: ImageFont.FreeTypeFont, width: int, *, char_break: bool
) -> list[str] | None:
    """Строки не шире `width`. Слово шире строки: None или (char_break) разрыв по символам."""
    lines: list[str] = []
    cur = ""
    for text, glued in toks:
        pieces = [text]
        if f.getlength(text) > width:
            if not char_break:
                return None
            pieces = _split_chars(text, f, width)
        for k, piece in enumerate(pieces):
            if k > 0:  # продолжение слова, разорванного по символам
                lines.append(cur)
                cur = piece
                continue
            sep = "" if (glued or not cur) else " "
            if cur and f.getlength(cur + sep + piece) > width:
                lines.append(cur)
                cur = piece
            else:
                cur += sep + piece
    if cur:
        lines.append(cur)
    return lines


def _line_height(f: ImageFont.FreeTypeFont) -> int:
    return max(1, round(f.size * LINE_SPACING))


def _fits(lines: list[str] | None, lh: int, box_h: int, max_lines: int) -> bool:
    return lines is not None and len(lines) <= max_lines and len(lines) * lh <= box_h


def fit_text(
    text: str,
    box_w: int,
    box_h: int,
    *,
    font_size: float,
    min_font_size: float,
    max_lines: int,
    bold: bool,
    dpi: int,
) -> FittedText:
    """Наибольший кегль от `font_size` до `min_font_size`, при котором текст влезает в рамку."""
    toks = tokens(text)
    pt = font_size
    while pt >= min_font_size - 1e-6:
        f = font(pt, bold=bold, dpi=dpi)
        lh = _line_height(f)
        lines = wrap(toks, f, box_w, char_break=False)
        if lines is not None and _fits(lines, lh, box_h, max_lines):
            return FittedText(lines, f, pt, lh, overflow=False)
        pt -= PT_STEP

    f = font(min_font_size, bold=bold, dpi=dpi)
    lh = _line_height(f)
    lines = wrap(toks, f, box_w, char_break=True) or [""]
    allowed = max(1, min(max_lines, box_h // lh))
    if _fits(lines, lh, box_h, max_lines):
        # Влезло только с разрывом слова по символам: печатаем целиком, но сообщаем
        return FittedText(lines, f, min_font_size, lh, overflow=True)
    lines = lines[:allowed]
    last = lines[-1]
    while last and f.getlength(last + ELLIPSIS) > box_w:
        last = last[:-1]
    lines[-1] = last + ELLIPSIS
    return FittedText(lines, f, min_font_size, lh, overflow=True)
