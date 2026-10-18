"""Принтеры: админка, калибровка, токен агента, список для панели (B2-01, AD-02)."""

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import PrinterOut
from app.printing.schemas import PrinterAdminOut, PrinterTokenOut
from app.terminals.tokens import hash_token
from tests.conftest import Devices

CSRF = {"X-Requested-With": "rs"}


async def _ok(r: httpx.Response, status: int = 200) -> dict[str, object]:
    assert r.status_code == status, r.text
    data: dict[str, object] = r.json()
    return data


async def test_create_printer_with_defaults(admin_client: httpx.AsyncClient) -> None:
    r = await admin_client.post("/api/admin/printers", headers=CSRF, json={"name": "Принтер 1"})
    body = PrinterAdminOut.model_validate(await _ok(r, 201))
    assert body.name == "Принтер 1"
    assert body.windows_printer_name is None
    assert (body.dpi, body.density, body.speed) == (203, 10, 3)
    assert (body.offset_x_mm, body.offset_y_mm) == (0.0, 0.0)
    assert body.status == "unknown"
    assert body.last_seen_at is None
    assert body.token_set is False


async def test_create_printer_with_calibration(admin_client: httpx.AsyncClient) -> None:
    r = await admin_client.post(
        "/api/admin/printers",
        headers=CSRF,
        json={
            "name": "Принтер 2",
            "windows_printer_name": "XP-360B",
            "dpi": 203,
            "offset_x_mm": -1.5,
            "offset_y_mm": 0.25,
            "density": 15,
            "speed": 6,
        },
    )
    body = PrinterAdminOut.model_validate(await _ok(r, 201))
    assert body.windows_printer_name == "XP-360B"
    assert (body.offset_x_mm, body.offset_y_mm) == (-1.5, 0.25)
    assert (body.density, body.speed) == (15, 6)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("density", -1),
        ("density", 16),
        ("speed", 0),
        ("speed", 7),
        ("offset_x_mm", 51),
        ("offset_y_mm", -51),
        ("dpi", 50),
        ("name", ""),
        ("name", "   "),
    ],
)
async def test_printer_validation(
    admin_client: httpx.AsyncClient, field: str, value: object
) -> None:
    body = {"name": "П", field: value}
    r = await admin_client.post("/api/admin/printers", headers=CSRF, json=body)
    data = await _ok(r, 422)
    assert data["code"] == "validation_error"
    assert field in data["details"]["fields"]  # type: ignore[index]


async def test_calibration_bounds_are_accepted(admin_client: httpx.AsyncClient) -> None:
    r = await admin_client.post(
        "/api/admin/printers",
        headers=CSRF,
        json={"name": "П", "density": 0, "speed": 1, "offset_x_mm": 50, "offset_y_mm": -50},
    )
    assert r.status_code == 201, r.text


async def test_printer_name_must_be_unique(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    await devices.printer("Принтер 1", token=False)
    other, _ = await devices.printer("Принтер 2", token=False)

    r = await admin_client.post("/api/admin/printers", headers=CSRF, json={"name": "Принтер 1"})
    assert (await _ok(r, 409))["code"] == "name_taken"

    r = await admin_client.put(
        f"/api/admin/printers/{other.id}", headers=CSRF, json={"name": "Принтер 1"}
    )
    assert (await _ok(r, 409))["code"] == "name_taken"

    r = await admin_client.put(
        f"/api/admin/printers/{other.id}", headers=CSRF, json={"name": "Принтер 2"}
    )
    assert r.status_code == 200


async def test_update_keeps_calibration_when_not_sent(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    printer, _ = await devices.printer(
        "П", offset_x_mm=-2, offset_y_mm=1, density=12, speed=4, windows_printer_name="XP"
    )
    r = await admin_client.put(
        f"/api/admin/printers/{printer.id}", headers=CSRF, json={"name": "Новое имя"}
    )
    body = PrinterAdminOut.model_validate(await _ok(r))
    assert body.name == "Новое имя"
    assert (body.offset_x_mm, body.offset_y_mm) == (-2.0, 1.0)
    assert (body.density, body.speed, body.windows_printer_name) == (12, 4, "XP")

    r = await admin_client.put(
        f"/api/admin/printers/{printer.id}",
        headers=CSRF,
        json={"name": "Новое имя", "offset_y_mm": 0.5, "density": 8, "windows_printer_name": None},
    )
    body = PrinterAdminOut.model_validate(await _ok(r))
    assert (body.offset_x_mm, body.offset_y_mm) == (-2.0, 0.5)
    assert (body.density, body.speed, body.windows_printer_name) == (8, 4, None)


async def test_status_and_last_seen_are_read_only(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    printer, _ = await devices.printer("П", status="ready", seen_ago_s=5)
    r = await admin_client.put(
        f"/api/admin/printers/{printer.id}",
        headers=CSRF,
        json={"name": "П", "status": "error", "last_seen_at": None},
    )
    body = PrinterAdminOut.model_validate(await _ok(r))
    assert body.status == "ready"
    assert body.last_seen_at is not None


async def test_unknown_printer_is_404(admin_client: httpx.AsyncClient) -> None:
    r = await admin_client.put("/api/admin/printers/999999", headers=CSRF, json={"name": "П"})
    assert (await _ok(r, 404))["code"] == "printer_not_found"
    r = await admin_client.post("/api/admin/printers/999999/token", headers=CSRF)
    assert (await _ok(r, 404))["code"] == "printer_not_found"


async def test_list_printers_is_paged(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    for i in range(1, 4):
        await devices.printer(f"Принтер {i}", token=i == 1)
    page = await _ok(await admin_client.get("/api/admin/printers?limit=2"))
    assert page["total"] == 3
    items = page["items"]
    assert [p["name"] for p in items] == ["Принтер 1", "Принтер 2"]  # type: ignore[index]
    assert [p["token_set"] for p in items] == [True, False]  # type: ignore[index]
    assert "agent_token_hash" not in items[0]  # type: ignore[operator]


async def test_agent_token_is_shown_once_and_stored_as_hash(
    admin_client: httpx.AsyncClient, db: AsyncSession, devices: Devices
) -> None:
    printer, _ = await devices.printer(token=False)
    r = await admin_client.post(f"/api/admin/printers/{printer.id}/token", headers=CSRF)
    issued = PrinterTokenOut.model_validate(await _ok(r))
    assert issued.id == printer.id
    assert issued.token.startswith("agt_") and len(issued.token) >= 40

    await db.refresh(printer)
    assert printer.agent_token_hash == hash_token(issued.token)
    assert printer.agent_token_hash != issued.token

    listing = (await admin_client.get("/api/admin/printers")).text
    assert issued.token not in listing
    assert printer.agent_token_hash not in listing

    r = await admin_client.post(
        "/api/agent/heartbeat",
        headers={"Authorization": f"Agent {issued.token}"},
        json={"printer_status": "ready"},
    )
    assert r.status_code == 204


async def test_new_agent_token_replaces_old_one(
    admin_client: httpx.AsyncClient, devices: Devices
) -> None:
    printer, old = await devices.printer()
    r = await admin_client.post(f"/api/admin/printers/{printer.id}/token", headers=CSRF)
    new = PrinterTokenOut.model_validate(await _ok(r)).token

    body = {"printer_status": "ready"}
    r = await admin_client.post(
        "/api/agent/heartbeat", headers={"Authorization": f"Agent {old}"}, json=body
    )
    assert r.status_code == 401
    r = await admin_client.post(
        "/api/agent/heartbeat", headers={"Authorization": f"Agent {new}"}, json=body
    )
    assert r.status_code == 204


async def test_panel_printer_list(admin_client: httpx.AsyncClient, devices: Devices) -> None:
    await devices.printer("Принтер 1", status="ready", seen_ago_s=3)
    await devices.printer("Принтер 2")
    r = await admin_client.get("/api/printers")
    assert r.status_code == 200
    items = [PrinterOut.model_validate(x) for x in r.json()]
    assert [(p.name, p.status) for p in items] == [("Принтер 1", "ready"), ("Принтер 2", "unknown")]
    assert items[0].last_seen_at is not None and items[1].last_seen_at is None
    # в списке для панели нет ни токенов, ни калибровки
    assert set(r.json()[0]) == {"id", "name", "status", "last_seen_at"}
