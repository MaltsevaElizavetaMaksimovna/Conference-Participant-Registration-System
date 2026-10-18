"""Текущий сотрудник и проверка разрешений — общий интерфейс для всех модулей.

Остальные модули импортируют только `CurrentStaff`, `get_current_staff` и `require_staff`.
В тестах сотрудник подменяется через `app.dependency_overrides[get_current_staff]`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends

from app.core.errors import AppError
from app.core.permissions import Permission


@dataclass(frozen=True)
class CurrentStaff:
    user_id: int
    login: str
    full_name: str
    role_id: int
    permissions: frozenset[Permission]
    session_id: str

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions


async def get_current_staff() -> CurrentStaff:
    """TODO B1-01: сессия из cookie `rs_session`, 401 unauthenticated, CSRF для записи.

    Пока — заглушка «администратор», чтобы эндпоинты-заглушки работали без входа.
    """
    return CurrentStaff(
        user_id=0,
        login="stub",
        full_name="Заглушка",
        role_id=0,
        permissions=frozenset(Permission),
        session_id="stub",
    )


def require_staff(*permissions: Permission) -> Callable[..., Awaitable[CurrentStaff]]:
    """Зависимость: сотрудник со всеми перечисленными разрешениями, иначе 403 forbidden."""

    async def dependency(staff: CurrentStaff = Depends(get_current_staff)) -> CurrentStaff:
        missing = [p for p in permissions if not staff.has(p)]
        if missing:
            raise AppError(
                "forbidden", "Недостаточно прав", 403, {"missing": [str(p) for p in missing]}
            )
        return staff

    return dependency
