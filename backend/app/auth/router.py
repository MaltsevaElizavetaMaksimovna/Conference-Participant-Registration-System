"""Вход и выход сотрудников, текущий профиль, принтер панели (B1-01)."""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import err
from app.api.deps import staff
from app.auth import service
from app.auth.deps import SESSION_COOKIE, CurrentStaff, get_current_staff
from app.auth.ratelimit import get_login_limiter
from app.auth.schemas import LoginIn, MeOut, PanelPrinterIn
from app.core.config import Settings
from app.core.db import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post(
    "/login",
    operation_id="auth_login",
    summary="Вход",
    description=(
        "Проверяет логин (без учёта регистра) и пароль, ставит cookie `rs_session` "
        "(HttpOnly, SameSite=Lax, срок — `RS_SESSION_TTL_HOURS`, по умолчанию 12 ч) и "
        "возвращает профиль. Разрешения фиксируются на момент входа: изменение роли "
        "действует со следующего входа. Ошибки: `401 invalid_credentials`, "
        "`403 user_blocked`, `429 too_many_requests` (10 неудач на пару IP + логин за 5 минут)."
    ),
    response_model=MeOut,
    responses=err(
        (401, "`invalid_credentials`: неверный логин или пароль"),
        (403, "`user_blocked`: учётная запись заблокирована"),
        422,
        429,
    ),
)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    settings = _settings(request)
    token, me = await service.authenticate(
        session,
        settings,
        get_login_limiter(request.app),
        login=body.login,
        password=body.password,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.env == "prod",
        path="/",
    )
    return me


@router.post(
    "/logout",
    operation_id="auth_logout",
    summary="Выход",
    description="Отзывает сессию и удаляет cookie.",
    status_code=204,
    response_class=Response,
    dependencies=staff(write=True),
    responses=err(401, 403),
)
async def logout(
    request: Request,
    current: CurrentStaff = Depends(get_current_staff),
    session: AsyncSession = Depends(get_session),
) -> Response:
    await service.revoke_session(session, current.session_id)
    response = Response(status_code=204)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=_settings(request).env == "prod",
    )
    return response


@router.get(
    "/me",
    operation_id="auth_me",
    summary="Текущий сотрудник",
    description=(
        "Профиль, роль и разрешения из снимка на момент входа. "
        "Без действующей сессии — `401 unauthenticated`."
    ),
    response_model=MeOut,
    dependencies=staff(),
    responses=err(401),
)
async def me(
    current: CurrentStaff = Depends(get_current_staff),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    return await service.current_profile(
        session, current.user_id, service.sort_permissions({str(p) for p in current.permissions})
    )


@router.put(
    "/me/printer",
    operation_id="auth_set_panel_printer",
    summary="Выбрать принтер панели",
    description=(
        "Разрешение: `stickers.print`. Запоминает принтер для печати из панели (RG-05); "
        "`null` сбрасывает выбор. Несуществующий принтер — `404 printer_not_found`."
    ),
    response_model=MeOut,
    dependencies=staff("stickers.print", write=True),
    responses=err(401, 403, (404, "`printer_not_found`: принтера с таким id нет"), 422),
)
async def set_panel_printer(
    body: PanelPrinterIn,
    current: CurrentStaff = Depends(get_current_staff),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    await service.set_panel_printer(session, current.user_id, body.printer_id)
    return await service.current_profile(
        session, current.user_id, service.sort_permissions({str(p) for p in current.permissions})
    )
