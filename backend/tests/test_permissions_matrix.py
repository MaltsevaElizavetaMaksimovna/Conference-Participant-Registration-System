"""Матрица «эндпоинт × разрешение» (B1-02, AD-04).

Идём по схеме OpenAPI и для каждой операции с авторизацией сотрудника (`StaffSession`) проверяем:
  1. без cookie -> `401 unauthenticated`;
  2. сотрудник без нужных разрешений -> `403 forbidden` (и `details.missing` называет их);
  3. сотрудник ровно с нужными разрешениями проходит защиту (ответ не 401/403);
  4. если разрешений несколько, то без любого одного из них -> `403`.

401/403 возвращаются зависимостями до разбора тела запроса, поэтому тело не отправляем:
для пунктов 1-2 это неважно, а в пункте 3 допустим любой ответ, кроме 401/403 (422 «нет тела»
тоже означает, что защита пройдена).

Не проверяются в пункте 3 (явный список ПРОПУЩЕННЫХ операций):
  - `GET /api/events/stream` — бесконечный поток SSE, тестовый клиент ждал бы его конца.
"""

import re
from typing import Any

import httpx
import pytest

from app.core.permissions import Permission
from app.main import app
from tests.conftest import LoginAs

# Не вызываем с «положительным» сотрудником: бесконечный поток
SKIP_POSITIVE: set[tuple[str, str]] = {("GET", "/api/events/stream")}

# Операции без авторизации по контракту
PUBLIC_OPERATIONS: set[tuple[str, str]] = {
    ("POST", "/api/auth/login"),
    ("GET", "/api/public/profile/{token}"),
    ("GET", "/api/public/profile/{token}/photo"),
}

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}


def _operations() -> list[tuple[str, str, dict[str, Any]]]:
    schema = app.openapi()
    return [
        (method.upper(), path, op)
        for path, methods in schema["paths"].items()
        if path.startswith("/api/")
        for method, op in methods.items()
        if method in HTTP_METHODS
    ]


def _staff_scopes(op: dict[str, Any]) -> list[str] | None:
    """Разрешения из схемы StaffSession или None, если у операции другая авторизация."""
    for requirement in op.get("security", []):
        if "StaffSession" in requirement:
            scopes: list[str] = requirement["StaffSession"]
            return scopes
    return None


STAFF_OPERATIONS = [
    pytest.param(method, path, scopes, id=f"{method} {path}")
    for method, path, op in _operations()
    if (scopes := _staff_scopes(op)) is not None
]


def _url(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_matrix_covers_the_expected_operations() -> None:
    methods_paths = {(m, p) for m, p, _ in _operations()}
    staff = {(m, p) for m, p, op in _operations() if _staff_scopes(op) is not None}
    assert len(staff) >= 40, "в матрицу попало подозрительно мало операций"
    # логин и публичный профиль — единственные открытые операции
    unauthenticated = {(m, p) for m, p, op in _operations() if not op.get("security")}
    assert unauthenticated == PUBLIC_OPERATIONS
    assert len(methods_paths) == len(_operations())


def test_all_scopes_are_known_permissions() -> None:
    known = {str(p) for p in Permission}
    used: set[str] = set()
    for _, _, op in _operations():
        scopes = _staff_scopes(op)
        if scopes:
            assert set(scopes) <= known
            used |= set(scopes)
    # каждое разрешение каталога где-то требуется, иначе оно «мёртвое»
    assert used == known


@pytest.mark.parametrize(("method", "path", "scopes"), STAFF_OPERATIONS)
async def test_without_session_is_401(
    anon: httpx.AsyncClient, method: str, path: str, scopes: list[str]
) -> None:
    r = await anon.request(method, _url(path), headers={"X-Requested-With": "rs"})
    assert r.status_code == 401, r.text
    assert r.json()["code"] == "unauthenticated"
    # и без CSRF-заголовка анонимный запрос — по-прежнему 401, а не 403
    r = await anon.request(method, _url(path))
    assert r.status_code == 401, r.text


@pytest.mark.parametrize(("method", "path", "scopes"), [p for p in STAFF_OPERATIONS if p.values[2]])
async def test_without_permission_is_403(
    login_as: LoginAs, method: str, path: str, scopes: list[str]
) -> None:
    c = await login_as()  # роль без единого разрешения
    r = await c.request(method, _url(path))
    assert r.status_code == 403, r.text
    body = r.json()
    assert body["code"] == "forbidden"
    assert set(body["details"]["missing"]) == set(scopes)


@pytest.mark.parametrize(("method", "path", "scopes"), STAFF_OPERATIONS)
async def test_with_exact_permissions_passes_the_guard(
    login_as: LoginAs, method: str, path: str, scopes: list[str]
) -> None:
    if (method, path) in SKIP_POSITIVE:
        pytest.skip("бесконечный поток SSE")
    c = await login_as(*scopes)
    r = await c.request(method, _url(path))
    assert r.status_code not in (401, 403), r.text


@pytest.mark.parametrize(
    ("method", "path", "scopes"), [p for p in STAFF_OPERATIONS if len(p.values[2]) > 1]
)
async def test_missing_any_single_permission_is_403(
    login_as: LoginAs, method: str, path: str, scopes: list[str]
) -> None:
    for lacking in scopes:
        c = await login_as(*(s for s in scopes if s != lacking))
        r = await c.request(method, _url(path))
        assert r.status_code == 403, (lacking, r.text)
        assert r.json()["details"]["missing"] == [lacking]


async def test_extra_permissions_do_not_replace_required_one(login_as: LoginAs) -> None:
    """Проверяется разрешение, а не «насколько роль большая»: всё, кроме нужного, не помогает."""
    c = await login_as(*(str(p) for p in Permission if p != Permission.USERS_MANAGE))
    r = await c.get("/api/admin/roles")
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"
