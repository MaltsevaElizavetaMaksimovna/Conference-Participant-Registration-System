"""Публичный профиль по токену из QR (без авторизации). ЗАГЛУШКИ (B2-13)."""

from fastapi import APIRouter, Response

from app.api.common import STUB_TAG, err
from app.api.stubs import JPEG_1X1
from app.badges.schemas import ProfileActive, ProfileOut, ProfileRevoked
from app.core.errors import AppError

router = APIRouter(prefix="/public/profile", tags=["public", STUB_TAG])

_NOT_FOUND = (404, "`profile_not_found`: токен неизвестен (ответ одинаковый для любого токена)")
_RATE = (429, "`too_many_requests`: слишком частые запросы с одного адреса")


def _profile_not_found() -> AppError:
    return AppError("profile_not_found", "Профиль не найден", 404)


@router.get(
    "/{token}",
    operation_id="public_profile",
    summary="Публичный профиль участника",
    description=(
        "Без авторизации. Страницу `/p/<token>` рисует фронт, данные берёт отсюда. "
        "**Заглушка:** токен `revoked` даёт `{status: revoked}`, токен `missing` — "
        "`404 profile_not_found`, любой другой — действующий профиль."
    ),
    response_model=ProfileOut,
    responses=err(_NOT_FOUND, _RATE),
)
async def public_profile(token: str) -> ProfileActive | ProfileRevoked:
    if token == "missing":
        raise _profile_not_found()
    if token == "revoked":
        return ProfileRevoked(status="revoked")
    return ProfileActive(
        status="active",
        full_name="Иванов Пётр Сергеевич",
        position="Инженер",
        organization="ООО Ромашка",
        photo_url=f"/api/public/profile/{token}/photo",
    )


@router.get(
    "/{token}/photo",
    operation_id="public_profile_photo",
    summary="Фото из публичного профиля",
    description="Без авторизации. JPEG, только для действующего токена; заглушка отдаёт 1×1.",
    response_class=Response,
    responses={
        200: {
            "description": "Фото в формате JPEG",
            "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(_NOT_FOUND, _RATE),
    },
)
async def public_profile_photo(token: str) -> Response:
    if token in ("missing", "revoked"):
        raise _profile_not_found()
    return Response(content=JPEG_1X1, media_type="image/jpeg")
