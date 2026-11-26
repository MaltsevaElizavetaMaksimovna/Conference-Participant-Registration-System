"""Upgrade an existing VM updater and test delivery through Yandex Mail."""

import argparse
import getpass
import json
import os
import re
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

CONFIG = Path("/etc/regsys/update.json")
MAIL = CONFIG.with_name("update-mail.env")
KEY = CONFIG.with_name("release-signing.pub")
INSTALL = Path("/opt/regsys-updater")
UNITS = Path("/etc/systemd/system")
TIMER = "regsys-update.timer"
SERVICE = "regsys-update.service"
MODULES = (
    "update.py",
    "compose_update.py",
    "github_release.py",
    "release_bundle.py",
    "release_signature.py",
    "release_report.py",
)


def replace(path, content, mode=0o600):
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def active_state(unit):
    return subprocess.check_output(
        ["systemctl", "show", "--property=ActiveState", "--value", unit], text=True
    ).strip()


def mail_settings(recipient):
    email = re.compile(r"[A-Za-z0-9._+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
    sender = input("Адрес отправителя в Яндекс Почте: ").strip()
    if not email.fullmatch(sender) or not email.fullmatch(recipient):
        raise SystemExit("Введите полные адреса отправителя и получателя.")
    password = getpass.getpass("Пароль приложения Яндекс: ")
    if not password or not password.isprintable():
        raise SystemExit("Требуется пароль приложения.")
    return {
        "REGSYS_SMTP_HOST": "smtp.yandex.ru",
        "REGSYS_SMTP_PORT": "465",
        "REGSYS_SMTP_FROM": sender,
        "REGSYS_SMTP_USER": sender.removesuffix("@yandex.ru"),
        "REGSYS_SMTP_PASSWORD": password,
        "REGSYS_SMTP_TO": recipient,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", type=Path, required=True)
    parser.add_argument("--recipient", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("Запустите настройку через sudo.")
    if active_state(TIMER) != "inactive" or active_state(SERVICE) not in (
        "inactive",
        "failed",
    ):
        raise SystemExit("Остановите таймер и дождитесь завершения службы обновления.")
    settings = json.loads(CONFIG.read_text(encoding="utf-8"))
    state = json.loads(
        (Path(settings["state_dir"]) / "state.json").read_text(encoding="utf-8")
    )
    if state["pending"] is not None or settings["maintenance"] not in (
        None,
        {"mode": "immediate"},
    ):
        raise SystemExit(
            "Сначала завершите незаконченный переход или закройте окно обслуживания."
        )
    subprocess.run(
        [
            "openssl",
            "pkey",
            "-pubin",
            "-in",
            str(args.public_key),
            "-pubcheck",
            "-noout",
        ],
        check=True,
    )
    mail = mail_settings(args.recipient)
    here = Path(__file__).resolve().parent
    for name in MODULES:
        replace(INSTALL / name, (here / name).read_bytes())
    for name in (SERVICE, TIMER):
        replace(UNITS / name, (here / name).read_bytes(), mode=0o644)
    replace(KEY, args.public_key.read_bytes())
    env = "".join(
        f"{name}={json.dumps(value, ensure_ascii=False)}\n"
        for name, value in mail.items()
    )
    replace(MAIL, env.encode())
    subprocess.run(
        ["systemd-analyze", "verify", str(UNITS / SERVICE), str(UNITS / TIMER)],
        check=True,
    )
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(
        [
            "systemd-run",
            "--wait",
            "--pipe",
            "--collect",
            f"--property=EnvironmentFile={MAIL}",
            "/usr/bin/python3",
            "-B",
            str(INSTALL / "update.py"),
            "--config",
            str(CONFIG),
            "--send-test",
        ],
        check=True,
    )
    settings.update(
        maintenance={"mode": "immediate"},
        release_public_key=str(KEY),
        mail_reports=True,
    )
    replace(CONFIG, (json.dumps(settings, indent=2) + "\n").encode())
    print(
        "Тестовое письмо отправлено. После проверки ящика включите regsys-update.timer."
    )


if __name__ == "__main__":
    main()
