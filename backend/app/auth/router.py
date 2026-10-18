"""Вход и выход сотрудников. ЗАГЛУШКИ (B1-01)."""

from typing import Annotated

from fastapi import APIRouter, Cookie, Response

from app.api.common import STUB_TAG, err
from app.api.deps import staff
from app.auth.schemas import LoginIn, MeOut, PanelPrinterIn
from app.core.errors import AppError
from app.roles.router import ALL_PERMISSIONS, REGISTRAR_PERMISSIONS
from app.roles.schemas import RoleRef

router = APIRouter(prefix="/auth", tags=["auth", STUB_TAG])

COOKIE = "rs_session"


def _me(kind: str, printer_id: int | None = None) -> MeOut:
    if kind == "admin":
        return MeOut(
            id=1,
            full_name="Администратор Системы",
            login="admin",
            role=RoleRef(id=1, name="Администратор"),
            permissions=ALL_PERMISSIONS,
            panel_printer_id=printer_id,
        )
    return MeOut(
        id=5,
        full_name="Смирнова Елена Викторовна",
        login="reg1",
        role=RoleRef(id=2, name="Регистратор"),
        permissions=REGISTRAR_PERMISSIONS,
        panel_printer_id=printer_id,
    )


@router.post(
    "/login",
    operation_id="auth_login",
    summary="Вход",
    description=(
        "Ставит cookie `rs_session` (HttpOnly). Ошибки: `401 invalid_credentials`, "
        "`403 user_blocked`. **Заглушка:** логин `admin` даёт все права, любой другой — "
        "права регистратора; пароль `wrong` даёт `invalid_credentials`, логин `blocked` — "
        "`user_blocked`."
    ),
    response_model=MeOut,
    responses=err(
        (401, "`invalid_credentials`: неверный логин или пароль"),
        (403, "`user_blocked`: учётная запись заблокирована"),
        422,
        429,
    ),
)
async def login(body: LoginIn, response: Response) -> MeOut:
    if body.password == "wrong":
        raise AppError("invalid_credentials", "Неверный логин или пароль", 401)
    if body.login == "blocked":
        raise AppError("user_blocked", "Учётная запись заблокирована", 403)
    kind = "admin" if body.login == "admin" else "registrar"
    response.set_cookie(
        COOKIE, f"stub-{kind}", httponly=True, samesite="lax", max_age=12 * 3600, path="/"
    )
    return _me(kind)


@router.post(
    "/logout",
    operation_id="auth_logout",
    summary="Выход",
    description="Завершает сессию и удаляет cookie.",
    status_code=204,
    response_class=Response,
    dependencies=staff(write=True),
    responses=err(401),
)
async def logout() -> Response:
    response = Response(status_code=204)
    response.delete_cookie(COOKIE, path="/")
    return response


@router.get(
    "/me",
    operation_id="auth_me",
    summary="Текущий сотрудник",
    description=(
        "Профиль, роль и разрешения. **Заглушка:** отдаёт администратора, а если вход делали "
        "под другим логином (cookie `stub-registrar`) — регистратора."
    ),
    response_model=MeOut,
    dependencies=staff(),
    responses=err(401),
)
async def me(
    rs_session: Annotated[str | None, Cookie()] = None,
) -> MeOut:
    return _me("registrar" if rs_session == "stub-registrar" else "admin")


@router.put(
    "/me/printer",
    operation_id="auth_set_panel_printer",
    summary="Выбрать принтер панели",
    description="Разрешение: `stickers.print`. Запоминает принтер для печати из панели (RG-05).",
    response_model=MeOut,
    dependencies=staff("stickers.print", write=True),
    responses=err(401, 403, 404, 422),
)
async def set_panel_printer(
    body: PanelPrinterIn,
    rs_session: Annotated[str | None, Cookie()] = None,
) -> MeOut:
    return _me("registrar" if rs_session == "stub-registrar" else "admin", body.printer_id)
