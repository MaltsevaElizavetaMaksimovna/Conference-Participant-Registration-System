"""Поля шаблона: `GET /api/admin/conferences/{id}/template-fields` (S-02)."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conference import ExtraFieldDef
from tests.conftest import LoginAs
from tests.registration_helpers import make_conference

STANDARD = ["last_name", "first_name", "middle_name", "position", "organization"]


def url(conference_id: int) -> str:
    return f"/api/admin/conferences/{conference_id}/template-fields"


async def test_fields_without_extra(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("conferences.manage")
    conf = await make_conference(db)
    r = await c.get(url(conf.id))
    assert r.status_code == 200, r.text
    fields = r.json()
    assert [f["group"] for f in fields] == ["standard"] * 5 + ["english"] * 5 + ["special"] * 3
    assert [f["key"] for f in fields if f["group"] == "standard"] == STANDARD
    assert [f["key"] for f in fields if f["group"] == "english"] == [f"{k}_en" for k in STANDARD]
    assert [f["key"] for f in fields if f["group"] == "special"] == ["full_name", "qr", "text"]
    labels = {f["key"]: f["label"] for f in fields}
    assert labels["last_name"] == "Фамилия"
    assert labels["organization_en"] == "Организация (EN)"
    assert all(f["label"] for f in fields)
    assert set(fields[0]) == {"key", "label", "group"}


async def test_extra_fields_come_from_the_conference(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("conferences.manage")
    conf, other = await make_conference(db), await make_conference(db, active=False)
    db.add_all(
        [
            ExtraFieldDef(conference_id=conf.id, key="sektsiya", label="Секция", sort_order=2),
            ExtraFieldDef(conference_id=conf.id, key="stol", label="Стол", sort_order=1),
            ExtraFieldDef(conference_id=other.id, key="chuzhoe", label="Чужое", sort_order=0),
        ]
    )
    await db.commit()

    fields = (await c.get(url(conf.id))).json()
    extra = [(f["key"], f["label"]) for f in fields if f["group"] == "extra"]
    assert extra == [("extra.stol", "Стол"), ("extra.sektsiya", "Секция")]
    # доп. поля стоят между английскими и специальными
    groups = [f["group"] for f in fields]
    assert groups == sorted(groups, key=["standard", "english", "extra", "special"].index)


async def test_fields_errors_and_permissions(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    conf = await make_conference(db)
    c = await login_as("conferences.manage")
    r = await c.get(url(999999))
    assert r.status_code == 404
    assert r.json()["code"] == "conference_not_found"
    assert (await (await login_as("imports.run")).get(url(conf.id))).status_code == 403
    assert (await anon.get(url(conf.id))).status_code == 401
