"""Роли, разрешения и учётные записи сотрудников (AD-03, AD-04). ЗАГЛУШКИ."""

from fastapi import APIRouter, Response

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff
from app.api.stubs import T0
from app.core.errors import AppError
from app.roles.schemas import (
    PermissionCode,
    PermissionOut,
    RoleIn,
    RoleOut,
    RoleRef,
    UserCreateIn,
    UserOut,
    UserUpdateIn,
)

roles_router = APIRouter(prefix="/admin/roles", tags=["admin: roles", STUB_TAG])
permissions_router = APIRouter(prefix="/admin/permissions", tags=["admin: roles", STUB_TAG])
users_router = APIRouter(prefix="/admin/users", tags=["admin: users", STUB_TAG])

PERMISSION_TITLES: dict[PermissionCode, str] = {
    "participants.view": "Просмотр и поиск участников",
    "registration.desk": "Регистрация со стойки, в том числе без наклейки",
    "stickers.print": "Печать и повторная печать наклеек",
    "participants.edit": "Исправление данных участника",
    "participants.add": "Добавление участника",
    "registration.foreign_code": "Отметка «Зарегистрирован по чужому коду»",
    "imports.run": "Загрузка участников",
    "conferences.manage": "Настройка конференций и шаблонов",
    "devices.manage": "Настройка терминалов и принтеров",
    "users.manage": "Управление учётными записями и ролями",
}

REGISTRAR_PERMISSIONS: list[PermissionCode] = [
    "participants.view",
    "registration.desk",
    "stickers.print",
    "participants.edit",
    "participants.add",
    "registration.foreign_code",
]
ALL_PERMISSIONS: list[PermissionCode] = list(PERMISSION_TITLES)


def _roles() -> list[RoleOut]:
    return [
        RoleOut(
            id=1, name="Администратор", is_system=True, permissions=ALL_PERMISSIONS, users_count=1
        ),
        RoleOut(
            id=2,
            name="Регистратор",
            is_system=True,
            permissions=REGISTRAR_PERMISSIONS,
            users_count=3,
        ),
    ]


def _role(role_id: int) -> RoleOut:
    for r in _roles():
        if r.id == role_id:
            return r
    raise AppError("role_not_found", "Роль не найдена", 404)


def _user(user_id: int, *, blocked: bool = False) -> UserOut:
    return UserOut(
        id=user_id,
        full_name="Смирнова Елена Викторовна",
        login="reg1",
        role=RoleRef(id=2, name="Регистратор"),
        is_blocked=blocked,
        created_at=T0,
    )


@roles_router.get(
    "",
    operation_id="roles_list",
    summary="Список ролей",
    description="Разрешение: `users.manage`.",
    response_model=Page[RoleOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def roles_list(limit: Limit = 50, offset: Offset = 0) -> Page[RoleOut]:
    items = _roles()
    return Page[RoleOut](items=items[offset : offset + limit], total=len(items))


@roles_router.post(
    "",
    operation_id="roles_create",
    summary="Создать роль",
    description="Разрешение: `users.manage`.",
    status_code=201,
    response_model=RoleOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, 422),
)
async def roles_create(body: RoleIn) -> RoleOut:
    return RoleOut(
        id=3, name=body.name, is_system=False, permissions=body.permissions, users_count=0
    )


@roles_router.put(
    "/{role_id}",
    operation_id="roles_update",
    summary="Изменить роль",
    description=(
        "Разрешение: `users.manage`. Изменение прав действует для сотрудников со следующего "
        "входа (AD-04). Нельзя убрать `users.manage` у последней роли, которая его имеет. "
        "В заглушке роль 99 даёт `last_admin_permission`."
    ),
    response_model=RoleOut,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        404,
        422,
        (409, "`last_admin_permission`: нельзя лишить последнюю роль права `users.manage`"),
    ),
)
async def roles_update(role_id: int, body: RoleIn) -> RoleOut:
    if role_id == 99:
        raise AppError(
            "last_admin_permission",
            "Нельзя убрать право управления пользователями у последней роли",
            409,
        )
    role = _role(role_id)
    return role.model_copy(update={"name": body.name, "permissions": body.permissions})


@roles_router.delete(
    "/{role_id}",
    operation_id="roles_delete",
    summary="Удалить роль",
    description=(
        "Разрешение: `users.manage`. Роль, назначенная сотрудникам, удалить нельзя. "
        "В заглушке роли 1 и 2 дают `role_in_use`, остальные удаляются."
    ),
    status_code=204,
    response_class=Response,
    dependencies=staff("users.manage", write=True),
    responses=err(
        401,
        403,
        404,
        (409, "`role_in_use`: роль назначена сотрудникам; `last_admin_permission`"),
    ),
)
async def roles_delete(role_id: int) -> None:
    if role_id in (1, 2):
        role = _role(role_id)
        raise AppError(
            "role_in_use",
            f"Роль «{role.name}» назначена сотрудникам ({role.users_count})",
            409,
            {"users_count": role.users_count},
        )


@permissions_router.get(
    "",
    operation_id="permissions_list",
    summary="Справочник разрешений",
    description="Разрешение: `users.manage`. Каталог разрешений зашит в коде (AD-04).",
    response_model=list[PermissionOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def permissions_list() -> list[PermissionOut]:
    return [PermissionOut(code=c, title=t) for c, t in PERMISSION_TITLES.items()]


@users_router.get(
    "",
    operation_id="users_list",
    summary="Список сотрудников",
    description="Разрешение: `users.manage`.",
    response_model=Page[UserOut],
    dependencies=staff("users.manage"),
    responses=err(401, 403),
)
async def users_list(limit: Limit = 50, offset: Offset = 0) -> Page[UserOut]:
    items = [_user(5), _user(6, blocked=True).model_copy(update={"login": "reg2"})]
    return Page[UserOut](items=items[offset : offset + limit], total=len(items))


@users_router.post(
    "",
    operation_id="users_create",
    summary="Создать сотрудника",
    description="Разрешение: `users.manage`.",
    status_code=201,
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, 422, (409, "`login_taken`: логин уже занят")),
)
async def users_create(body: UserCreateIn) -> UserOut:
    role = _role(body.role_id)
    return _user(7).model_copy(
        update={
            "full_name": body.full_name,
            "login": body.login,
            "role": RoleRef(id=role.id, name=role.name),
        }
    )


@users_router.put(
    "/{user_id}",
    operation_id="users_update",
    summary="Изменить сотрудника",
    description="Разрешение: `users.manage`.",
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, 404, 422),
)
async def users_update(user_id: int, body: UserUpdateIn) -> UserOut:
    user = _user(user_id)
    update: dict[str, object] = {}
    if body.full_name is not None:
        update["full_name"] = body.full_name
    if body.role_id is not None:
        role = _role(body.role_id)
        update["role"] = RoleRef(id=role.id, name=role.name)
    return user.model_copy(update=update)


@users_router.post(
    "/{user_id}/block",
    operation_id="users_block",
    summary="Заблокировать сотрудника",
    description="Разрешение: `users.manage`. Действующие сессии сотрудника отзываются.",
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, 404),
)
async def users_block(user_id: int) -> UserOut:
    return _user(user_id, blocked=True)


@users_router.post(
    "/{user_id}/unblock",
    operation_id="users_unblock",
    summary="Разблокировать сотрудника",
    description="Разрешение: `users.manage`.",
    response_model=UserOut,
    dependencies=staff("users.manage", write=True),
    responses=err(401, 403, 404),
)
async def users_unblock(user_id: int) -> UserOut:
    return _user(user_id, blocked=False)


router = APIRouter()
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(users_router)
