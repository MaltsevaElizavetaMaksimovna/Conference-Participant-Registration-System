"""Настройки приложения из переменных окружения с префиксом RS_."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_SECRET_KEY = "dev-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RS_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "postgresql+psycopg://postgres@127.0.0.1:5432/regsys"
    db_connect_timeout_s: int = 5
    secret_key: str = DEFAULT_SECRET_KEY
    # Список через запятую: RS_CORS_ORIGINS=http://localhost:5173,https://reg.example.ru
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    # Первый администратор: создаётся командой `python -m app.cli bootstrap`, если сотрудников нет
    bootstrap_admin_login: str | None = None
    bootstrap_admin_password: str | None = None

    # --- «Числа со звёздочкой» из требований (В-13): не зашиваем в код ---
    session_ttl_hours: int = 12  # срок сессии сотрудника
    terminal_idle_timeout_s: int = 60  # возврат терминала на экран ожидания
    result_screen_s: int = 10  # сколько показывать экран результата
    scan_response_timeout_s: int = 2  # ответ на скан, NF-01
    print_start_timeout_s: int = 3  # печать должна начаться, NF-01
    panel_refresh_s: int = 5  # обновление счётчика в панели, NF-01
    search_timeout_s: int = 1  # ответ поиска по ФИО, NF-01
    search_min_chars: int = 2  # поиск начинается с N символов, RG-02
    terminal_fail_threshold: int = 3  # «Нет связи с сервером» после N неудач подряд
    long_poll_timeout_s: int = 25  # long-poll агента печати
    print_confirm_timeout_s: int = 30  # агент не подтвердил задание -> error
    sse_keepalive_s: int = 15
    login_rate_limit_per_min: int = 10
    public_profile_rate_limit_per_min: int = 30
    import_max_file_mb: int = 10
    import_max_rows: int = 5000
    # Терминалы и принтеры (B2-01)
    device_last_seen_throttle_s: int = 10  # last_seen_at терминала пишем не чаще раза в N с
    printer_online_timeout_s: int = 30  # принтер «на связи», если heartbeat не старше N с

    # --- Сканирование QR (B2-02) ---
    # Регулярка для извлечения ID участника из ссылки приглашения (первая группа = ID).
    # Формат реальных приглашений пока неизвестен (В-04); переопределяется у конференции
    # (`conference.invite_id_regex`). Пусто — разбор по умолчанию (query-параметр или путь).
    invite_id_regex: str | None = None
    # Публичный адрес системы (ссылка на наклейке: `<адрес>/p/<token>`). Нужен, чтобы узнать
    # QR с наклейки и не принять его за приглашение.
    public_base_url: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @model_validator(mode="after")
    def _check_prod(self) -> "Settings":
        if self.env == "prod" and self.secret_key == DEFAULT_SECRET_KEY:
            raise ValueError("RS_SECRET_KEY должен быть задан в prod")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
