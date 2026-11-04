"""Запись результатов фоновой загрузки фото в БД (B1-06).

Фото качаются после COMMIT импорта и параллельно, поэтому:
- фото участнику ставится условным UPDATE: только если ссылка в `source_data` всё ещё та, по
  которой качали (повторная загрузка файла могла её сменить, тогда результат устарел);
- итог по загрузке пишется в отчёт одним атомарным UPDATE поверх JSONB (`jsonb_set`, `||`), без
  чтения-изменения-записи, чтобы не затереть параллельные изменения отчёта.
"""

import json

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.participant import Participant

PHOTO_NOT_LOADED = "Строка {row}: фото не загружено"


async def save_participant_photo(
    session: AsyncSession, participant_id: int, url: str, photo_path: str, sha256: str
) -> bool:
    """Поставить фото, если ссылка не менялась. Возвращает, применилось ли. Коммитит."""
    result = await session.execute(
        update(Participant)
        .where(
            Participant.id == participant_id,
            Participant.source_data["photo_url"].astext == url,
        )
        .values(photo_path=photo_path, photo_sha256=sha256)
        .returning(Participant.id)
        .execution_options(synchronize_session=False)
    )
    applied = result.first() is not None
    await session.commit()
    return applied


async def finish_batch_photos(
    session: AsyncSession, batch_id: int, *, loaded: int, failed_rows: list[int]
) -> None:
    """Итог загрузки фото в `import_batch.report`: счётчики и предупреждения. Коммитит."""
    warnings = [PHOTO_NOT_LOADED.format(row=row) for row in sorted(failed_rows)]
    await session.execute(
        text(
            """
            UPDATE import_batch SET report = jsonb_set(
                jsonb_set(
                    report,
                    '{photos}',
                    coalesce(report->'photos', '{}'::jsonb)
                        || jsonb_build_object('loaded', CAST(:loaded AS int),
                                              'failed', CAST(:failed AS int),
                                              'done', true)
                ),
                '{warnings}',
                coalesce(report->'warnings', '[]'::jsonb) || CAST(:warnings AS jsonb)
            )
            WHERE id = :batch_id
            """
        ),
        {
            "batch_id": batch_id,
            "loaded": loaded,
            "failed": len(failed_rows),
            "warnings": json.dumps(warnings, ensure_ascii=False),
        },
    )
    await session.commit()
