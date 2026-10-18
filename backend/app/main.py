"""Точка входа: `uvicorn app.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health
from app.core.config import Settings, get_settings
from app.core.db import make_engine, make_sessionmaker
from app.core.errors import register_error_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    # Движок создаётся лениво (соединения — по первому запросу)
    engine = make_engine(settings.database_url, settings.db_connect_timeout_s)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        await engine.dispose()

    app = FastAPI(title="Registration System API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_error_handlers(app)

    app.include_router(health.router)
    # Роутеры доменных модулей подключать здесь, например prefix="/api/auth"
    return app


app = create_app()
