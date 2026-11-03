"""Шрифты наклейки: DejaVu Sans (свободная лицензия, см. `app/badges/fonts/LICENSE`)."""

from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
REGULAR = FONTS_DIR / "DejaVuSans.ttf"
BOLD = FONTS_DIR / "DejaVuSans-Bold.ttf"

POINTS_PER_INCH = 72


def px_for_pt(pt: float, dpi: int) -> int:
    return max(4, round(pt * dpi / POINTS_PER_INCH))


@lru_cache(maxsize=256)
def _load(bold: bool, size_px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(BOLD if bold else REGULAR), size=size_px)


def font(pt: float, *, bold: bool, dpi: int) -> ImageFont.FreeTypeFont:
    """Шрифт кеглем `pt` для принтера `dpi`."""
    return _load(bold, px_for_pt(pt, dpi))
