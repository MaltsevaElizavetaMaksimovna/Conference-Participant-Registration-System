"""Схемы принтеров и агента печати (AD-02, TR-04, TR-08)."""

from pydantic import BaseModel, ConfigDict, Field

from app.api.common import PrinterOut, PrinterStatus


class PrinterAdminOut(PrinterOut):
    windows_printer_name: str | None = Field(
        description="Имя принтера в Windows на компьютере с агентом", examples=["XP-360B"]
    )
    dpi: int = Field(examples=[203])
    offset_x_mm: float = Field(description="Калибровка: сдвиг печати по X, мм", examples=[0.0])
    offset_y_mm: float = Field(description="Калибровка: сдвиг печати по Y, мм", examples=[0.0])
    density: int = Field(description="Плотность печати TSPL `DENSITY`, 0..15", examples=[10])
    speed: int = Field(description="Скорость печати TSPL `SPEED`, 1..6", examples=[3])
    token_set: bool = Field(description="Выдан ли токен агенту", examples=[True])


class PrinterIn(BaseModel):
    """Создание и изменение. В `PUT` меняются только переданные поля (кроме `name`)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=100, examples=["Принтер 1"])
    windows_printer_name: str | None = Field(default=None, max_length=200, examples=["XP-360B"])
    dpi: int = Field(default=203, ge=100, le=1200)
    offset_x_mm: float = Field(default=0.0, ge=-50, le=50, description="Сдвиг по X, мм")
    offset_y_mm: float = Field(default=0.0, ge=-50, le=50, description="Сдвиг по Y, мм")
    density: int = Field(default=10, ge=0, le=15, description="Плотность печати, 0..15")
    speed: int = Field(default=3, ge=1, le=6, description="Скорость печати, 1..6")


class PrinterTokenOut(BaseModel):
    id: int = Field(examples=[1])
    token: str = Field(
        description="Токен агента для `Authorization: Agent <token>`. Показывается один раз!",
        examples=["agt_Zk3x9QnS7Vb2LmT4Zk3x9QnS7Vb2LmT4"],
    )


class AgentJobCopy(BaseModel):
    """Одна наклейка задания (у двустороннего бейджа их две)."""

    png_base64: str = Field(description="PNG-изображение наклейки, base64")
    width_mm: float = Field(examples=[58.0])
    height_mm: float = Field(examples=[40.0])
    gap_mm: float = Field(description="Зазор между наклейками для команды GAP", examples=[2.0])


class AgentJob(BaseModel):
    job_id: int = Field(examples=[501])
    copies: list[AgentJobCopy] = Field(description="Наклейки по порядку печати, одним заданием")
    # Калибровка принтера из админки: агент применяет её к TSPL (SHIFT/DENSITY/SPEED)
    offset_x_mm: float = Field(default=0, description="Сдвиг по горизонтали, мм", examples=[-1.0])
    offset_y_mm: float = Field(default=0, description="Сдвиг по вертикали, мм", examples=[0.0])
    density: int = Field(default=10, description="Плотность печати 0–15", examples=[10])
    speed: int = Field(default=3, description="Скорость печати 1–6", examples=[3])


class AgentResultIn(BaseModel):
    ok: bool = Field(description="Напечатано ли задание")
    error: str | None = Field(default=None, description="Причина, если ok=false", examples=[None])


class HeartbeatIn(BaseModel):
    printer_status: PrinterStatus = Field(description="Состояние принтера, как видит агент")
