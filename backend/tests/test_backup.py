"""Тесты резервного копирования БД и фото (B1-14, NF-05)."""

import os
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import psycopg
import pytest
from sqlalchemy.engine import make_url

from app.core.config import Settings
from scripts.backup import (
    BackupError,
    main,
    make_backup,
    pg_tool,
    rotate,
    verify_backup,
)


def _admin_conninfo(sa_url: str) -> str:
    """Формирует строку подключения psycopg к БД postgres."""
    url = make_url(sa_url)
    return url.set(drivername="postgresql", database="postgres").render_as_string(
        hide_password=False
    )


def test_make_backup_success(database_url: str, tmp_path: Path) -> None:
    """make_backup создаёт непустые файлы .dump и -photos.zip; в zip есть фото."""
    photo_dir = tmp_path / "photos"
    sample_file = photo_dir / "3" / "17-abc.jpg"
    sample_file.parent.mkdir(parents=True, exist_ok=True)
    sample_file.write_bytes(b"test-photo-data")

    backup_dir = tmp_path / "b"
    settings = Settings(
        database_url=database_url,
        backup_dir=backup_dir,
        photo_dir=photo_dir,
        backup_keep=3,
    )
    files = make_backup(settings)

    assert files.dump.is_file()
    assert files.dump.stat().st_size > 0
    assert files.photos.is_file()
    assert files.photos.stat().st_size > 0
    assert files.size == files.dump.stat().st_size + files.photos.stat().st_size

    # Проверка отсутствия временных файлов
    tmp_files = list(backup_dir.glob("*.tmp"))
    assert tmp_files == []

    # В zip присутствует файл 3/17-abc.jpg
    with zipfile.ZipFile(files.photos) as zf:
        assert "3/17-abc.jpg" in zf.namelist()
        assert zf.read("3/17-abc.jpg") == b"test-photo-data"


def test_verify_backup(database_url: str, tmp_path: Path) -> None:
    """verify_backup возвращает словарь со всеми таблицами, временная БД удаляется."""
    settings = Settings(
        database_url=database_url,
        backup_dir=tmp_path / "b",
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )
    files = make_backup(settings)

    counts = verify_backup(settings, files.dump)
    expected_tables = {
        "conference",
        "participant",
        "staff_user",
        "change_log",
        "event_log",
        "import_batch",
        "alembic_version",
    }
    assert expected_tables.issubset(counts.keys())
    for tbl in expected_tables:
        assert counts[tbl] >= 0
    assert counts["alembic_version"] == 1

    # Проверка отсутствия временных БД regsys_verify_*
    with psycopg.connect(_admin_conninfo(database_url), autocommit=True) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE 'regsys_verify_%'"
        ).fetchall()
        assert rows == []


def test_make_backup_nonexistent_db(database_url: str, tmp_path: Path) -> None:
    """DbTarget на несуществующую БД вызывает BackupError, мусор не остаётся."""
    bad_url = (
        make_url(database_url).set(database="no_such_db").render_as_string(hide_password=False)
    )
    backup_dir = tmp_path / "b"
    settings = Settings(
        database_url=bad_url,
        backup_dir=backup_dir,
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )

    with pytest.raises(BackupError):
        make_backup(settings)

    if backup_dir.is_dir():
        dumps = list(backup_dir.glob("*.dump"))
        tmps = list(backup_dir.glob("*.tmp"))
        assert dumps == []
        assert tmps == []


def test_password_not_in_args_and_env(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пароль передаётся только через PGPASSWORD и отсутствует в args и текстах ошибок."""
    secret = "secret-pass-123"
    auth_url = make_url(database_url).set(password=secret).render_as_string(hide_password=False)
    settings = Settings(
        database_url=auth_url,
        backup_dir=tmp_path / "b",
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )

    recorded_calls: list[tuple[list[str], dict[str, str]]] = []
    real_run = subprocess.run

    def wrapped_run(cmd: Any, *args: Any, **kwargs: Any) -> Any:
        env = kwargs.get("env") or {}
        recorded_calls.append((list(cmd), dict(env)))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", wrapped_run)

    files = make_backup(settings)
    assert files.dump.is_file()
    assert len(recorded_calls) >= 1

    for cmd, env in recorded_calls:
        for arg in cmd:
            assert secret not in arg
        assert env.get("PGPASSWORD") == secret

    # Проверка, что текст BackupError при ошибке не содержит secret
    bad_url = (
        make_url(database_url)
        .set(database="no_such_db", password=secret)
        .render_as_string(hide_password=False)
    )
    bad_settings = Settings(
        database_url=bad_url,
        backup_dir=tmp_path / "b_bad",
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )
    with pytest.raises(BackupError) as exc_info:
        make_backup(bad_settings)
    assert secret not in str(exc_info.value)


def test_rotate(tmp_path: Path) -> None:
    """Ротация удаляет старые наборы и сохраняет чужие файлы."""
    bdir = tmp_path / "backups"
    bdir.mkdir(parents=True, exist_ok=True)

    # 5 наборов-пустышек regsys-2026110{1..5}-120000.dump + -photos.zip
    for day in range(1, 6):
        (bdir / f"regsys-2026110{day}-120000.dump").write_bytes(b"dump")
        (bdir / f"regsys-2026110{day}-120000-photos.zip").write_bytes(b"photos")

    # Чужой файл
    notes = bdir / "notes.txt"
    notes.write_text("заметки", encoding="utf-8")

    deleted = rotate(bdir, 3)

    # Удалены два самых старых набора (дни 01 и 02)
    assert len(deleted) == 4
    deleted_names = {p.name for p in deleted}
    assert deleted_names == {
        "regsys-20261101-120000.dump",
        "regsys-20261101-120000-photos.zip",
        "regsys-20261102-120000.dump",
        "regsys-20261102-120000-photos.zip",
    }

    # notes.txt на месте
    assert notes.is_file()

    # Оставшиеся наборы на месте
    for day in (3, 4, 5):
        assert (bdir / f"regsys-2026110{day}-120000.dump").is_file()
        assert (bdir / f"regsys-2026110{day}-120000-photos.zip").is_file()

    # Висящий .tmp старше 1 часа удаляется, свежий остаётся
    old_tmp = bdir / "regsys-old.dump.tmp"
    old_tmp.write_bytes(b"old")
    past_time = time.time() - 7200
    os.utime(old_tmp, (past_time, past_time))

    fresh_tmp = bdir / "regsys-fresh.dump.tmp"
    fresh_tmp.write_bytes(b"fresh")

    deleted_extra = rotate(bdir, 3)
    assert old_tmp in deleted_extra
    assert not old_tmp.exists()
    assert fresh_tmp.is_file()


def test_backup_mirror(database_url: str, tmp_path: Path) -> None:
    """Копирование на второй носитель дублирует файлы дампа и фото."""
    mirror_dir = tmp_path / "m"
    settings = Settings(
        database_url=database_url,
        backup_dir=tmp_path / "b",
        backup_mirror_dir=mirror_dir,
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )

    files = make_backup(settings)

    assert (mirror_dir / files.dump.name).is_file()
    assert (mirror_dir / files.photos.name).is_file()
    assert (mirror_dir / files.dump.name).stat().st_size == files.dump.stat().st_size
    assert (mirror_dir / files.photos.name).stat().st_size == files.photos.stat().st_size
    assert list(mirror_dir.glob("*.tmp")) == []


def test_main_cli(database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Команды CLI now, list, verify завершаются с ожидаемым кодом возврата."""
    settings = Settings(
        database_url=database_url,
        backup_dir=tmp_path / "b",
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )
    monkeypatch.setattr("scripts.backup.get_settings", lambda: settings)

    assert main(["now"]) == 0
    assert main(["list"]) == 0
    assert main(["verify"]) == 0
    assert main(["verify", "--file", str(tmp_path / "nope.dump")]) == 1


def test_pg_tool(database_url: str, tmp_path: Path) -> None:
    """pg_tool находит исполняемые файлы pg_dump и pg_restore."""
    settings = Settings(
        database_url=database_url,
        backup_dir=tmp_path / "b",
        photo_dir=tmp_path / "photos",
        backup_keep=3,
    )
    assert pg_tool("pg_dump", settings).is_file()
    assert pg_tool("pg_restore", settings).is_file()
