"""Конференции (B1-04, AD-01): CRUD, валидация, привязка шаблонов, атомарная активация."""

from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import Conference, LabelTemplate
from app.models.participant import Participant
from tests.conftest import LoginAs, StaffClient

URL = "/api/admin/conferences"
BODY: dict[str, Any] = {
    "title": "Инновации-2026",
    "date_from": "2026-11-20",
    "date_to": "2026-11-21",
    "badge_type": "double",
}


async def manager(login_as: LoginAs) -> StaffClient:
    return await login_as("conferences.manage")


async def create(c: StaffClient, **fields: Any) -> dict[str, Any]:
    r = await c.post(URL, json={**BODY, **fields})
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


async def template(db: AsyncSession, conference_id: int, kind: str) -> LabelTemplate:
    tpl = LabelTemplate(
        conference_id=conference_id, name=f"{kind}-tpl", kind=kind, width_mm=60, height_mm=40
    )
    db.add(tpl)
    await db.commit()
    return tpl


async def test_create_and_list(login_as: LoginAs) -> None:
    c = await manager(login_as)
    created = await create(c)
    assert created["title"] == "Инновации-2026"
    assert created["badge_type"] == "double"
    assert created["is_active"] is False
    assert created["participants_total"] == 0
    assert created["front_template_id"] is None

    second = await create(c, title="  Вторая  ", badge_type="none")
    assert second["title"] == "Вторая"
    page = (await c.get(URL)).json()
    assert page["total"] == 2
    assert [i["id"] for i in page["items"]] == [second["id"], created["id"]]


async def test_badge_types(login_as: LoginAs) -> None:
    c = await manager(login_as)
    for badge in ("single", "double", "none"):
        assert (await create(c, badge_type=badge))["badge_type"] == badge
    r = await c.post(URL, json={**BODY, "badge_type": "triple"})
    assert r.status_code == 422


async def test_validation(login_as: LoginAs) -> None:
    c = await manager(login_as)
    r = await c.post(URL, json={**BODY, "date_from": "2026-11-21", "date_to": "2026-11-20"})
    assert r.status_code == 422
    assert r.json()["code"] == "validation_error"
    assert "date_to" in r.json()["details"]["fields"]
    # одна дата — допустимо
    await create(c, date_from="2026-11-20", date_to="2026-11-20")
    r = await c.post(URL, json={**BODY, "title": "   "})
    assert r.status_code == 422
    assert "title" in r.json()["details"]["fields"]


async def test_invite_regex_must_compile_and_have_a_group(login_as: LoginAs) -> None:
    c = await manager(login_as)
    for bad in ("(unclosed", r"id=\d+"):
        r = await c.post(URL, json={**BODY, "invite_id_regex": bad})
        assert r.status_code == 422, bad
        assert "invite_id_regex" in r.json()["details"]["fields"]
    ok = await create(c, invite_id_regex=r"id=(B\d+-\d+)")
    assert ok["invite_id_regex"] == r"id=(B\d+-\d+)"
    assert (await create(c, invite_id_regex="  "))["invite_id_regex"] is None


async def test_update(login_as: LoginAs) -> None:
    c = await manager(login_as)
    conf = await create(c)
    r = await c.put(
        f"{URL}/{conf['id']}", json={**BODY, "title": "Новое имя", "badge_type": "single"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Новое имя"
    assert r.json()["badge_type"] == "single"
    assert (await c.put(f"{URL}/999999", json=BODY)).json()["code"] == "conference_not_found"


async def test_attach_templates(login_as: LoginAs, db: AsyncSession) -> None:
    c = await manager(login_as)
    conf = await create(c)
    other = await create(c, title="Другая")
    front = await template(db, conf["id"], "front")
    back = await template(db, conf["id"], "back")
    changed = await template(db, conf["id"], "changed")
    changed_back = await template(db, conf["id"], "changed_back")

    ids = {
        "front_template_id": front.id,
        "back_template_id": back.id,
        "changed_template_id": changed.id,
        "changed_back_template_id": changed_back.id,
    }
    r = await c.put(f"{URL}/{conf['id']}", json={**BODY, **ids})
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in ids} == ids

    # шаблон другого вида в чужом поле
    r = await c.put(f"{URL}/{conf['id']}", json={**BODY, "front_template_id": back.id})
    assert r.status_code == 422
    assert "front_template_id" in r.json()["details"]["fields"]
    # несуществующий шаблон
    r = await c.put(f"{URL}/{conf['id']}", json={**BODY, "back_template_id": 999999})
    assert r.status_code == 422
    # шаблон другой конференции
    r = await c.put(f"{URL}/{other['id']}", json={**BODY, "front_template_id": front.id})
    assert r.status_code == 422
    assert "front_template_id" in r.json()["details"]["fields"]
    # при создании шаблонов ещё нет
    r = await c.post(URL, json={**BODY, "front_template_id": front.id})
    assert r.status_code == 422
    # отвязать можно
    r = await c.put(f"{URL}/{conf['id']}", json=BODY)
    assert r.json()["front_template_id"] is None


async def test_activate_is_exclusive_and_keeps_old_data(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c = await manager(login_as)
    first, second = await create(c), await create(c, title="Вторая")

    r = await c.post(f"{URL}/{first['id']}/activate")
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is True

    db.add(
        Participant(
            conference_id=first["id"],
            external_id="A1",
            last_name="Иванов",
            first_name="Пётр",
            search_norm="иванов петр",
        )
    )
    await db.commit()

    r = await c.post(f"{URL}/{second['id']}/activate")
    assert r.json()["is_active"] is True
    db.expunge_all()
    active = list(await db.scalars(select(Conference.id).where(Conference.is_active)))
    assert active == [second["id"]]

    items = {i["id"]: i for i in (await c.get(URL)).json()["items"]}
    assert items[first["id"]]["is_active"] is False
    assert items[first["id"]]["participants_total"] == 1  # данные прошлой конференции целы
    assert (await db.scalar(select(func.count()).select_from(Participant))) == 1

    # повторная активация идемпотентна
    assert (await c.post(f"{URL}/{second['id']}/activate")).status_code == 200
    # и можно вернуть прошлую
    await c.post(f"{URL}/{first['id']}/activate")
    db.expunge_all()
    assert list(await db.scalars(select(Conference.id).where(Conference.is_active))) == [
        first["id"]
    ]


async def test_activate_unknown_is_404_and_keeps_current(login_as: LoginAs) -> None:
    c = await manager(login_as)
    conf = await create(c)
    await c.post(f"{URL}/{conf['id']}/activate")
    r = await c.post(f"{URL}/999999/activate")
    assert r.status_code == 404
    assert r.json()["code"] == "conference_not_found"
    items = (await c.get(URL)).json()["items"]
    assert [i["is_active"] for i in items] == [True]


async def test_permissions(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    other = await login_as("imports.run", "participants.view")
    assert (await other.get(URL)).status_code == 403
    assert (await other.post(URL, json=BODY)).status_code == 403
    assert (await other.put(f"{URL}/1", json=BODY)).status_code == 403
    assert (await other.post(f"{URL}/1/activate")).status_code == 403
    assert (await anon.get(URL)).status_code == 401
    # меняющие запросы требуют CSRF-заголовок
    c = await manager(login_as)
    del c.headers["X-Requested-With"]
    r = await c.post(URL, json=BODY)
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_required"


async def test_get_one(login_as: LoginAs, db: AsyncSession, anon: httpx.AsyncClient) -> None:
    c = await manager(login_as)
    conf = await create(c, invite_id_regex=r"id=(\d+)")
    db.add(
        Participant(
            conference_id=conf["id"],
            external_id="A1",
            last_name="Иванов",
            first_name="Пётр",
            search_norm="иванов петр",
        )
    )
    await db.commit()

    r = await c.get(f"{URL}/{conf['id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == conf["id"]
    assert body["title"] == BODY["title"]
    assert body["badge_type"] == "double"
    assert body["invite_id_regex"] == r"id=(\d+)"
    assert body["participants_total"] == 1
    assert body["is_active"] is False

    r = await c.get(f"{URL}/999999")
    assert r.status_code == 404
    assert r.json()["code"] == "conference_not_found"

    other = await login_as("imports.run")
    assert (await other.get(f"{URL}/{conf['id']}")).status_code == 403
    assert (await anon.get(f"{URL}/{conf['id']}")).status_code == 401


async def test_active_conference(login_as: LoginAs, anon: httpx.AsyncClient) -> None:
    # любой сотрудник, даже без разрешений
    nobody = await login_as()
    assert (await anon.get("/api/conferences/active")).status_code == 401
    assert (await nobody.get("/api/conferences/active")).json() is None

    c = await manager(login_as)
    conf = await create(c, title="Активная", front_template_id=None)
    assert (await nobody.get("/api/conferences/active")).json() is None
    await c.post(f"{URL}/{conf['id']}/activate")

    r = await nobody.get("/api/conferences/active")
    assert r.status_code == 200, r.text
    assert r.json() == {
        "id": conf["id"],
        "title": "Активная",
        "date_from": "2026-11-20",
        "date_to": "2026-11-21",
        "badge_type": "double",
    }
