"""Проверка и пересохранение фото участника в JPEG (B1-06, IM-01, QR-02)."""

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS: frozenset[str] = frozenset({"JPEG", "PNG", "WEBP"})


class PhotoImageError(Exception):
    """Файл не годится как фото. `reason` — машинная причина."""

    reason: str

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def normalize_photo(
    data: bytes,
    *,
    max_pixels: int,
    max_side_px: int,
    quality: int,
) -> bytes:
    """Проверить картинку и пересохранить в JPEG.

    RGB, без метаданных, длинная сторона ≤ max_side_px.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        try:
            try:
                img: Image.Image = Image.open(io.BytesIO(data))
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise PhotoImageError("too_many_pixels") from e
            except (UnidentifiedImageError, OSError, ValueError) as e:
                raise PhotoImageError("not_image") from e

            if img.format not in ALLOWED_FORMATS:
                raise PhotoImageError("unsupported_format")

            # размер известен из заголовка: проверяем до декодирования пикселей
            width, height = img.size
            if width * height > max_pixels:
                raise PhotoImageError("too_many_pixels")

            try:
                img.verify()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise PhotoImageError("too_many_pixels") from e
            except Exception as e:
                raise PhotoImageError("broken") from e

            try:
                # verify() портит объект: открываем заново
                img = Image.open(io.BytesIO(data))
                img.load()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise PhotoImageError("too_many_pixels") from e
            except Exception as e:
                raise PhotoImageError("broken") from e

            try:
                img = ImageOps.exif_transpose(img)
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise PhotoImageError("too_many_pixels") from e
            except Exception as e:
                raise PhotoImageError("broken") from e

            if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                rgba = img.convert("RGBA")
                background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                img = Image.alpha_composite(background, rgba).convert("RGB")
            else:
                img = img.convert("RGB")

            img.thumbnail((max_side_px, max_side_px), Image.Resampling.LANCZOS)

            # новая картинка без info: EXIF (в т.ч. GPS) и ICC не переносятся
            clean_img = Image.new("RGB", img.size)
            clean_img.paste(img)

            out = io.BytesIO()
            clean_img.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()

        except PhotoImageError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
            raise PhotoImageError("too_many_pixels") from e
        except Exception as e:
            raise PhotoImageError("broken") from e
