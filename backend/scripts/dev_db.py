"""Локальная PostgreSQL для разработки без Docker (пакет pgserver).

    python scripts/dev_db.py          # поднять сервер, создать БД regsys, напечатать DATABASE_URL
    python scripts/dev_db.py --stop   # остановить сервер

Данные лежат в backend/.devdb и переживают перезапуск. Сервер продолжает работать
после выхода скрипта. Информационные сообщения идут в stderr, в stdout — только URL.
"""

import subprocess
import sys
from pathlib import Path

import pgserver
import psycopg

DB_NAME = "regsys"
DEV_DB_PATH = Path(__file__).resolve().parent.parent / ".devdb"


def ensure_database(admin_uri: str, name: str) -> None:
    with psycopg.connect(admin_uri, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')
            print(f"Создана БД {name}", file=sys.stderr)


def to_sqlalchemy_url(uri: str, db_name: str) -> str:
    """postgresql://postgres:@127.0.0.1:PORT/postgres -> postgresql+psycopg://.../db_name."""
    base = uri.rsplit("/", 1)[0]
    return base.replace("postgresql://", "postgresql+psycopg://", 1) + f"/{db_name}"


def start() -> str:
    DEV_DB_PATH.mkdir(exist_ok=True)
    # cleanup_mode=None: сервер не гасится при выходе процесса
    server = pgserver.get_server(DEV_DB_PATH, cleanup_mode=None)
    uri = server.get_uri()
    ensure_database(uri, DB_NAME)
    return to_sqlalchemy_url(uri, DB_NAME)


def stop() -> None:
    # pg_ctl напрямую: у pgserver остановка зависит от счётчика процессов-владельцев
    pg_ctl = Path(pgserver.__file__).parent / "pginstall" / "bin" / "pg_ctl"
    subprocess.run([str(pg_ctl), "-D", str(DEV_DB_PATH), "-m", "fast", "-w", "stop"], check=False)


if __name__ == "__main__":
    if "--stop" in sys.argv[1:]:
        stop()
    else:
        print(start())
