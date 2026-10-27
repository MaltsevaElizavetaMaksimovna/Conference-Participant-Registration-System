"""Публичный профиль по токену из QR (QR-02, NF-06): без авторизации, без лишних данных."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import err
from app.badges import service
from app.badges.ratelimit import get_public_limiter
from app.badges.schemas import ProfileActive, ProfileOut, ProfileRevoked
from app.core.db import get_session
from app.core.errors import AppError, error_response
from app.core.text import full_name

# Ссылка из QR открывается на личных телефонах: ничего не кэшируем, не передаём адрес страницы
# дальше и не даём поисковикам индексировать.
PUBLIC_HEADERS = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
}


class PublicRoute(APIRoute):
    """Добавляет защитные заголовки к любому ответу маршрута, в том числе к 404 и 429."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            try:
                response = await original(request)
            except AppError as e:
                response = error_response(e.status_code, e.code, e.message, e.details)
                if e.status_code == 429 and "retry_after_s" in e.details:
                    response.headers["Retry-After"] = str(e.details["retry_after_s"])
            response.headers.update(PUBLIC_HEADERS)
            return response

        return handler


async def limit_requests(request: Request) -> None:
    """Не больше N запросов за окно с одного IP на оба адреса вместе (до любой работы с БД)."""
    ip = request.client.host if request.client else "unknown"
    retry_after = get_public_limiter(request.app).hit(ip)
    if retry_after is not None:
        raise AppError(
            "too_many_requests",
            "Слишком много запросов. Повторите позже",
            429,
            {"retry_after_s": retry_after},
        )


router = APIRouter(
    prefix="/public/profile",
    tags=["public"],
    route_class=PublicRoute,
    dependencies=[Depends(limit_requests)],
)

_RATE = (
    429,
    "`too_many_requests`: слишком частые запросы с одного адреса; `details.retry_after_s`",
)

_HEADERS_NOTE = (
    "Заголовки: `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, "
    "`X-Robots-Tag: noindex, nofollow`, `X-Content-Type-Options: nosniff`. "
    "Лимит: `RS_PUBLIC_PROFILE_RATE_LIMIT` запросов за `RS_PUBLIC_PROFILE_RATE_WINDOW_S` секунд "
    "с одного IP на оба адреса вместе."
)


def _profile_not_found() -> AppError:
    return AppError("profile_not_found", "Профиль не найден", 404)


@router.get(
    "/{token}",
    operation_id="public_profile",
    summary="Публичный профиль участника",
    description=(
        "Без авторизации. Страницу `/p/<token>` рисует фронт, данные берёт отсюда. "
        "Действующий код: ФИО, должность, организация и `photo_url` (`null`, если фото нет); "
        "пустые должность и организация приходят как `null`. Отозванный код: `200` и только "
        "`{status: revoked}`. Неизвестный или записанный неверно код: `404 profile_not_found`. "
        + _HEADERS_NOTE
    ),
    response_model=ProfileOut,
    responses=err(
        (
            404,
            "`profile_not_found`: токен неизвестен или записан неверно (ответ всегда одинаковый)",
        ),
        _RATE,
    ),
)
async def public_profile(
    token: str, session: AsyncSession = Depends(get_session)
) -> ProfileActive | ProfileRevoked:
    record = await service.find_profile(session, token)
    if record is None:
        raise _profile_not_found()
    if record.revoked:
        return ProfileRevoked(status="revoked")
    return ProfileActive(
        status="active",
        full_name=full_name(*record.name_parts),
        position=(record.position or "").strip() or None,
        organization=(record.organization or "").strip() or None,
        photo_url=f"/api/public/profile/{token}/photo" if record.photo_path else None,
    )


@router.get(
    "/{token}/photo",
    operation_id="public_profile_photo",
    summary="Фото из публичного профиля",
    description=(
        "Без авторизации. JPEG, только для действующего кода. Неизвестный или отозванный код: "
        "`404 profile_not_found`; у участника нет фото (или файл пропал): `404 photo_not_found`. "
        + _HEADERS_NOTE
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Фото в формате JPEG",
            "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(
            (404, "`profile_not_found` (код неизвестен или отозван) или `photo_not_found`"),
            _RATE,
        ),
    },
)
async def public_profile_photo(
    request: Request, token: str, session: AsyncSession = Depends(get_session)
) -> FileResponse:
    record = await service.find_profile(session, token)
    if record is None or record.revoked:
        raise _profile_not_found()
    path = service.resolve_photo(request.app.state.settings.photo_dir, record.photo_path)
    if path is None:
        raise AppError("photo_not_found", "Фото не найдено", 404)
    return FileResponse(path, media_type="image/jpeg")
