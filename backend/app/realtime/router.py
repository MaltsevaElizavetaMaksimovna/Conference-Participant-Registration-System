"""Поток событий для панели (SSE). ЗАГЛУШКА (B1-11)."""

from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.api.common import STUB_TAG, err
from app.api.deps import staff
from app.realtime.schemas import StatsEvent

router = APIRouter(prefix="/events", tags=["realtime", STUB_TAG])

SSE_EXAMPLE = (
    'event: stats\ndata: {"registered": 120, "total": 300}\n\n'
    ": keep-alive\n\n"
    'event: participant_updated\ndata: {"participant": {"id": 17, ...}}\n\n'
)


async def _stub_stream() -> AsyncIterator[str]:
    # TODO B1-11: настоящий поток с подпиской на изменения и keep-alive раз в 15 с
    event = StatsEvent(registered=120, total=300)
    yield f"event: stats\ndata: {event.model_dump_json()}\n\n"
    yield ": keep-alive\n\n"


@router.get(
    "/stream",
    operation_id="events_stream",
    summary="Поток событий (SSE)",
    description=(
        "Разрешение: `participants.view`. `Content-Type: text/event-stream`. События: "
        "`stats` (`{registered, total}`) — сразу при подключении и после каждой регистрации; "
        "`participant_updated` (`{participant: ParticipantShort}`); строки `: keep-alive` "
        "раз в 15 с. Подключайтесь через `EventSource` с `withCredentials`. "
        "**Заглушка:** отдаёт одно событие `stats` и keep-alive, затем закрывает поток."
    ),
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Поток server-sent events",
            "content": {
                "text/event-stream": {"schema": {"type": "string"}, "example": SSE_EXAMPLE}
            },
        },
        **err(401, 403),
    },
    dependencies=staff("participants.view"),
)
async def events_stream() -> StreamingResponse:
    return StreamingResponse(
        _stub_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
