"""Импорт участников (IM-01..IM-04). Загрузка из файла и шаблон — реальные (B1-05, B1-07, B1-08);
Битрикс24 — заглушка (B1-16)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff
from app.api.stubs import XLSX_CONTENT_TYPE
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import AppError
from app.imports import service
from app.imports.schemas import (
    BitrixSettingsIn,
    BitrixSettingsOut,
    ImportAcceptedOut,
    ImportBatchShort,
    ImportReportOut,
)
from app.imports.template import build_template

router = APIRouter(prefix="/admin", tags=["admin: imports"])

_UPLOAD_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file"],
                    "properties": {
                        "file": {
                            "type": "string",
                            "format": "binary",
                            "description": "Файл .xlsx или .csv с участниками",
                        }
                    },
                }
            }
        },
    }
}


@router.post(
    "/conferences/{conference_id}/imports",
    operation_id="imports_upload",
    summary="Загрузить участников из файла",
    description=(
        "Разрешение: `imports.run`. multipart/form-data, поле `file` (.xlsx или .csv, первая "
        "строка — заголовки; обязательные столбцы: идентификатор, фамилия, имя; остальные "
        "неизвестные столбцы становятся дополнительными полями). Файл обрабатывается в "
        "запросе, ответ `202 {batch_id}`, отчёт — `GET .../imports/{batch_id}`. "
        "Повторная загрузка той же конференции обновляет данные по идентификатору, "
        "не сбрасывая регистрации; исправленное вручную из файла не перезаписывается "
        "(расхождения — в отчёте), отсутствующие в файле не удаляются (список — в отчёте). "
        "Фото по ссылкам скачиваются фоном после ответа; прогресс — `photos` в отчёте."
    ),
    status_code=202,
    response_model=ImportAcceptedOut,
    openapi_extra=_UPLOAD_BODY,
    dependencies=staff("imports.run", write=True),
    responses=err(
        401,
        403,
        (404, "`conference_not_found`: конференции нет"),
        (413, "`file_too_large`: файл больше лимита"),
        (
            422,
            "`bad_file`: «Поддерживаются файлы .xlsx и .csv», файл не читается или нет "
            "обязательных столбцов (ничего не загружено); `validation_error`: нет поля `file`",
        ),
    ),
)
async def imports_upload(
    conference_id: int,
    request: Request,
    file: Annotated[UploadFile, File(description="Файл .xlsx или .csv")],
    session: AsyncSession = Depends(get_session),
    current: CurrentStaff = Depends(get_current_staff),
) -> ImportAcceptedOut:
    settings: Settings = request.app.state.settings
    limit = settings.import_max_file_mb * 1024 * 1024
    data = await file.read(limit + 1)  # на байт больше лимита, чтобы заметить превышение
    result = await service.import_file(
        session,
        settings,
        conference_id=conference_id,
        user_id=current.user_id,
        file_name=file.filename or "",
        data=data,
    )
    request.app.state.photo_worker.submit(result.batch_id, result.photo_jobs)
    return ImportAcceptedOut(batch_id=result.batch_id)


@router.get(
    "/conferences/{conference_id}/imports",
    operation_id="imports_list",
    summary="История загрузок конференции",
    description=(
        "Разрешение: `imports.run`. Загрузки из файла и из Битрикс24, новые сверху. "
        "`loaded`, `updated`, `skipped` — итоги; подробности — `GET .../imports/{id}`."
    ),
    response_model=Page[ImportBatchShort],
    dependencies=staff("imports.run"),
    responses=err(401, 403, (404, "`conference_not_found`: конференции нет")),
)
async def imports_list(
    conference_id: int,
    limit: Limit = 50,
    offset: Offset = 0,
    session: AsyncSession = Depends(get_session),
) -> Page[ImportBatchShort]:
    items, total = await service.list_batches(session, conference_id, limit, offset)
    return Page[ImportBatchShort](items=items, total=total)


@router.get(
    "/conferences/{conference_id}/imports/{batch_id}",
    operation_id="imports_report",
    summary="Отчёт об импорте",
    description="Разрешение: `imports.run`.",
    response_model=ImportReportOut,
    dependencies=staff("imports.run"),
    responses=err(401, 403, (404, "`import_not_found`: загрузки нет в этой конференции")),
)
async def imports_report(
    conference_id: int, batch_id: int, session: AsyncSession = Depends(get_session)
) -> ImportReportOut:
    return await service.get_report(session, conference_id, batch_id)


@router.get(
    "/import-template.xlsx",
    operation_id="imports_template",
    summary="Шаблон файла для импорта",
    description=(
        "Разрешение: `imports.run`. Пустой .xlsx: заголовки столбцов (обязательные помечены "
        "«*») и строка-пример; удалите её перед загрузкой."
    ),
    response_class=Response,
    responses={
        200: {
            "description": "Файл-шаблон .xlsx",
            "content": {XLSX_CONTENT_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(401, 403),
    },
    dependencies=staff("imports.run"),
)
async def imports_template() -> Response:
    return Response(
        content=build_template(),
        media_type=XLSX_CONTENT_TYPE,
        headers={"Content-Disposition": 'attachment; filename="import-template.xlsx"'},
    )


@router.post(
    "/conferences/{conference_id}/imports/bitrix",
    operation_id="imports_bitrix",
    summary="Загрузить участников из Битрикс24",
    description=(
        "Разрешение: `imports.run`. Фоновая загрузка, отчёт — `GET .../imports/{batch_id}`. "
        "В заглушке конференция 503 даёт `bitrix_unavailable`."
    ),
    status_code=202,
    response_model=ImportAcceptedOut,
    tags=[STUB_TAG],
    dependencies=staff("imports.run", write=True),
    responses=err(401, 403, 404, (502, "`bitrix_unavailable`: Битрикс24 недоступен")),
)
async def imports_bitrix(conference_id: int) -> ImportAcceptedOut:
    if conference_id == 503:
        raise AppError(
            "bitrix_unavailable", "Битрикс24 недоступен. Попробуйте позже или загрузите файл", 502
        )
    return ImportAcceptedOut(batch_id=13)


_BITRIX_NOTE = (
    "URL вебхука (секрет) через API не передаётся: он задаётся на сервере в "
    "`RS_BITRIX_WEBHOOK_URL`, а `webhook_configured` показывает, задан ли он."
)

_STUB_BITRIX = BitrixSettingsIn(
    entity="contact",
    filter={"=SOURCE_ID": "WEB"},
    field_map={
        "external_id": "ID",
        "last_name": "LAST_NAME",
        "first_name": "NAME",
        "middle_name": "SECOND_NAME",
        "organization": "COMPANY_TITLE",
        "position": "POST",
    },
)


def _webhook_configured(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    return settings.bitrix_webhook_url is not None


@router.get(
    "/conferences/{conference_id}/bitrix-settings",
    operation_id="bitrix_settings_get",
    summary="Настройки загрузки из Битрикс24",
    description=(
        f"Разрешение: `imports.run`. Откуда брать участников, фильтр и соответствие полей. "
        f"{_BITRIX_NOTE} Заглушка: настройки фиксированные, `webhook_configured` берётся "
        "из окружения."
    ),
    response_model=BitrixSettingsOut,
    tags=[STUB_TAG],
    dependencies=staff("imports.run"),
    responses=err(401, 403, 404),
)
async def bitrix_settings_get(conference_id: int, request: Request) -> BitrixSettingsOut:
    return BitrixSettingsOut(
        **_STUB_BITRIX.model_dump(), webhook_configured=_webhook_configured(request)
    )


@router.put(
    "/conferences/{conference_id}/bitrix-settings",
    operation_id="bitrix_settings_put",
    summary="Сохранить настройки загрузки из Битрикс24",
    description=(
        f"Разрешение: `imports.run`. Полная замена настроек. {_BITRIX_NOTE} "
        "Для `entity=smart_process` обязателен `entity_type_id`. Заглушка ничего не "
        "сохраняет и возвращает присланное."
    ),
    response_model=BitrixSettingsOut,
    tags=[STUB_TAG],
    dependencies=staff("imports.run", write=True),
    responses=err(401, 403, 404, 422),
)
async def bitrix_settings_put(
    conference_id: int, body: BitrixSettingsIn, request: Request
) -> BitrixSettingsOut:
    return BitrixSettingsOut(**body.model_dump(), webhook_configured=_webhook_configured(request))
