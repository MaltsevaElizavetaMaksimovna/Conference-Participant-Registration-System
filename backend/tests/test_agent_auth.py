"""Агент печати: авторизация по токену и heartbeat (B2-01, AD-02, NF-05)."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import Devices


def agent(token: str) -> dict[str, str]:
    return {"Authorization": f"Agent {token}"}


def terminal(token: str) -> dict[str, str]:
    return {"Authorization": f"Terminal {token}"}


HEARTBEAT = "/api/agent/heartbeat"


async def _beat(client: httpx.AsyncClient, headers: dict[str, str], status: str) -> httpx.Response:
    return await client.post(HEARTBEAT, headers=headers, json={"printer_status": status})


# ---------------------------------------------------------------- heartbeat


async def test_heartbeat_updates_printer(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    printer, token = await devices.printer()
    assert printer.status == "unknown" and printer.last_seen_at is None

    r = await _beat(db_client, agent(token), "ready")
    assert r.status_code == 204 and r.content == b""
    await db.refresh(printer)
    assert printer.status == "ready"
    assert printer.last_seen_at is not None

    first = printer.last_seen_at
    await _beat(db_client, agent(token), "error")
    await db.refresh(printer)
    assert printer.status == "error"
    assert printer.last_seen_at >= first


async def test_heartbeat_touches_only_its_own_printer(
    db_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    mine, token = await devices.printer()
    other, _ = await devices.printer(status="offline")
    await _beat(db_client, agent(token), "ready")
    await db.refresh(other)
    assert other.status == "offline" and other.last_seen_at is None


@pytest.mark.parametrize("status", ["ready", "offline", "error", "unknown"])
async def test_heartbeat_accepts_contract_statuses(
    db_client: httpx.AsyncClient, devices: Devices, status: str
) -> None:
    _, token = await devices.printer()
    assert (await _beat(db_client, agent(token), status)).status_code == 204


@pytest.mark.parametrize("status", ["online", "paper_out", "", "READY"])
async def test_heartbeat_rejects_unknown_status(
    db_client: httpx.AsyncClient, devices: Devices, status: str
) -> None:
    _, token = await devices.printer()
    r = await _beat(db_client, agent(token), status)
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_heartbeat_makes_terminal_printer_online(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    printer, agent_token = await devices.printer()
    _, term_token = await devices.terminal(printer=printer)

    async def online() -> bool:
        r = await db_client.get("/api/terminal/ping", headers=terminal(term_token))
        return bool(r.json()["printer_online"])

    assert await online() is False  # агент ещё не выходил на связь
    await _beat(db_client, agent(agent_token), "ready")
    assert await online() is True
    await _beat(db_client, agent(agent_token), "error")
    assert await online() is False


# ----------------------------------------------------------------- авторизация


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Agent"},
        {"Authorization": "Agent wrong-token"},
        {"Authorization": "Bearer wrong-token"},
    ],
)
async def test_missing_or_wrong_agent_token_is_401(
    db_client: httpx.AsyncClient, devices: Devices, headers: dict[str, str]
) -> None:
    await devices.printer()
    r = await _beat(db_client, headers, "ready")
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_device_token"


async def test_terminal_token_does_not_work_as_agent_token(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, term_token = await devices.terminal()
    for scheme in ("Agent", "Terminal"):
        r = await _beat(db_client, {"Authorization": f"{scheme} {term_token}"}, "ready")
        assert r.status_code == 401, scheme


async def test_agent_token_does_not_work_as_terminal_token(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, agent_token = await devices.printer()
    for scheme in ("Terminal", "Agent"):
        r = await db_client.get(
            "/api/terminal/ping", headers={"Authorization": f"{scheme} {agent_token}"}
        )
        assert r.status_code == 401, scheme


async def test_printer_without_token_cannot_authenticate(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    await devices.printer(token=False)
    # токен пустой — пользователь не должен пройти с пустым хэшем или произвольной строкой
    r = await _beat(db_client, agent("x"), "ready")
    assert r.status_code == 401


async def test_job_endpoints_are_under_agent_auth(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.printer()
    # С токеном запрос проходит авторизацию: заданий нет (204), задания 1 нет (404)
    calls = [
        ("GET", "/api/agent/jobs/next?wait=0", {}, 204),
        ("POST", "/api/agent/jobs/1/result", {"json": {"ok": True}}, 404),
    ]
    for method, url, kwargs, authorized in calls:
        no_auth = await db_client.request(method, url, **kwargs)
        assert no_auth.status_code == 401, url
        assert no_auth.json()["code"] == "invalid_device_token", url
        ok = await db_client.request(method, url, headers=agent(token), **kwargs)
        assert ok.status_code == authorized, url


async def test_agent_token_does_not_open_staff_api(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.printer()
    for url in ("/api/admin/printers", "/api/printers", "/api/participants"):
        r = await db_client.get(url, headers=agent(token))
        assert r.status_code == 401, url
