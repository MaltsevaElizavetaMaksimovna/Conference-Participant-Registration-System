"""Точка входа: `uvicorn app.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.auth.router import router as auth_router
from app.badges.router import router as badges_router
from app.conferences.router import active_router as active_conference_router
from app.conferences.router import router as conferences_router
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import register_error_handlers
from app.eventlog.router import router as eventlog_router
from app.imports.photo_worker import PhotoWorker
from app.imports.router import router as imports_router
from app.participants.router import router as participants_router
from app.printing.router import router as printing_router
from app.printing.sweeper import PrintSweeper
from app.realtime.hub import EventHub, psycopg_conninfo
from app.realtime.router import router as realtime_router
from app.registration.router import router as registration_router
from app.roles.router import router as roles_router
from app.templates.router import fields_router as template_fields_router
from app.templates.router import router as templates_router
from app.terminals.router import router as terminals_router

DESCRIPTION = """
Бэкенд системы регистрации участников конференции.

**Контракт для фронтенда:** этот OpenAPI (`/docs`, `/openapi.json`) — источник правды.

Эндпоинты с тегом **`stub`** пока заглушки: отдают фиктивные данные в правильном формате,
не обращаются к БД и не проверяют авторизацию (схемы авторизации в Swagger только показывают,
что потребуется). Тег `stub` исчезнет, когда эндпоинт получит реальную логику.

## Формат ошибок

Все ошибки 4xx/5xx приходят в одном виде:

```json
{"code": "already_registered", "message": "Вы уже зарегистрированы (20.11, 09:15)…", "details": {}}
```

`message` можно сразу показывать пользователю, логика фронта опирается на `code`.
Ошибки валидации: `422`, `code="validation_error"`,
`details.fields = {"last_name": "Укажите фамилию"}`.

## Авторизация (три вида, не взаимозаменяемы)

1. **Сотрудник** — cookie `rs_session` после `POST /api/auth/login`; запросы, которые что-то
   меняют, требуют заголовок `X-Requested-With: rs`.
2. **Терминал** — `Authorization: Terminal <token>`.
3. **Агент печати** — `Authorization: Agent <token>`.

Публичный профиль (`/api/public/profile/*`) работает без авторизации.

Списки: `?limit=50&offset=0`, ответ `{"items": [...], "total": 123}`.
Время — ISO 8601 с часовым поясом.
"""

OPENAPI_TAGS: list[dict[str, Any]] = [
    {"name": "auth", "description": "Вход и выход сотрудников, текущий профиль, принтер панели."},
    {"name": "admin: roles", "description": "Роли и справочник разрешений (AD-04)."},
    {"name": "admin: users", "description": "Учётные записи сотрудников (AD-03)."},
    {"name": "admin: conferences", "description": "Конференции и активация (AD-01)."},
    {
        "name": "conferences",
        "description": "Активная конференция для шапки панели (любой сотрудник).",
    },
    {
        "name": "admin: imports",
        "description": "Импорт участников из Excel и Битрикс24 (IM-01..04).",
    },
    {"name": "admin: templates", "description": "Шаблоны наклеек, предпросмотр, пробная печать."},
    {"name": "admin: events", "description": "Журнал событий активной конференции."},
    {"name": "admin: terminals", "description": "Терминалы самообслуживания и их токены (AD-02)."},
    {"name": "admin: printers", "description": "Принтеры и токены агентов печати (AD-02)."},
    {"name": "participants", "description": "Список, поиск, карточка и правка участников."},
    {
        "name": "desk",
        "description": "Действия на стойке: регистрация, повторная печать, чужой код, "
        "статус печати, принтеры.",
    },
    {"name": "realtime", "description": "Поток событий SSE для панели (счётчик, обновления)."},
    {"name": "terminal", "description": "Терминал самообслуживания: `Authorization: Terminal`."},
    {"name": "agent", "description": "Агент печати на ПК терминала: `Authorization: Agent`."},
    {"name": "public", "description": "Публичный профиль по QR с наклейки, без авторизации."},
    {"name": "health", "description": "Проверка работоспособности и доступности БД."},
    {
        "name": "stub",
        "description": "Заглушка: фиктивные данные, без БД и проверки авторизации.",
    },
]


def _use_error_format_for_422(app: FastAPI) -> None:
    """FastAPI описывает 422 своей схемой HTTPValidationError, а API отвечает `ErrorOut`."""
    original = app.openapi

    def patched() -> dict[str, Any]:
        fresh = app.openapi_schema is None
        schema = original()
        if fresh:
            for methods in schema.get("paths", {}).values():
                for op in methods.values():
                    resp = op.get("responses", {}).get("422")
                    ref = (
                        resp.get("content", {}).get("application/json", {}).get("schema", {})
                        if resp
                        else {}
                    ).get("$ref", "")
                    if ref.endswith("/HTTPValidationError"):
                        op["responses"]["422"] = {
                            "description": "`validation_error`: см. `details.fields`",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ErrorOut"}
                                }
                            },
                        }
            for name in ("HTTPValidationError", "ValidationError"):
                schema.get("components", {}).get("schemas", {}).pop(name, None)
        return schema

    app.openapi = patched  # type: ignore[method-assign]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Движок создаётся лениво (соединения — по первому запросу)
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.print_sweeper.start()
        yield
        await app.state.print_sweeper.stop()
        await app.state.event_hub.stop()
        await app.state.photo_worker.stop()
        await engine.dispose()

    app = FastAPI(
        title="Registration System API",
        version="0.1.0",
        description=DESCRIPTION,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.event_hub = EventHub(psycopg_conninfo(settings.database_url), app.state.sessionmaker)
    app.state.print_sweeper = PrintSweeper(app.state.sessionmaker, settings)
    app.state.photo_worker = PhotoWorker(app.state.sessionmaker, lambda: app.state.settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)
    _use_error_format_for_422(app)

    app.include_router(health.router)
    api = APIRouter(prefix="/api")
    for r in (
        auth_router,
        roles_router,
        conferences_router,
        active_conference_router,
        imports_router,
        eventlog_router,
        participants_router,
        realtime_router,
        registration_router,
        printing_router,
        templates_router,
        template_fields_router,
        terminals_router,
        badges_router,
    ):
        api.include_router(r)
    app.include_router(api)
    return app


app = create_app()
