"""Схемы публичного профиля по QR с наклейки (QR-02, NF-06)."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field


class ProfileActive(BaseModel):
    status: Literal["active"]
    full_name: str = Field(examples=["Иванов Пётр Сергеевич"])
    position: str | None = Field(examples=["Инженер"])
    organization: str | None = Field(examples=["ООО Ромашка"])
    photo_url: str | None = Field(
        description="Относительная ссылка на фото; null, если фото нет",
        examples=["/api/public/profile/Zk3x9QnS7Vb2LmT4/photo"],
    )


class ProfileRevoked(BaseModel):
    """Код отозван (например, участнику выдали новый по чужому коду)."""

    status: Literal["revoked"]


ProfileOut = Annotated[ProfileActive | ProfileRevoked, Field(discriminator="status")]
