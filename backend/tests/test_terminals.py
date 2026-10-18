"""Терминалы: админка, авторизация по токену, отключение, ping (B2-01, B2-06, AD-02, NF-05)."""

from datetime import date

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import Conference
from app.models.device import Terminal
from app.terminals.schemas import PingOut, TerminalOut, TerminalTokenOut
from app.terminals.tokens import hash_token
from tests.conftest import Devices

CSRF = {"X-Requested-With": "rs"}
DISABLED_TEXT = "Терминал не работает, воспользуйтесь соседним"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Terminal {token}"}


async def _json(r: httpx.Response, status: int) -> dict[str, object]:
    assert r.status_code == status, r.text
    data: dict[str, object] = r.json()
    return data


# ------------------------------------------------------------------ админка: CRUD


async def test_create_terminal(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    printer, _ = await devices.printer("Принтер 1")
    r = await admin_client.post(
        "/api/admin/terminals",
        headers=CSRF,
        json={"name": "  Терминал 1  ", "printer_id": printer.id},
    )
    body = TerminalOut.model_validate(await _json(r, 201))
    assert body.name == "Терминал 1"  # пробелы по краям убраны
    assert body.enabled is True
    assert body.printer_id == printer.id
    assert body.token_set is False
    assert body.last_seen_at is None


async def test_create_terminal_without_printer_and_disabled(
    admin_client: httpx.AsyncClient,
) -> None:
    r = await admin_client.post(
        "/api/admin/terminals", headers=CSRF, json={"name": "Т", "enabled": False}
    )
    body = TerminalOut.model_validate(await _json(r, 201))
    assert body.enabled is False
    assert body.printer_id is None


async def test_terminal_name_must_be_unique(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    await devices.terminal("Терминал 1", token=False)
    other, _ = await devices.terminal("Терминал 2", token=False)

    r = await admin_client.post("/api/admin/terminals", headers=CSRF, json={"name": "Терминал 1"})
    assert (await _json(r, 409))["code"] == "name_taken"

    r = await admin_client.put(
        f"/api/admin/terminals/{other.id}", headers=CSRF, json={"name": "Терминал 1"}
    )
    assert (await _json(r, 409))["code"] == "name_taken"

    # своё же имя при изменении — не конфликт
    r = await admin_client.put(
        f"/api/admin/terminals/{other.id}", headers=CSRF, json={"name": "Терминал 2"}
    )
    assert r.status_code == 200


async def test_terminal_printer_must_exist(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    r = await admin_client.post(
        "/api/admin/terminals", headers=CSRF, json={"name": "Т", "printer_id": 999999}
    )
    body = await _json(r, 422)
    assert body["code"] == "printer_not_found"

    terminal, _ = await devices.terminal(token=False)
    r = await admin_client.put(
        f"/api/admin/terminals/{terminal.id}",
        headers=CSRF,
        json={"name": terminal.name, "printer_id": 999999},
    )
    assert (await _json(r, 422))["code"] == "printer_not_found"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
async def test_terminal_name_validation(admin_client: httpx.AsyncClient, name: str) -> None:
    r = await admin_client.post("/api/admin/terminals", headers=CSRF, json={"name": name})
    body = await _json(r, 422)
    assert body["code"] == "validation_error"
    assert "name" in body["details"]["fields"]  # type: ignore[index]


async def test_update_terminal_changes_only_sent_fields(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    printer, _ = await devices.printer()
    terminal, _ = await devices.terminal("Т", printer=printer)

    # отключаем: привязка к принтеру остаётся
    r = await admin_client.put(
        f"/api/admin/terminals/{terminal.id}", headers=CSRF, json={"name": "Т", "enabled": False}
    )
    body = TerminalOut.model_validate(await _json(r, 200))
    assert (body.enabled, body.printer_id) == (False, printer.id)

    # переименование не включает терминал обратно
    r = await admin_client.put(
        f"/api/admin/terminals/{terminal.id}", headers=CSRF, json={"name": "Т2"}
    )
    body = TerminalOut.model_validate(await _json(r, 200))
    assert (body.name, body.enabled, body.printer_id) == ("Т2", False, printer.id)

    # явный null отвязывает принтер, enabled включает
    r = await admin_client.put(
        f"/api/admin/terminals/{terminal.id}",
        headers=CSRF,
        json={"name": "Т2", "enabled": True, "printer_id": None},
    )
    body = TerminalOut.model_validate(await _json(r, 200))
    assert (body.enabled, body.printer_id) == (True, None)


async def test_unknown_terminal_is_404(admin_client: httpx.AsyncClient) -> None:
    r = await admin_client.put("/api/admin/terminals/999999", headers=CSRF, json={"name": "Т"})
    assert (await _json(r, 404))["code"] == "terminal_not_found"
    r = await admin_client.post("/api/admin/terminals/999999/token", headers=CSRF)
    assert (await _json(r, 404))["code"] == "terminal_not_found"


async def test_list_terminals_is_paged(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    for i in range(1, 4):
        await devices.terminal(f"Терминал {i}", token=i == 2)
    r = await admin_client.get("/api/admin/terminals?limit=2&offset=1")
    page = await _json(r, 200)
    assert page["total"] == 3
    items = page["items"]
    assert [t["name"] for t in items] == ["Терминал 2", "Терминал 3"]  # type: ignore[index]
    assert [t["token_set"] for t in items] == [True, False]  # type: ignore[index]


# ------------------------------------------------------------------------- токен


async def test_token_is_shown_once_and_stored_as_hash(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    terminal, _ = await devices.terminal(token=False)
    r = await admin_client.post(f"/api/admin/terminals/{terminal.id}/token", headers=CSRF)
    issued = TerminalTokenOut.model_validate(await _json(r, 200))
    assert issued.id == terminal.id
    assert issued.token.startswith("trm_") and len(issued.token) >= 40

    await db.refresh(terminal)
    assert terminal.token_hash == hash_token(issued.token)
    assert terminal.token_hash != issued.token
    assert len(terminal.token_hash) == 64

    # токен нигде больше не показывается
    listing = (await admin_client.get("/api/admin/terminals")).text
    assert issued.token not in listing and terminal.token_hash not in listing
    assert (await admin_client.get("/api/admin/terminals")).json()["items"][0]["token_set"] is True

    r = await admin_client.get("/api/terminal/ping", headers=auth(issued.token))
    assert r.status_code == 200


async def test_new_token_replaces_old_one(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    terminal, old = await devices.terminal()
    assert (await admin_client.get("/api/terminal/ping", headers=auth(old))).status_code == 200

    r = await admin_client.post(f"/api/admin/terminals/{terminal.id}/token", headers=CSRF)
    new = TerminalTokenOut.model_validate(await _json(r, 200)).token
    assert new != old

    r = await admin_client.get("/api/terminal/ping", headers=auth(old))
    assert (await _json(r, 401))["code"] == "invalid_device_token"
    assert (await admin_client.get("/api/terminal/ping", headers=auth(new))).status_code == 200


# ----------------------------------------------------------------- авторизация


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": ""},
        {"Authorization": "Terminal"},
        {"Authorization": "Terminal "},
        {"Authorization": "Terminal wrong-token"},
        {"Authorization": "Bearer wrong-token"},
        {"Authorization": "wrong-token"},
    ],
)
async def test_missing_or_wrong_token_is_401(
    admin_client: httpx.AsyncClient, devices: Devices, headers: dict[str, str]
) -> None:
    await devices.terminal()
    r = await admin_client.get("/api/terminal/ping", headers=headers)
    body = await _json(r, 401)
    assert body["code"] == "invalid_device_token"


async def test_scheme_must_be_terminal(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    _, token = await devices.terminal()
    for scheme in ("Bearer", "Agent", "Basic"):
        r = await admin_client.get(
            "/api/terminal/ping", headers={"Authorization": f"{scheme} {token}"}
        )
        assert r.status_code == 401, scheme
    # схема без учёта регистра
    r = await admin_client.get(
        "/api/terminal/ping", headers={"Authorization": f"terminal  {token}"}
    )
    assert r.status_code == 200


async def test_all_terminal_endpoints_require_a_token(admin_client: httpx.AsyncClient) -> None:
    calls = [
        ("GET", "/api/terminal/ping", {}),
        ("POST", "/api/terminal/scan", {"json": {"raw": "abc"}}),
        (
            "POST",
            "/api/terminal/confirm",
            {"json": {"participant_id": 1, "scan_id": "s"}, "headers": {"Idempotency-Key": "k"}},
        ),
        ("POST", "/api/terminal/report-error", {"json": {"participant_id": 1, "scan_id": "s"}}),
        ("GET", "/api/terminal/print-jobs/1", {}),
    ]
    for method, url, kwargs in calls:
        r = await admin_client.request(method, url, **kwargs)
        assert r.status_code == 401, url
        assert r.json()["code"] == "invalid_device_token", url


# ----------------------------------------------------------- отключённый терминал


async def test_disabled_terminal_gets_423_everywhere(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal(enabled=False)
    for method, url, kwargs in [
        ("GET", "/api/terminal/ping", {}),
        ("POST", "/api/terminal/scan", {"json": {"raw": "B24-1001"}}),
        ("GET", "/api/terminal/print-jobs/1", {}),
    ]:
        r = await admin_client.request(method, url, headers=auth(token), **kwargs)
        body = await _json(r, 423)
        assert body["code"] == "terminal_disabled", url
        assert body["message"] == DISABLED_TEXT, url


async def test_terminal_can_be_disabled_and_enabled_again(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    terminal, token = await devices.terminal(name="Т")
    assert (await admin_client.get("/api/terminal/ping", headers=auth(token))).status_code == 200

    url = f"/api/admin/terminals/{terminal.id}"
    await admin_client.put(url, headers=CSRF, json={"name": "Т", "enabled": False})
    assert (await admin_client.get("/api/terminal/ping", headers=auth(token))).status_code == 423

    await admin_client.put(url, headers=CSRF, json={"name": "Т", "enabled": True})
    assert (await admin_client.get("/api/terminal/ping", headers=auth(token))).status_code == 200


# --------------------------------------------------------------- last_seen_at


async def test_last_seen_is_set_on_first_request(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    terminal, token = await devices.terminal()
    assert terminal.last_seen_at is None
    await admin_client.get("/api/terminal/ping", headers=auth(token))
    await db.refresh(terminal)
    assert terminal.last_seen_at is not None


async def test_last_seen_is_written_at_most_every_10_seconds(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    fresh, fresh_token = await devices.terminal(seen_ago_s=3)
    stale, stale_token = await devices.terminal(seen_ago_s=30)
    before = fresh.last_seen_at

    await admin_client.get("/api/terminal/ping", headers=auth(fresh_token))
    await admin_client.get("/api/terminal/ping", headers=auth(stale_token))
    await db.refresh(fresh)
    await db.refresh(stale)
    assert fresh.last_seen_at == before  # 3 с назад: не трогаем
    assert stale.last_seen_at is not None
    assert stale.last_seen_at > before  # 30 с назад: обновили


async def test_disabled_terminal_still_reports_last_seen(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    terminal, token = await devices.terminal(enabled=False)
    await admin_client.get("/api/terminal/ping", headers=auth(token))
    await db.refresh(terminal)
    assert terminal.last_seen_at is not None


# ------------------------------------------------------------------------ ping


async def _active_conference(db: AsyncSession, badge_type: str = "double") -> Conference:
    conference = Conference(
        title="Конференция «Инновации-2026»",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 21),
        badge_type=badge_type,
        is_active=True,
    )
    db.add(conference)
    await db.commit()
    return conference


async def _ping(client: httpx.AsyncClient, token: str) -> PingOut:
    r = await client.get("/api/terminal/ping", headers=auth(token))
    assert r.status_code == 200, r.text
    return PingOut.model_validate_json(r.content)


async def test_ping_without_conference(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    _, token = await devices.terminal("Терминал 2")
    ping = await _ping(admin_client, token)
    assert ping.terminal_name == "Терминал 2"
    assert ping.enabled is True
    assert ping.conference is None
    assert ping.printer_online is False  # принтер не привязан
    assert ping.server_time.utcoffset() is not None
    assert (ping.settings.idle_timeout_s, ping.settings.result_screen_s) == (60, 10)


async def test_ping_shows_active_conference(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    _, token = await devices.terminal()
    old = Conference(
        title="Прошлая",
        date_from=date(2025, 1, 1),
        date_to=date(2025, 1, 2),
        badge_type="none",
        is_active=False,
    )
    db.add(old)
    await _active_conference(db, "double")
    ping = await _ping(admin_client, token)
    assert ping.conference is not None
    assert ping.conference.title == "Конференция «Инновации-2026»"
    assert ping.conference.badge_type == "double"


@pytest.mark.parametrize(
    ("status", "seen_ago_s", "online"),
    [
        ("ready", 5, True),
        ("ready", 29, True),
        ("ready", 45, False),  # heartbeat устарел
        ("offline", 5, False),
        ("error", 5, False),
        ("unknown", 5, False),
        ("ready", None, False),  # агент ни разу не выходил на связь
    ],
)
async def test_ping_printer_online(
    admin_client: httpx.AsyncClient,
    devices: Devices,
    status: str,
    seen_ago_s: float | None,
    online: bool,
) -> None:
    printer, _ = await devices.printer(status=status, seen_ago_s=seen_ago_s)
    _, token = await devices.terminal(printer=printer)
    assert (await _ping(admin_client, token)).printer_online is online


async def test_ping_looks_only_at_own_printer(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    ready, _ = await devices.printer(status="ready", seen_ago_s=1)
    broken, _ = await devices.printer(status="error", seen_ago_s=1)
    _, token_ok = await devices.terminal(printer=ready)
    _, token_bad = await devices.terminal(printer=broken)
    assert (await _ping(admin_client, token_ok)).printer_online is True
    assert (await _ping(admin_client, token_bad)).printer_online is False


# --------------------------------------------------- токен терминала не открывает API сотрудника


async def test_terminal_token_is_not_accepted_by_staff_api_schema(
    admin_client: httpx.AsyncClient,
) -> None:
    """Терминальные и агентские ручки не требуют сессию сотрудника, и наоборот.

    Схемы разные: сотрудник — cookie `rs_session`, терминал и агент — заголовок Authorization.
    """
    schema = (await admin_client.get("/openapi.json")).json()
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            security = op.get("security", [])
            names = {name for item in security for name in item}
            where = f"{method} {path}"
            if path.startswith("/api/terminal/"):
                assert names == {"TerminalToken"}, where
            elif path.startswith("/api/agent/"):
                assert names == {"AgentToken"}, where
            elif path.startswith("/api/admin/terminals") or path.startswith("/api/admin/printers"):
                assert names == {"StaffSession"}, where


async def test_terminal_token_does_not_open_staff_api(
    db_client: httpx.AsyncClient, devices: Devices
) -> None:
    _, token = await devices.terminal()
    for url in ("/api/admin/terminals", "/api/printers", "/api/participants"):
        r = await db_client.get(url, headers=auth(token))
        assert r.status_code == 401, url


async def test_terminals_in_db_keep_only_hashes(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    _, token = await devices.terminal()
    hashes = (await db.scalars(select(Terminal.token_hash))).all()
    assert hashes == [hash_token(token)]
    assert token not in hashes
