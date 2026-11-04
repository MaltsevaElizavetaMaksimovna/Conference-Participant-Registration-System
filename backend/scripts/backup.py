"""Резервное копирование БД и фото (B1-14, NF-05).

Запуск из каталога backend:
    python scripts/backup.py now
    python scripts/backup.py loop
    python scripts/backup.py verify [--file F]
    python scripts/backup.py list
"""

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings, get_settings  # noqa: E402


@dataclass(frozen=True)
class DbTarget:
    """Параметры подключения к базе данных из RS_DATABASE_URL."""

    host: str | None
    port: int | None
    user: str | None
    password: str | None
    database: str

    @classmethod
    def from_url(cls, url: str) -> "DbTarget":
        u = make_url(url)
        return cls(
            host=u.host,
            port=u.port,
            user=u.username,
            password=u.password,
            database=u.database or "",
        )

    def args(self) -> list[str]:
        """Аргументы командной строки без пароля: -h, -p, -U (только заданные)."""
        result: list[str] = []
        if self.host:
            result.extend(["-h", self.host])
        if self.port is not None:
            result.extend(["-p", str(self.port)])
        if self.user:
            result.extend(["-U", self.user])
        return result

    def env(self) -> dict[str, str]:
        """Копия переменных окружения с PGPASSWORD, если пароль задан."""
        res = dict(os.environ)
        if self.password is not None:
            res["PGPASSWORD"] = self.password
        return res

    def conninfo(self, database: str | None = None) -> str:
        """Строка подключения psycopg без пароля (значения экранирует psycopg)."""
        params: dict[str, str | int] = {"dbname": database or self.database}
        if self.host:
            params["host"] = self.host
        if self.port is not None:
            params["port"] = self.port
        if self.user:
            params["user"] = self.user
        return make_conninfo("", **params)


@dataclass(frozen=True)
class BackupFiles:
    """Пути к файлам резервной копии и их суммарный размер в байтах."""

    dump: Path
    photos: Path
    size: int


class BackupError(Exception):
    """Ошибка резервного копирования или восстановления."""


def _sanitize(text: str, *secrets_to_hide: str | None) -> str:
    """Удаляет пароли и секреты из текста ошибки."""
    for s in secrets_to_hide:
        if s and s in text:
            text = text.replace(s, "******")
    return text


def pg_tool(name: str, settings: Settings) -> Path:
    """Определяет путь к утилите PostgreSQL (pg_dump или pg_restore)."""
    exe_name = f"{name}.exe" if sys.platform == "win32" and not name.endswith(".exe") else name

    # 1. Из каталога settings.pg_bin_dir, если задан и файл существует
    if settings.pg_bin_dir is not None:
        p = settings.pg_bin_dir / exe_name
        if p.is_file():
            return p
        p_raw = settings.pg_bin_dir / name
        if p_raw.is_file():
            return p_raw

    # 2. Поиск в PATH
    which_path = shutil.which(name)
    if which_path is not None:
        return Path(which_path)

    # 3. Встроенные бинарники пакета pgserver
    try:
        import pgserver

        if getattr(pgserver, "__file__", None):
            pg_bin = Path(pgserver.__file__).parent / "pginstall" / "bin"
            p = pg_bin / exe_name
            if p.is_file():
                return p
            p_raw = pg_bin / name
            if p_raw.is_file():
                return p_raw
    except Exception:
        pass

    raise BackupError(f"Не найден {name}: укажите каталог в RS_PG_BIN_DIR или добавьте в PATH")


def _list_backup_sets(directory: Path) -> dict[str, list[Path]]:
    """Находит наборы резервных копий regsys-*, сгруппированные по имени набора."""
    if not directory.is_dir():
        return {}
    sets: dict[str, list[Path]] = {}
    for p in directory.iterdir():
        if not p.is_file():
            continue
        if p.name.startswith("regsys-") and p.name.endswith(".dump"):
            name = p.name[:-5]
            sets.setdefault(name, []).append(p)
        elif p.name.startswith("regsys-") and p.name.endswith("-photos.zip"):
            name = p.name[:-11]
            sets.setdefault(name, []).append(p)
    return sets


def rotate(directory: Path, keep: int) -> list[Path]:
    """Удаляет старые наборы резервных копий, оставляя keep самых новых."""
    deleted: list[Path] = []
    if not directory.is_dir():
        return deleted

    # 1. Удаление висящих .tmp файлов старше 1 часа
    now_ts = time.time()
    for p in directory.iterdir():
        if p.is_file() and p.name.startswith("regsys-") and p.name.endswith(".tmp"):
            try:
                if (now_ts - p.stat().st_mtime) > 3600:
                    p.unlink(missing_ok=True)
                    deleted.append(p)
            except OSError:
                pass

    # 2. Группировка наборов и удаление старых
    sets = _list_backup_sets(directory)
    if not sets:
        return deleted

    sorted_names = sorted(sets.keys())
    to_delete = sorted_names if keep <= 0 else sorted_names[:-keep]

    for name in to_delete:
        for p in sets[name]:
            try:
                p.unlink(missing_ok=True)
                deleted.append(p)
            except OSError:
                pass

    return deleted


def latest_dump(directory: Path) -> Path | None:
    """Возвращает путь к самому свежему дампу в каталоге или None."""
    if not directory.is_dir():
        return None
    dumps = [
        p
        for p in directory.iterdir()
        if p.is_file() and p.name.startswith("regsys-") and p.name.endswith(".dump")
    ]
    if not dumps:
        return None
    return sorted(dumps, key=lambda p: p.name)[-1]


def make_backup(settings: Settings, *, now: datetime | None = None) -> BackupFiles:
    """Создаёт резервную копию базы данных и фотографий."""
    if now is None:
        now = datetime.now(UTC)
    elif now.tzinfo is not None:
        now = now.astimezone(UTC)

    stamp = now.strftime("%Y%m%d-%H%M%S")
    name = f"regsys-{stamp}"

    backup_dir = settings.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)

    dump_tmp = backup_dir / f"{name}.dump.tmp"
    dump_final = backup_dir / f"{name}.dump"
    photos_tmp = backup_dir / f"{name}-photos.zip.tmp"
    photos_final = backup_dir / f"{name}-photos.zip"

    target = DbTarget.from_url(settings.database_url)
    pg_dump_bin = pg_tool("pg_dump", settings)
    pg_restore_bin = pg_tool("pg_restore", settings)

    # 1. Дамп базы данных
    cmd = [
        str(pg_dump_bin),
        "-Fc",
        "--no-owner",
        "--no-privileges",
        "-f",
        str(dump_tmp),
        *target.args(),
        target.database,
    ]

    try:
        res = subprocess.run(
            cmd,
            env=target.env(),
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        dump_tmp.unlink(missing_ok=True)
        raise BackupError(f"Превышено время ожидания pg_dump: {e}") from e
    except OSError as e:
        dump_tmp.unlink(missing_ok=True)
        raise BackupError(f"Не удалось запустить pg_dump: {e}") from e

    if res.returncode != 0 or not dump_tmp.is_file() or dump_tmp.stat().st_size == 0:
        dump_tmp.unlink(missing_ok=True)
        err = _sanitize(
            res.stderr.strip()[:500] if res.stderr else "файл дампа пустой или не создан",
            target.password,
            settings.database_url,
        )
        raise BackupError(f"Ошибка создания дампа БД: {err}")

    # Проверка читаемости дампа через pg_restore --list
    list_cmd = [str(pg_restore_bin), "--list", str(dump_tmp)]
    try:
        list_res = subprocess.run(
            list_cmd,
            env=target.env(),
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as e:
        dump_tmp.unlink(missing_ok=True)
        raise BackupError(f"Превышено время ожидания проверки дампа: {e}") from e
    except OSError as e:
        dump_tmp.unlink(missing_ok=True)
        raise BackupError(f"Не удалось запустить pg_restore для проверки: {e}") from e

    if list_res.returncode != 0:
        dump_tmp.unlink(missing_ok=True)
        err = _sanitize(
            list_res.stderr.strip()[:500] if list_res.stderr else "",
            target.password,
            settings.database_url,
        )
        raise BackupError(f"Дамп повреждён (pg_restore --list завершился с ошибкой): {err}")

    os.replace(dump_tmp, dump_final)

    # 2. Архив фотографий
    try:
        with zipfile.ZipFile(photos_tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            if settings.photo_dir.is_dir():
                for root, _dirs, files in os.walk(settings.photo_dir):
                    for f in files:
                        full_p = Path(root) / f
                        rel_p = full_p.relative_to(settings.photo_dir)
                        zf.write(full_p, arcname=rel_p.as_posix())
        os.replace(photos_tmp, photos_final)
    except Exception as e:
        photos_tmp.unlink(missing_ok=True)
        raise BackupError(f"Ошибка создания архива фото: {e}") from e

    # 3. Ротация основного каталога (до копирования: сбой второго носителя её не отменяет)
    rotate(backup_dir, settings.backup_keep)

    # 4. Второй носитель (зеркало)
    if settings.backup_mirror_dir is not None:
        mirror_dir = settings.backup_mirror_dir
        try:
            mirror_dir.mkdir(parents=True, exist_ok=True)
            for src, dst_name in [
                (dump_final, dump_final.name),
                (photos_final, photos_final.name),
            ]:
                dst_tmp = mirror_dir / f"{dst_name}.tmp"
                dst_final = mirror_dir / dst_name
                try:
                    shutil.copyfile(src, dst_tmp)
                    os.replace(dst_tmp, dst_final)
                finally:
                    dst_tmp.unlink(missing_ok=True)
            rotate(mirror_dir, settings.backup_keep)
        except Exception as e:
            raise BackupError(f"Ошибка копирования на второй носитель {mirror_dir}: {e}") from e

    total_size = dump_final.stat().st_size + photos_final.stat().st_size
    return BackupFiles(dump=dump_final, photos=photos_final, size=total_size)


def verify_backup(settings: Settings, dump: Path) -> dict[str, int]:
    """Проверяет восстановимость дампа во временную БД и возвращает число строк в таблицах."""
    if not dump.is_file():
        raise BackupError(f"Файл дампа не найден: {dump}")

    target = DbTarget.from_url(settings.database_url)
    verify_db = f"regsys_verify_{secrets.token_hex(6)}"
    if verify_db == target.database:
        raise BackupError("Имя временной базы совпадает с рабочей базой данных")

    pg_restore_bin = pg_tool("pg_restore", settings)
    admin_conninfo = target.conninfo("postgres")

    # Создание временной БД
    try:
        with psycopg.connect(admin_conninfo, password=target.password, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{verify_db}"')
    except Exception as e:
        err = _sanitize(str(e), target.password, settings.database_url)
        raise BackupError(f"Не удалось создать временную БД: {err}") from e

    cmd = [
        str(pg_restore_bin),
        "--no-owner",
        "--no-privileges",
        "--exit-on-error",
        *target.args(),
        "-d",
        verify_db,
        str(dump),
    ]

    try:
        try:
            res = subprocess.run(
                cmd,
                env=target.env(),
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired as e:
            raise BackupError(f"Превышено время ожидания pg_restore: {e}") from e
        except OSError as e:
            raise BackupError(f"Не удалось запустить pg_restore: {e}") from e

        if res.returncode != 0:
            err = _sanitize(
                res.stderr.strip()[:500] if res.stderr else "",
                target.password,
                settings.database_url,
            )
            raise BackupError(f"Ошибка восстановления pg_restore: {err}")

        verify_conninfo = target.conninfo(verify_db)
        tables = (
            "conference",
            "participant",
            "staff_user",
            "change_log",
            "event_log",
            "import_batch",
        )
        result: dict[str, int] = {}
        with (
            psycopg.connect(verify_conninfo, password=target.password) as vconn,
            vconn.cursor() as cur,
        ):
            try:
                cur.execute("SELECT count(*) FROM alembic_version")
                row = cur.fetchone()
                alembic_count = int(row[0]) if row else 0
            except Exception as e:
                raise BackupError("Таблица alembic_version отсутствует в дампе") from e

            if alembic_count != 1:
                raise BackupError(
                    f"В таблице alembic_version {alembic_count} строк, ожидалась ровно 1"
                )
            result["alembic_version"] = alembic_count

            for tbl in tables:
                try:
                    cur.execute(f'SELECT count(*) FROM "{tbl}"')
                    row = cur.fetchone()
                    result[tbl] = int(row[0]) if row else 0
                except Exception as e:
                    raise BackupError(f"Не удалось прочитать таблицу {tbl}: {e}") from e

        return result
    finally:
        try:
            with psycopg.connect(admin_conninfo, password=target.password, autocommit=True) as conn:
                conn.execute(f'DROP DATABASE IF EXISTS "{verify_db}" WITH (FORCE)')
        except Exception:
            pass


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа CLI для резервного копирования."""
    parser = argparse.ArgumentParser(
        prog="backup.py",
        description="Резервное копирование БД и фото (B1-14, NF-05)",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("now", help="Создать резервную копию")
    subparsers.add_parser("loop", help="Периодическое создание копий")
    verify_p = subparsers.add_parser("verify", help="Проверить дамп")
    verify_p.add_argument("--file", "-f", type=Path, default=None, help="Путь к дампу")
    subparsers.add_parser("list", help="Список резервных копий")

    if argv is None:
        argv = sys.argv[1:]

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    if not args.command:
        parser.print_help()
        return 1

    settings = get_settings()

    if args.command == "now":
        try:
            bf = make_backup(settings)
            print(f"Дамп БД: {bf.dump}")
            print(f"Архив фото: {bf.photos}")
            print(f"Общий размер: {bf.size} байт")
            return 0
        except Exception as e:
            print(f"Ошибка резервного копирования: {e}", file=sys.stderr)
            return 1

    if args.command == "loop":
        interval_s = settings.backup_interval_min * 60
        print(
            f"Запуск периодического резервного копирования "
            f"(интервал: {settings.backup_interval_min} мин)..."
        )
        try:
            while True:
                try:
                    bf = make_backup(settings)
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                    print(
                        f"[{now_str}] Резервная копия создана: "
                        f"{bf.dump.name}, {bf.photos.name} ({bf.size} байт)"
                    )
                except Exception as e:
                    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                    print(
                        f"[{now_str}] Ошибка резервного копирования: {e}",
                        file=sys.stderr,
                    )
                time.sleep(interval_s)
        except KeyboardInterrupt:
            print("\nРезервное копирование остановлено.")
            return 0

    if args.command == "verify":
        dump_path: Path | None = args.file
        if dump_path is None:
            dump_path = latest_dump(settings.backup_dir)
            if dump_path is None:
                print("Резервные копии не найдены", file=sys.stderr)
                return 1
        try:
            counts = verify_backup(settings, dump_path)
            print(f"Дамп проверен: {dump_path.name}")
            for tbl, count in sorted(counts.items()):
                print(f"  {tbl}: {count}")
            return 0
        except Exception as e:
            print(f"Ошибка проверки дампа: {e}", file=sys.stderr)
            return 1

    if args.command == "list":
        try:
            sets = _list_backup_sets(settings.backup_dir)
            if not sets:
                print("Резервные копии не найдены")
                return 0
            for sname in sorted(sets.keys()):
                files = sets[sname]
                total_sz = sum(f.stat().st_size for f in files)
                print(f"{sname}: {total_sz} байт")
                for f in sorted(files, key=lambda x: x.name):
                    print(f"  {f.name} ({f.stat().st_size} байт)")
            return 0
        except Exception as e:
            print(f"Ошибка при получении списка: {e}", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
