"""Импорт участников (IM-01..IM-04). Загрузка из файла и шаблон — реальные (B1-05, B1-07, B1-08);
Битрикс24 — заглушка (B1-16)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.common import STUB_TAG, err
from app.api.deps import staff
from app.api.stubs import XLSX_CONTENT_TYPE
from app.auth.deps import CurrentStaff, get_current_staff
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import AppError
from app.imports import service
from app.imports.schemas import ImportAcceptedOut, ImportReportOut
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
        "(расхождения — в отчёте), отсутствующие в файле не удаляются (список — в отчёте)."
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
    batch_id = await service.import_file(
        session,
        settings,
        conference_id=conference_id,
        user_id=current.user_id,
        file_name=file.filename or "",
        data=data,
    )
    return ImportAcceptedOut(batch_id=batch_id)


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
