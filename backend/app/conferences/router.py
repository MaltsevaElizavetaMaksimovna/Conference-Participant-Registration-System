"""Конференции (AD-01, B1-04)."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, Page, err
from app.api.deps import staff
from app.conferences import service
from app.conferences.schemas import ConferenceIn, ConferenceOut
from app.core.db import get_session

router = APIRouter(prefix="/admin/conferences", tags=["admin: conferences"])

_NOT_FOUND = (404, "`conference_not_found`: конференции нет")
_TEMPLATES = (
    "Шаблон привязывается только после создания конференции, должен принадлежать ей и иметь "
    "вид `front`/`back`/`changed`/`changed_back` соответственно полю."
)


@router.get(
    "",
    operation_id="conferences_list",
    summary="Список конференций",
    description="Разрешение: `conferences.manage`. Сначала новые.",
    response_model=Page[ConferenceOut],
    dependencies=staff("conferences.manage"),
    responses=err(401, 403),
)
async def conferences_list(
    limit: Limit = 50, offset: Offset = 0, session: AsyncSession = Depends(get_session)
) -> Page[ConferenceOut]:
    items, total = await service.list_conferences(session, limit, offset)
    return Page[ConferenceOut](items=items, total=total)


@router.post(
    "",
    operation_id="conferences_create",
    summary="Создать конференцию",
    description=(
        "Разрешение: `conferences.manage`. Новая конференция неактивна; шаблоны к ней "
        "привязываются после создания (`PUT`)."
    ),
    status_code=201,
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, 422),
)
async def conferences_create(
    body: ConferenceIn, session: AsyncSession = Depends(get_session)
) -> ConferenceOut:
    return await service.create_conference(session, body)


@router.put(
    "/{conference_id}",
    operation_id="conferences_update",
    summary="Изменить конференцию",
    description=f"Разрешение: `conferences.manage`. {_TEMPLATES}",
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, _NOT_FOUND, 422),
)
async def conferences_update(
    conference_id: int, body: ConferenceIn, session: AsyncSession = Depends(get_session)
) -> ConferenceOut:
    return await service.update_conference(session, conference_id, body)


@router.post(
    "/{conference_id}/activate",
    operation_id="conferences_activate",
    summary="Сделать конференцию активной",
    description=(
        "Разрешение: `conferences.manage`. Атомарно: предыдущая активная становится неактивной. "
        "Терминалы и панель работают с активной конференцией; данные прошлых сохраняются."
    ),
    response_model=ConferenceOut,
    dependencies=staff("conferences.manage", write=True),
    responses=err(401, 403, _NOT_FOUND),
)
async def conferences_activate(
    conference_id: int, session: AsyncSession = Depends(get_session)
) -> ConferenceOut:
    return await service.activate_conference(session, conference_id)
