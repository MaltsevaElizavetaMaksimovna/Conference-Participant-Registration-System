"""Атомарное сохранение фото участника в каталог фото (B1-06, IM-01, QR-02)."""

import hashlib
import os
import tempfile
from pathlib import Path, PurePosixPath


def store_photo(
    photo_dir: Path,
    conference_id: int,
    participant_id: int,
    jpeg: bytes,
) -> tuple[str, str]:
    """Записать JPEG атомарно; вернуть (путь относительно photo_dir в POSIX-виде, sha256 hex)."""
    sha = hashlib.sha256(jpeg).hexdigest()
    filename = f"{participant_id}-{sha[:16]}.jpg"
    rel_path = PurePosixPath(str(conference_id), filename).as_posix()

    target_dir = photo_dir / str(conference_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / filename

    with tempfile.NamedTemporaryFile(dir=target_dir, delete=False, suffix=".tmp") as temp_file:
        temp_path = Path(temp_file.name)
        try:
            temp_file.write(jpeg)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        except BaseException:
            temp_file.close()
            temp_path.unlink(missing_ok=True)
            raise
    try:
        os.replace(temp_path, target_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise

    return rel_path, sha
