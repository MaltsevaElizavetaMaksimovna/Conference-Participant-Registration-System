"""Единый формат ошибки API: {"code": str, "message": str, "details": {}}."""

import logging
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("app.errors")

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
    # 400 от фреймворка — тело не разобралось (не JSON или не UTF-8); его текст английский
    400: ("invalid_body", "Не удалось прочитать тело запроса: нужен JSON в кодировке UTF-8"),
    401: ("unauthorized", "Требуется вход в систему"),
    403: ("forbidden", "Недостаточно прав"),
    404: ("not_found", "Не найдено"),
    405: ("method_not_allowed", "Метод не поддерживается"),
    409: ("conflict", "Конфликт состояния"),
    423: ("locked", "Ресурс заблокирован"),
    429: ("too_many_requests", "Слишком много запросов"),
}


class AppError(Exception):
    """Ожидаемая бизнес-ошибка. Пример: AppError("already_registered", "...", 409)."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details or {}},
        headers=headers,
    )


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    e = cast(AppError, exc)
    return error_response(e.status_code, e.code, e.message, e.details)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    e = cast(RequestValidationError, exc)
    fields: dict[str, str] = {}
    for err in e.errors():
        loc = [str(p) for p in err["loc"]]
        # ("body"|"query"|"path", "поле", ...) -> "поле"
        name = ".".join(loc[1:]) if len(loc) > 1 else ".".join(loc)
        msg = str(err["msg"]).removeprefix("Value error, ")
        fields.setdefault(name or "body", msg)
    return error_response(
        422, "validation_error", "Некорректные данные запроса", {"fields": fields}
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    e = cast(StarletteHTTPException, exc)
    code, message = _HTTP_ERRORS.get(
        e.status_code, ("http_error", HTTPStatus(e.status_code).phrase)
    )
    # Свой текст (не стандартная фраза Starlette) оставляем как есть
    if (
        e.status_code != 400
        and isinstance(e.detail, str)
        and e.detail != HTTPStatus(e.status_code).phrase
    ):
        message = e.detail
    headers = dict(e.headers) if e.headers else None
    return error_response(e.status_code, code, message, headers=headers)


class _UnhandledHttpErrors:
    """Пишет безопасную диагностику до передачи ошибки ASGI-серверу."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def track_start(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception as exc:
            route = getattr(scope.get("route"), "path", "<unknown>")
            log.error(
                "Необработанное исключение: %s %s (%s)", scope["method"], route, type(exc).__name__
            )
            if started:
                # Поток уже начался: сервер должен закрыть соединение.
                raise RuntimeError("Ошибка после начала HTTP-ответа") from None
            response = error_response(500, "internal_error", "Внутренняя ошибка сервера")
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_middleware(_UnhandledHttpErrors)
