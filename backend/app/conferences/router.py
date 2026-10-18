"""Конференции (AD-01). ЗАГЛУШКИ (B1-04)."""

from datetime import date

from fastapi import APIRouter

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff
from app.api.stubs import T0
from app.conferences.schemas import ConferenceIn, ConferenceOut

router = APIRouter(prefix="/admin/conferences", tags=["admin: conferences", STUB_TAG])


def _conf(conf_id: int, *, active: bool, title: str = "Демо-конференция") -> ConferenceOut:
    return ConferenceOut(
        id=conf_id,
        title=title,
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 21),
        badge_type="single",
        front_template_id=1,
        back_template_id=None,
        changed_template_id=2,
        changed_back_template_id=None,
        invite_id_regex=None,
        is_active=active,
        participants_total=300,
        created_at=T0,
    )


@router.get(
    "",
    operation_id="conferences_list",
    summary="Список конференций",
    description="Разрешение: `conferences.manage`.",
    response_model=Page[ConferenceOut],
    dependencies=staff("conferences.manage"),
    responses=err(401, 403),
)
async def conferences_list(limit: Limit = 50, offset: Offset = 0) -> Page[ConferenceOut]:
    items = [_conf(1, active=True), _conf(2, active=False, title="Прошлогодняя конференция")]
    return Page[ConferenceOut](items=items[offset : offset + limit], total=len(items))


@router.post(
    "",
    operation_id="conferences_create",
    summary="Создать конференцию",
    description="Разрешение: `conferences.manage`. Новая конференция неактивна.",
    status_code=201,
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, 422),
)
async def conferences_create(body: ConferenceIn) -> ConferenceOut:
    return ConferenceOut(
        **body.model_dump(), id=3, is_active=False, participants_total=0, created_at=T0
    )


@router.put(
    "/{conference_id}",
    operation_id="conferences_update",
    summary="Изменить конференцию",
    description="Разрешение: `conferences.manage`.",
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, 404, 422),
)
async def conferences_update(conference_id: int, body: ConferenceIn) -> ConferenceOut:
    return ConferenceOut(
        **body.model_dump(),
        id=conference_id,
        is_active=conference_id == 1,
        participants_total=300,
        created_at=T0,
    )


@router.post(
    "/{conference_id}/activate",
    operation_id="conferences_activate",
    summary="Сделать конференцию активной",
    description=(
        "Разрешение: `conferences.manage`. Атомарно: предыдущая активная становится неактивной. "
        "Терминалы и панель работают с активной конференцией."
    ),
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, 404),
)
async def conferences_activate(conference_id: int) -> ConferenceOut:
    return _conf(conference_id, active=True)
