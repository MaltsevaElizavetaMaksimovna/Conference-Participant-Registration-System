"""Поток событий для панели (SSE, B1-11, RG-04, NF-01)."""

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.common import err
from app.api.deps import staff
from app.realtime.stream import event_stream

router = APIRouter(prefix="/events", tags=["realtime"])

SSE_EXAMPLE = (
    'event: stats\ndata: {"registered": 120, "total": 300}\n\n'
    ": keep-alive\n\n"
    'event: participant_updated\ndata: {"id": 17, "status": "registered", "flags": []}\n\n'
)


@router.get(
    "/stream",
    operation_id="events_stream",
    summary="Поток событий (SSE)",
    description=(
        "Разрешение: `participants.view`. `Content-Type: text/event-stream`. События: "
        "`stats` (`{registered, total}`) — сразу при подключении и после каждой регистрации; "
        "`participant_updated` (`{id, status, flags}`: статус и полный список пометок "
        "участника, по ним обновляйте строку списка); строки `: keep-alive` раз в 15 с. "
        "Неизвестные имена событий игнорируйте. Подключайтесь через `EventSource` с "
        "`withCredentials`. Поток бесконечный; при обрыве `EventSource` переподключается и "
        "снова получает `stats`. Обновление в панели — не позже 5 с после регистрации (NF-01)."
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
async def events_stream(request: Request) -> StreamingResponse:
    state = request.app.state
    return StreamingResponse(
        event_stream(state.event_hub, state.sessionmaker, state.settings.sse_keepalive_s),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
