"""Модели SQLAlchemy. Импорт пакета регистрирует все таблицы в `Base.metadata` (для Alembic)."""

from app.models.conference import Conference, ExtraFieldDef, LabelTemplate
from app.models.device import Printer, Terminal
from app.models.imports import ImportBatch
from app.models.participant import BadgeToken, ChangeLog, EventLog, Participant
from app.models.printing import IdempotencyRecord, PrintJob
from app.models.staff import Role, RolePermission, StaffSession, StaffUser

__all__ = [
    "BadgeToken",
    "ChangeLog",
    "Conference",
    "EventLog",
    "ExtraFieldDef",
    "IdempotencyRecord",
    "ImportBatch",
    "LabelTemplate",
    "Participant",
    "PrintJob",
    "Printer",
    "Role",
    "RolePermission",
    "StaffSession",
    "StaffUser",
    "Terminal",
]
