"""Схемы входа сотрудников (RG-01, AD-04, RG-05)."""

from pydantic import BaseModel, Field

from app.roles.schemas import PermissionCode, RoleRef


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
