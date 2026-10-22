"""Контракт API (S-02): OpenAPI содержит все пути, заглушки отвечают."""

import re
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import TypeAdapter

from app.api.common import ErrorOut, Page, PrintJobRefOut
from app.auth.deps import CurrentStaff, get_current_staff
from app.badges.schemas import ProfileActive, ProfileRevoked
from app.conferences.schemas import ConferenceOut
from app.core.permissions import Permission
from app.imports.schemas import ImportAcceptedOut, ImportReportOut
from app.participants.schemas import (
    DuplicatesOut,
    ParticipantCard,
    ParticipantCreatedOut,
    ParticipantShort,
    ParticipantStats,
)
from app.printing.schemas import AgentJob
from app.realtime.schemas import StatsEvent
from app.registration.schemas import PrintJobOut, RegisterOut
from app.templates.schemas import OverflowItem, TemplateElement, TemplateOut
from app.terminals.deps import (
    CurrentAgent,
    CurrentTerminal,
    get_current_agent,
    get_current_terminal,
)
from app.terminals.schemas import (
    ConfirmOut,
    PingOut,
    ReportErrorOut,
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
    ("PUT", "/api/admin/conferences/{}"),
    ("POST", "/api/admin/conferences/{}/activate"),
    ("POST", "/api/admin/conferences/{}/imports"),
    ("GET", "/api/admin/conferences/{}/imports/{}"),
    ("GET", "/api/admin/import-template.xlsx"),
    ("POST", "/api/admin/conferences/{}/imports/bitrix"),
    ("GET", "/api/participants"),
    ("GET", "/api/participants/stats"),
    ("GET", "/api/participants/{}"),
    ("GET", "/api/participants/{}/photo"),
    ("PATCH", "/api/participants/{}"),
    ("POST", "/api/participants/check-duplicates"),
    ("POST", "/api/participants"),
    ("GET", "/api/events/stream"),
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
    ("POST", "/api/agent/heartbeat"),
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
    assert len(CONTRACT) == 62


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
    # conferences / imports
    ("conf_list", "GET", "/api/admin/conferences", {}, 200, Page[ConferenceOut]),
    (
        "conf_create",
        "POST",
        "/api/admin/conferences",
        {"json": {"title": "Новая", "date_from": "2026-12-01", "date_to": "2026-12-02"}},
        201,
        ConferenceOut,
    ),
    (
        "conf_update",
        "PUT",
        "/api/admin/conferences/1",
        {"json": {"title": "Демо", "date_from": "2026-12-01", "date_to": "2026-12-02"}},
        200,
        ConferenceOut,
    ),
    ("conf_activate", "POST", "/api/admin/conferences/2/activate", {}, 200, ConferenceOut),
    (
        "import_upload",
        "POST",
        "/api/admin/conferences/1/imports",
        {"files": {"file": ("p.xlsx", b"PK", "application/octet-stream")}},
        202,
        ImportAcceptedOut,
    ),
    ("import_report", "GET", "/api/admin/conferences/1/imports/12", {}, 200, ImportReportOut),
    (
        "import_bitrix",
        "POST",
        "/api/admin/conferences/1/imports/bitrix",
        {},
        202,
        ImportAcceptedOut,
    ),
    # participants
    ("p_list", "GET", "/api/participants", {}, 200, Page[ParticipantShort]),
    ("p_stats", "GET", "/api/participants/stats", {}, 200, ParticipantStats),
    ("p_get", "GET", "/api/participants/17", {}, 200, ParticipantCard),
    ("p_get_unreg", "GET", "/api/participants/18", {}, 200, ParticipantCard),
    (
        "p_patch",
        "PATCH",
        "/api/participants/17",
        {"json": {"organization": "ООО"}},
        200,
        ParticipantCard,
    ),
    (
        "p_dups",
        "POST",
        "/api/participants/check-duplicates",
        {"json": {"last_name": "Иванов", "first_name": "Пётр"}},
        200,
        DuplicatesOut,
    ),
    (
        "p_create",
        "POST",
        "/api/participants",
        {"json": {"last_name": "Кузнецов", "first_name": "Алексей", "with_sticker": True}},
        201,
        ParticipantCreatedOut,
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
    # templates
    ("tpl_list", "GET", "/api/admin/conferences/1/templates", {}, 200, Page[TemplateOut]),
    (
        "tpl_create",
        "POST",
        "/api/admin/conferences/1/templates",
        {"json": {"name": "Т", "kind": "front", "width_mm": 60, "height_mm": 40}},
        201,
        TemplateOut,
    ),
    ("tpl_get", "GET", "/api/admin/conferences/1/templates/1", {}, 200, TemplateOut),
    (
        "tpl_put",
        "PUT",
        "/api/admin/conferences/1/templates/1",
        {"json": {"name": "Т", "kind": "back", "width_mm": 60, "height_mm": 40, "elements": []}},
        200,
        TemplateOut,
    ),
    ("tpl_copy", "POST", "/api/admin/conferences/1/templates/1/copy-to/2", {}, 201, TemplateOut),
    (
        "tpl_resize",
        "POST",
        "/api/admin/conferences/1/templates/1/resize",
        {"json": {"width_mm": 58, "height_mm": 40}},
        200,
        TemplateOut,
    ),
    (
        "tpl_overflow",
        "GET",
        "/api/admin/conferences/1/templates/1/overflow",
        {},
        200,
        Page[OverflowItem],
    ),
    (
        "tpl_test_print",
        "POST",
        "/api/admin/conferences/1/templates/1/test-print",
        {"json": {"participant_id": 17, "printer_id": 1}},
        200,
        PrintJobRefOut,
    ),
    # terminal
    (
        "t_confirm",
        "POST",
        "/api/terminal/confirm",
        {
            "headers": {**TERMINAL, "Idempotency-Key": "3f2b8c1e-5a6d-4e7f-9b0a-1c2d3e4f5a6b"},
            "json": {"participant_id": 17, "scan_id": "scan_1"},
        },
        200,
        ConfirmOut,
    ),
    (
        "t_report",
        "POST",
        "/api/terminal/report-error",
        {"headers": TERMINAL, "json": {"participant_id": 17, "scan_id": "scan_1"}},
        200,
        ReportErrorOut,
    ),
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


async def test_binary_endpoints(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/participants/17/photo")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content.startswith(JPEG_MAGIC)

    r = await client.get("/api/admin/conferences/1/templates/1/preview.png?participant_id=17")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(PNG_MAGIC)

    r = await client.get("/api/admin/import-template.xlsx")
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]


async def test_agent_job_contains_valid_png(client: httpx.AsyncClient) -> None:
    import base64

    r = await client.get("/api/agent/jobs/next", headers=AGENT)
    job = AgentJob.model_validate_json(r.content)
    assert job.copies
    assert base64.b64decode(job.copies[0].png_base64).startswith(PNG_MAGIC)


# --------------------------------------------------------------------- scan


async def test_confirm_requires_idempotency_key(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/terminal/confirm",
        headers=TERMINAL,
        json={"participant_id": 17, "scan_id": "scan_1"},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"


async def test_confirm_registered_has_print_job(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/terminal/confirm",
        headers={**TERMINAL, "Idempotency-Key": "k-1"},
        json={"participant_id": 17, "scan_id": "scan_1"},
    )
    body = ConfirmOut.model_validate_json(r.content)
    assert body.result == "registered"
    assert body.print_job_id is not None


# Отключённый терминал (423) и неверные токены проверяются по-настоящему в test_terminals.py
# и test_agent_auth.py.


# ---------------------------------------------------------------- профиль


async def test_profile_active(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/public/profile/abc123")
    assert r.status_code == 200
    body = ProfileActive.model_validate_json(r.content)
    assert body.status == "active"
    assert body.photo_url == "/api/public/profile/abc123/photo"
    photo = await client.get(body.photo_url)
    assert photo.status_code == 200
    assert photo.headers["content-type"] == "image/jpeg"


async def test_profile_revoked(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/public/profile/revoked")
    assert r.status_code == 200
    assert r.json() == {"status": "revoked"}
    ProfileRevoked.model_validate_json(r.content)
    assert (await client.get("/api/public/profile/revoked/photo")).status_code == 404


async def test_profile_missing_is_404_in_error_format(client: httpx.AsyncClient) -> None:
    for url in ("/api/public/profile/missing", "/api/public/profile/missing/photo"):
        r = await client.get(url)
        assert r.status_code == 404
        err = ErrorOut.model_validate_json(r.content)
        assert err.code == "profile_not_found"
        assert err.details == {}


# ------------------------------------------------------------------- SSE


async def test_sse_stream(client: httpx.AsyncClient) -> None:
    r = await client.get("/api/events/stream")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"
    assert "event: stats" in r.text
    assert ": keep-alive" in r.text
    data_line = next(line for line in r.text.splitlines() if line.startswith("data: "))
    stats = StatsEvent.model_validate_json(data_line.removeprefix("data: "))
    assert stats.total >= stats.registered


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


async def test_participant_card_actions_differ(client: httpx.AsyncClient) -> None:
    done = ParticipantCard.model_validate_json((await client.get("/api/participants/17")).content)
    fresh = ParticipantCard.model_validate_json((await client.get("/api/participants/18")).content)
    assert not done.actions.can_register and "can_register" in done.actions.reasons
    assert fresh.actions.can_register and fresh.status == "not_registered"


async def test_participants_list_filters(client: httpx.AsyncClient) -> None:
    async def ids(query: str) -> list[int]:
        r = await client.get(f"/api/participants?{query}")
        page = Page[ParticipantShort].model_validate_json(r.content)
        assert page.total == len(page.items)
        return [p.id for p in page.items]

    assert await ids("filter=all") == [17, 18, 19]
    assert await ids("filter=not_registered") == [18]
    assert await ids("filter=flagged") == [17, 19]
    assert await ids("q=петров") == [18]
    bad = await client.get("/api/participants?filter=nope")
    await _assert_error(bad, 422, "validation_error")
