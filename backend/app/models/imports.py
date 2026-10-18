"""Партии импорта участников."""

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import ImportSource, ImportStatus
from app.models.base import JSONB_OBJECT, created_at, fk, in_check, pk


class ImportBatch(Base):
    __tablename__ = "import_batch"
    __table_args__ = (
        in_check("source", ImportSource, "source"),
        in_check("status", ImportStatus, "status"),
    )

    id: Mapped[int] = pk()
    conference_id: Mapped[int] = fk("conference.id")
    source: Mapped[str]
    file_name: Mapped[str | None]
    file_sha256: Mapped[str | None]
    user_id: Mapped[int | None] = fk("staff_user.id", nullable=True)
    status: Mapped[str] = mapped_column(server_default=text("'running'"))
    report: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=JSONB_OBJECT)
    created_at: Mapped[datetime] = created_at()
    finished_at: Mapped[datetime | None]
