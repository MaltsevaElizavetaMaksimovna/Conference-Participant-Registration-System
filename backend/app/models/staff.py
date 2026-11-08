"""Сотрудники: роли, разрешения, учётные записи, сессии."""

from datetime import datetime

from sqlalchemy import Index, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.permissions import Permission
from app.models.base import FALSE, created_at, fk, in_check, pk, updated_at


class Role(Base):
    __tablename__ = "role"

    id: Mapped[int] = pk()
    name: Mapped[str] = mapped_column(unique=True)
    # Метка «создана при установке»; такую роль можно удалять
    is_system: Mapped[bool] = mapped_column(server_default=FALSE)
    created_at: Mapped[datetime] = created_at()


class RolePermission(Base):
    __tablename__ = "role_permission"
    __table_args__ = (in_check("permission", Permission, "permission"),)

    role_id: Mapped[int] = fk("role.id", ondelete="CASCADE", primary_key=True)
    permission: Mapped[str] = mapped_column(primary_key=True)


class StaffUser(Base):
    __tablename__ = "staff_user"

    id: Mapped[int] = pk()
    full_name: Mapped[str]
    login: Mapped[str]
    password_hash: Mapped[str]
    role_id: Mapped[int] = fk("role.id")
    is_blocked: Mapped[bool] = mapped_column(server_default=FALSE)
    # Принтер, выбранный в панели (RG-05)
    panel_printer_id: Mapped[int | None] = fk("printer.id", nullable=True)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


# Логин уникален без учёта регистра
Index("uq_staff_user_login_lower", func.lower(StaffUser.login), unique=True)


class StaffSession(Base):
    __tablename__ = "staff_session"
    __table_args__ = (Index("ix_staff_session_user_id", "user_id"),)

    # sha256 токена из cookie
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = fk("staff_user.id")
    # Снимок прав на момент входа (AD-04: изменения действуют со следующего входа)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(Text))
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime]
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]
    ip: Mapped[str | None]
    user_agent: Mapped[str | None]
