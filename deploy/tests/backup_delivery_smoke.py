"""Сквозная проверка production-бэкапа на одноразовой БД и синтетическом фото."""

import argparse
import filecmp
import tempfile
import time
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import psycopg
from PIL import Image
from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings
from scripts.backup import verify_backup

PHOTO_NAME = "ci/sample.jpg"


def sample_photo() -> bytes:
    with BytesIO() as output:
        Image.new("RGB", (8, 8), "blue").save(output, format="JPEG")
        return output.getvalue()


def seed(settings: Settings) -> None:
    url = make_url(settings.database_url).set(drivername="postgresql")
    with psycopg.connect(url.render_as_string(hide_password=False)) as connection:
        connection.execute(
            "INSERT INTO conference (title, date_from, date_to, badge_type) "
            "VALUES ('Backup CI', DATE '2026-01-01', DATE '2026-01-02', 'none')"
        )
    photo = settings.photo_dir / PHOTO_NAME
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(sample_photo())


def wait_for_pair(mirror: Path) -> tuple[Path, Path]:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        for dump in sorted(mirror.glob("regsys-*.dump"), reverse=True):
            photos = dump.with_name(f"{dump.stem}-photos.zip")
            if photos.is_file():
                return dump, photos
        time.sleep(1)
    raise TimeoutError("Планировщик не создал полную пару файлов на зеркале")


def verify(settings: Settings) -> None:
    if settings.backup_mirror_dir is None:
        raise RuntimeError("Для проверки поставки нужно подключить зеркало")
    dump, photos = wait_for_pair(settings.backup_mirror_dir)
    for source in (dump, photos):
        assert filecmp.cmp(source, settings.backup_dir / source.name, shallow=False)
    counts = verify_backup(settings, dump)
    assert counts["conference"] == 1 and counts["alembic_version"] == 1

    with tempfile.TemporaryDirectory(prefix="regsys_photo_restore_") as directory:
        restored = Path(directory) / "sample.jpg"
        with ZipFile(photos) as archive:
            restored.write_bytes(archive.read(PHOTO_NAME))
        assert restored.read_bytes() == sample_photo()
        with Image.open(restored) as image:
            image.verify()
    print("Дамп восстановлен в отдельную БД, фото из зеркала восстановлено и совпало.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("seed", "verify"))
    args = parser.parse_args()
    (seed if args.step == "seed" else verify)(get_settings())
