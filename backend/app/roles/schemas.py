"""Схемы ролей, разрешений и учётных записей сотрудников (AD-03, AD-04)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Совпадает с `Permission` (app/core/permissions.py); тест в test_roles сверяет списки
PermissionCode = Literal[
    "participants.view",
    "registration.desk",
    "stickers.print",
    "participants.edit",
    "participants.add",
    "registration.foreign_code",
    "imports.run",
    "conferences.manage",
    "devices.manage",
    "users.manage",
]


class PermissionOut(BaseModel):
    code: PermissionCode = Field(examples=["participants.view"])
    title: str = Field(
        description="Название для интерфейса", examples=["Просмотр и поиск участников"]
    )


class RoleRef(BaseModel):
    id: int = Field(examples=[2])
    name: str = Field(examples=["Регистратор"])


class RoleOut(RoleRef):
    is_system: bool = Field(description="Создана при установке (удалять можно)", examples=[True])
    permissions: list[PermissionCode] = Field(examples=[["participants.view", "registration.desk"]])
    users_count: int = Field(description="Сколько сотрудников имеют эту роль", examples=[3])


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Старший регистратор"])
    permissions: list[PermissionCode] = Field(examples=[["participants.view", "stickers.print"]])

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Укажите название роли")
        return v


class UserOut(BaseModel):
    id: int = Field(examples=[5])
    full_name: str = Field(examples=["Смирнова Елена Викторовна"])
    login: str = Field(examples=["reg1"])
    role: RoleRef
    is_blocked: bool = Field(examples=[False])
    created_at: datetime = Field(examples=["2026-11-01T10:00:00+03:00"])


MIN_PASSWORD_LEN = 8


def _check_password(v: object) -> object:
    if isinstance(v, str) and len(v) < MIN_PASSWORD_LEN:
        raise ValueError(f"Пароль должен быть не короче {MIN_PASSWORD_LEN} символов")
    return v


class UserCreateIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200, examples=["Смирнова Елена Викторовна"])
    login: str = Field(min_length=1, max_length=64, examples=["reg1"])
    password: str = Field(min_length=MIN_PASSWORD_LEN, max_length=128, examples=["S3cret-pass"])
    role_id: int = Field(examples=[2])

    @field_validator("full_name")
    @classmethod
    def _full_name_not_blank(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("Укажите ФИО")
        return v

    @field_validator("login")
    @classmethod
    def _login_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Укажите логин")
        return v

    _password_len = field_validator("password", mode="before")(_check_password)


class UserUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role_id: int | None = None
    password: str | None = Field(
        default=None,
        min_length=MIN_PASSWORD_LEN,
        max_length=128,
        description="Новый пароль; пусто — не менять. Завершает остальные сессии сотрудника",
    )

    @field_validator("full_name")
    @classmethod
    def _full_name_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = " ".join(v.split())
        if not v:
            raise ValueError("Укажите ФИО")
        return v

    _password_len = field_validator("password", mode="before")(_check_password)
