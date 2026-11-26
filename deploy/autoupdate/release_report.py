"""Collect deployment status and deliver queued reports over authenticated SMTP."""

import datetime as dt
import json
import os
import shutil
import smtplib
import ssl
import tempfile
import uuid
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

from compose_update import UpdateError, run


def now():
    return dt.datetime.now(dt.UTC)


def new_record(tag, before):
    return {
        "id": f"<{uuid.uuid4().hex}@regsys.local>",
        "date": format_datetime(now()),
        "tag": tag,
        "before": before,
        "after": before,
        "outcome": "Остановка до переключения",
        "backup": None,
        "duration_seconds": 0,
        "metrics": {},
    }


def status_snapshot(root, compose, https=None):
    metrics = {
        "HTTPS": "не проверено",
        "API": "не проверено",
        "PostgreSQL": "не проверено",
    }
    if https is None:
        try:
            compose.health(compose.config())
        except (UpdateError, OSError, KeyError, ValueError):
            https = False
        else:
            https = True
    metrics["HTTPS"] = "доступен" if https else "проверка не прошла"
    try:
        rows = run(
            "read deployment health",
            "docker",
            "ps",
            "-a",
            "--filter",
            "label=com.docker.compose.project=regsys-prod",
            "--filter",
            "label=com.docker.compose.oneoff=False",
            "--format",
            '{{.Label "com.docker.compose.service"}}\t{{.State}}\t{{.Status}}',
            timeout=10,
        )
        for row in rows.splitlines():
            service, state, status = row.split("\t", 2)
            if service in ("api", "db"):
                name = "API" if service == "api" else "PostgreSQL"
                metrics[name] = next(
                    (
                        health
                        for health in ("healthy", "unhealthy")
                        if f"({health})" in status
                    ),
                    "starting" if "(health: starting)" in status else state,
                )
    except (UpdateError, OSError, ValueError):
        pass
    metrics["Свободно на диске"] = f"{shutil.disk_usage(root).free / 2**30:.1f} GiB"
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                metrics["Доступно RAM"] = f"{int(line.split()[1]) / 1024:.0f} MiB"
                break
    except (OSError, ValueError):
        pass
    return metrics


def make_message(record, sender, recipient):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = f"[regsys] {record['tag']} · {record['outcome']}"
    message["Date"] = record["date"]
    message["Message-ID"] = record["id"]
    metrics = "\n".join(f"{key}: {value}" for key, value in record["metrics"].items())
    message.set_content(
        f"Релиз: {record['tag']}\n"
        f"Результат: {record['outcome']}\n"
        f"Версия: {record['before']} → {record['after']}\n"
        f"Начало: {record['date']}\n"
        f"Длительность: {record['duration_seconds']} с\n"
        f"Проверенный бэкап: {record['backup'] or 'не подтверждён'}\n"
        f"{metrics}\n"
    )
    return message


def enqueue(root, record):
    queue = root / "mail-queue"
    queue.mkdir(mode=0o700, exist_ok=True)
    filename = uuid.UUID(record["id"].removeprefix("<").split("@", 1)[0]).hex
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=queue, encoding="utf-8", delete=False
        ) as file:
            temporary = Path(file.name)
            json.dump(record, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(queue / f"{filename}.json")
        sync_directory(queue)
        sync_directory(root)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def sync_directory(path):
    if hasattr(os, "O_DIRECTORY"):
        fd = os.open(path, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def deliver(record):
    host = os.environ["REGSYS_SMTP_HOST"]
    port = int(os.environ.get("REGSYS_SMTP_PORT", "587"))
    sender = os.environ["REGSYS_SMTP_FROM"]
    recipient = os.environ["REGSYS_SMTP_TO"]
    message = make_message(record, sender, recipient)
    context = ssl.create_default_context()
    if port == 465:
        connection = smtplib.SMTP_SSL(host, port, timeout=10, context=context)
    else:
        connection = smtplib.SMTP(host, port, timeout=10)
    with connection as client:
        if port != 465:
            client.starttls(context=context)
        client.login(os.environ["REGSYS_SMTP_USER"], os.environ["REGSYS_SMTP_PASSWORD"])
        client.send_message(message, from_addr=sender, to_addrs=[recipient])


def flush(root):
    try:
        queued = sorted(
            (root / "mail-queue").glob("*.json"), key=lambda file: file.stat().st_mtime
        )
        for path in queued[:5]:
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                make_message(record, "sender@example.test", "recipient@example.test")
            except (AttributeError, KeyError, TypeError, ValueError):
                path.rename(path.with_suffix(".invalid"))
                print("Invalid deployment report quarantined", flush=True)
                continue
            deliver(record)
            path.unlink()
            print("Deployment report sent", flush=True)
    except (OSError, ValueError, KeyError, smtplib.SMTPException):
        print("Deployment report retained for retry", flush=True)
        return False
    return len(queued) <= 5
