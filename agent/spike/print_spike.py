#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Спайк печати S-04: Xprinter XP-360B (USB, 203 dpi, TSPL).

Рисуем наклейку целиком картинкой (Pillow), переводим в 1 бит и шлём в принтер
командой TSPL BITMAP как RAW-задание через win32print.

Подкоманды: list, status, test, two, raw, bench.

Полярность бит. В TSPL (BITMAP) бит 0 = чёрная точка, 1 = пусто. В Pillow mode "1"
бит 1 = белый, 0 = чёрный, т.е. соглашения совпадают, и по умолчанию биты Pillow
уходят в принтер как есть. Если на реальном принтере всё напечаталось «негативом»
(чёрный квадрат вышел белым), запускайте с --invert. Какая полярность верна на
XP-360B, и выясняет этот спайк.

Модуль рендера (render_label, render_simple_label) и упаковки (to_tspl) потом
переедут в настоящий print-agent без изменений.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import math
import re
import sys
import time
import traceback
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "spike_out"
LOG_PATH = OUT_DIR / "spike_log.txt"

DPI = 203
DPMM = 8  # 203 dpi ~ 8 точек на мм (так же считает и мануал TSPL)
PX_PER_PT = DPI / 72.0

DEFAULT_FONT_REGULAR = r"C:\Windows\Fonts\arial.ttf"
DEFAULT_FONT_BOLD = r"C:\Windows\Fonts\arialbd.ttf"

TEST_NAME = "Константинопольский-Задунайский Александр Вячеславович"
TEST_ORG = ("ООО «Научно-производственное объединение радиоэлектронных систем и технологий "
            "имени академика Иванова», г. Новосибирск")
TEST_URL = "https://reg.example/p/AbCdEf123456"
SCALE_PT = (6, 7, 8, 9, 10, 12, 14)

# --------------------------------------------------------------------------
# Расшифровка статусов Windows (числа зашиты, чтобы работало и без pywin32)
# --------------------------------------------------------------------------
PRINTER_STATUS = {
    0x1: "PAUSED (пауза)", 0x2: "ERROR (ошибка)", 0x4: "PENDING_DELETION (удаляется)",
    0x8: "PAPER_JAM (замятие)", 0x10: "PAPER_OUT (нет бумаги/ленты)",
    0x20: "MANUAL_FEED", 0x40: "PAPER_PROBLEM (проблема с лентой)",
    0x80: "OFFLINE (не в сети)", 0x100: "IO_ACTIVE", 0x200: "BUSY (занят)",
    0x400: "PRINTING (печатает)", 0x800: "OUTPUT_BIN_FULL", 0x1000: "NOT_AVAILABLE (недоступен)",
    0x2000: "WAITING", 0x4000: "PROCESSING", 0x8000: "INITIALIZING",
    0x10000: "WARMING_UP", 0x20000: "TONER_LOW", 0x40000: "NO_TONER",
    0x80000: "PAGE_PUNT", 0x100000: "USER_INTERVENTION (нужно вмешательство)",
    0x200000: "OUT_OF_MEMORY", 0x400000: "DOOR_OPEN (открыта крышка)",
    0x800000: "SERVER_UNKNOWN", 0x1000000: "POWER_SAVE",
}
JOB_STATUS = {
    0x1: "PAUSED (на паузе)", 0x2: "ERROR (ошибка)", 0x4: "DELETING (удаляется)",
    0x8: "SPOOLING (спулится)", 0x10: "PRINTING (печатается)", 0x20: "OFFLINE (принтер не в сети)",
    0x40: "PAPEROUT (нет ленты)", 0x80: "PRINTED (напечатано)", 0x100: "DELETED (удалено)",
    0x200: "BLOCKED_DEVQ", 0x400: "USER_INTERVENTION (нужно вмешательство)",
    0x800: "RESTART", 0x1000: "COMPLETE (завершено)", 0x2000: "RETAINED",
    0x4000: "RENDERING_LOCALLY",
}
PRINTER_ATTRIBUTES = {
    0x1: "QUEUED", 0x2: "DIRECT", 0x4: "DEFAULT", 0x8: "SHARED", 0x10: "NETWORK",
    0x20: "HIDDEN", 0x40: "LOCAL", 0x80: "ENABLE_DEVQ", 0x100: "KEEPPRINTEDJOBS",
    0x200: "DO_COMPLETE_FIRST", 0x400: "WORK_OFFLINE (включён «Работать автономно»)",
    0x800: "ENABLE_BIDI",
}
ATTR_WORK_OFFLINE = 0x400


def decode_flags(value: int, table: dict, zero: str = "0 (норма/ничего)") -> str:
    if not value:
        return zero
    names = [n for bit, n in table.items() if value & bit]
    known = 0
    for bit in table:
        known |= bit
    if value & ~known:
        names.append(f"0x{value & ~known:X}?")
    return " | ".join(names) + f"  [0x{value:X}]"


# --------------------------------------------------------------------------
# Лог и вывод
# --------------------------------------------------------------------------
class Log:
    """Печатает в консоль и дописывает в spike_log.txt."""

    def __init__(self):
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self._f = open(LOG_PATH, "a", encoding="utf-8")
        self.t_start = time.perf_counter()

    def line(self, text: str = "") -> None:
        print(text)
        self._f.write(text + "\n")
        self._f.flush()

    def header(self, argv: list[str]) -> None:
        self._f.write("\n" + "=" * 78 + "\n")
        self.line(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] запуск: print_spike.py {' '.join(argv)}")
        self.line(f"python {sys.version.split()[0]}, {sys.platform}")

    def footer(self, ok: bool) -> None:
        self.line(f"-- итого: {'OK' if ok else 'ЕСТЬ ОШИБКИ'}, {time.perf_counter() - self.t_start:.1f} с")
        self._f.close()


# --------------------------------------------------------------------------
# Рендер наклейки
# --------------------------------------------------------------------------
@dataclass
class Fonts:
    regular: str = DEFAULT_FONT_REGULAR
    bold: str = DEFAULT_FONT_BOLD

    def check(self) -> None:
        for p in (self.regular, self.bold):
            if not Path(p).is_file():
                raise SystemExit(f"Файл шрифта не найден: {p}. Укажите --font-regular/--font-bold.")


@lru_cache(maxsize=256)
def _font(path: str, pt: float) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size=max(4, round(pt * PX_PER_PT)))


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Слова, разбитые после дефисов. (текст, без_пробела_перед)."""
    toks: list[tuple[str, bool]] = []
    for word in text.split():
        for i, part in enumerate(re.findall(r"[^-]+-?|-", word)):
            toks.append((part, i > 0))
    return toks


def _wrap(d: ImageDraw.ImageDraw, toks, font, width: int, charbreak: bool):
    lines: list[str] = []
    cur = ""
    for text, glue in toks:
        pieces = [text]
        if d.textlength(text, font=font) > width:
            if not charbreak:
                return None
            pieces, buf = [], ""
            for ch in text:
                if buf and d.textlength(buf + ch, font=font) > width:
                    pieces.append(buf)
                    buf = ""
                buf += ch
            pieces.append(buf)
        for k, piece in enumerate(pieces):
            sep = "" if (glue or k > 0 or not cur) else " "
            if k > 0:  # продолжение слова, разбитого по символам
                lines.append(cur)
                cur = piece
            elif cur and d.textlength(cur + sep + piece, font=font) > width:
                lines.append(cur)
                cur = piece
            else:
                cur += sep + piece
    if cur:
        lines.append(cur)
    return lines


def fit_text(d, text, font_path, box_w, box_h, max_pt, min_pt, step=0.5, spacing=1.12):
    """Подбирает наибольший кегль, при котором текст помещается в рамку.

    Переносит по словам и после дефисов. Если не помещается даже на min_pt, рвёт
    слова по символам и обрезает с «…» (overflow=True).
    Возвращает (lines, font, pt, line_height, overflow).
    """
    toks = _tokens(text)
    pt = max_pt
    while pt >= min_pt - 1e-6:
        font = _font(font_path, pt)
        lh = int(round(font.size * spacing))
        lines = _wrap(d, toks, font, box_w, charbreak=False)
        if lines is not None and len(lines) * lh <= box_h:
            return lines, font, pt, lh, False
        pt -= step
    font = _font(font_path, min_pt)
    lh = int(round(font.size * spacing))
    lines = _wrap(d, toks, font, box_w, charbreak=True) or [""]
    max_lines = max(1, box_h // lh)
    overflow = len(lines) > max_lines
    if overflow:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and d.textlength(last + "…", font=font) > box_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return lines, font, min_pt, lh, overflow


def _draw_lines(d, lines, font, x, y, lh):
    for ln in lines:
        d.text((x, y), ln, font=font, fill=0)
        y += lh
    return y


def _frame(d: ImageDraw.ImageDraw, W: int, H: int) -> None:
    """Рамка по самому краю + линейка (риски каждые 10 мм), чтобы видеть смещение и обрезку."""
    d.rectangle([0, 0, W - 1, H - 1], outline=0, width=2)
    for mm in range(10, int(W / DPMM), 10):
        x = mm * DPMM
        d.line([(x, 0), (x, 9)], fill=0, width=2)
        d.line([(x, H - 10), (x, H - 1)], fill=0, width=2)
    for mm in range(10, int(H / DPMM), 10):
        y = mm * DPMM
        d.line([(0, y), (9, y)], fill=0, width=2)
        d.line([(W - 10, y), (W - 1, y)], fill=0, width=2)


def _corner_marker(d, fonts: Fonts, x: int, y: int, text="ВЕРХ / ЛЕВО") -> int:
    d.polygon([(x, y), (x + 24, y), (x, y + 24)], fill=0)
    f = _font(fonts.bold, 7)
    d.text((x + 30, y + 2), text, font=f, fill=0)
    return y + 26


def draw_qr(d: ImageDraw.ImageDraw, url: str, x: int, y: int, target_px: int, ecc="m") -> int:
    """Рисует QR целыми пикселями (без сглаживания). Возвращает сторону в пикселях
    (включая тихую зону 2 модуля)."""
    import segno

    qr = segno.make(url, error=ecc, boost_error=False)
    matrix = qr.matrix
    n = len(matrix)
    quiet = 2
    mod = max(2, round(target_px / (n + 2 * quiet)))
    side = (n + 2 * quiet) * mod
    d.rectangle([x, y, x + side - 1, y + side - 1], fill=255)
    for r, row in enumerate(matrix):
        for c, v in enumerate(row):
            if v:
                px, py = x + (c + quiet) * mod, y + (r + quiet) * mod
                d.rectangle([px, py, px + mod - 1, py + mod - 1], fill=0)
    return side


def _binarize(img_l: Image.Image, threshold: int) -> Image.Image:
    """Серое -> 1 бит по порогу, без дизеринга. Тёмное (< порога) = чёрный."""
    bw = img_l.point(lambda p: 255 if p >= threshold else 0, mode="L")
    return bw.convert("1", dither=Image.Dither.NONE)


def render_label(w_mm: float, h_mm: float, *, name: str = TEST_NAME, org: str = TEST_ORG,
                 qr_url: str = TEST_URL, fonts: Fonts | None = None, caption: str = "",
                 test_elements: bool = True, threshold: int = 128,
                 info: dict | None = None) -> Image.Image:
    """Основная (тестовая) наклейка. Возвращает Image mode "1" размером в точках принтера.

    test_elements=True добавляет шкалу кеглей и чёрный квадрат 5x5 мм для проверки полярности.
    info (если передан) заполняется: размеры, подобранные кегли, переполнение.
    """
    fonts = fonts or Fonts()
    W, H = round(w_mm * DPMM), round(h_mm * DPMM)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    info = info if info is not None else {}
    info.update(width_dots=W, height_dots=H)
    m = 12

    _frame(d, W, H)
    y = _corner_marker(d, fonts, m, m)
    if caption:
        f = _font(fonts.regular, 6)
        d.text((W - m - d.textlength(caption, font=f), m + 3), caption, font=f, fill=0)

    # Размер QR ~20 мм; правая колонка = QR
    qr_target = min(20 * DPMM, int(W * 0.42), H - 2 * m - 40)
    # реальная сторона известна только после расчёта матрицы, поэтому считаем заранее
    import segno
    n = len(segno.make(qr_url, error="m", boost_error=False).matrix)
    mod = max(2, round(qr_target / (n + 4)))
    qr_side = (n + 4) * mod
    qr_x, qr_y = W - m - qr_side, H - m - qr_side
    col_w = qr_x - m - 8  # левая колонка

    # ФИО на всю ширину
    name_h = max(50, round(H * 0.18))
    lines, font, pt, lh, ov = fit_text(d, name, fonts.bold, W - 2 * m, name_h, 16, 8)
    _draw_lines(d, lines, font, m, y, lh)
    info.update(name_pt=pt, name_lines=len(lines), name_overflow=ov)
    y += name_h + 4

    # Организация (левая колонка)
    org_h = max(50, round(H * 0.30)) if test_elements else qr_y - y
    lines, font, pt, lh, ov = fit_text(d, org, fonts.regular, col_w, org_h, 8, 6)
    _draw_lines(d, lines, font, m, y, lh)
    info.update(org_pt=pt, org_lines=len(lines), org_overflow=ov, org_chars=len(org))
    y_after_org = y + len(lines) * lh + 4

    # QR
    side = draw_qr(d, qr_url, qr_x, qr_y, qr_target)
    info.update(qr_modules=n, qr_module_px=mod, qr_side_px=side, qr_side_mm=round(side / DPMM, 1))

    if test_elements:
        # чёрный квадрат 5x5 мм + подпись справа от QR-колонки сверху
        sq = 5 * DPMM
        sq_y = y
        d.rectangle([qr_x, sq_y, qr_x + sq - 1, sq_y + sq - 1], fill=0)
        f = _font(fonts.bold, 6)
        tx = qr_x + sq + 6
        d.text((tx, sq_y), "должен быть", font=f, fill=0)
        d.text((tx, sq_y + int(f.size * 1.15)), "ЧЁРНЫМ", font=f, fill=0)
        info.update(black_square=(qr_x, sq_y, sq, sq))

        # шкала кеглей в левой колонке
        sx, sy = m, y_after_org
        row_h = 0
        shown = []
        clipped = False
        for p in SCALE_PT:
            f = _font(fonts.regular, p)
            txt = f"Ая {p}pt"
            tw = int(d.textlength(txt, font=f))
            if sx + tw > m + col_w and sx > m:
                sx, sy, row_h = m, sy + row_h + 2, 0
            lhp = int(f.size * 1.1)
            if sy + lhp > H - 6:
                clipped = True
                break
            d.text((sx, sy), txt, font=f, fill=0)
            shown.append(p)
            row_h = max(row_h, lhp)
            sx += tw + 10
        info.update(scale_shown=shown, scale_clipped=clipped)
    return _binarize(img, threshold)


def render_simple_label(w_mm: float, h_mm: float, *, title: str, name: str, org: str,
                        qr_url: str, fonts: Fonts | None = None, caption: str = "",
                        threshold: int = 128) -> Image.Image:
    """Простая наклейка для проверок two/bench: заголовок, ФИО, организация, QR."""
    fonts = fonts or Fonts()
    W, H = round(w_mm * DPMM), round(h_mm * DPMM)
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    m = 12
    _frame(d, W, H)
    y = _corner_marker(d, fonts, m, m, text="ВЕРХ / ЛЕВО" if title else "TOP / LEFT")
    if caption:
        f = _font(fonts.regular, 6)
        d.text((W - m - d.textlength(caption, font=f), m + 3), caption, font=f, fill=0)
    d.text((m, y + 2), title, font=_font(fonts.bold, 16), fill=0)
    y += int(16 * PX_PER_PT * 1.2) + 4
    qr_target = min(20 * DPMM, int(W * 0.42), H - y - m - 20)
    import segno
    n = len(segno.make(qr_url, error="m", boost_error=False).matrix)
    mod = max(2, round(qr_target / (n + 4)))
    side = (n + 4) * mod
    draw_qr(d, qr_url, W - m - side, H - m - side, qr_target)
    lines, font, _, lh, _ = fit_text(d, name, fonts.bold, W - 2 * m, max(40, round(H * 0.18)), 14, 8)
    y = _draw_lines(d, lines, font, m, y, lh) + 4
    lines, font, _, lh, _ = fit_text(d, org, fonts.regular, W - 2 * m - side - 8,
                                     max(24, H - m - y), 9, 6)
    _draw_lines(d, lines, font, m, y, lh)
    return _binarize(img, threshold)


# --------------------------------------------------------------------------
# Упаковка в TSPL
# --------------------------------------------------------------------------
_INVERT_TABLE = bytes(range(255, -1, -1))


def _mm(v: float) -> str:
    return f"{v:g}"


# Калибровка принтера. Значения по умолчанию взяты из скрипта, который уже печатал
# на XP-360B пользователя (58x80, DENSITY 10, SPEED 3, сдвиг на 2 мм влево).
PRINT_SETTINGS = {"density": 10, "speed": 3, "shift_x_mm": -2.0}


def tspl_header(w_mm: float, h_mm: float, gap_mm: float) -> bytes:
    return (f"SIZE {_mm(w_mm)} mm,{_mm(h_mm)} mm\r\n"
            f"GAP {_mm(gap_mm)} mm,0 mm\r\n"
            "DIRECTION 1\r\n"
            f"DENSITY {int(PRINT_SETTINGS['density'])}\r\n"
            f"SPEED {int(PRINT_SETTINGS['speed'])}\r\n").encode("ascii")


def shift_x(img: Image.Image, shift_mm: float) -> Image.Image:
    """Сдвигает изображение по горизонтали (минус = влево), освободившееся место белое."""
    dx = round(shift_mm * DPMM)
    if dx == 0:
        return img
    src = img if img.mode == "1" else img.convert("1")
    out = Image.new("1", src.size, 1)
    out.paste(src, (dx, 0))
    return out


def pack_bitmap(img: Image.Image, invert: bool = False, threshold: int = 128):
    """Упаковывает картинку в байты BITMAP: 8 точек в байте, старший бит слева.

    По умолчанию чёрный пиксель -> бит 0, белый -> 1 (как в Pillow mode "1" и по мануалу
    TSPL). invert=True переворачивает. Ширина дополняется БЕЛЫМ до кратной 8.
    Возвращает (data, width_bytes, height_dots).
    """
    if img.mode != "1":
        img = _binarize(img.convert("L"), threshold)
    wb = math.ceil(img.width / 8)
    if img.width != wb * 8:
        canvas = Image.new("1", (wb * 8, img.height), 1)
        canvas.paste(img, (0, 0))
        img = canvas
    data = img.tobytes()  # 1 = белый, MSB первым
    if invert:
        data = data.translate(_INVERT_TABLE)
    assert len(data) == wb * img.height
    return data, wb, img.height


def tspl_page(img: Image.Image, copies: int = 1, invert: bool = False) -> bytes:
    """Одна страница задания: CLS, BITMAP, PRINT 1,copies."""
    img = shift_x(img, float(PRINT_SETTINGS["shift_x_mm"]))
    data, wb, h = pack_bitmap(img, invert)
    return (b"CLS\r\n" + f"BITMAP 0,0,{wb},{h},0,".encode("ascii") + data + b"\r\n"
            + f"PRINT 1,{int(copies)}\r\n".encode("ascii"))


def to_tspl(img: Image.Image, w_mm: float, h_mm: float, gap_mm: float,
            copies: int = 1, invert: bool = False) -> bytes:
    """Полное задание TSPL для одной картинки."""
    return tspl_header(w_mm, h_mm, gap_mm) + tspl_page(img, copies, invert)


def verify_tspl(job: bytes) -> list[str]:
    """Разбирает готовое задание и проверяет, что длина данных BITMAP = width_bytes*height."""
    out, pos = [], 0
    while True:
        i = job.find(b"BITMAP ", pos)
        if i < 0:
            break
        j = i + 7
        parts = []
        for _ in range(5):
            k = job.index(b",", j)
            parts.append(int(job[j:k]))
            j = k + 1
        x, y, wb, h, mode = parts
        expected = wb * h
        tail = job[j + expected:j + expected + 2]
        ok = tail == b"\r\n"
        out.append(f"BITMAP {x},{y},{wb},{h},{mode}: ожидаем {expected} байт данных, "
                   f"после них CRLF: {'да' if ok else 'НЕТ'} -> {'OK' if ok else 'ОШИБКА'}")
        pos = j + expected
    if not out:
        out.append("BITMAP в задании нет (это нормально для raw)")
    return out


# --------------------------------------------------------------------------
# Работа с принтером (pywin32, импорт ленивый)
# --------------------------------------------------------------------------
def _w32():
    try:
        import win32print  # type: ignore
    except ImportError as e:  # не Windows или не установлен pywin32
        raise SystemExit("Нужен pywin32 и Windows: pip install -r requirements.txt "
                         f"({e}). Для проверки без принтера используйте --dry-run.")
    return win32print


def enum_printers():
    w = _w32()
    flags = w.PRINTER_ENUM_LOCAL | w.PRINTER_ENUM_CONNECTIONS
    return w.EnumPrinters(flags, None, 2)


def open_printer(name: str):
    w = _w32()
    try:
        return w.OpenPrinter(name)
    except Exception as e:  # pywintypes.error
        names = []
        try:
            names = [p["pPrinterName"] for p in enum_printers()]
        except Exception:
            pass
        raise SystemExit(f"Не удалось открыть принтер «{name}»: {e}\n"
                         f"Доступные принтеры: {', '.join(names) or '(список пуст)'}\n"
                         "Имя нужно писать точно как в команде list.")


def send_raw(h, data: bytes, doc="spike"):
    """RAW-задание. Возвращает (job_id, мс на отправку). Время отсчитываем от вызова."""
    w = _w32()
    t0 = time.perf_counter()
    job = w.StartDocPrinter(h, 1, (doc, None, "RAW"))
    try:
        w.StartPagePrinter(h)
        w.WritePrinter(h, data)
        w.EndPagePrinter(h)
    finally:
        w.EndDocPrinter(h)
    return job, t0, (time.perf_counter() - t0) * 1000


def _snapshot(h, job_id):
    """(printer_status, attributes, cjobs, job_dict|None)."""
    w = _w32()
    info = w.GetPrinter(h, 2)
    job = None
    for j in w.EnumJobs(h, 0, -1, 1) or []:
        if j["JobId"] == job_id:
            job = j
            break
    return info["Status"], info["Attributes"], info.get("cJobs", 0), job


def watch(h, job_id, t0, log: Log, seconds=15.0, poll=0.5, stop_when_gone=False):
    """Опрашивает статус принтера и задания, печатает таймлайн изменений.

    Возвращает dict: gone_ms (когда задание пропало из очереди), seen (видели ли его
    в очереди), first_printing_ms, events (список строк).
    """
    res = {"gone_ms": None, "seen": False, "first_printing_ms": None}
    last = None
    k = 0
    log.line(f"   таймлайн (опрос каждые {poll} с, до {seconds:g} с; время от начала отправки):")
    while True:
        target = t0 + k * poll
        delay = target - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        ms = int((time.perf_counter() - t0) * 1000)
        try:
            pst, attrs, cj, job = _snapshot(h, job_id)
        except Exception as e:
            state = ("ОШИБКА опроса", str(e))
            if state != last:
                log.line(f"   {ms:6d} мс | ошибка опроса статуса: {e}")
                last = state
            pst = attrs = cj = job = None
        else:
            if job is not None:
                res["seen"] = True
                if res["first_printing_ms"] is None and job["Status"] & 0x10:
                    res["first_printing_ms"] = ms
                jtxt = (f"задание {job_id}: {decode_flags(job['Status'], JOB_STATUS, '0 (в очереди)')}, "
                        f"страниц напечатано {job.get('PagesPrinted', '?')}/{job.get('TotalPages', '?')}"
                        + (f", «{job['pStatus']}»" if job.get("pStatus") else ""))
            elif res["seen"]:
                jtxt = f"задание {job_id}: ИСЧЕЗЛО из очереди"
                if res["gone_ms"] is None:
                    res["gone_ms"] = ms
            else:
                jtxt = f"задание {job_id}: в очереди не видно (ещё/уже)"
                if res["gone_ms"] is None and ms > 0:
                    res["gone_ms"] = ms
            off = "ДА" if attrs & ATTR_WORK_OFFLINE else "нет"
            state = (pst, off, jtxt)
            if state != last:
                log.line(f"   {ms:6d} мс | принтер: {decode_flags(pst, PRINTER_STATUS, '0 (готов)')}; "
                         f"автономно: {off}; в очереди заданий: {cj} | {jtxt}")
                last = state
        k += 1
        if time.perf_counter() - t0 >= seconds:
            break
        if stop_when_gone and res["gone_ms"] is not None:
            break
    return res


def print_job(printer: str, data: bytes, label: str, log: Log, seconds=15.0, stop_when_gone=False):
    h = open_printer(printer)
    try:
        log.line(f">> отправка «{label}»: {len(data)} байт на «{printer}»")
        try:
            job_id, t0, send_ms = send_raw(h, data, doc=f"spike-{label}"[:60])
        except Exception as e:
            log.line(f"   ОШИБКА ОТПРАВКИ: {type(e).__name__}: {e}")
            return None
        log.line(f"   StartDoc..EndDoc заняли {send_ms:.0f} мс, номер задания в спулере: {job_id}")
        res = watch(h, job_id, t0, log, seconds=seconds, stop_when_gone=stop_when_gone)
        res["send_ms"] = send_ms
        res["job_id"] = job_id
        return res
    finally:
        _w32().ClosePrinter(h)


# --------------------------------------------------------------------------
# Команды
# --------------------------------------------------------------------------
def cmd_list(args, log: Log) -> bool:
    try:
        printers = enum_printers()
    except SystemExit as e:
        log.line(str(e))
        return False
    except Exception as e:
        log.line(f"Не удалось получить список принтеров: {e}")
        return False
    if not printers:
        log.line("Принтеров в системе нет.")
        return True
    log.line(f"Принтеров: {len(printers)}")
    for p in printers:
        off = "ДА" if p["Attributes"] & ATTR_WORK_OFFLINE else "нет"
        log.line(f"- «{p['pPrinterName']}»")
        log.line(f"    драйвер: {p['pDriverName']}")
        log.line(f"    порт: {p['pPortName']}")
        log.line(f"    статус: {decode_flags(p['Status'], PRINTER_STATUS, '0 (готов)')}")
        log.line(f"    автономно (WORK_OFFLINE): {off}; заданий в очереди: {p.get('cJobs', '?')}")
    return True


def cmd_status(args, log: Log) -> bool:
    w = _w32()
    h = open_printer(args.printer)
    try:
        info = w.GetPrinter(h, 2)
        log.line(f"Принтер «{info['pPrinterName']}»: драйвер {info['pDriverName']}, порт {info['pPortName']}")
        log.line(f"  статус: {decode_flags(info['Status'], PRINTER_STATUS, '0 (готов)')}")
        log.line(f"  атрибуты: {decode_flags(info['Attributes'], PRINTER_ATTRIBUTES)}")
        log.line(f"  WORK_OFFLINE: {'ДА' if info['Attributes'] & ATTR_WORK_OFFLINE else 'нет'}")
        jobs = w.EnumJobs(h, 0, -1, 1) or []
        log.line(f"  заданий в очереди: {len(jobs)}")
        for j in jobs:
            log.line(f"   - №{j['JobId']} «{j.get('pDocument')}» пользователь {j.get('pUserName')}: "
                     f"{decode_flags(j['Status'], JOB_STATUS, '0 (в очереди)')}; "
                     f"страниц {j.get('PagesPrinted', '?')}/{j.get('TotalPages', '?')}"
                     + (f"; «{j['pStatus']}»" if j.get("pStatus") else ""))
    finally:
        w.ClosePrinter(h)
    return True


def _need_printer(args):
    if not args.dry_run and not args.printer:
        raise SystemExit("Укажите --printer ИМЯ (имена: команда list) или используйте --dry-run.")


def _save_dry(name: str, img: Image.Image | None, job: bytes | None, log: Log) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if img is not None:
        p = OUT_DIR / f"{name}.png"
        img.save(p)
        log.line(f"   PNG: {p}  ({img.width}x{img.height} точек)")
    if job is not None:
        p = OUT_DIR / f"{name}.prn"
        p.write_bytes(job)
        log.line(f"   PRN: {p}  ({len(job)} байт)")
        for s in verify_tspl(job):
            log.line(f"   проверка: {s}")


def _fonts(args) -> Fonts:
    f = Fonts(args.font_regular, args.font_bold)
    f.check()
    return f


def _tag(args) -> str:
    return f"{args.w:g}x{args.h:g}" + ("_inv" if args.invert else "")


def cmd_test(args, log: Log) -> bool:
    _need_printer(args)
    fonts = _fonts(args)
    caption = f"{args.w:g}x{args.h:g} gap{args.gap:g} thr{args.threshold}" + (" INV" if args.invert else "")
    info: dict = {}
    img = render_label(args.w, args.h, fonts=fonts, caption=caption, threshold=args.threshold, info=info)
    log.line(f"Рендер: {info}")
    if info.get("name_overflow") or info.get("org_overflow") or info.get("scale_clipped"):
        log.line("   ВНИМАНИЕ: часть текста не поместилась (см. флаги overflow/clipped выше).")
    job = to_tspl(img, args.w, args.h, args.gap, args.copies, args.invert)
    if args.dry_run:
        log.line("[dry-run] печать не выполняется")
        _save_dry(f"test_{_tag(args)}", img, job, log)
        return True
    res = print_job(args.printer, job, "test", log, seconds=15.0)
    return res is not None


def _two_images(args, fonts):
    front = render_simple_label(args.w, args.h, title="ЛИЦО / RU", name="Иванов Иван Иванович",
                                org="ООО «Ромашка», г. Москва, отдел информационных систем",
                                qr_url=TEST_URL, fonts=fonts, caption="2: лицевая 1/2",
                                threshold=args.threshold)
    back = render_simple_label(args.w, args.h, title="BACK / EN", name="John A. Smith",
                               org="Daisy LLC, Moscow, Information Systems Dept.",
                               qr_url=TEST_URL, fonts=fonts, caption="2: back 2/2",
                               threshold=args.threshold)
    return front, back


def cmd_two(args, log: Log) -> bool:
    _need_printer(args)
    fonts = _fonts(args)
    front, back = _two_images(args, fonts)
    header = tspl_header(args.w, args.h, args.gap)
    job_two = header + tspl_page(front, 1, args.invert) + tspl_page(back, 1, args.invert)
    job_copies = to_tspl(front, args.w, args.h, args.gap, 2, args.invert)
    if args.dry_run:
        log.line("[dry-run] печать не выполняется")
        _save_dry(f"two_front_{_tag(args)}", front, None, log)
        _save_dry(f"two_back_{_tag(args)}", back, None, log)
        log.line("A) одно задание: две РАЗНЫЕ наклейки (CLS/BITMAP/PRINT 1 дважды)")
        _save_dry(f"two_job_{_tag(args)}", None, job_two, log)
        log.line("B) одна картинка, PRINT 1,2")
        _save_dry(f"two_copies2_{_tag(args)}", None, job_copies, log)
        return True
    log.line("A) одно задание: ДВЕ РАЗНЫЕ наклейки (сначала RU, потом EN)")
    r1 = print_job(args.printer, job_two, "two-different", log, seconds=15.0)
    if not args.no_pause:
        input("   Посмотрите, что вышло (должно быть 2 РАЗНЫЕ наклейки). Enter - дальше... ")
    log.line("B) одна картинка с PRINT 1,2 (ждём ДВЕ ОДИНАКОВЫЕ наклейки)")
    r2 = print_job(args.printer, job_copies, "print-1-2", log, seconds=15.0)
    return r1 is not None and r2 is not None


def cmd_raw(args, log: Log) -> bool:
    _need_printer(args)
    text = args.command.replace("\\n", "\r\n")
    data = text.encode("cp1251", errors="replace") + b"\r\n"
    log.line(f"RAW: {data!r}")
    if args.dry_run:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        p = OUT_DIR / "raw.prn"
        p.write_bytes(data)
        log.line(f"[dry-run] сохранено {p}")
        return True
    log.line("   Если команда ничего не печатает и ничего не вернёт - это нормально, смотрите на принтер.")
    res = print_job(args.printer, data, "raw", log, seconds=args.seconds)
    return res is not None


def cmd_bench(args, log: Log) -> bool:
    _need_printer(args)
    fonts = _fonts(args)
    now = _dt.datetime.now().strftime("%H:%M:%S")
    if args.dry_run:
        img = render_simple_label(args.w, args.h, title=f"BENCH 1/{args.n}", name="Иванов Иван",
                                  org=f"Замер скорости, {now}", qr_url=TEST_URL, fonts=fonts,
                                  caption=f"bench {now}", threshold=args.threshold)
        job = to_tspl(img, args.w, args.h, args.gap, 1, args.invert)
        log.line("[dry-run] печать не выполняется, сохраняю одну наклейку-образец")
        _save_dry(f"bench_{_tag(args)}", img, job, log)
        return True
    rows = []
    for i in range(1, args.n + 1):
        stamp = _dt.datetime.now().strftime("%H:%M:%S")
        img = render_simple_label(args.w, args.h, title=f"BENCH {i}/{args.n}", name="Иванов Иван",
                                  org=f"Замер скорости, {stamp}", qr_url=TEST_URL, fonts=fonts,
                                  caption=f"bench {stamp}", threshold=args.threshold)
        job = to_tspl(img, args.w, args.h, args.gap, 1, args.invert)
        log.line(f"--- наклейка {i}/{args.n}")
        res = print_job(args.printer, job, f"bench{i}", log, seconds=60.0, stop_when_gone=True)
        rows.append(res)
    log.line("ИТОГ bench (мс от начала отправки; «исчезло» = задание ушло из очереди):")
    gone = []
    for i, r in enumerate(rows, 1):
        if not r:
            log.line(f"  {i}: ошибка отправки")
            continue
        g = r["gone_ms"]
        fp = r["first_printing_ms"]
        log.line(f"  {i}: отправка {r['send_ms']:.0f} мс; статус PRINTING с {fp if fp is not None else '-'} мс; "
                 f"исчезло {g if g is not None else 'НЕ исчезло за 60 с'} мс")
        if g is not None:
            gone.append(g)
    if gone:
        log.line(f"  исчезновение из очереди: мин {min(gone)} / среднее {sum(gone) // len(gone)} / "
                 f"макс {max(gone)} мс")
    log.line("  Засеките секундомером на телефоне время от запуска до выезда наклейки и запишите в таблицу.")
    return all(rows)


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="print_spike.py",
                                description="Спайк печати на Xprinter XP-360B (TSPL BITMAP, RAW).")
    sub = p.add_subparsers(dest="cmd", required=True)

    def printer_arg(sp, required=False):
        sp.add_argument("--printer", required=required, help="имя принтера в Windows (см. команду list)")

    def label_args(sp):
        sp.add_argument("--w", type=float, default=58, help="ширина наклейки, мм (58)")
        sp.add_argument("--h", type=float, default=80, help="высота наклейки, мм (80)")
        sp.add_argument("--gap", type=float, default=2, help="зазор между наклейками, мм (2)")
        sp.add_argument("--copies", type=int, default=1, help="копий (PRINT 1,n)")
        sp.add_argument("--invert", action="store_true", help="перевернуть биты, если квадрат вышел белым")
        sp.add_argument("--threshold", type=int, default=128, help="порог чёрного 0..255 (128)")
        sp.add_argument("--dry-run", action="store_true",
                        help="не печатать, а сохранить PNG и .prn в spike_out/")
        sp.add_argument("--shift-x", type=float, default=-2.0,
                        help="сдвиг картинки по горизонтали, мм; минус = влево (-2)")
        sp.add_argument("--density", type=int, default=10, help="плотность печати 0..15 (10)")
        sp.add_argument("--speed", type=int, default=3, help="скорость 1..6 (3)")
        sp.add_argument("--font-regular", default=DEFAULT_FONT_REGULAR, help="TTF обычный (с кириллицей)")
        sp.add_argument("--font-bold", default=DEFAULT_FONT_BOLD, help="TTF жирный (с кириллицей)")

    sp = sub.add_parser("list", help="список принтеров Windows")
    sp.set_defaults(fn=cmd_list)

    sp = sub.add_parser("status", help="статус принтера и очередь заданий")
    printer_arg(sp, required=True)
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("test", help="основная тестовая наклейка + таймлайн статусов")
    printer_arg(sp)
    label_args(sp)
    sp.set_defaults(fn=cmd_test)

    sp = sub.add_parser("two", help="две разные наклейки одним заданием + PRINT 1,2")
    printer_arg(sp)
    label_args(sp)
    sp.add_argument("--no-pause", action="store_true", help="не ждать Enter между заданиями A и B")
    sp.set_defaults(fn=cmd_two)

    sp = sub.add_parser("raw", help="отправить произвольную строку TSPL (например GAPDETECT)")
    printer_arg(sp)
    sp.add_argument("command", help="команда TSPL; \\n внутри строки = перевод строки CRLF")
    sp.add_argument("--seconds", type=float, default=8.0, help="сколько секунд следить за очередью (8)")
    sp.add_argument("--dry-run", action="store_true")
    sp.set_defaults(fn=cmd_raw)

    sp = sub.add_parser("bench", help="N наклеек подряд отдельными заданиями, замер времени")
    printer_arg(sp)
    label_args(sp)
    sp.add_argument("--n", type=int, default=5, help="сколько наклеек (5)")
    sp.set_defaults(fn=cmd_bench)
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)
    for key, attr in (("density", "density"), ("speed", "speed"), ("shift_x_mm", "shift_x")):
        if hasattr(args, attr):
            PRINT_SETTINGS[key] = getattr(args, attr)
    log = Log()
    log.header(argv)
    ok = False
    try:
        ok = bool(args.fn(args, log))
    except SystemExit as e:
        if e.code not in (None, 0):
            log.line(str(e.code))
    except KeyboardInterrupt:
        log.line("Прервано пользователем.")
    except Exception:
        log.line("НЕОЖИДАННАЯ ОШИБКА:")
        log.line(traceback.format_exc())
    log.footer(ok)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
