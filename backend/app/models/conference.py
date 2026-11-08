"""Конференция, описание доп. полей, шаблоны наклеек."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Index, Numeric, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.enums import BadgeType, TemplateKind
from app.models.base import FALSE, JSONB_ARRAY, ZERO, created_at, fk, in_check, pk, updated_at


class Conference(Base):
    __tablename__ = "conference"
    __table_args__ = (
        in_check("badge_type", BadgeType, "badge_type"),
        # Активной может быть только одна конференция
        Index(
            "uq_conference_single_active",
            text("(true)"),
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = pk()
    title: Mapped[str]
    date_from: Mapped[date]
    date_to: Mapped[date]
    badge_type: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default=FALSE)
    # Регулярка для извлечения ID из ссылки приглашения; NULL — глобальное значение (В-04)
    invite_id_regex: Mapped[str | None]
    # Циклические FK conference <-> label_template: в миграции создаются отдельным ALTER
    front_template_id: Mapped[int | None] = fk("label_template.id", nullable=True, use_alter=True)
    back_template_id: Mapped[int | None] = fk("label_template.id", nullable=True, use_alter=True)
    changed_template_id: Mapped[int | None] = fk("label_template.id", nullable=True, use_alter=True)
    changed_back_template_id: Mapped[int | None] = fk(
        "label_template.id", nullable=True, use_alter=True
    )
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ExtraFieldDef(Base):
    __tablename__ = "extra_field_def"
    __table_args__ = (UniqueConstraint("conference_id", "key", name="uq_extra_field_def_key"),)

    id: Mapped[int] = pk()
    conference_id: Mapped[int] = fk("conference.id")
    key: Mapped[str]  # slug
    label: Mapped[str]  # исходный заголовок столбца
    sort_order: Mapped[int] = mapped_column(server_default=ZERO)


class LabelTemplate(Base):
    __tablename__ = "label_template"
    __table_args__ = (in_check("kind", TemplateKind, "kind"),)

    id: Mapped[int] = pk()
    conference_id: Mapped[int] = fk("conference.id")
    name: Mapped[str]
    kind: Mapped[str]
    width_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    height_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    gap_mm: Mapped[Decimal] = mapped_column(Numeric(6, 2), server_default=text("2"))
    elements: Mapped[list[Any]] = mapped_column(JSONB, server_default=JSONB_ARRAY)
    version: Mapped[int] = mapped_column(server_default=text("1"))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
