"""История загрузок: `GET /api/admin/conferences/{id}/imports` (S-02)."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.imports import ImportBatch
from tests.conftest import LoginAs, StaffClient
from tests.import_files import make_conference, people, upload_report, xlsx_bytes


def url(conference_id: int) -> str:
    return f"/api/admin/conferences/{conference_id}/imports"


async def test_list_shows_batches_newest_first_with_totals(
    login_as: LoginAs, db: AsyncSession
) -> None:
    c: StaffClient = await login_as("imports.run")
    conf, other = await make_conference(db), await make_conference(db, "Другая")

    # первая загрузка: 3 строки, у одной нет фамилии -> пропущена
    rows = people(3)
    rows[1][1] = ""
    first = await upload_report(c, conf, "first.xlsx", xlsx_bytes(rows))
    # вторая: тот же файл, у первого участника меняется должность, плюс новый участник
    rows2 = people(4)
    rows2[0][4] = "Директор"
    rows2[1][1] = ""
    second = await upload_report(c, conf, "second.xlsx", xlsx_bytes(rows2))
    await upload_report(c, other, "other.xlsx", xlsx_bytes(people(2)))

    r = await c.get(url(conf))
    assert r.status_code == 200, r.text
    page = r.json()
    assert page["total"] == 2
    new, old = page["items"]
    assert [new["id"], old["id"]] == [second["batch_id"], first["batch_id"]]
    assert set(new) == {
        "id",
        "source",
        "file_name",
        "status",
        "created_at",
        "finished_at",
        "user_login",
        "loaded",
        "updated",
        "skipped",
    }
    assert (old["file_name"], old["source"], old["status"]) == ("first.xlsx", "file", "done")
    assert old["user_login"] == c.login
    assert (old["loaded"], old["updated"], old["skipped"]) == (2, 0, 1)
    assert new["finished_at"] is not None
    # итоги в списке совпадают с полным отчётом
    assert (new["loaded"], new["updated"], new["skipped"]) == (
        second["loaded"],
        second["updated"],
        second["skipped"],
    )
    assert new["updated"] == 1


async def test_list_pagination_and_running_batch(login_as: LoginAs, db: AsyncSession) -> None:
    c = await login_as("imports.run")
    conf = await make_conference(db)
    for _ in range(3):
        db.add(
            ImportBatch(conference_id=conf, source="bitrix", status="running", created_at=utcnow())
        )
    await db.commit()

    r = await c.get(url(conf), params={"limit": 2, "offset": 1})
    page = r.json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    item = page["items"][0]
    assert item["source"] == "bitrix"
    assert item["file_name"] is None
    assert item["user_login"] is None
    assert item["status"] == "running"
    assert item["finished_at"] is None
    assert (item["loaded"], item["updated"], item["skipped"]) == (0, 0, 0)


async def test_list_errors_and_permissions(
    login_as: LoginAs, anon: httpx.AsyncClient, db: AsyncSession
) -> None:
    conf = await make_conference(db)
    c = await login_as("imports.run")
    r = await c.get(url(999999))
    assert r.status_code == 404
    assert r.json()["code"] == "conference_not_found"
    assert (await c.get(url(conf))).json() == {"items": [], "total": 0}
    assert (await (await login_as("conferences.manage")).get(url(conf))).status_code == 403
    assert (await anon.get(url(conf))).status_code == 401
