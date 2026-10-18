"""Единый формат ошибки API: {"code": str, "message": str, "details": {}}."""

import logging
from http import HTTPStatus
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("app.errors")

_HTTP_ERRORS: dict[int, tuple[str, str]] = {
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
    if isinstance(e.detail, str) and e.detail != HTTPStatus(e.status_code).phrase:
        message = e.detail
    headers = dict(e.headers) if e.headers else None
    return error_response(e.status_code, code, message, headers=headers)


async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("Необработанное исключение: %s %s", request.method, request.url.path)
    return error_response(500, "internal_error", "Внутренняя ошибка сервера")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
