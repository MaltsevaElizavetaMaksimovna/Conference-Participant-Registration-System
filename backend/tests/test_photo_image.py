"""Тесты проверки, нормализации и сохранения фото участников (IM-01, QR-02)."""

import hashlib
import io
import random
from pathlib import Path

import pytest
from PIL import Image

from app.imports.photo_image import ALLOWED_FORMATS, PhotoImageError, normalize_photo
from app.imports.photo_store import store_photo


def test_allowed_formats_constant() -> None:
    """ALLOWED_FORMATS содержит в точности JPEG, PNG, WEBP."""
    assert frozenset({"JPEG", "PNG", "WEBP"}) == ALLOWED_FORMATS


def test_normalize_photo_jpeg_keep_size() -> None:
    """JPEG 800x600 не увеличивается при max_side_px=1200."""
    bio = io.BytesIO()
    Image.new("RGB", (800, 600), (120, 140, 160)).save(bio, format="JPEG")
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (800, 600)


def test_normalize_photo_png_scale_down() -> None:
    """PNG 3000x1000 уменьшается до длинной стороны max_side_px=1200 (1200x400)."""
    bio = io.BytesIO()
    Image.new("RGB", (3000, 1000), (40, 80, 120)).save(bio, format="PNG")
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (1200, 400)


def test_normalize_photo_rgba_transparent_on_white() -> None:
    """Прозрачный PNG RGBA накладывается на белый фон."""
    bio = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(bio, format="PNG")
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        pixel = img.getpixel((0, 0))
        assert isinstance(pixel, tuple)
        r, g, b = pixel[:3]
        assert r >= 250 and g >= 250 and b >= 250


def test_normalize_photo_strip_exif() -> None:
    """EXIF метаданные полностью удаляются из результата."""
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    bio = io.BytesIO()
    Image.new("RGB", (100, 100), (100, 100, 100)).save(bio, format="JPEG", exif=exif.tobytes())
    raw_data = bio.getvalue()

    with Image.open(io.BytesIO(raw_data)) as source_img:
        assert source_img.getexif().get(0x010F) == "TestCam"

    result = normalize_photo(
        raw_data,
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        out_exif = img.getexif()
        assert len(out_exif) == 0
        assert dict(out_exif) == {}


def test_normalize_photo_exif_orientation_applied() -> None:
    """Ориентация EXIF (6 = поворот 90 CW) применяется: 200x100 -> 100x200."""
    exif = Image.Exif()
    exif[0x0112] = 6
    bio = io.BytesIO()
    Image.new("RGB", (200, 100), (50, 100, 150)).save(bio, format="JPEG", exif=exif.tobytes())
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.size == (100, 200)


def test_normalize_photo_not_an_image() -> None:
    """Случайные байты вызывают PhotoImageError с reason == 'not_image'."""
    with pytest.raises(PhotoImageError) as exc_info:
        normalize_photo(
            b"not an image",
            max_pixels=10_000_000,
            max_side_px=1200,
            quality=85,
        )
    assert exc_info.value.reason == "not_image"


def test_normalize_photo_unsupported_format() -> None:
    """Формат GIF запрещён -> PhotoImageError('unsupported_format')."""
    bio = io.BytesIO()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(bio, format="GIF")
    with pytest.raises(PhotoImageError) as exc_info:
        normalize_photo(
            bio.getvalue(),
            max_pixels=10_000_000,
            max_side_px=1200,
            quality=85,
        )
    assert exc_info.value.reason == "unsupported_format"


def test_normalize_photo_decompression_bomb() -> None:
    """Картинка с числом пикселей больше max_pixels отклоняется как 'too_many_pixels'."""
    bio = io.BytesIO()
    Image.new("RGB", (5000, 5000), (255, 255, 255)).save(bio, format="PNG")
    data = bio.getvalue()
    with pytest.raises(PhotoImageError) as exc_info:
        normalize_photo(
            data,
            max_pixels=1_000_000,
            max_side_px=1200,
            quality=85,
        )
    assert exc_info.value.reason == "too_many_pixels"


def test_normalize_photo_truncated_jpeg() -> None:
    """Обрезанный JPEG отклоняется с причиной 'broken' или 'not_image'."""
    if hasattr(Image, "effect_noise"):
        noise_img = Image.effect_noise((400, 400), 50.0).convert("RGB")
    else:
        noise_img = Image.frombytes("RGB", (400, 400), random.randbytes(400 * 400 * 3))

    bio = io.BytesIO()
    noise_img.save(bio, format="JPEG")
    raw = bio.getvalue()
    truncated = raw[: int(len(raw) * 0.6)]

    with pytest.raises(PhotoImageError) as exc_info:
        normalize_photo(
            truncated,
            max_pixels=10_000_000,
            max_side_px=1200,
            quality=85,
        )
    assert exc_info.value.reason in {"broken", "not_image"}


def test_store_photo_atomic_and_idempotent(tmp_path: Path) -> None:
    """Атомарное сохранение фото, вычисление sha256 и идемпотентность."""
    data = b"fake-jpeg-bytes-for-photo-storage"
    expected_sha = hashlib.sha256(data).hexdigest()
    expected_sha16 = expected_sha[:16]
    expected_rel = f"3/17-{expected_sha16}.jpg"

    rel_path, sha = store_photo(tmp_path, 3, 17, data)
    assert rel_path == expected_rel
    assert sha == expected_sha

    target_file = tmp_path / "3" / f"17-{expected_sha16}.jpg"
    assert target_file.is_file()
    assert target_file.read_bytes() == data

    tmp_dir = tmp_path / "3"
    assert list(tmp_dir.glob("*.tmp")) == []

    rel_path_2, sha_2 = store_photo(tmp_path, 3, 17, data)
    assert rel_path_2 == expected_rel
    assert sha_2 == expected_sha
    assert target_file.read_bytes() == data
    assert list(tmp_dir.glob("*.tmp")) == []


def test_normalize_photo_webp_supported() -> None:
    """WebP поддерживается и корректно нормализуется в JPEG."""
    bio = io.BytesIO()
    Image.new("RGB", (200, 200), (80, 160, 240)).save(bio, format="WEBP")
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        assert img.size == (200, 200)


def test_normalize_photo_la_mode() -> None:
    """Режим LA с прозрачностью накладывается на белый фон."""
    bio = io.BytesIO()
    Image.new("LA", (50, 50), (0, 0)).save(bio, format="PNG")
    result = normalize_photo(
        bio.getvalue(),
        max_pixels=10_000_000,
        max_side_px=1200,
        quality=85,
    )

    with Image.open(io.BytesIO(result)) as img:
        assert img.format == "JPEG"
        assert img.mode == "RGB"
        pixel = img.getpixel((0, 0))
        assert isinstance(pixel, tuple)
        r, g, b = pixel[:3]
        assert r >= 250 and g >= 250 and b >= 250
