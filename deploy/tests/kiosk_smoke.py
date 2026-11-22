"""Live acceptance of the kiosk Caddyfile against a temporary RegistrationSystem database."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from kiosk_smoke_fixture import (
    KIOSK_A,
    KIOSK_B,
    PING,
    PUBLIC,
    REPO,
    KioskClient,
    build_config,
    certificates,
    enable_kiosks,
    free_port,
    serve,
)

sys.path.insert(0, str(REPO / "backend"))

import pgserver
from app.cli import migrate
from app.core.db import make_engine, make_sessionmaker
from app.models.device import Terminal
from app.models.participant import BadgeToken, Participant
from app.models.printing import PrintJob
from app.terminals.service import issue_terminal_token
from sqlalchemy import func, select
from tests.conftest import Devices, create_role, create_user
from tests.registration_helpers import make_conference, make_participant

SCAN = "/api/terminal/scan"
CONFIRM = "/api/terminal/confirm"
FETCH = {"Sec-Fetch-Site": "same-origin"}
INVITE = "B24-8872"


async def provision(database):
    async with database() as db:
        devices = Devices(db)
        terminal_a, token_a = await devices.terminal("Kiosk A")
        _, token_b = await devices.terminal("Kiosk B")
        role = await create_role(db, "Smoke", "participants.view")
        await create_user(db, role, login="smoke", password="synthetic-smoke-password")
        conference = await make_conference(db, badge_type="none")
        participant = await make_participant(db, conference, INVITE)
        db.add(
            BadgeToken(
                participant_id=participant.id, token="synthetic-phone-profile-01"
            )
        )
        await db.commit()
        return terminal_a.id, token_a, token_b, participant.id


async def assert_no_registration(database, participant_id):
    async with database() as db:
        participant = await db.get(Participant, participant_id)
        assert participant.registered_at is None
        assert not await db.scalar(select(func.count()).select_from(PrintJob))


async def exercise(
    client, directory, database, terminal_id, token_a, token_b, participant_id, browser
):
    client.assert_tls_denied(KIOSK_A)
    client.assert_tls_denied(
        KIOSK_A, "b", headers={"Authorization": f"Terminal {token_a}"}
    )
    client.assert_tls_denied(KIOSK_B, "a")
    assert (
        client.request(PUBLIC, PING, headers={"Host": f"{KIOSK_A}:{client.port}"})[0]
        == 421
    )
    assert (
        client.request(
            KIOSK_B, PING, device="b", headers={"Host": f"{KIOSK_A}:{client.port}"}
        )[0]
        == 421
    )
    assert (
        client.request(
            KIOSK_A, PING, device="a", headers={"Sec-Fetch-Site": "same-site"}
        )[0]
        == 403
    )
    async with database() as db:
        assert (await db.get(Terminal, terminal_id)).last_seen_at is None

    for host, device, name in ((KIOSK_A, "a", "Kiosk A"), (KIOSK_B, "b", "Kiosk B")):
        status, body, headers = client.request(
            host,
            PING,
            device=device,
            headers={
                **FETCH,
                "Authorization": f"Terminal {token_b if device == 'a' else token_a}",
            },
        )
        assert status == 200 and json.loads(body)["terminal_name"] == name, status
        assert headers["Cache-Control"] == "no-store"
        assert not any(key.lower().startswith("access-control-") for key in headers)
        assert client.request(host, "/", device=device)[0] == 200
        assert (
            client.request(
                host, "/api/terminal/print-jobs/9999", device=device, headers=FETCH
            )[0]
            == 404
        )
        for path in (
            "/api/auth/me",
            "/api/agent/jobs/next",
            "/api/public/profile/synthetic-phone-profile-01",
        ):
            assert client.request(host, path, device=device, headers=FETCH)[0] == 404

    await assert_no_registration(database, participant_id)
    if browser:
        await asyncio.to_thread(
            subprocess.run,
            [
                *browser,
                client.origin(PUBLIC),
                client.origin(KIOSK_A),
                str(directory),
                INVITE,
            ],
            check=True,
            env={**os.environ, "NODE_EXTRA_CA_CERTS": str(directory / "ca.pem")},
        )

    scan = {"raw": INVITE}
    headers = {**FETCH, "Origin": client.origin(KIOSK_A)}
    status, body, _ = client.request(
        KIOSK_A, SCAN, device="a", data=scan, headers=headers
    )
    result = json.loads(body)
    assert status == 200 and result["participant"]["id"] == participant_id, (
        status,
        result,
    )
    confirm = {"participant_id": participant_id, "scan_id": result["scan_id"]}
    headers["Idempotency-Key"] = "smoke-confirm"
    assert (
        client.request(
            KIOSK_A,
            CONFIRM,
            device="a",
            data=confirm,
            headers={**headers, "Sec-Fetch-Site": "same-site"},
        )[0]
        == 403
    )
    for origin in (client.origin(KIOSK_B), "https://foreign.example.test", "null"):
        assert (
            client.request(
                KIOSK_A,
                CONFIRM,
                device="a",
                data=confirm,
                headers={**headers, "Origin": origin},
            )[0]
            == 403
        )
    assert (
        client.request(KIOSK_A, CONFIRM, device="a", data=confirm, headers=FETCH)[0]
        == 403
    )
    await assert_no_registration(database, participant_id)
    status, body, _ = client.request(
        KIOSK_A, CONFIRM, device="a", data=confirm, headers=headers
    )
    assert status == 200 and json.loads(body)["print_job_id"] is None, (status, body)
    async with database() as db:
        assert (
            await db.get(Participant, participant_id)
        ).status == "registered_no_sticker"
        assert not await db.scalar(select(func.count()).select_from(PrintJob))
        terminal = await db.get(Terminal, terminal_id)
        terminal.is_enabled = False
        await db.commit()
        assert client.request(KIOSK_A, PING, device="a", headers=FETCH)[0] == 423
        rotated = await issue_terminal_token(db, terminal_id)
        terminal.is_enabled = True
        await db.commit()
    assert client.request(KIOSK_A, PING, device="a", headers=FETCH)[0] == 401
    replacement = directory / "replacement.token"
    replacement.write_text(rotated.token, encoding="ascii")
    replacement.replace(directory / "a.token")
    assert client.request(KIOSK_A, PING, device="a", headers=FETCH)[0] == 200


def public_routes(client, token):
    assert client.request(PUBLIC, "/")[0] == 200
    assert client.request(PUBLIC, "/login")[0] == 200
    assert client.request(PUBLIC, SCAN, data={"raw": INVITE})[0] == 401
    assert (
        client.request(PUBLIC, PING, headers={"Authorization": f"Terminal {token}"})[0]
        == 200
    )
    assert (
        client.request(PUBLIC, "/api/public/profile/synthetic-phone-profile-01")[0]
        == 200
    )
    status, _, headers = client.request(
        PUBLIC,
        "/api/auth/login",
        data={
            "login": "smoke",
            "password": "synthetic-smoke-password",
        },
    )
    assert status == 200 and "rs_session=" in headers["Set-Cookie"]


async def run(args):
    with tempfile.TemporaryDirectory(
        prefix="kiosk-smoke-", dir=args.scratch, ignore_cleanup_errors=True
    ) as tmp:
        directory = Path(tmp)
        certificates(directory, args.openssl)
        (directory / "pg").mkdir()
        server = pgserver.get_server(directory / "pg", cleanup_mode="stop")
        try:
            url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
            migrate(url)
            engine = make_engine(url)
            try:
                database = make_sessionmaker(engine)
                terminal_id, token_a, token_b, participant_id = await provision(
                    database
                )
                api_port, tls_port = free_port(), free_port()
                config = build_config(directory, args.spa, api_port, tls_port)
                env = {
                    key: val
                    for key, val in os.environ.items()
                    if not key.startswith("RS_")
                }
                env.update(
                    RS_DATABASE_URL=url,
                    RS_ENV="test",
                    RS_PUBLIC_HOST=f"{PUBLIC}:{tls_port}",
                    RS_PHOTO_DIR=str(directory / "photos"),
                    RS_BACKUP_DIR=str(directory / "backups"),
                    XDG_DATA_HOME=str(directory / "data"),
                    XDG_CONFIG_HOME=str(directory / "config"),
                    PYTHONPATH=str(REPO / "backend"),
                )
                api = [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--port",
                    str(api_port),
                    "--loop",
                    "app.core.loop:selector_loop_factory",
                    "--no-access-log",
                ]
                caddy = [
                    args.caddy,
                    "run",
                    "--config",
                    config,
                    "--adapter",
                    "caddyfile",
                ]
                client = KioskClient(directory, tls_port)
                with serve(api, directory, env, api_port, "api"):
                    # Baseline without a kiosk site or token file.
                    with serve(caddy, directory, env, tls_port, "caddy-baseline"):
                        public_routes(client, token_b)
                    enable_kiosks(directory, tls_port, token_a, token_b)
                    validation = await asyncio.to_thread(
                        subprocess.run,
                        [
                            args.caddy,
                            "validate",
                            "--config",
                            config,
                            "--adapter",
                            "caddyfile",
                        ],
                        env=env,
                        cwd=directory,
                        check=False,
                        capture_output=True,
                    )
                    if validation.returncode:
                        raise RuntimeError(validation.stderr.decode(errors="replace"))
                    with serve(caddy, directory, env, tls_port, "caddy"):
                        await exercise(
                            client,
                            directory,
                            database,
                            terminal_id,
                            token_a,
                            token_b,
                            participant_id,
                            args.browser,
                        )
                        public_routes(client, token_b)
                    for log in directory.glob("*.log"):
                        assert not any(
                            token.encode() in log.read_bytes()
                            for token in (token_a, token_b)
                        )
            finally:
                await engine.dispose()
        finally:
            server.cleanup()
    print("Kiosk HTTPS acceptance passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caddy", type=Path, required=True)
    parser.add_argument("--openssl", type=Path, required=True)
    parser.add_argument("--spa", type=lambda path: Path(path).resolve(), required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--browser", nargs="+")
    args = parser.parse_args()
    if not (args.spa / "index.html").is_file():
        parser.error("--spa must be a built Vite dist directory")
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(run(args))
