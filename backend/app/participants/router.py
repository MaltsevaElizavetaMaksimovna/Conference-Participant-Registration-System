"""Участники: список, поиск, карточка, правка, добавление. ЗАГЛУШКИ (B1-09..B1-12)."""

from typing import Annotated

from fastapi import APIRouter, Query, Response

from app.api.common import STUB_TAG, Limit, Offset, Page, err
from app.api.deps import staff
from app.api.stubs import JPEG_1X1, T0
from app.core.errors import AppError
from app.participants.schemas import (
    CheckDuplicatesIn,
    DuplicatesOut,
    EventItem,
    ExtraField,
    FlagInfo,
    HistoryItem,
    ParticipantActions,
    ParticipantCard,
    ParticipantCreatedOut,
    ParticipantCreateIn,
    ParticipantFilter,
    ParticipantShort,
    ParticipantSort,
    ParticipantStats,
    ParticipantUpdateIn,
    RegistrationInfo,
)

router = APIRouter(prefix="/participants", tags=["participants", STUB_TAG])

# Фиксированные участники заглушек: 17 — зарегистрирован, 18 — нет, 19 — без наклейки.
SAMPLE_IDS = (17, 18, 19)

_SHORT = [
    ParticipantShort(
        id=17,
        full_name="Иванов Пётр Сергеевич",
        organization="ООО Ромашка",
        status="registered",
        flags=["data_changed"],
    ),
    ParticipantShort(
        id=18,
        full_name="Петрова Анна Ивановна",
        organization="АО Василёк",
        status="not_registered",
        flags=[],
    ),
    ParticipantShort(
        id=19,
        full_name="Сидоров Олег Николаевич",
        organization=None,
        status="registered_no_sticker",
        flags=["sticker_not_printed"],
    ),
]

REGISTERED_AT_TEXT = "20.11 09:15, Терминал 2"

# Время регистрации в заглушке для `sort=registered_at`: 17 раньше 19, 18 не регистрировался
_REGISTERED_AT = {17: T0, 19: T0.replace(minute=40)}


def sample_short(participant_id: int) -> ParticipantShort:
    for p in _SHORT:
        if p.id == participant_id:
            return p
    raise AppError("participant_not_found", "Участник не найден", 404)


def sample_card(participant_id: int) -> ParticipantCard:
    """Карточка заглушки; 404 `participant_not_found` для id вне (17, 18, 19)."""
    short = sample_short(participant_id)
    last, first, middle = short.full_name.split(" ")
    registered = short.status != "not_registered"
    registration = (
        RegistrationInfo(at=T0, source="terminal", terminal_name="Терминал 2", user_login=None)
        if registered
        else None
    )
    flags = [FlagInfo(code=code, at=T0, by=None) for code in short.flags]
    return ParticipantCard(
        id=short.id,
        external_id=f"B24-{1000 + short.id - 16}",
        last_name=last,
        first_name=first,
        middle_name=middle,
        position="Инженер" if short.id == 17 else None,
        organization=short.organization,
        extra=[ExtraField(key="section", label="Секция", value="A")],
        status=short.status,
        registration=registration,
        flags=flags,
        photo_url=f"/api/participants/{short.id}/photo" if short.id != 19 else None,
        profile_url=f"https://reg.example.ru/p/stub-token-{short.id}" if registered else None,
        print_count=1 if short.status == "registered" else 0,
        rescan_count=2 if registered else 0,
        history=(
            [
                HistoryItem(
                    field="organization",
                    old="Ромашка",
                    new="ООО Ромашка",
                    source="manual",
                    user_login="reg1",
                    at=T0.replace(minute=0),
                )
            ]
            if short.id == 17
            else []
        ),
        events=(
            [
                EventItem(type="registered", at=T0, terminal_name="Терминал 2", user_login=None),
                EventItem(
                    type="scan_rescan",
                    at=T0.replace(minute=30),
                    terminal_name="Терминал 1",
                    user_login=None,
                ),
            ]
            if registered
            else []
        ),
        actions=ParticipantActions(
            can_register=not registered,
            can_reprint=registered,
            can_edit=True,
            can_foreign_code=True,
            reasons={"can_register": f"Уже зарегистрирован {REGISTERED_AT_TEXT}"}
            if registered
            else {"can_reprint": "Сначала зарегистрируйте участника"},
        ),
    )


@router.get(
    "",
    operation_id="participants_list",
    summary="Список и поиск участников",
    description=(
        "Разрешение: `participants.view`. Участники активной конференции. Поиск `q` — по ФИО, "
        "начиная с 2 символов (RG-02). `filter=flagged` — участники с пометками. "
        "Сортировка `sort`: `name` (по умолчанию, по ФИО), `registered_at` (раньше "
        "зарегистрированные выше), `-registered_at` (позже выше); незарегистрированные "
        "всегда в конце. Заглушка отдаёт трёх фиксированных участников (id 17, 18, 19)."
    ),
    response_model=Page[ParticipantShort],
    dependencies=staff("participants.view"),
    responses=err(401, 403, 422),
)
async def participants_list(
    q: Annotated[str | None, Query(description="Поиск по ФИО", examples=["иван"])] = None,
    filter: Annotated[ParticipantFilter, Query(description="Фильтр списка")] = "all",
    sort: Annotated[ParticipantSort, Query(description="Порядок списка")] = "name",
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ParticipantShort]:
    items = list(_SHORT)
    if q:
        needle = q.strip().lower().replace("ё", "е")
        items = [p for p in items if needle in p.full_name.lower().replace("ё", "е")]
    if filter == "registered":
        items = [p for p in items if p.status != "not_registered"]
    elif filter == "not_registered":
        items = [p for p in items if p.status == "not_registered"]
    elif filter == "flagged":
        items = [p for p in items if p.flags]
    if sort == "name":
        items.sort(key=lambda p: p.full_name)
    else:
        done = sorted(
            (p for p in items if p.id in _REGISTERED_AT),
            key=lambda p: (_REGISTERED_AT[p.id], p.id),
            reverse=sort == "-registered_at",
        )
        items = [*done, *(p for p in items if p.id not in _REGISTERED_AT)]
    return Page[ParticipantShort](items=items[offset : offset + limit], total=len(items))


@router.get(
    "/stats",
    operation_id="participants_stats",
    summary="Счётчик «зарегистрировано / всего»",
    description="Разрешение: `participants.view`. Живое обновление — `GET /api/events/stream`.",
    response_model=ParticipantStats,
    dependencies=staff("participants.view"),
    responses=err(401, 403),
)
async def participants_stats() -> ParticipantStats:
    return ParticipantStats(registered=120, total=300)


@router.post(
    "/check-duplicates",
    operation_id="participants_check_duplicates",
    summary="Поиск дубликатов перед добавлением",
    description="Разрешение: `participants.add`. Похожие ФИО среди участников (RG-07).",
    response_model=DuplicatesOut,
    dependencies=staff("participants.add", write=True),
    responses=err(401, 403, 422),
)
async def participants_check_duplicates(body: CheckDuplicatesIn) -> DuplicatesOut:
    needle = body.last_name.strip().lower().replace("ё", "е")
    items = [p for p in _SHORT if p.full_name.lower().replace("ё", "е").startswith(needle)]
    return DuplicatesOut(items=items)


@router.post(
    "",
    operation_id="participants_create",
    summary="Добавить участника и зарегистрировать",
    description=(
        "Разрешение: `participants.add` (+ `stickers.print` при `with_sticker`). "
        "Участник получает пометку «Добавлен вручную» и сразу регистрируется (RG-07)."
    ),
    status_code=201,
    response_model=ParticipantCreatedOut,
    dependencies=staff("participants.add", write=True),
    responses=err(401, 403, 422),
)
async def participants_create(body: ParticipantCreateIn) -> ParticipantCreatedOut:
    base = sample_card(18)
    card = base.model_copy(
        update={
            "id": 20,
            "external_id": None,
            "last_name": body.last_name,
            "first_name": body.first_name,
            "middle_name": body.middle_name,
            "position": body.position,
            "organization": body.organization,
            "status": "registered" if body.with_sticker else "registered_no_sticker",
            "registration": RegistrationInfo(
                at=T0, source="desk", terminal_name=None, user_login="reg1"
            ),
            "flags": [FlagInfo(code="manual_added", at=T0, by="reg1")],
            "photo_url": None,
            "print_count": 1 if body.with_sticker else 0,
            "actions": ParticipantActions(
                can_register=False,
                can_reprint=True,
                can_edit=True,
                can_foreign_code=True,
                reasons={"can_register": "Уже зарегистрирован"},
            ),
        }
    )
    return ParticipantCreatedOut(participant=card, print_job_id=501 if body.with_sticker else None)


@router.get(
    "/{participant_id}",
    operation_id="participants_get",
    summary="Карточка участника",
    description=(
        "Разрешение: `participants.view`. Поле `actions` бэкенд вычисляет сам: кнопка неактивна, "
        "если флаг `false`, подсказка — в `actions.reasons`. Заглушка знает id 17 "
        "(зарегистрирован), 18 (нет), 19 (без наклейки); остальные дают 404."
    ),
    response_model=ParticipantCard,
    dependencies=staff("participants.view"),
    responses=err(401, 403, (404, "`participant_not_found`: участник не найден")),
)
async def participants_get(participant_id: int) -> ParticipantCard:
    return sample_card(participant_id)


@router.get(
    "/{participant_id}/photo",
    operation_id="participants_photo",
    summary="Фото участника",
    description="Разрешение: `participants.view`. JPEG; заглушка отдаёт пиксель 1×1.",
    response_class=Response,
    responses={
        200: {
            "description": "Фото в формате JPEG",
            "content": {"image/jpeg": {"schema": {"type": "string", "format": "binary"}}},
        },
        **err(401, 403, (404, "`photo_not_found`: у участника нет фото")),
    },
    dependencies=staff("participants.view"),
)
async def participants_photo(participant_id: int) -> Response:
    sample_short(participant_id)
    return Response(content=JPEG_1X1, media_type="image/jpeg")


@router.patch(
    "/{participant_id}",
    operation_id="participants_update",
    summary="Исправить данные участника",
    description=(
        "Разрешение: `participants.edit`. Передавайте только изменённые поля. "
        "Изменения попадают в журнал и включают пометку «Данные изменены» (ER-03)."
    ),
    response_model=ParticipantCard,
    dependencies=staff("participants.edit", write=True),
    responses=err(401, 403, 404, 422),
)
async def participants_update(participant_id: int, body: ParticipantUpdateIn) -> ParticipantCard:
    card = sample_card(participant_id)
    update = body.model_dump(exclude_unset=True)
    return card.model_copy(update=update)
