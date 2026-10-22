"""Конвейер импорта участников (IM-01, IM-02): файл -> источник -> upsert одной транзакцией.

Порядок: лимит размера -> тип (расширение и сигнатура) -> чтение таблицы -> сопоставление
заголовков -> проверка строк (обязательные поля, дубли ID) -> доп. поля -> upsert -> `search_norm`
-> `change_log` (только изменённые поля существующих участников) -> отчёт в `import_batch.report`.

Правила повторной загрузки: совпадение по `external_id`; поля из `manual_fields` не
перезаписываются (расхождение попадает в отчёт); регистрации, пометки и история не трогаются;
участники, которых нет в файле, остаются (список — в отчёте).
Фото по ссылке скачивает B1-06: здесь ссылка только сохраняется в `source_data["photo_url"]`.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import ChangeSource, ImportSource, ImportStatus
from app.core.errors import AppError
from app.core.text import full_name
from app.imports.columns import FIELD_BY_KEY, FIELDS, REQUIRED_KEYS, unique_slug
from app.imports.readers import ImportFileError, file_too_large, read_table
from app.imports.schemas import (
    ImportBatchShort,
    ImportConflict,
    ImportMissing,
    ImportReportOut,
    ImportRowError,
)
from app.imports.source import ParticipantSource, SourceRow, TableSource
from app.models.base import utcnow
from app.models.conference import Conference, ExtraFieldDef
from app.models.imports import ImportBatch
from app.models.participant import ChangeLog, Participant
from app.models.staff import StaffUser
from app.participants.service import NAME_FIELDS, compute_search_norm

log = logging.getLogger("app.imports")

_IMPORT_LOCK = 0x52_53_49_4D  # "RSIM": одна загрузка на конференцию за раз
MAX_REPORT_ITEMS = 5000
_CHUNK = 500
_NOUN = {"external_id": "идентификатор", "last_name": "фамилия", "first_name": "имя"}
# Стандартные поля участника, которые файл может обновлять (без ID и ссылки на фото)
_UPDATABLE = tuple(f.key for f in FIELDS if f.key not in ("external_id", "photo_url"))


@dataclass
class _Outcome:
    total_rows: int = 0
    loaded: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: list[ImportRowError] = field(default_factory=list)
    conflicts: list[ImportConflict] = field(default_factory=list)
    missing: list[ImportMissing] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def row_error(row: int, reason: str) -> ImportRowError:
    return ImportRowError(row=row, reason=reason, message=f"Строка {row}: {reason}")


def summary_text(o: _Outcome) -> str:
    parts = [f"Загружено: {o.loaded}", f"пропущено: {len(o.errors)}"]
    if o.updated:
        parts.append(f"обновлено: {o.updated}")
    if o.unchanged:
        parts.append(f"без изменений: {o.unchanged}")
    if o.conflicts:
        parts.append(f"расхождений: {len(o.conflicts)}")
    if o.missing:
        parts.append(f"нет в файле: {len(o.missing)}")
    return ", ".join(parts)


# --------------------------------------------------------------------------- вход


async def import_file(
    session: AsyncSession,
    settings: Settings,
    *,
    conference_id: int,
    user_id: int | None,
    file_name: str,
    data: bytes,
) -> int:
    """Загружает участников из файла; возвращает id партии. Ошибки файла: 413/422."""
    from app.conferences.service import conference_not_found

    if await session.get(Conference, conference_id) is None:
        raise conference_not_found()
    if len(data) > settings.import_max_file_mb * 1024 * 1024:
        raise file_too_large(settings.import_max_file_mb)

    name = PurePath(file_name.replace("\\", "/")).name[:255] or "file"
    source, rows = await asyncio.to_thread(_parse, name, data, settings.import_max_rows)

    batch = ImportBatch(
        conference_id=conference_id,
        source=ImportSource.FILE.value,
        file_name=name,
        file_sha256=hashlib.sha256(data).hexdigest(),
        user_id=user_id,
        status=ImportStatus.RUNNING.value,
    )
    session.add(batch)
    await session.commit()
    batch_id = batch.id
    try:
        outcome = await _apply(session, conference_id, batch_id, user_id, source, rows)
        report = await session.get(ImportBatch, batch_id, populate_existing=True)
        assert report is not None
        report.status = ImportStatus.DONE.value
        report.finished_at = utcnow()
        report.report = _report_json(outcome)
        await session.commit()
    except Exception as e:
        log.exception("Импорт %s конференции %s завершился ошибкой", batch_id, conference_id)
        await session.rollback()
        failed = await session.get(ImportBatch, batch_id, populate_existing=True)
        if failed is not None:
            failed.status = ImportStatus.FAILED.value
            failed.finished_at = utcnow()
            failed.report = {"error": type(e).__name__}
            await session.commit()
        raise AppError(
            "import_failed",
            "Не удалось обработать файл, ничего не загружено. Попробуйте ещё раз",
            500,
            {"batch_id": batch_id},
        ) from e
    return batch_id


def _parse(name: str, data: bytes, max_rows: int) -> tuple[TableSource, list[SourceRow]]:
    table = read_table(name, data, max_rows)
    source = TableSource(table, text_cells=name.lower().endswith(".csv"))
    return source, list(source.rows())


# --------------------------------------------------------------------------- upsert


async def _apply(
    session: AsyncSession,
    conference_id: int,
    batch_id: int,
    user_id: int | None,
    source: ParticipantSource,
    rows: list[SourceRow],
) -> _Outcome:
    await session.execute(select(func.pg_advisory_xact_lock(_IMPORT_LOCK, conference_id)))
    out = _Outcome(total_rows=len(rows))
    valid, ids_in_file = _validate(rows, out)
    out.warnings.extend(source.warnings)

    extra_keys = await _ensure_extra_defs(session, conference_id, source.extra_labels)
    existing = await _load_existing(
        session, conference_id, [r.values["external_id"] for r in valid]
    )

    new_rows: list[dict[str, Any]] = []
    log_rows: list[dict[str, Any]] = []
    for row in valid:
        ext_id = row.values["external_id"]
        fields, extra, photo = _row_payload(row, source, extra_keys)
        participant = existing.get(ext_id)
        if participant is None:
            new_rows.append(_new_participant(conference_id, ext_id, fields, extra, photo))
            out.loaded += 1
            continue
        changes, photo_changed = _update_participant(participant, fields, extra, photo, out)
        if changes or photo_changed:
            out.updated += 1
            log_rows.extend(
                {
                    "participant_id": participant.id,
                    "field": f,
                    "old_value": old,
                    "new_value": new,
                    "source": ChangeSource.IMPORT.value,
                    "user_id": user_id,
                    "import_batch_id": batch_id,
                }
                for f, old, new in changes
            )
        else:
            out.unchanged += 1

    for i in range(0, len(new_rows), _CHUNK * 2):
        await session.execute(insert(Participant), new_rows[i : i + _CHUNK * 2])
    await session.flush()  # UPDATE изменённых участников
    for i in range(0, len(log_rows), _CHUNK * 2):
        await session.execute(insert(ChangeLog), log_rows[i : i + _CHUNK * 2])

    await _collect_missing(session, conference_id, ids_in_file, out)
    _cap(out)
    return out


def _validate(rows: list[SourceRow], out: _Outcome) -> tuple[list[SourceRow], set[str]]:
    """Отбрасывает строки без обязательных полей и повторы ID (грузится первая)."""
    valid: list[SourceRow] = []
    first_seen: dict[str, int] = {}
    ids_in_file: set[str] = set()
    for row in rows:
        ext_id = row.values.get("external_id", "")
        if ext_id:
            ids_in_file.add(ext_id)
        if row.error:
            out.errors.append(row_error(row.number, row.error))
            continue
        missing = [k for k in REQUIRED_KEYS if not row.values.get(k)]
        if missing:
            if len(missing) == 1:
                reason = FIELD_BY_KEY[missing[0]].reason_missing
            else:
                reason = "не указаны: " + ", ".join(_NOUN[k] for k in missing)
            out.errors.append(row_error(row.number, reason))
            continue
        if ext_id in first_seen:
            out.errors.append(
                row_error(
                    row.number,
                    f"повторяется идентификатор {ext_id} (загружена строка {first_seen[ext_id]})",
                )
            )
            continue
        first_seen[ext_id] = row.number
        valid.append(row)
        photo = row.values.get("photo_url", "")
        if photo and not photo.lower().startswith(("http://", "https://")):
            out.warnings.append(f"Строка {row.number}: ссылка на фото не похожа на http(s)-адрес")
    return valid, ids_in_file


async def _ensure_extra_defs(
    session: AsyncSession, conference_id: int, labels: list[str]
) -> dict[str, str]:
    """Заголовок доп. столбца -> ключ; новые поля добавляются в `extra_field_def`."""
    if not labels:
        return {}
    defs = list(
        await session.scalars(
            select(ExtraFieldDef)
            .where(ExtraFieldDef.conference_id == conference_id)
            .order_by(ExtraFieldDef.sort_order, ExtraFieldDef.id)
        )
    )
    by_label = {d.label.casefold(): d.key for d in defs}
    taken = {d.key for d in defs}
    next_order = max((d.sort_order for d in defs), default=-1) + 1
    result: dict[str, str] = {}
    for label in labels:
        key = by_label.get(label.casefold())
        if key is None:
            key = unique_slug(label, taken)
            taken.add(key)
            by_label[label.casefold()] = key
            session.add(
                ExtraFieldDef(
                    conference_id=conference_id, key=key, label=label, sort_order=next_order
                )
            )
            next_order += 1
        result[label] = key
    await session.flush()
    return result


async def _load_existing(
    session: AsyncSession, conference_id: int, ids: list[str]
) -> dict[str, Participant]:
    found: dict[str, Participant] = {}
    for i in range(0, len(ids), _CHUNK):
        chunk = ids[i : i + _CHUNK]
        for p in await session.scalars(
            select(Participant).where(
                Participant.conference_id == conference_id, Participant.external_id.in_(chunk)
            )
        ):
            if p.external_id is not None:
                found[p.external_id] = p
    return found


def _row_payload(
    row: SourceRow, source: ParticipantSource, extra_keys: dict[str, str]
) -> tuple[dict[str, str | None], dict[str, str | None], str | None | bool]:
    """(стандартные поля из файла, доп. поля по ключам, ссылка на фото или False — столбца нет)."""
    fields = {f: (row.values.get(f) or None) for f in _UPDATABLE if f in source.fields}
    extra = {extra_keys[label]: (row.extra.get(label) or None) for label in source.extra_labels}
    photo: str | None | bool = (
        (row.values.get("photo_url") or None) if "photo_url" in source.fields else False
    )
    return fields, extra, photo


def _source_data(
    fields: dict[str, str | None], extra: dict[str, str | None], photo: str | None | bool
) -> dict[str, Any]:
    data: dict[str, Any] = dict(fields)
    data.update({f"extra.{k}": v for k, v in extra.items()})
    if photo is not False:
        data["photo_url"] = photo
    return data


def _new_participant(
    conference_id: int,
    ext_id: str,
    fields: dict[str, str | None],
    extra: dict[str, str | None],
    photo: str | None | bool,
) -> dict[str, Any]:
    values: dict[str, Any] = {f: fields.get(f) for f in _UPDATABLE}
    return {
        "conference_id": conference_id,
        "external_id": ext_id,
        **values,
        "extra": {k: v for k, v in extra.items() if v is not None},
        "source_data": _source_data(fields, extra, photo),
        "search_norm": compute_search_norm(
            values["last_name"], values["first_name"], values["middle_name"]
        ),
    }


def _update_participant(
    p: Participant,
    fields: dict[str, str | None],
    extra: dict[str, str | None],
    photo: str | None | bool,
    out: _Outcome,
) -> tuple[list[tuple[str, str | None, str | None]], bool]:
    """Применяет данные файла: (изменения полей: поле, было, стало; изменилась ли ссылка на фото).

    Ссылка на фото не поле участника (в `change_log` не пишется), но её смена важна для B1-06.
    """
    manual = set(p.manual_fields or [])
    changes: list[tuple[str, str | None, str | None]] = []
    ext_id = p.external_id or ""

    def conflict(field_name: str, system: str | None, file_value: str | None) -> None:
        out.conflicts.append(
            ImportConflict(
                participant_id=p.id,
                external_id=ext_id,
                field=field_name,
                system_value=system,
                file_value=file_value,
            )
        )

    for name, new in fields.items():
        current: str | None = getattr(p, name)
        if current == new:
            continue
        if name in manual:
            conflict(name, current, new)
            continue
        setattr(p, name, new)
        changes.append((name, current, new))

    current_extra: dict[str, Any] = dict(p.extra or {})
    extra_changed = False
    for key, new in extra.items():
        name = f"extra.{key}"
        current = current_extra.get(key)
        if current == new:
            continue
        if name in manual:
            conflict(name, current, new)
            continue
        extra_changed = True
        if new is None:
            current_extra.pop(key, None)
        else:
            current_extra[key] = new
        changes.append((name, current, new))
    if extra_changed:
        p.extra = current_extra

    if any(c[0] in NAME_FIELDS for c in changes):
        p.search_norm = compute_search_norm(p.last_name, p.first_name, p.middle_name)

    old_source = dict(p.source_data or {})
    new_source = {**old_source, **_source_data(fields, extra, photo)}
    if new_source != old_source:
        p.source_data = new_source
    photo_changed = photo is not False and old_source.get("photo_url") != photo
    return changes, photo_changed


async def _collect_missing(
    session: AsyncSession, conference_id: int, ids_in_file: set[str], out: _Outcome
) -> None:
    rows = await session.execute(
        select(
            Participant.id,
            Participant.external_id,
            Participant.last_name,
            Participant.first_name,
            Participant.middle_name,
        )
        .where(Participant.conference_id == conference_id, Participant.external_id.is_not(None))
        .order_by(Participant.id)
    )
    for pid, ext_id, last, first, middle in rows:
        if ext_id is not None and ext_id not in ids_in_file:
            out.missing.append(
                ImportMissing(
                    participant_id=pid,
                    external_id=ext_id,
                    full_name=full_name(last, first, middle),
                )
            )


def _cap(out: _Outcome) -> None:
    for name in ("conflicts", "missing"):
        items = getattr(out, name)
        if len(items) > MAX_REPORT_ITEMS:
            setattr(out, name, items[:MAX_REPORT_ITEMS])
            label = "расхождений" if name == "conflicts" else "отсутствующих участников"
            out.warnings.append(f"В отчёте показаны первые {MAX_REPORT_ITEMS} {label}")


def _report_json(o: _Outcome) -> dict[str, Any]:
    return {
        "summary": summary_text(o),
        "total_rows": o.total_rows,
        "loaded": o.loaded,
        "updated": o.updated,
        "unchanged": o.unchanged,
        "skipped": len(o.errors),
        "errors": [e.model_dump() for e in o.errors],
        "conflicts": [c.model_dump() for c in o.conflicts],
        "missing": [m.model_dump() for m in o.missing],
        "warnings": o.warnings,
    }


# --------------------------------------------------------------------------- отчёт


async def get_report(session: AsyncSession, conference_id: int, batch_id: int) -> ImportReportOut:
    batch = await session.get(ImportBatch, batch_id, populate_existing=True)
    if batch is None or batch.conference_id != conference_id:
        raise AppError("import_not_found", "Загрузка не найдена", 404)
    r = batch.report or {}
    errors = [ImportRowError(**e) for e in r.get("errors", [])]
    if batch.status == ImportStatus.FAILED.value:
        errors = [
            ImportRowError(row=None, reason="внутренняя ошибка", message="Загрузка не удалась")
        ]
    return ImportReportOut(
        batch_id=batch.id,
        conference_id=batch.conference_id,
        source=batch.source,  # type: ignore[arg-type]
        file_name=batch.file_name,
        status=batch.status,  # type: ignore[arg-type]
        summary=r.get("summary", ""),
        total_rows=r.get("total_rows", 0),
        loaded=r.get("loaded", 0),
        updated=r.get("updated", 0),
        unchanged=r.get("unchanged", 0),
        skipped=r.get("skipped", len(errors)),
        errors=errors,
        conflicts=[ImportConflict(**c) for c in r.get("conflicts", [])],
        missing=[ImportMissing(**m) for m in r.get("missing", [])],
        warnings=r.get("warnings", []),
        started_at=batch.created_at,
        finished_at=batch.finished_at,
    )


async def list_batches(
    session: AsyncSession, conference_id: int, limit: int, offset: int
) -> tuple[list[ImportBatchShort], int]:
    """Загрузки конференции, новые сверху."""
    if await session.get(Conference, conference_id) is None:
        raise AppError("conference_not_found", "Конференция не найдена", 404)
    total = (
        await session.scalar(
            select(func.count())
            .select_from(ImportBatch)
            .where(ImportBatch.conference_id == conference_id)
        )
        or 0
    )
    rows = await session.execute(
        select(ImportBatch, StaffUser.login)
        .outerjoin(StaffUser, StaffUser.id == ImportBatch.user_id)
        .where(ImportBatch.conference_id == conference_id)
        .order_by(ImportBatch.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = []
    for batch, login in rows:
        r = batch.report or {}
        items.append(
            ImportBatchShort(
                id=batch.id,
                source=batch.source,  # type: ignore[arg-type]
                file_name=batch.file_name,
                status=batch.status,  # type: ignore[arg-type]
                created_at=batch.created_at,
                finished_at=batch.finished_at,
                user_login=login,
                loaded=r.get("loaded", 0),
                updated=r.get("updated", 0),
                skipped=r.get("skipped", 0),
            )
        )
    return items, total


__all__ = ["ImportFileError", "get_report", "import_file", "list_batches"]
