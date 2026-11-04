"""Автотесты предпросмотра, проверки переполнения и пробной печати шаблона (B2-09, PR-02, PR-03)."""

import uuid
from io import BytesIO
from typing import Any

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.badges.render.data import label_data
from app.badges.render.label import DPI, dots, render_label, to_png
from app.badges.render.text_fit import fit_text, overflows
from app.core.config import Settings
from app.core.text import normalize_search
from app.models.device import Printer
from app.models.participant import BadgeToken, Participant
from app.models.printing import PrintJob
from app.templates import preview
from app.templates.service import get_template, template_spec
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

LONG_ORG = (
    "Научно-исследовательский институт проблем проектирования "
    "и моделирования сложных технических систем"
)


async def manager(login_as: LoginAs) -> StaffClient:
    """Клиент сотрудника с правом conferences.manage."""
    return await login_as("conferences.manage")


async def create_conf(c: StaffClient, **fields: Any) -> dict[str, Any]:
    """Создание тестовой конференции."""
    r = await c.post("/api/admin/conferences", json={**CONF_BODY, **fields})
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def error_info(r: httpx.Response) -> tuple[str, dict[str, Any]]:
    """Извлечение кода ошибки и details из ответа."""
    data: dict[str, Any] = r.json()
    if "error" in data and isinstance(data["error"], dict):
        return str(data["error"].get("code", "")), dict(data["error"].get("details", {}))
    return str(data.get("code", "")), dict(data.get("details", {}))


async def create_participant(
    db: AsyncSession,
    conference_id: int,
    *,
    last_name: str = "Иванов",
    first_name: str = "Пётр",
    middle_name: str | None = "Сергеевич",
    position: str | None = "Инженер",
    organization: str | None = "ООО Ромашка",
    external_id: str | None = None,
) -> Participant:
    """Создание участника в БД."""
    ext_id = external_id or f"EXT-{uuid.uuid4().hex[:8]}"
    p = Participant(
        conference_id=conference_id,
        external_id=ext_id,
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        position=position,
        organization=organization,
        search_norm=normalize_search(f"{last_name} {first_name} {middle_name or ''}"),
    )
    db.add(p)
    await db.commit()
    return p


async def create_printer(db: AsyncSession, name: str | None = None) -> Printer:
    """Создание принтера в БД."""
    prn_name = name or f"Принтер-{uuid.uuid4().hex[:8]}"
    printer = Printer(name=prn_name)
    db.add(printer)
    await db.commit()
    return printer


# 1. preview.png без participant_id -> 200, PNG 480x320, no-store
async def test_preview_png_sample_without_participant(login_as: LoginAs) -> None:
    """Предпросмотр без participant_id: 200, content-type: image/png, no-store, 480x320."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]
    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    r = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/preview.png")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/png"
    assert r.headers.get("cache-control") == "no-store"

    img = Image.open(BytesIO(r.content))
    assert img.size == (480, 320)


# 2. preview.png с участником этой конференции и ошибки
async def test_preview_png_with_participant(login_as: LoginAs, db: AsyncSession) -> None:
    """Предпросмотр с участником: 200, картинка отличается от образца."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]
    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    p = await create_participant(
        db,
        cid,
        last_name="Сидоров",
        first_name="Алексей",
        organization="ПАО Тест",
    )

    r_sample = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/preview.png")
    assert r_sample.status_code == 200, r_sample.text

    r_part = await c.get(
        f"/api/admin/conferences/{cid}/templates/{tid}/preview.png?participant_id={p.id}"
    )
    assert r_part.status_code == 200, r_part.text
    assert r_part.headers["content-type"] == "image/png"
    assert r_part.headers.get("cache-control") == "no-store"
    assert r_part.content != r_sample.content


async def test_preview_png_errors_and_permissions(login_as: LoginAs, db: AsyncSession) -> None:
    """Ошибки предпросмотра: участник чужой конф, несуществующие объекты, 403 без прав."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]
    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    # Участник другой конференции -> 404 participant_not_found
    conf2 = await create_conf(c, title="Другая конференция")
    p_other = await create_participant(db, conf2["id"])
    r_other = await c.get(
        f"/api/admin/conferences/{cid}/templates/{tid}/preview.png?participant_id={p_other.id}"
    )
    assert r_other.status_code == 404, r_other.text
    assert error_info(r_other)[0] == "participant_not_found"

    # Несуществующий участник -> 404 participant_not_found
    r_no_part = await c.get(
        f"/api/admin/conferences/{cid}/templates/{tid}/preview.png?participant_id=999999"
    )
    assert r_no_part.status_code == 404, r_no_part.text
    assert error_info(r_no_part)[0] == "participant_not_found"

    # Несуществующий шаблон -> 404 template_not_found
    r_no_tpl = await c.get(f"/api/admin/conferences/{cid}/templates/999999/preview.png")
    assert r_no_tpl.status_code == 404, r_no_tpl.text
    assert error_info(r_no_tpl)[0] == "template_not_found"

    # Без разрешения -> 403
    viewer = await login_as("participants.view")
    r_no_perm = await viewer.get(f"/api/admin/conferences/{cid}/templates/{tid}/preview.png")
    assert r_no_perm.status_code == 403, r_no_perm.text


# 3. Предпросмотр не выдаёт код бейджа
async def test_preview_does_not_issue_badge_token(login_as: LoginAs, db: AsyncSession) -> None:
    """Предпросмотр не выдаёт код бейджа незарегистрированному участнику."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]
    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    p = await create_participant(db, cid)
    pid = p.id

    r = await c.get(
        f"/api/admin/conferences/{cid}/templates/{tid}/preview.png?participant_id={pid}"
    )
    assert r.status_code == 200, r.text

    # В badge_token нет записей этого участника
    tokens = (await db.scalars(select(BadgeToken).where(BadgeToken.participant_id == pid))).all()
    assert len(tokens) == 0

    # Статус участника остался not_registered
    p_db = (await db.scalars(select(Participant).where(Participant.id == pid))).one()
    assert p_db.status == "not_registered"
    assert p_db.registered_at is None


# 4. QR в предпросмотре через прямой вызов сервиса
async def test_preview_png_qr_service_call(
    login_as: LoginAs, db: AsyncSession, database_url: str
) -> None:
    """QR в предпросмотре (прямой вызов сервиса) совпадает с to_png(render_label(...))."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]
    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    p = await create_participant(db, cid, last_name="Иванов", first_name="Пётр")
    pid = p.id

    token = BadgeToken(participant_id=pid, token="tok-123", status="active")
    db.add(token)
    await db.commit()

    test_settings = Settings(
        env="test",
        database_url=database_url,
        public_base_url="https://reg.example.ru",
    )

    actual_png = await preview.preview_png(db, test_settings, cid, tid, pid)

    tpl = await get_template(db, cid, tid)
    p_fresh = (await db.scalars(select(Participant).where(Participant.id == pid))).one()
    expected_png = to_png(
        render_label(
            template_spec(tpl),
            label_data(p_fresh, "https://reg.example.ru/p/tok-123"),
        ).image
    )

    assert actual_png == expected_png


# 5. overflow: участники, которые не помещаются в шаблон
async def test_template_overflow_items(login_as: LoginAs, db: AsyncSession) -> None:
    """GET overflow возвращает ровно элемент с длинной организацией; text и чужие не попадают."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]

    org_w_mm = 20.0
    if overflows(
        "ООО Ромашка",
        dots(org_w_mm),
        dots(5.0),
        min_font_size=8.0,
        max_lines=1,
        bold=False,
        dpi=DPI,
    ):
        org_w_mm = 25.0

    overflow_template: dict[str, Any] = {
        "name": "Шаблон с маленьким полем",
        "kind": "front",
        "width_mm": 60,
        "height_mm": 40,
        "gap_mm": 2,
        "elements": [
            {
                "type": "field",
                "field": "organization",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": org_w_mm,
                "h_mm": 5,
                "font_size": 10,
                "min_font_size": 8,
                "max_lines": 1,
            },
            {
                "type": "text",
                "text": "Очень длинный текст надписи, заведомо не влезающий в рамку",
                "x_mm": 5,
                "y_mm": 15,
                "w_mm": 10,
                "h_mm": 5,
                "font_size": 10,
                "min_font_size": 8,
                "max_lines": 1,
            },
        ],
    }

    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=overflow_template)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    # Трое участников в этой конференции:
    # 1: с очень длинной организацией (>= 100 символов)
    p_long = await create_participant(
        db,
        cid,
        last_name="Иванов",
        first_name="Иван",
        middle_name="Иванович",
        organization=LONG_ORG,
    )
    # 2: с короткой организацией («ООО Ромашка» помещается)
    await create_participant(
        db,
        cid,
        last_name="Петров",
        first_name="Пётр",
        middle_name="Петрович",
        organization="ООО Ромашка",
    )
    # 3: без организации
    await create_participant(
        db,
        cid,
        last_name="Сидоров",
        first_name="Сидор",
        middle_name="Сидорович",
        organization=None,
    )

    # Участник другой конференции с длинной организацией (не должен попасть)
    conf_other = await create_conf(c, title="Другая конференция")
    await create_participant(
        db,
        conf_other["id"],
        last_name="Смирнов",
        first_name="Сергей",
        organization=LONG_ORG,
    )

    r = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/overflow")
    assert r.status_code == 200, r.text
    data: dict[str, Any] = r.json()
    items: list[dict[str, Any]] = data["items"]

    assert len(items) == 1
    item = items[0]
    assert item["participant_id"] == p_long.id
    assert item["full_name"] == "Иванов Иван Иванович"
    assert item["field"] == "organization"
    assert item["value"] == LONG_ORG


async def test_template_overflow_alphabetical_order(login_as: LoginAs, db: AsyncSession) -> None:
    """Порядок элементов в overflow сортируется по фамилии (Абрамов перед Яковлев)."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]

    org_w_mm = 20.0
    if overflows(
        "ООО Ромашка",
        dots(org_w_mm),
        dots(5.0),
        min_font_size=8.0,
        max_lines=1,
        bold=False,
        dpi=DPI,
    ):
        org_w_mm = 25.0

    overflow_template: dict[str, Any] = {
        "name": "Шаблон сортировки",
        "kind": "front",
        "width_mm": 60,
        "height_mm": 40,
        "gap_mm": 2,
        "elements": [
            {
                "type": "field",
                "field": "organization",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": org_w_mm,
                "h_mm": 5,
                "font_size": 10,
                "min_font_size": 8,
                "max_lines": 1,
            }
        ],
    }

    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=overflow_template)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    # Создаём сначала Яковлева, затем Абрамова (чтобы ID Абрамова был больше)
    p_yakovlev = await create_participant(
        db,
        cid,
        last_name="Яковлев",
        first_name="Яков",
        middle_name="Яковлевич",
        organization=LONG_ORG,
    )
    p_abramov = await create_participant(
        db,
        cid,
        last_name="Абрамов",
        first_name="Абрам",
        middle_name="Абрамович",
        organization=LONG_ORG,
    )

    r = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/overflow")
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]

    assert len(items) == 2
    assert items[0]["participant_id"] == p_abramov.id
    assert items[0]["full_name"] == "Абрамов Абрам Абрамович"
    assert items[1]["participant_id"] == p_yakovlev.id
    assert items[1]["full_name"] == "Яковлев Яков Яковлевич"


# 6. PUT шаблона возвращает тот же overflow; после расширения рамки overflow пуст
async def test_template_put_overflow_and_expansion(login_as: LoginAs, db: AsyncSession) -> None:
    """PUT шаблона возвращает в overflow тот же список; после расширения рамки overflow пуст."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]

    org_w_mm = 20.0
    if overflows(
        "ООО Ромашка",
        dots(org_w_mm),
        dots(5.0),
        min_font_size=8.0,
        max_lines=1,
        bold=False,
        dpi=DPI,
    ):
        org_w_mm = 25.0

    tpl_body: dict[str, Any] = {
        "name": "Шаблон для PUT",
        "kind": "front",
        "width_mm": 60,
        "height_mm": 40,
        "gap_mm": 2,
        "elements": [
            {
                "type": "field",
                "field": "organization",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": org_w_mm,
                "h_mm": 5,
                "font_size": 10,
                "min_font_size": 8,
                "max_lines": 1,
            }
        ],
    }

    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=tpl_body)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    await create_participant(db, cid, organization=LONG_ORG)

    # 1. GET overflow
    r_get = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/overflow")
    assert r_get.status_code == 200, r_get.text
    get_items = r_get.json()["items"]
    assert len(get_items) == 1

    # 2. PUT с тем же шаблоном -> overflow совпадает с GET
    r_put = await c.put(f"/api/admin/conferences/{cid}/templates/{tid}", json=tpl_body)
    assert r_put.status_code == 200, r_put.text
    put_data = r_put.json()
    assert put_data["overflow"] == get_items

    # 3. PUT с расширенной рамкой организации -> overflow пуст
    expanded_body: dict[str, Any] = {
        **tpl_body,
        "elements": [
            {
                "type": "field",
                "field": "organization",
                "x_mm": 5,
                "y_mm": 5,
                "w_mm": 50,
                "h_mm": 30,
                "font_size": 10,
                "min_font_size": 8,
                "max_lines": 10,
            }
        ],
    }
    r_put_expanded = await c.put(
        f"/api/admin/conferences/{cid}/templates/{tid}", json=expanded_body
    )
    assert r_put_expanded.status_code == 200, r_put_expanded.text
    assert r_put_expanded.json()["overflow"] == []

    # 4. GET overflow после расширения также пуст
    r_get_after = await c.get(f"/api/admin/conferences/{cid}/templates/{tid}/overflow")
    assert r_get_after.status_code == 200, r_get_after.text
    assert r_get_after.json()["items"] == []


# 7. test-print
async def test_template_test_print_success_and_db_state(
    login_as: LoginAs, db: AsyncSession
) -> None:
    """Пробная печать шаблона: статус 200, поля PrintJob, статус участника не меняется."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]

    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    printer = await create_printer(db)
    prid = printer.id

    p = await create_participant(db, cid)
    pid = p.id

    # Пробная печать с участником
    r = await c.post(
        f"/api/admin/conferences/{cid}/templates/{tid}/test-print",
        json={"participant_id": pid, "printer_id": prid},
    )
    assert r.status_code == 200, r.text
    job_id: int = r.json()["print_job_id"]
    assert isinstance(job_id, int) and job_id > 0

    # Проверяем запись в БД
    job = (await db.scalars(select(PrintJob).where(PrintJob.id == job_id))).one()
    assert job.kind == "test"
    assert job.sides == 1
    assert job.template_id == tid
    assert job.participant_id == pid
    assert job.printer_id == prid
    assert job.status == "pending"
    assert job.created_by_user_id == c.user_id

    # Участник остался not_registered, registered_at is None
    p_db = (await db.scalars(select(Participant).where(Participant.id == pid))).one()
    assert p_db.status == "not_registered"
    assert p_db.registered_at is None

    # Пробная печать с participant_id: null
    r_null = await c.post(
        f"/api/admin/conferences/{cid}/templates/{tid}/test-print",
        json={"participant_id": None, "printer_id": prid},
    )
    assert r_null.status_code == 200, r_null.text
    job_id_null: int = r_null.json()["print_job_id"]
    job_null = (await db.scalars(select(PrintJob).where(PrintJob.id == job_id_null))).one()
    assert job_null.participant_id is None
    assert job_null.kind == "test"
    assert job_null.sides == 1
    assert job_null.template_id == tid
    assert job_null.printer_id == prid
    assert job_null.status == "pending"
    assert job_null.created_by_user_id == c.user_id


async def test_template_test_print_errors_and_permissions(
    login_as: LoginAs, db: AsyncSession
) -> None:
    """Ошибки пробной печати: 404 для принтера/участника/шаблона и 403 без прав."""
    c = await manager(login_as)
    conf = await create_conf(c)
    cid = conf["id"]

    r_tpl = await c.post(f"/api/admin/conferences/{cid}/templates", json=SAMPLE_TEMPLATE)
    assert r_tpl.status_code == 201, r_tpl.text
    tid = r_tpl.json()["id"]

    printer = await create_printer(db)
    prid = printer.id
    p = await create_participant(db, cid)
    pid = p.id

    # Несуществующий принтер -> 404 printer_not_found
    r_no_prn = await c.post(
        f"/api/admin/conferences/{cid}/templates/{tid}/test-print",
        json={"participant_id": pid, "printer_id": 999999},
    )
    assert r_no_prn.status_code == 404, r_no_prn.text
    assert error_info(r_no_prn)[0] == "printer_not_found"

    # Участник другой конференции -> 404 participant_not_found
    conf2 = await create_conf(c, title="Другая конференция")
    p_other = await create_participant(db, conf2["id"])
    r_other_p = await c.post(
        f"/api/admin/conferences/{cid}/templates/{tid}/test-print",
        json={"participant_id": p_other.id, "printer_id": prid},
    )
    assert r_other_p.status_code == 404, r_other_p.text
    assert error_info(r_other_p)[0] == "participant_not_found"

    # Несуществующий шаблон -> 404 template_not_found
    r_no_tpl = await c.post(
        f"/api/admin/conferences/{cid}/templates/999999/test-print",
        json={"participant_id": pid, "printer_id": prid},
    )
    assert r_no_tpl.status_code == 404, r_no_tpl.text
    assert error_info(r_no_tpl)[0] == "template_not_found"

    # Без разрешения -> 403
    viewer = await login_as("participants.view")
    r_no_perm = await viewer.post(
        f"/api/admin/conferences/{cid}/templates/{tid}/test-print",
        json={"participant_id": pid, "printer_id": prid},
    )
    assert r_no_perm.status_code == 403, r_no_perm.text


# 8. overflows(...) совпадает с fit_text(...).overflow
@pytest.mark.parametrize(
    (
        "text",
        "box_w",
        "box_h",
        "font_size",
        "min_font_size",
        "max_lines",
        "expected_overflow",
    ),
    [
        ("Короткий текст", 300, 100, 14.0, 8.0, 2, False),
        (
            "Очень длинный текст, который заведомо не поместится в маленькую рамку",
            40,
            20,
            14.0,
            8.0,
            1,
            True,
        ),
        ("Сверхдлинноесловокотороеширечемвсярамка", 80, 80, 14.0, 8.0, 3, True),
        (
            "Раз два три четыре пять шесть семь восемь девять десять",
            120,
            300,
            14.0,
            8.0,
            1,
            True,
        ),
        (
            "Раз два три четыре пять шесть семь восемь девять десять",
            120,
            300,
            14.0,
            8.0,
            10,
            False,
        ),
    ],
)
def test_overflows_matches_fit_text(
    text: str,
    box_w: int,
    box_h: int,
    font_size: float,
    min_font_size: float,
    max_lines: int,
    expected_overflow: bool,
) -> None:
    """overflows(...) совпадает с fit_text(...).overflow для различных сценариев."""
    bold = False
    dpi = DPI
    of = overflows(
        text,
        box_w,
        box_h,
        min_font_size=min_font_size,
        max_lines=max_lines,
        bold=bold,
        dpi=dpi,
    )
    ft = fit_text(
        text,
        box_w,
        box_h,
        font_size=font_size,
        min_font_size=min_font_size,
        max_lines=max_lines,
        bold=bold,
        dpi=dpi,
    )
    assert of == ft.overflow
    assert of == expected_overflow
