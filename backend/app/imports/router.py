"""Импорт участников (IM-01..IM-04). ЗАГЛУШКИ (B1-05, B1-08, B1-16)."""

from typing import Any

from fastapi import APIRouter, Request, Response

from app.api.common import STUB_TAG, err
from app.api.deps import staff
from app.api.stubs import T0, XLSX_CONTENT_TYPE
from app.core.errors import AppError
from app.imports.schemas import ImportAcceptedOut, ImportReportOut, ImportRowError

router = APIRouter(prefix="/admin", tags=["admin: imports", STUB_TAG])

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
        "Разрешение: `imports.run`. multipart/form-data, поле `file` (.xlsx или .csv). "
        "Обработка идёт в фоне: ответ `202 {batch_id}`, итог — `GET .../imports/{batch_id}`."
    ),
    status_code=202,
    response_model=ImportAcceptedOut,
    openapi_extra=_UPLOAD_BODY,
    dependencies=staff("imports.run", write=True),
    responses=err(
        401,
        403,
        404,
        (413, "`file_too_large`: файл больше лимита"),
        (422, "`validation_error` / `bad_file`: файл не читается или нет нужных столбцов"),
    ),
)
async def imports_upload(conference_id: int, request: Request) -> ImportAcceptedOut:
    # TODO B1-05: разбор multipart (потребуется python-multipart) и запуск фоновой загрузки
    return ImportAcceptedOut(batch_id=12)


@router.get(
    "/conferences/{conference_id}/imports/{batch_id}",
    operation_id="imports_report",
    summary="Отчёт об импорте",
    description="Разрешение: `imports.run`.",
    response_model=ImportReportOut,
    dependencies=staff("imports.run"),
    responses=err(401, 403, 404),
)
async def imports_report(conference_id: int, batch_id: int) -> ImportReportOut:
    return ImportReportOut(
        batch_id=batch_id,
        conference_id=conference_id,
        source="file",
        file_name="participants.xlsx",
        status="done",
        total_rows=300,
        created=290,
        updated=8,
        unchanged=0,
        failed=2,
        errors=[
            ImportRowError(row=17, field="last_name", message="Не указана фамилия"),
            ImportRowError(row=42, field="photo", message="Фото не удалось загрузить"),
        ],
        started_at=T0,
        finished_at=T0.replace(second=10),
    )


@router.get(
    "/import-template.xlsx",
    operation_id="imports_template",
    summary="Шаблон файла для импорта",
    description="Разрешение: `imports.run`. Заглушка отдаёт пустое тело (TODO B1-08).",
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
    # TODO B1-08: настоящий шаблон с заголовками столбцов
    return Response(
        content=b"",
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
    dependencies=staff("imports.run", write=True),
    responses=err(401, 403, 404, (502, "`bitrix_unavailable`: Битрикс24 недоступен")),
)
async def imports_bitrix(conference_id: int) -> ImportAcceptedOut:
    if conference_id == 503:
        raise AppError(
            "bitrix_unavailable", "Битрикс24 недоступен. Попробуйте позже или загрузите файл", 502
        )
    return ImportAcceptedOut(batch_id=13)
