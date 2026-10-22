"""Журнал событий (S-02): скан, регистрация, печать, правки по активной конференции."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import Limit, Offset, Page, err
from app.api.deps import staff
from app.core.db import get_session
from app.eventlog import service
from app.eventlog.schemas import EventOut
from app.participants.schemas import EventType

router = APIRouter(prefix="/admin/events", tags=["admin: events"])


@router.get(
    "",
    operation_id="events_list",
    summary="Журнал событий",
    description=(
        "Разрешение: `participants.view`. События активной конференции (сканы, регистрации, "
        "печать, правки), новые сверху; без активной конференции список пуст. "
        "Фильтры `type`, `participant_id`, `terminal_id` сочетаются через И."
    ),
    response_model=Page[EventOut],
    dependencies=staff("participants.view"),
    responses=err(401, 403, 422),
)
async def events_list(
    type: Annotated[EventType | None, Query(description="Тип события")] = None,
    participant_id: Annotated[int | None, Query(description="Только события участника")] = None,
    terminal_id: Annotated[int | None, Query(description="Только события терминала")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> Page[EventOut]:
    items, total = await service.list_events(
        session,
        type=type,
        participant_id=participant_id,
        terminal_id=terminal_id,
        limit=limit,
        offset=offset,
    )
    return Page[EventOut](items=items, total=total)
