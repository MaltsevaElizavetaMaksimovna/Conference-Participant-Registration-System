"""Генерация команд языка TSPL для принтера Xprinter XP-360B."""

from __future__ import annotations

import io
import math
from typing import TYPE_CHECKING

from PIL import Image

if TYPE_CHECKING:
    from regsys_agent.api import Job

DPI = 203


def _to_mode_1(img: Image.Image, threshold: int = 128) -> Image.Image:
    """Привести изображение к режиму '1' без дизеринга по заданному порогу."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        alpha = img.convert("RGBA").split()[3]
        bg.paste(img, mask=alpha)
        gray = bg.convert("L")
    elif img.mode == "1" or img.mode != "L":
        gray = img.convert("L")
    else:
        gray = img

    bw = gray.point(lambda p: 255 if p >= threshold else 0, mode="L")
    return bw.convert("1", dither=Image.Dither.NONE)


def _shift_image(img: Image.Image, offset_x_mm: float, offset_y_mm: float, dpi: int) -> Image.Image:
    """Сдвинуть изображение по горизонтали и вертикали.

    Освободившееся место заполняется белым (1).
    Отрицательные значения смещают влево и вверх.
    """
    dx = round(offset_x_mm * dpi / 25.4)
    dy = round(offset_y_mm * dpi / 25.4)
    if dx == 0 and dy == 0:
        return img

    shifted = Image.new("1", img.size, 1)
    shifted.paste(img, (dx, dy))
    return shifted


def _pack_bitmap(img: Image.Image) -> tuple[bytes, int, int]:
    """Упаковать изображение в байты TSPL BITMAP.

    8 точек в байте, старший бит слева, белый = 1, чёрный = 0.
    Ширина дополняется белым до кратной 8.
    Возвращает (data, width_bytes, height_dots).
    """
    wb = math.ceil(img.width / 8)
    if img.width != wb * 8:
        canvas = Image.new("1", (wb * 8, img.height), 1)
        canvas.paste(img, (0, 0))
        img = canvas

    data = img.tobytes()
    return data, wb, img.height


def build_job(job: Job, dpi: int = DPI) -> bytes:
    """Сформировать полное TSPL-задание для принтера."""
    if not job.copies:
        return b""

    first = job.copies[0]
    header = (
        f"SIZE {first.width_mm:g} mm,{first.height_mm:g} mm\r\n"
        f"GAP {first.gap_mm:g} mm,0 mm\r\n"
        "DIRECTION 1\r\n"
        f"DENSITY {job.density}\r\n"
        f"SPEED {job.speed}\r\n"
    ).encode("ascii")

    pages = bytearray(header)
    for copy in job.copies:
        with Image.open(io.BytesIO(copy.png)) as raw_img:
            img_1 = _to_mode_1(raw_img)
        shifted = _shift_image(img_1, job.offset_x_mm, job.offset_y_mm, dpi)
        data, wb, h = _pack_bitmap(shifted)
        pages.extend(b"CLS\r\n")
        pages.extend(f"BITMAP 0,0,{wb},{h},0,".encode("ascii"))
        pages.extend(data)
        pages.extend(b"\r\nPRINT 1,1\r\n")

    return bytes(pages)
