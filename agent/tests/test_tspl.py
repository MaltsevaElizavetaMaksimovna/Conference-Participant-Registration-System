"""Тесты генерации команд TSPL для принтера XP-360B."""

from __future__ import annotations

import io

from PIL import Image

from regsys_agent.api import Copy, Job
from regsys_agent.tspl import DPI, build_job


def _make_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_tspl_bitmap_pattern() -> None:
    """Узор 16x4 точек: чёрный = 0, белый = 1, MSB слева, без инверсии."""
    img = Image.new("1", (16, 4), 1)
    # Строка 0: 8 чёрных точек, затем 8 белых
    for x in range(8):
        img.putpixel((x, 0), 0)
    # Строка 1: чередование чёрный / белый
    for x in range(16):
        img.putpixel((x, 1), 0 if x % 2 == 0 else 1)
    # Строка 2: вся белая (по умолчанию)
    # Строка 3: вся чёрная
    for x in range(16):
        img.putpixel((x, 3), 0)

    png_bytes = _make_png(img)
    copy = Copy(png=png_bytes, width_mm=58, height_mm=80, gap_mm=2)
    job = Job(job_id=1, copies=[copy], density=10, speed=3)

    raw_job = build_job(job)

    prefix = b"BITMAP 0,0,2,4,0,"
    assert prefix in raw_job
    idx = raw_job.index(prefix) + len(prefix)
    bitmap_data = raw_job[idx : idx + 8]

    # Строка 0: 00000000 (0x00), 11111111 (0xFF)
    # Строка 1: 01010101 (0x55), 01010101 (0x55)
    # Строка 2: 11111111 (0xFF), 11111111 (0xFF)
    # Строка 3: 00000000 (0x00), 00000000 (0x00)
    expected = bytes([0x00, 0xFF, 0x55, 0x55, 0xFF, 0xFF, 0x00, 0x00])
    assert bitmap_data == expected

    # Сразу после данных обязательно \r\n
    assert raw_job[idx + 8 : idx + 10] == b"\r\n"


def test_tspl_width_padding_13_dots() -> None:
    """Ширина 13 точек дополняется белыми битами (1) до кратной 8 (2 байта)."""
    # 13x4 все чёрные точки (0)
    img = Image.new("1", (13, 4), 0)
    png_bytes = _make_png(img)

    copy = Copy(png=png_bytes, width_mm=58, height_mm=80, gap_mm=2)
    job = Job(job_id=2, copies=[copy], density=10, speed=3)

    raw_job = build_job(job)

    prefix = b"BITMAP 0,0,2,4,0,"
    assert prefix in raw_job
    idx = raw_job.index(prefix) + len(prefix)
    bitmap_data = raw_job[idx : idx + 8]

    # Первый байт (точки 0..7): все 0 -> 0x00
    # Второй байт (точки 8..12 чёрные = 0, дополнение 13..15 белые = 1) -> 00000111 = 0x07
    expected = bytes([0x00, 0x07] * 4)
    assert bitmap_data == expected
    assert raw_job[idx + 8 : idx + 10] == b"\r\n"


def test_tspl_two_copies_single_header() -> None:
    """Две наклейки: заголовок один раз, затем две страницы с CLS и PRINT 1,1."""
    img1 = Image.new("1", (16, 4), 1)
    img2 = Image.new("1", (16, 4), 0)
    c1 = Copy(png=_make_png(img1), width_mm=58, height_mm=80, gap_mm=2)
    c2 = Copy(png=_make_png(img2), width_mm=58, height_mm=80, gap_mm=2)
    job = Job(job_id=3, copies=[c1, c2], density=10, speed=3)

    raw_job = build_job(job)

    assert raw_job.count(b"SIZE 58 mm,80 mm\r\n") == 1
    assert raw_job.count(b"GAP 2 mm,0 mm\r\n") == 1
    assert raw_job.count(b"DIRECTION 1\r\n") == 1
    assert raw_job.count(b"DENSITY 10\r\n") == 1
    assert raw_job.count(b"SPEED 3\r\n") == 1
    assert raw_job.count(b"CLS\r\n") == 2
    assert raw_job.count(b"PRINT 1,1\r\n") == 2


def test_tspl_header_parameters_formatting() -> None:
    """Параметры калибровки и геометрии форматируются через :g в ASCII."""
    img = Image.new("1", (8, 2), 1)
    copy = Copy(png=_make_png(img), width_mm=58.5, height_mm=80.25, gap_mm=2.5)
    job = Job(job_id=4, copies=[copy], density=14, speed=5)

    raw_job = build_job(job)

    assert raw_job.startswith(
        b"SIZE 58.5 mm,80.25 mm\r\nGAP 2.5 mm,0 mm\r\nDIRECTION 1\r\nDENSITY 14\r\nSPEED 5\r\n"
    )


def test_tspl_shift_x_moves_column() -> None:
    """Сдвиг offset_x_mm=-1 при 203 dpi сдвигает столбец на 8 точек влево."""
    # 16x4, все белые (1), кроме столбца x=8 (чёрный = 0)
    img = Image.new("1", (16, 4), 1)
    for y in range(4):
        img.putpixel((8, y), 0)

    copy = Copy(png=_make_png(img), width_mm=58, height_mm=80, gap_mm=2)
    # При 203 dpi: round(-1 * 203 / 25.4) = -8 точек
    job = Job(job_id=5, copies=[copy], offset_x_mm=-1.0, offset_y_mm=0.0)

    raw_job = build_job(job, dpi=DPI)

    prefix = b"BITMAP 0,0,2,4,0,"
    idx = raw_job.index(prefix) + len(prefix)
    bitmap_data = raw_job[idx : idx + 8]

    # Столбец x=8 сместился в x=0.
    # В байте 0 точка 0 — это MSB (бит 7). Остальные точки белые (1) -> 01111111 = 0x7F
    # Во втором байте все точки стали белыми (1) -> 11111111 = 0xFF
    expected = bytes([0x7F, 0xFF] * 4)
    assert bitmap_data == expected


def test_tspl_bitmap_length_and_tail() -> None:
    """Длина данных BITMAP в точности равна width_bytes * height, и после них CRLF."""
    img = Image.new("RGB", (25, 10), (255, 255, 255))
    copy = Copy(png=_make_png(img), width_mm=58, height_mm=80, gap_mm=2)
    job = Job(job_id=6, copies=[copy])

    raw_job = build_job(job)

    prefix = b"BITMAP 0,0,4,10,0,"
    assert prefix in raw_job
    idx = raw_job.index(prefix) + len(prefix)
    expected_len = 4 * 10
    assert len(raw_job[idx : idx + expected_len]) == expected_len
    assert raw_job[idx + expected_len : idx + expected_len + 2] == b"\r\n"
