"""Схемы входа сотрудников (RG-01, AD-04, RG-05)."""

from pydantic import BaseModel, Field, field_validator

from app.roles.schemas import MIN_PASSWORD_LEN, PermissionCode, RoleRef, _check_password


class LoginIn(BaseModel):
    login: str = Field(min_length=1, max_length=64, examples=["reg1"])
    password: str = Field(min_length=1, max_length=128, examples=["S3cret-pass"])


class MeOut(BaseModel):
    """Текущий сотрудник. Права берутся из снимка на момент входа (AD-04)."""

    id: int = Field(examples=[5])
    full_name: str = Field(examples=["Смирнова Елена Викторовна"])
    login: str = Field(examples=["reg1"])
    role: RoleRef
    permissions: list[PermissionCode] = Field(
        description="Разрешения роли; по ним фронт показывает или прячет разделы панели",
        examples=[["participants.view", "registration.desk"]],
    )
    panel_printer_id: int | None = Field(
        description="Принтер, выбранный в панели для печати наклеек (RG-05); null — не выбран",
        examples=[1],
    )


class PanelPrinterIn(BaseModel):
    printer_id: int | None = Field(
        description="Идентификатор из GET /api/printers; null — сбросить выбор", examples=[1]
    )


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128, examples=["S3cret-pass"])
    new_password: str = Field(
        min_length=MIN_PASSWORD_LEN,
        max_length=128,
        description=f"Не короче {MIN_PASSWORD_LEN} символов",
        examples=["N3w-S3cret-pass"],
    )

    _password_len = field_validator("new_password", mode="before")(_check_password)
