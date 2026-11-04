"""Контракт API (S-02): OpenAPI содержит все пути, заглушки отвечают."""

import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter

from app.api.common import ErrorOut, PrintJobRefOut
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.permissions import Permission
from app.imports.schemas import BitrixSettingsOut, ImportAcceptedOut
from app.participants.schemas import (
    ParticipantCard,
    ParticipantShort,
)
from app.printing.schemas import AgentJob
from app.registration.schemas import PrintJobOut, RegisterOut
from app.templates.schemas import TemplateElement
from app.terminals.deps import (
    CurrentAgent,
    CurrentTerminal,
    get_current_agent,
    get_current_terminal,
)
from app.terminals.schemas import (
    PingOut,
    ScanAlreadyRegistered,
    ScanFound,
    ScanNotFound,
    ScanOut,
    TerminalPrintJobOut,
)

# Параметры пути записаны как `{}`.
CONTRACT: set[tuple[str, str]] = {
    # --- сотрудники
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("PUT", "/api/auth/me/printer"),
    ("PUT", "/api/auth/me/password"),
    ("GET", "/api/admin/roles"),
    ("POST", "/api/admin/roles"),
    ("PUT", "/api/admin/roles/{}"),
    ("DELETE", "/api/admin/roles/{}"),
    ("GET", "/api/admin/permissions"),
    ("GET", "/api/admin/users"),
    ("POST", "/api/admin/users"),
    ("PUT", "/api/admin/users/{}"),
    ("POST", "/api/admin/users/{}/block"),
    ("POST", "/api/admin/users/{}/unblock"),
    ("GET", "/api/admin/conferences"),
    ("POST", "/api/admin/conferences"),
    ("GET", "/api/admin/conferences/{}"),
    ("PUT", "/api/admin/conferences/{}"),
    ("POST", "/api/admin/conferences/{}/activate"),
    ("GET", "/api/conferences/active"),
    ("GET", "/api/admin/conferences/{}/imports"),
    ("POST", "/api/admin/conferences/{}/imports"),
    ("GET", "/api/admin/conferences/{}/imports/{}"),
    ("GET", "/api/admin/import-template.xlsx"),
    ("POST", "/api/admin/conferences/{}/imports/bitrix"),
    ("GET", "/api/admin/conferences/{}/bitrix-settings"),
    ("PUT", "/api/admin/conferences/{}/bitrix-settings"),
    ("GET", "/api/participants"),
    ("GET", "/api/participants/stats"),
    ("GET", "/api/participants/{}"),
    ("GET", "/api/participants/{}/photo"),
    ("PATCH", "/api/participants/{}"),
    ("POST", "/api/participants/check-duplicates"),
    ("POST", "/api/participants"),
    ("GET", "/api/events/stream"),
    ("GET", "/api/admin/events"),
    # --- действия на стойке
    ("POST", "/api/participants/{}/register"),
    ("POST", "/api/participants/{}/reprint"),
    ("POST", "/api/participants/{}/foreign-code"),
    ("GET", "/api/print-jobs/{}"),
    ("GET", "/api/printers"),
    # --- шаблоны, терминалы, принтеры — админ
    ("GET", "/api/admin/conferences/{}/templates"),
    ("POST", "/api/admin/conferences/{}/templates"),
    ("GET", "/api/admin/conferences/{}/templates/{}"),
    ("PUT", "/api/admin/conferences/{}/templates/{}"),
    ("DELETE", "/api/admin/conferences/{}/templates/{}"),
    ("GET", "/api/admin/conferences/{}/template-fields"),
    ("POST", "/api/admin/conferences/{}/templates/{}/copy-to/{}"),
    ("POST", "/api/admin/conferences/{}/templates/{}/resize"),
    ("GET", "/api/admin/conferences/{}/templates/{}/preview.png"),
    ("GET", "/api/admin/conferences/{}/templates/{}/overflow"),
    ("POST", "/api/admin/conferences/{}/templates/{}/test-print"),
    ("GET", "/api/admin/terminals"),
    ("POST", "/api/admin/terminals"),
    ("PUT", "/api/admin/terminals/{}"),
    ("POST", "/api/admin/terminals/{}/token"),
    ("GET", "/api/admin/printers"),
    ("POST", "/api/admin/printers"),
    ("PUT", "/api/admin/printers/{}"),
    ("POST", "/api/admin/printers/{}/token"),
    # --- терминал
    ("GET", "/api/terminal/ping"),
    ("POST", "/api/terminal/scan"),
    ("POST", "/api/terminal/confirm"),
    ("POST", "/api/terminal/report-error"),
    ("GET", "/api/terminal/print-jobs/{}"),
    # --- агент печати
    ("GET", "/api/agent/jobs/next"),
    ("POST", "/api/agent/jobs/{}/result"),
    ("POST", "/api/agent/heartbeat"),
    # --- публичный профиль
    ("GET", "/api/public/profile/{}"),
    ("GET", "/api/public/profile/{}/photo"),
}

# Реализованные эндпоинты (без тега `stub`); их проверяют отдельные тесты, не таблица заглушек
IMPLEMENTED_PREFIXES: tuple[str, ...] = (
    "/api/auth/",
    "/api/admin/roles",
    "/api/admin/permissions",
    "/api/admin/users",
)

TERMINAL = {"Authorization": "Terminal test-token"}
AGENT = {"Authorization": "Agent test-token"}
CSRF = {"X-Requested-With": "rs"}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"

# Эндпоинты с настоящей логикой (проверяются в test_terminals.py, test_printers.py,
# test_agent_auth.py): у них нет тега `stub`, заглушками их здесь не гоняем.
REAL: set[tuple[str, str]] = {
    ("GET", "/api/printers"),
    ("GET", "/api/admin/terminals"),
    ("POST", "/api/admin/terminals"),
    ("PUT", "/api/admin/terminals/{}"),
    ("POST", "/api/admin/terminals/{}/token"),
    ("GET", "/api/admin/printers"),
    ("POST", "/api/admin/printers"),
    ("PUT", "/api/admin/printers/{}"),
    ("POST", "/api/admin/printers/{}/token"),
    ("GET", "/api/terminal/ping"),
    ("POST", "/api/terminal/scan"),
    ("POST", "/api/terminal/confirm"),
    ("POST", "/api/terminal/report-error"),
    ("POST", "/api/agent/heartbeat"),
    ("GET", "/api/admin/conferences"),
    ("POST", "/api/admin/conferences"),
    ("GET", "/api/admin/conferences/{}"),
    ("PUT", "/api/admin/conferences/{}"),
    ("POST", "/api/admin/conferences/{}/activate"),
    ("GET", "/api/conferences/active"),
    ("GET", "/api/admin/conferences/{}/imports"),
    ("POST", "/api/admin/conferences/{}/imports"),
    ("GET", "/api/admin/conferences/{}/imports/{}"),
    ("GET", "/api/admin/import-template.xlsx"),
    ("GET", "/api/admin/conferences/{}/template-fields"),
    ("GET", "/api/admin/conferences/{}/templates"),
    ("POST", "/api/admin/conferences/{}/templates"),
    ("GET", "/api/admin/conferences/{}/templates/{}"),
    ("PUT", "/api/admin/conferences/{}/templates/{}"),
    ("DELETE", "/api/admin/conferences/{}/templates/{}"),
    ("POST", "/api/admin/conferences/{}/templates/{}/copy-to/{}"),
    ("POST", "/api/admin/conferences/{}/templates/{}/resize"),
    ("GET", "/api/admin/conferences/{}/templates/{}/preview.png"),
    ("GET", "/api/admin/conferences/{}/templates/{}/overflow"),
    ("POST", "/api/admin/conferences/{}/templates/{}/test-print"),
    ("GET", "/api/admin/events"),
    ("GET", "/api/public/profile/{}"),
    ("GET", "/api/public/profile/{}/photo"),
    ("GET", "/api/participants"),
    ("GET", "/api/participants/stats"),
    ("GET", "/api/participants/{}"),
    ("GET", "/api/participants/{}/photo"),
    ("PATCH", "/api/participants/{}"),
    ("GET", "/api/events/stream"),
    ("POST", "/api/participants/check-duplicates"),
    ("POST", "/api/participants"),
}


@pytest.fixture(autouse=True)
def _stub_device_auth(app: FastAPI) -> None:
    """Заглушки терминала и агента не ходят в БД: проверку токена подменяем."""

    async def terminal() -> CurrentTerminal:
        return CurrentTerminal(terminal_id=1, name="Терминал 1", printer_id=1)

    async def agent() -> CurrentAgent:
        return CurrentAgent(printer_id=1, name="Принтер 1")

    app.dependency_overrides[get_current_terminal] = terminal
    app.dependency_overrides[get_current_agent] = agent


async def get_openapi(client: httpx.AsyncClient) -> dict[str, Any]:
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    data: dict[str, Any] = r.json()
    return data


@pytest.fixture(autouse=True)
def _staff_with_all_permissions(app: FastAPI) -> None:
    """Заглушки сотрудника проверяются без входа: сотрудник подменён на «всё можно» (B1-01)."""
    staff = CurrentStaff(
        user_id=0,
        login="stub",
        full_name="Заглушка",
        role_id=0,
        permissions=frozenset(Permission),
        session_id="stub",
    )

    async def _stub_staff() -> CurrentStaff:
        return staff

    app.dependency_overrides[get_current_staff] = _stub_staff


def _operations(schema: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    ops: dict[tuple[str, str], dict[str, Any]] = {}
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/"):
            continue
        for method, op in methods.items():
            ops[(method.upper(), re.sub(r"\{[^}]+\}", "{}", path))] = op
    return ops


# ---------------------------------------------------------------- OpenAPI


async def test_openapi_has_all_contract_paths(client: httpx.AsyncClient) -> None:
    ops = _operations(await get_openapi(client))
    assert set(ops) == CONTRACT, {
        "missing": sorted(CONTRACT - set(ops)),
        "extra": sorted(set(ops) - CONTRACT),
    }
    assert len(CONTRACT) == 71


async def test_every_operation_is_tagged_and_named(client: httpx.AsyncClient) -> None:
    schema = await get_openapi(client)
    ops = _operations(schema)
    operation_ids = [op["operationId"] for op in ops.values()]
    assert len(set(operation_ids)) == len(operation_ids)
    declared = {t["name"] for t in schema["tags"]}
    for (method, path), op in ops.items():
        where = f"{method} {path}"
        real = (method, path) in REAL or path.startswith(IMPLEMENTED_PREFIXES)
        assert ("stub" in op["tags"]) != real, where
        assert len(op["tags"]) >= (1 if real else 2), where
        assert set(op["tags"]) <= declared, where
        assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", op["operationId"]), where
        assert op.get("summary"), where


async def test_security_schemes_declared(client: httpx.AsyncClient) -> None:
    schema = await get_openapi(client)
    schemes = schema["components"]["securitySchemes"]
    assert schemes["StaffSession"]["in"] == "cookie"
    assert schemes["StaffSession"]["name"] == "rs_session"
    for name in ("TerminalToken", "AgentToken"):
        assert schemes[name]["in"] == "header"
        assert schemes[name]["name"] == "Authorization"
    ops = _operations(schema)
    assert ops[("GET", "/api/terminal/ping")]["security"] == [{"TerminalToken": []}]
    assert ops[("GET", "/api/agent/jobs/next")]["security"] == [{"AgentToken": []}]
    assert ops[("GET", "/api/admin/roles")]["security"] == [{"StaffSession": ["users.manage"]}]
    assert "security" not in ops[("GET", "/api/public/profile/{}")]
    assert "security" not in ops[("POST", "/api/auth/login")]


async def test_422_is_documented_in_error_format(client: httpx.AsyncClient) -> None:
    schema = await get_openapi(client)
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    for (method, path), op in _operations(schema).items():
        resp = op["responses"].get("422")
        if resp:
            ref = resp["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/ErrorOut"), f"{method} {path}"


# ------------------------------------------------- примеры JSON из контракта


def test_contract_examples_validate() -> None:
    ParticipantShort.model_validate(
        {
            "id": 17,
            "full_name": "Иванов Пётр Сергеевич",
            "organization": "ООО Ромашка",
            "status": "registered",
            "flags": ["data_changed"],
        }
    )
    at = "2026-11-20T09:15:03+03:00"
    card = ParticipantCard.model_validate(
        {
            "id": 17,
            "external_id": "B24-1001",
            "last_name": "Иванов",
            "first_name": "Пётр",
            "middle_name": "Сергеевич",
            "position": "Инженер",
            "organization": "ООО Ромашка",
            "last_name_en": None,
            "first_name_en": None,
            "middle_name_en": None,
            "position_en": None,
            "organization_en": None,
            "extra": [{"key": "section", "label": "Секция", "value": "A"}],
            "status": "registered",
            "registration": {
                "at": at,
                "source": "terminal",
                "terminal_name": "Терминал 2",
                "user_login": None,
            },
            "flags": [{"code": "error_reported", "at": at, "by": None}],
            "photo_url": "/api/participants/17/photo",
            "profile_url": "https://example.ru/p/token",
            "print_count": 1,
            "rescan_count": 2,
            "history": [
                {
                    "field": "organization",
                    "old": "Ромашка",
                    "new": "ООО Ромашка",
                    "source": "manual",
                    "user_login": "reg1",
                    "at": at,
                }
            ],
            "events": [
                {"type": "scan_rescan", "at": at, "terminal_name": "Терминал 1", "user_login": None}
            ],
            "actions": {
                "can_register": False,
                "can_reprint": True,
                "can_edit": True,
                "can_foreign_code": True,
                "reasons": {"can_register": "Уже зарегистрирован 20.11 09:15, Терминал 2"},
            },
        }
    )
    assert card.registration is not None and card.registration.at.utcoffset() is not None

    TemplateElement.model_validate(
        {
            "type": "field",
            "field": "last_name",
            "text": None,
            "x_mm": 3,
            "y_mm": 3,
            "w_mm": 54,
            "h_mm": 10,
            "font_size": 14,
            "min_font_size": 8,
            "max_lines": 2,
            "align": "left",
            "bold": True,
        }
    )
    PingOut.model_validate(
        {
            "terminal_name": "Терминал 2",
            "enabled": True,
            "conference": {"title": "Демо", "badge_type": "single"},
            "printer_online": True,
            "server_time": at,
            "settings": {"idle_timeout_s": 60, "result_screen_s": 10},
        }
    )
    scan = TypeAdapter(ScanOut)
    assert isinstance(
        scan.validate_python(
            {
                "result": "found",
                "scan_id": "x",
                "participant": {
                    "id": 17,
                    "full_name": "Иванов Пётр Сергеевич",
                    "position": "не указано",
                    "organization": "ООО Ромашка",
                },
            }
        ),
        ScanFound,
    )
    assert isinstance(
        scan.validate_python({"result": "not_found", "message": "Участник не найден."}),
        ScanNotFound,
    )
    assert isinstance(
        scan.validate_python({"result": "already_registered", "message": "Вы уже…"}),
        ScanAlreadyRegistered,
    )
    ErrorOut.model_validate({"code": "already_registered", "message": "Вы уже…", "details": {}})


# ---------------------------------------------------------- заглушки: таблица

Case = tuple[str, str, str, dict[str, Any], int, Any]
# (id, метод, url, kwargs запроса, ожидаемый код, модель | None для пустого тела)
CASES: list[Case] = [
    # auth: реальные эндпоинты (B1-01), см. tests/test_auth.py
    # roles / users: реальные эндпоинты (B1-02, B1-03), см. test_roles.py и test_users.py
    # conferences / imports: реальные эндпоинты (B1-04, B1-05, B1-08), см. test_conferences.py
    # и test_import*.py; заглушка осталась только у загрузки из Битрикс24
    (
        "import_bitrix",
        "POST",
        "/api/admin/conferences/1/imports/bitrix",
        {},
        202,
        ImportAcceptedOut,
    ),
    ("bitrix_get", "GET", "/api/admin/conferences/1/bitrix-settings", {}, 200, BitrixSettingsOut),
    (
        "bitrix_put",
        "PUT",
        "/api/admin/conferences/1/bitrix-settings",
        {
            "json": {
                "entity": "smart_process",
                "entity_type_id": 1038,
                "filter": {"=STAGE_ID": "DT1038_1:NEW"},
                "field_map": {"last_name": "ufCrm_5_LAST_NAME"},
            }
        },
        200,
        BitrixSettingsOut,
    ),
    # desk
    (
        "register",
        "POST",
        "/api/participants/18/register",
        {"json": {"with_sticker": True}},
        200,
        RegisterOut,
    ),
    ("reprint", "POST", "/api/participants/17/reprint", {}, 200, PrintJobRefOut),
    ("foreign", "POST", "/api/participants/17/foreign-code", {}, 200, PrintJobRefOut),
    ("print_job", "GET", "/api/print-jobs/501", {}, 200, PrintJobOut),
    # terminal
    (
        "t_print_job",
        "GET",
        "/api/terminal/print-jobs/501",
        {"headers": TERMINAL},
        200,
        TerminalPrintJobOut,
    ),
    # agent
    ("a_next", "GET", "/api/agent/jobs/next", {"headers": AGENT}, 200, AgentJob),
    ("a_next_empty", "GET", "/api/agent/jobs/next?wait=0", {"headers": AGENT}, 204, None),
    (
        "a_result",
        "POST",
        "/api/agent/jobs/501/result",
        {"headers": AGENT, "json": {"ok": False, "error": "Нет ленты"}},
        204,
        None,
    ),
]


@pytest.mark.parametrize(
    ("method", "url", "kwargs", "status", "model"),
    [pytest.param(m, u, k, s, mod, id=i) for i, m, u, k, s, mod in CASES],
)
async def test_stub_endpoint(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    kwargs: dict[str, Any],
    status: int,
    model: Any,
) -> None:
    r = await client.request(method, url, **kwargs)
    assert r.status_code == status, r.text
    if model is None:
        assert r.content == b""
    else:
        TypeAdapter(model).validate_json(r.content)


# ------------------------------------------------------------- бинарные файлы


async def test_agent_job_contains_valid_png(client: httpx.AsyncClient) -> None:
    import base64

    r = await client.get("/api/agent/jobs/next", headers=AGENT)
    job = AgentJob.model_validate_json(r.content)
    assert job.copies
    assert base64.b64decode(job.copies[0].png_base64).startswith(PNG_MAGIC)


# Отключённый терминал (423) и неверные токены проверяются по-настоящему в test_terminals.py
# и test_agent_auth.py.


# ------------------------------------------------------------------ ошибки


async def _assert_error(r: httpx.Response, status: int, code: str) -> ErrorOut:
    assert r.status_code == status, r.text
    err = ErrorOut.model_validate_json(r.content)
    assert err.code == code
    return err


async def test_validation_error_format(client: httpx.AsyncClient) -> None:
    r = await client.patch("/api/participants/17", json={"last_name": "   "})
    err = await _assert_error(r, 422, "validation_error")
    assert err.details["fields"]["last_name"] == "Укажите фамилию"

    r = await client.post(
        "/api/admin/conferences",
        json={"title": "X", "date_from": "2026-12-05", "date_to": "2026-12-01"},
    )
    err = await _assert_error(r, 422, "validation_error")
    assert "date_to" in err.details["fields"]


async def test_participant_scenarios(client: httpx.AsyncClient) -> None:
    r = await client.post("/api/participants/17/register", json={"with_sticker": True})
    err = await _assert_error(r, 409, "already_registered")
    assert err.details["source"] == "terminal"
    assert "registered_at" in err.details

    r = await client.post("/api/participants/18/reprint")
    await _assert_error(r, 409, "not_registered")

    r = await client.get("/api/participants/999")
    await _assert_error(r, 404, "participant_not_found")

    r = await client.post("/api/admin/conferences/503/imports/bitrix")
    await _assert_error(r, 502, "bitrix_unavailable")


# ------------------------------------------------- v1.0: новые заглушки


async def test_bitrix_settings_never_expose_the_webhook(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    url = "/api/admin/conferences/1/bitrix-settings"
    assert (await client.get(url)).json()["webhook_configured"] is False

    secret = "https://example.bitrix24.ru/rest/1/very-secret-key/"
    app.state.settings = app.state.settings.model_copy(update={"bitrix_webhook_url": secret})
    r = await client.get(url)
    assert r.json()["webhook_configured"] is True
    assert "very-secret-key" not in r.text
    assert "webhook_url" not in r.json()

    bad = await client.put(url, json={"entity": "smart_process"})
    err = await _assert_error(bad, 422, "validation_error")
    assert "entity_type_id" in err.details["fields"]
    bad = await client.put(url, json={"entity": "lead"})
    await _assert_error(bad, 422, "validation_error")
