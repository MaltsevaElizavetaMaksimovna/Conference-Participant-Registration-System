"""Перечисления предметной области.

В БД хранятся как varchar + CHECK (значения CHECK генерируются из этих классов,
см. `app.models.base.in_check`), поэтому список значений живёт только здесь.
"""

from enum import StrEnum


class BadgeType(StrEnum):
    SINGLE = "single"
    DOUBLE = "double"
    NONE = "none"


class TemplateKind(StrEnum):
    FRONT = "front"
    BACK = "back"
    CHANGED = "changed"
    CHANGED_BACK = "changed_back"


class ParticipantStatus(StrEnum):
    NOT_REGISTERED = "not_registered"
    REGISTERED = "registered"
    REGISTERED_NO_STICKER = "registered_no_sticker"


class RegSource(StrEnum):
    TERMINAL = "terminal"
    DESK = "desk"


class BadgeTokenStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ChangeSource(StrEnum):
    MANUAL = "manual"
    IMPORT = "import"


class EventType(StrEnum):
    SCAN_NOT_FOUND = "scan_not_found"
    SCAN_RESCAN = "scan_rescan"
    ERROR_REPORTED = "error_reported"
    REGISTERED = "registered"
    PRINT_OK = "print_ok"
    PRINT_ERROR = "print_error"
    REPRINT = "reprint"
    FOREIGN_CODE = "foreign_code"
    DATA_CHANGED = "data_changed"
    MANUAL_ADDED = "manual_added"


class PrintJobKind(StrEnum):
    FIRST = "first"
    REPRINT = "reprint"
    FOREIGN = "foreign"
    TEST = "test"


class PrintJobStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    DONE = "done"
    ERROR = "error"


class ImportSource(StrEnum):
    FILE = "file"
    BITRIX = "bitrix"


class ImportStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
