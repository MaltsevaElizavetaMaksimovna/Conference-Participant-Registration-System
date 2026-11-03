"""Автотесты API шаблонов наклеек (PR-01..PR-05, AD-01)."""

from typing import Any

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import Conference, LabelTemplate
from tests.conftest import LoginAs, StaffClient

CONF_BODY: dict[str, Any] = {
    "title": "Инновации-2026",
    "date_from": "2026-11-20",
    "date_to": "2026-11-21",
    "badge_type": "double",
}

SAMPLE_TEMPLATE: dict[str, Any] = {
    "name": "Лицевая",
    "kind": "front",
    "width_mm": 60,
    "height_mm": 40,
    "gap_mm": 2,
    "elements": [
        {
            "type": "field",
            "field": "last_name",
            "x_mm": 5,
            "y_mm": 5,
            "w_mm": 50,
            "h_mm": 10,
            "font_size": 14,
            "min_font_size": 8,
            "max_lines": 2,
        },
        {
            "type": "field",
            "field": "organization",
            "x_mm": 5,
            "y_mm": 17,
            "w_mm": 50,
            "h_mm": 8,
        },
        {"type": "qr", "x_mm": 40, "y_mm": 24, "w_mm": 12, "h_mm": 12},
    ],
}


async def manager(login_as: LoginAs) -> StaffClient:
    """Клиент сотрудника с правом conferences.manage."""
    return await login_as("conferences.manage")


async def create_conf(c: StaffClient, **fields: Any) -> dict[str, Any]:
    """Создание тестовой конференции."""
    r = await c.post("/api/admin/conferences", json={**CONF_BODY, **fields})
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def templates_url(conference_id: int) -> str:
    """Базовый URL шаблонов конференции."""
    return f"/api/admin/conferences/{conference_id}/templates"


def error_info(r: httpx.Response) -> tuple[str, dict[str, Any]]:
    """Извлечение кода ошибки и details из ответа."""
    data: dict[str, Any] = r.json()
    if "error" in data and isinstance(data["error"], dict):
        return str(data["error"].get("code", "")), dict(data["error"].get("details", {}))
    return str(data.get("code", "")), dict(data.get("details", {}))


def has_field_error(details: dict[str, Any], field_prefix: str) -> bool:
    """Проверка наличия ошибки по префиксу поля в details.fields."""
    fields: dict[str, Any] = details.get("fields", {})
    return any(k == field_prefix or k.startswith(f"{field_prefix}.") for k in fields)


# 1. POST -> 201, все поля + id, conference_id, version == 1, updated_at, warnings == []
async def test_create_template_success(login_as: LoginAs) -> None:
    """Создание шаблона: статус 201, полная структура ответа, version=1, пустые warnings."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    r = await c.post(url, json=SAMPLE_TEMPLATE)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()

    assert isinstance(data["id"], int) and data["id"] > 0
    assert data["conference_id"] == conf["id"]
    assert data["version"] == 1
    assert isinstance(data["updated_at"], str)
    assert data["warnings"] == []

    assert data["name"] == SAMPLE_TEMPLATE["name"]
    assert data["kind"] == SAMPLE_TEMPLATE["kind"]
    assert data["width_mm"] == SAMPLE_TEMPLATE["width_mm"]
    assert data["height_mm"] == SAMPLE_TEMPLATE["height_mm"]
    assert data["gap_mm"] == SAMPLE_TEMPLATE["gap_mm"]

    elements: list[dict[str, Any]] = data["elements"]
    assert len(elements) == len(SAMPLE_TEMPLATE["elements"])
    for expected, actual in zip(SAMPLE_TEMPLATE["elements"], elements, strict=True):
        for k, v in expected.items():
            assert actual[k] == v


# 2. GET список и GET одного
async def test_list_templates_and_get_one(login_as: LoginAs) -> None:
    """Список шаблонов с сортировкой по id, пагинация limit/offset и получение по id."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    tpl1 = (await c.post(url, json={**SAMPLE_TEMPLATE, "name": "Шаблон 1"})).json()
    tpl2 = (await c.post(url, json={**SAMPLE_TEMPLATE, "name": "Шаблон 2"})).json()
    tpl3 = (await c.post(url, json={**SAMPLE_TEMPLATE, "name": "Шаблон 3"})).json()

    # Полный список
    r = await c.get(url)
    assert r.status_code == 200, r.text
    page: dict[str, Any] = r.json()
    assert page["total"] == 3
    items: list[dict[str, Any]] = page["items"]
    ids = [i["id"] for i in items]
    assert ids == sorted(ids)
    assert ids == [tpl1["id"], tpl2["id"], tpl3["id"]]

    # Пагинация limit/offset
    p1 = (await c.get(f"{url}?limit=2&offset=0")).json()
    assert p1["total"] == 3
    assert [i["id"] for i in p1["items"]] == [tpl1["id"], tpl2["id"]]

    p2 = (await c.get(f"{url}?limit=2&offset=2")).json()
    assert p2["total"] == 3
    assert [i["id"] for i in p2["items"]] == [tpl3["id"]]

    # GET одного шаблона
    r_one = await c.get(f"{url}/{tpl2['id']}")
    assert r_one.status_code == 200, r_one.text
    one: dict[str, Any] = r_one.json()
    assert one["id"] == tpl2["id"]
    assert one["name"] == "Шаблон 2"
    assert one["elements"] == tpl2["elements"]


# 3. PR-01: Создать шаблон 60x40 с ФИО и организацией
async def test_pr01_create_template_with_fio_and_org(login_as: LoginAs) -> None:
    """PR-01: Создание шаблона 60x40 с элементами last_name и organization."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    r = await c.post(url, json=SAMPLE_TEMPLATE)
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()

    r_get = await c.get(f"{url}/{created['id']}")
    assert r_get.status_code == 200, r_get.text
    fetched: dict[str, Any] = r_get.json()

    assert fetched["width_mm"] == 60
    assert fetched["height_mm"] == 40
    fields = [el.get("field") for el in fetched.get("elements", []) if el.get("type") == "field"]
    assert "last_name" in fields
    assert "organization" in fields


# 4. PUT -> 200, полная замена, version растёт, overflow == []
async def test_update_template_full_replacement_and_version(login_as: LoginAs) -> None:
    """PUT: полная замена элементов, инкремент version (2, 3) и поле overflow."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    created = (await c.post(url, json=SAMPLE_TEMPLATE)).json()
    assert created["version"] == 1

    # Замена: убираем элемент organization
    updated_body = {
        **SAMPLE_TEMPLATE,
        "name": "Лицевая без организации",
        "elements": [
            {
                "type": "field",
                "field": "last_name",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": 50,
                "h_mm": 10,
                "font_size": 14,
                "min_font_size": 8,
                "max_lines": 2,
            },
            {"type": "qr", "x_mm": 40, "y_mm": 24, "w_mm": 12, "h_mm": 12},
        ],
    }

    r1 = await c.put(f"{url}/{created['id']}", json=updated_body)
    assert r1.status_code == 200, r1.text
    put1: dict[str, Any] = r1.json()
    assert put1["version"] == 2
    assert put1["overflow"] == []
    assert put1["name"] == "Лицевая без организации"
    fields1 = [el.get("field") for el in put1.get("elements", []) if el.get("type") == "field"]
    assert "organization" not in fields1
    assert "last_name" in fields1

    # Проверка через последующий GET
    get1 = (await c.get(f"{url}/{created['id']}")).json()
    assert get1["version"] == 2
    fields_get1 = [el.get("field") for el in get1.get("elements", []) if el.get("type") == "field"]
    assert "organization" not in fields_get1

    # Второе обновление: version становится 3
    r2 = await c.put(f"{url}/{created['id']}", json={**updated_body, "name": "Лицевая v3"})
    assert r2.status_code == 200, r2.text
    put2: dict[str, Any] = r2.json()
    assert put2["version"] == 3
    assert put2["overflow"] == []
    assert put2["name"] == "Лицевая v3"


# 5. Виды front, back, changed, changed_back и ошибка 422 для неизвестного
async def test_template_kinds(login_as: LoginAs) -> None:
    """Допустимые виды шаблонов и ошибка 422 для неизвестного вида."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    for kind in ("front", "back", "changed", "changed_back"):
        body = {**SAMPLE_TEMPLATE, "name": f"Шаблон {kind}", "kind": kind}
        r = await c.post(url, json=body)
        assert r.status_code == 201, f"{kind}: {r.text}"
        assert r.json()["kind"] == kind

    # Неизвестный вид
    r_bad = await c.post(url, json={**SAMPLE_TEMPLATE, "kind": "unsupported_kind"})
    assert r_bad.status_code == 422, r_bad.text
    code, details = error_info(r_bad)
    assert code == "validation_error"
    assert has_field_error(details, "kind")


# 6. Валидация 422 validation_error
async def test_template_validation_errors(login_as: LoginAs) -> None:
    """Валидация 422: границы, координаты, поля, extra, текст, кегли, лимит, имя."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    # Элемент выходит за правый край (x_mm + w_mm > width_mm)
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "width_mm": 60,
            "elements": [
                {
                    "type": "field",
                    "field": "last_name",
                    "x_mm": 15,
                    "y_mm": 5,
                    "w_mm": 50,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # Элемент выходит за нижний край (y_mm + h_mm > height_mm)
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "height_mm": 40,
            "elements": [
                {
                    "type": "field",
                    "field": "last_name",
                    "x_mm": 5,
                    "y_mm": 35,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # Отрицательный x_mm
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "last_name",
                    "x_mm": -1,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # type=field без field
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [{"type": "field", "x_mm": 5, "y_mm": 5, "w_mm": 20, "h_mm": 10}],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # field неизвестный
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "password",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # field: "extra.section" — допустим (201)
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "extra.section",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text

    # field: "extra.Bad Key" — 422
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "extra.Bad Key",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # field: "full_name" и "last_name_en" — допустимы (201)
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "full_name",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 50,
                    "h_mm": 10,
                },
                {
                    "type": "field",
                    "field": "last_name_en",
                    "x_mm": 5,
                    "y_mm": 17,
                    "w_mm": 50,
                    "h_mm": 8,
                },
            ],
        },
    )
    assert r.status_code == 201, r.text

    # type=text без text
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [{"type": "text", "x_mm": 5, "y_mm": 5, "w_mm": 20, "h_mm": 10}],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # type=text с пустым текстом "  "
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "text",
                    "text": "   ",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # type=text с текстом — 201
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "text",
                    "text": "Оргкомитет",
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 201, r.text

    # min_font_size > font_size — 422
    r = await c.post(
        url,
        json={
            **SAMPLE_TEMPLATE,
            "elements": [
                {
                    "type": "field",
                    "field": "last_name",
                    "font_size": 10,
                    "min_font_size": 14,
                    "x_mm": 5,
                    "y_mm": 5,
                    "w_mm": 20,
                    "h_mm": 10,
                }
            ],
        },
    )
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements.0")

    # 51 элемент — 422
    elements_51 = [
        {"type": "field", "field": "last_name", "x_mm": 5, "y_mm": 5, "w_mm": 10, "h_mm": 5}
        for _ in range(51)
    ]
    r = await c.post(url, json={**SAMPLE_TEMPLATE, "elements": elements_51})
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "elements")

    # Пустое имя "  " — 422
    r = await c.post(url, json={**SAMPLE_TEMPLATE, "name": "   "})
    assert r.status_code == 422, r.text
    code, details = error_info(r)
    assert code == "validation_error"
    assert has_field_error(details, "name")


# 7. Предупреждения: near_edge при приближении к краю (POST и GET)
async def test_near_edge_warnings(login_as: LoginAs) -> None:
    """Предупреждение near_edge при расстоянии менее 3 мм до края в POST и GET."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    # Элемент с x_mm: 1 (ближе 3 мм к левому краю)
    body_near_left = {
        **SAMPLE_TEMPLATE,
        "name": "Элемент у левого края",
        "elements": [
            {
                "type": "field",
                "field": "last_name",
                "x_mm": 1,
                "y_mm": 5,
                "w_mm": 40,
                "h_mm": 10,
            }
        ],
    }
    r = await c.post(url, json=body_near_left)
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    warnings: list[dict[str, Any]] = data.get("warnings", [])
    assert any(
        w.get("element") == 0 and w.get("code") == "near_edge" and bool(w.get("message"))
        for w in warnings
    )

    # В последующем GET предупреждения также сохраняются
    r_get = await c.get(f"{url}/{data['id']}")
    assert r_get.status_code == 200, r_get.text
    get_warnings: list[dict[str, Any]] = r_get.json().get("warnings", [])
    assert any(
        w.get("element") == 0 and w.get("code") == "near_edge" and bool(w.get("message"))
        for w in get_warnings
    )

    # Элемент у правого края: x_mm + w_mm == width_mm - 1
    # width_mm=60, w_mm=40 -> x_mm = 60 - 1 - 40 = 19
    body_near_right = {
        **SAMPLE_TEMPLATE,
        "name": "Элемент у правого края",
        "width_mm": 60,
        "elements": [
            {
                "type": "field",
                "field": "last_name",
                "x_mm": 19,
                "y_mm": 5,
                "w_mm": 40,
                "h_mm": 10,
            }
        ],
    }
    r_right = await c.post(url, json=body_near_right)
    assert r_right.status_code == 201, r_right.text
    right_warnings: list[dict[str, Any]] = r_right.json().get("warnings", [])
    assert any(
        w.get("element") == 0 and w.get("code") == "near_edge" and bool(w.get("message"))
        for w in right_warnings
    )


# 8. Ошибки 404: conference_not_found и template_not_found
async def test_template_not_found_404(login_as: LoginAs) -> None:
    """404: несуществующая конференция, несуществующий шаблон, шаблон чужой конференции."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    # Список и создание для несуществующей конференции
    r = await c.get("/api/admin/conferences/999999/templates")
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "conference_not_found"

    r = await c.post("/api/admin/conferences/999999/templates", json=SAMPLE_TEMPLATE)
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "conference_not_found"

    # Несуществующий шаблон (GET, PUT, DELETE)
    r = await c.get(f"{url}/999999")
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"

    r = await c.put(f"{url}/999999", json=SAMPLE_TEMPLATE)
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"

    r = await c.delete(f"{url}/999999")
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"

    # Шаблон другой конференции по адресу чужой конференции
    other_conf = await create_conf(c, title="Вторая конференция")
    other_url = templates_url(other_conf["id"])
    tpl = (await c.post(url, json=SAMPLE_TEMPLATE)).json()

    r = await c.get(f"{other_url}/{tpl['id']}")
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"

    r = await c.put(f"{other_url}/{tpl['id']}", json=SAMPLE_TEMPLATE)
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"

    r = await c.delete(f"{other_url}/{tpl['id']}")
    assert r.status_code == 404
    code, _ = error_info(r)
    assert code == "template_not_found"


async def bind(db: AsyncSession, conference_id: int, **templates: int | None) -> None:
    """Привязать шаблоны к конференции напрямую в БД.

    Через UPDATE, а не через объект: `app_db` перед каждым запросом очищает identity map,
    и загруженный ранее объект `Conference` уже отсоединён от сессии.
    """
    await db.execute(update(Conference).where(Conference.id == conference_id).values(**templates))
    await db.commit()


# 9. DELETE -> 204, затем 404; конфликт 409 template_in_use
async def test_delete_template_and_conflict_when_in_use(
    login_as: LoginAs, db: AsyncSession
) -> None:
    """DELETE: успешное удаление (204 -> 404) и отказ 409 template_in_use при привязке."""
    c = await manager(login_as)
    conf = await create_conf(c)
    url = templates_url(conf["id"])

    # Успешное удаление непривязанного шаблона
    tpl = (await c.post(url, json=SAMPLE_TEMPLATE)).json()
    r_del = await c.delete(f"{url}/{tpl['id']}")
    assert r_del.status_code == 204

    r_get = await c.get(f"{url}/{tpl['id']}")
    assert r_get.status_code == 404
    code, _ = error_info(r_get)
    assert code == "template_not_found"
    assert await db.get(LabelTemplate, tpl["id"]) is None

    # Привязка через front_template_id -> 409 template_in_use
    tpl_front = (await c.post(url, json=SAMPLE_TEMPLATE)).json()
    await bind(db, conf["id"], front_template_id=tpl_front["id"])

    r_in_use1 = await c.delete(f"{url}/{tpl_front['id']}")
    assert r_in_use1.status_code == 409, r_in_use1.text
    code1, details1 = error_info(r_in_use1)
    assert code1 == "template_in_use"
    assert details1.get("conference_id") == conf["id"]
    # Шаблон остался цел
    assert (await c.get(f"{url}/{tpl_front['id']}")).status_code == 200

    # Отвязываем front_template_id
    await bind(db, conf["id"], front_template_id=None)

    # Привязка через changed_template_id -> 409 template_in_use
    tpl_changed = (
        await c.post(url, json={**SAMPLE_TEMPLATE, "name": "Для изменений", "kind": "changed"})
    ).json()
    await bind(db, conf["id"], changed_template_id=tpl_changed["id"])

    r_in_use2 = await c.delete(f"{url}/{tpl_changed['id']}")
    assert r_in_use2.status_code == 409, r_in_use2.text
    code2, details2 = error_info(r_in_use2)
    assert code2 == "template_in_use"
    assert details2.get("conference_id") == conf["id"]
    # Шаблон остался цел
    assert (await c.get(f"{url}/{tpl_changed['id']}")).status_code == 200


# 10. PR-01: Скопировать шаблон прошлой конференции
async def test_pr01_copy_template_to_another_conference(login_as: LoginAs) -> None:
    """PR-01: Копирование шаблона в другую конференцию и независимость копии."""
    c = await manager(login_as)
    conf_src = await create_conf(c, title="Конференция 2025")
    conf_dst = await create_conf(c, title="Конференция 2026")
    src_url = templates_url(conf_src["id"])
    dst_url = templates_url(conf_dst["id"])

    src_tpl = (await c.post(src_url, json=SAMPLE_TEMPLATE)).json()

    # Копирование в целевую конференцию
    r_copy = await c.post(f"{src_url}/{src_tpl['id']}/copy-to/{conf_dst['id']}")
    assert r_copy.status_code == 201, r_copy.text
    copy_tpl: dict[str, Any] = r_copy.json()

    assert copy_tpl["conference_id"] == conf_dst["id"]
    assert copy_tpl["id"] != src_tpl["id"]
    assert copy_tpl["name"] == src_tpl["name"]
    assert copy_tpl["kind"] == src_tpl["kind"]
    assert copy_tpl["width_mm"] == src_tpl["width_mm"]
    assert copy_tpl["height_mm"] == src_tpl["height_mm"]
    assert copy_tpl["gap_mm"] == src_tpl["gap_mm"]
    assert copy_tpl["elements"] == src_tpl["elements"]
    assert copy_tpl["version"] == 1

    # Исходный шаблон не изменился
    src_get = (await c.get(f"{src_url}/{src_tpl['id']}")).json()
    assert src_get["conference_id"] == conf_src["id"]
    assert src_get["version"] == 1
    assert src_get["name"] == src_tpl["name"]

    # Копию можно изменить через PUT, исходный при этом не меняется
    new_name = "Измененная копия в новой конференции"
    r_put = await c.put(f"{dst_url}/{copy_tpl['id']}", json={**SAMPLE_TEMPLATE, "name": new_name})
    assert r_put.status_code == 200, r_put.text
    assert r_put.json()["name"] == new_name

    src_after = (await c.get(f"{src_url}/{src_tpl['id']}")).json()
    assert src_after["name"] == src_tpl["name"]
    assert src_after["elements"] == src_tpl["elements"]

    # Целевая конференция не существует -> 404 conference_not_found
    r_bad_dst = await c.post(f"{src_url}/{src_tpl['id']}/copy-to/999999")
    assert r_bad_dst.status_code == 404
    code, _ = error_info(r_bad_dst)
    assert code == "conference_not_found"


# 11. Без права conferences.manage -> 403
async def test_template_permissions(login_as: LoginAs) -> None:
    """Без права conferences.manage возвращается 403 на запросы к шаблонам."""
    admin = await manager(login_as)
    conf = await create_conf(admin)
    url = templates_url(conf["id"])
    tpl = (await admin.post(url, json=SAMPLE_TEMPLATE)).json()

    viewer = await login_as("participants.view")

    assert (await viewer.get(url)).status_code == 403
    assert (await viewer.post(url, json=SAMPLE_TEMPLATE)).status_code == 403
    assert (await viewer.get(f"{url}/{tpl['id']}")).status_code == 403
    assert (await viewer.put(f"{url}/{tpl['id']}", json=SAMPLE_TEMPLATE)).status_code == 403
    assert (await viewer.delete(f"{url}/{tpl['id']}")).status_code == 403
    assert (await viewer.post(f"{url}/{tpl['id']}/copy-to/{conf['id']}")).status_code == 403
