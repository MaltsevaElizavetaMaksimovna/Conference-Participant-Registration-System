"""Начальная схема БД (S-03).

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conference",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("badge_type", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("invite_id_regex", sa.Text(), nullable=True),
        sa.Column("front_template_id", sa.BigInteger(), nullable=True),
        sa.Column("back_template_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_template_id", sa.BigInteger(), nullable=True),
        sa.Column("changed_back_template_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "badge_type IN ('single', 'double', 'none')", name=op.f("ck_conference_badge_type")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conference")),
    )
    op.create_index(
        "uq_conference_single_active",
        "conference",
        [sa.literal_column("(true)")],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "idempotency_record",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_idempotency_record")),
    )
    op.create_table(
        "printer",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("agent_token_hash", sa.Text(), nullable=True),
        sa.Column("windows_printer_name", sa.Text(), nullable=True),
        sa.Column("dpi", sa.Integer(), server_default=sa.text("203"), nullable=False),
        sa.Column(
            "offset_x_mm",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "offset_y_mm",
            sa.Numeric(precision=5, scale=2),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("density", sa.SmallInteger(), server_default=sa.text("10"), nullable=False),
        sa.Column("speed", sa.SmallInteger(), server_default=sa.text("3"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'unknown'"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("density BETWEEN 0 AND 15", name=op.f("ck_printer_density")),
        sa.CheckConstraint("speed BETWEEN 1 AND 6", name=op.f("ck_printer_speed")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_printer")),
        sa.UniqueConstraint("agent_token_hash", name=op.f("uq_printer_agent_token_hash")),
        sa.UniqueConstraint("name", name=op.f("uq_printer_name")),
    )
    op.create_table(
        "role",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role")),
        sa.UniqueConstraint("name", name=op.f("uq_role_name")),
    )
    op.create_table(
        "extra_field_def",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["conference_id"],
            ["conference.id"],
            name=op.f("fk_extra_field_def_conference_id_conference"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_extra_field_def")),
        sa.UniqueConstraint("conference_id", "key", name="uq_extra_field_def_key"),
    )
    op.create_table(
        "label_template",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("width_mm", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("height_mm", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column(
            "gap_mm", sa.Numeric(precision=6, scale=2), server_default=sa.text("2"), nullable=False
        ),
        sa.Column(
            "elements",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('front', 'back', 'changed', 'changed_back')",
            name=op.f("ck_label_template_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"],
            ["conference.id"],
            name=op.f("fk_label_template_conference_id_conference"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_label_template")),
    )
    # Циклические FK conference <-> label_template создаются после обеих таблиц
    for column in (
        "front_template_id",
        "back_template_id",
        "changed_template_id",
        "changed_back_template_id",
    ):
        op.create_foreign_key(
            op.f(f"fk_conference_{column}_label_template"),
            "conference",
            "label_template",
            [column],
            ["id"],
        )
    op.create_table(
        "role_permission",
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("permission", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "permission IN ('participants.view', 'registration.desk', 'stickers.print', 'participants.edit', 'participants.add', 'registration.foreign_code', 'imports.run', 'conferences.manage', 'devices.manage', 'users.manage')",
            name=op.f("ck_role_permission_permission"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["role.id"],
            name=op.f("fk_role_permission_role_id_role"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission", name=op.f("pk_role_permission")),
    )
    op.create_table(
        "staff_user",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("login", sa.Text(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role_id", sa.BigInteger(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("panel_printer_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["panel_printer_id"],
            ["printer.id"],
            name=op.f("fk_staff_user_panel_printer_id_printer"),
        ),
        sa.ForeignKeyConstraint(["role_id"], ["role.id"], name=op.f("fk_staff_user_role_id_role")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_user")),
    )
    op.create_index(
        "uq_staff_user_login_lower", "staff_user", [sa.literal_column("lower(login)")], unique=True
    )
    op.create_table(
        "terminal",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=True),
        sa.Column("printer_id", sa.BigInteger(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["printer_id"], ["printer.id"], name=op.f("fk_terminal_printer_id_printer")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terminal")),
        sa.UniqueConstraint("name", name=op.f("uq_terminal_name")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_terminal_token_hash")),
    )
    op.create_table(
        "import_batch",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=True),
        sa.Column("file_sha256", sa.Text(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column(
            "report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("source IN ('file', 'bitrix')", name=op.f("ck_import_batch_source")),
        sa.CheckConstraint(
            "status IN ('running', 'done', 'failed')", name=op.f("ck_import_batch_status")
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"],
            ["conference.id"],
            name=op.f("fk_import_batch_conference_id_conference"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["staff_user.id"], name=op.f("fk_import_batch_user_id_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_batch")),
    )
    op.create_table(
        "participant",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=False),
        sa.Column("middle_name", sa.Text(), nullable=True),
        sa.Column("position", sa.Text(), nullable=True),
        sa.Column("organization", sa.Text(), nullable=True),
        sa.Column("last_name_en", sa.Text(), nullable=True),
        sa.Column("first_name_en", sa.Text(), nullable=True),
        sa.Column("middle_name_en", sa.Text(), nullable=True),
        sa.Column("position_en", sa.Text(), nullable=True),
        sa.Column("organization_en", sa.Text(), nullable=True),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "source_data",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "manual_fields",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_manual_added", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("photo_path", sa.Text(), nullable=True),
        sa.Column("photo_sha256", sa.Text(), nullable=True),
        sa.Column("search_norm", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'not_registered'"), nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reg_source", sa.Text(), nullable=True),
        sa.Column("reg_terminal_id", sa.BigInteger(), nullable=True),
        sa.Column("reg_user_id", sa.BigInteger(), nullable=True),
        sa.Column("error_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sticker_not_printed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("foreign_code_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("foreign_code_by", sa.BigInteger(), nullable=True),
        sa.Column("print_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("rescan_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'not_registered') = (registered_at IS NULL)",
            name=op.f("ck_participant_status_registered_at"),
        ),
        sa.CheckConstraint(
            "reg_source IN ('terminal', 'desk')", name=op.f("ck_participant_reg_source")
        ),
        sa.CheckConstraint(
            "status IN ('not_registered', 'registered', 'registered_no_sticker')",
            name=op.f("ck_participant_status"),
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"],
            ["conference.id"],
            name=op.f("fk_participant_conference_id_conference"),
        ),
        sa.ForeignKeyConstraint(
            ["foreign_code_by"],
            ["staff_user.id"],
            name=op.f("fk_participant_foreign_code_by_staff_user"),
        ),
        sa.ForeignKeyConstraint(
            ["reg_terminal_id"],
            ["terminal.id"],
            name=op.f("fk_participant_reg_terminal_id_terminal"),
        ),
        sa.ForeignKeyConstraint(
            ["reg_user_id"], ["staff_user.id"], name=op.f("fk_participant_reg_user_id_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_participant")),
        sa.UniqueConstraint("conference_id", "external_id", name="uq_participant_external_id"),
    )
    op.create_index(
        "ix_participant_conference_search_norm",
        "participant",
        ["conference_id", "search_norm"],
        unique=False,
        postgresql_ops={"search_norm": "text_pattern_ops"},
    )
    op.create_index(
        "ix_participant_conference_status", "participant", ["conference_id", "status"], unique=False
    )
    op.create_table(
        "staff_session",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("permissions", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["staff_user.id"], name=op.f("fk_staff_session_user_id_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_session")),
    )
    op.create_index("ix_staff_session_user_id", "staff_session", ["user_id"], unique=False)
    op.create_table(
        "badge_token",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'revoked')", name=op.f("ck_badge_token_status")),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participant.id"],
            name=op.f("fk_badge_token_participant_id_participant"),
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"], ["staff_user.id"], name=op.f("fk_badge_token_revoked_by_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_badge_token")),
        sa.UniqueConstraint("token", name=op.f("uq_badge_token_token")),
    )
    op.create_index(
        "uq_badge_token_participant_active",
        "badge_token",
        ["participant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "change_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("import_batch_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source IN ('manual', 'import')", name=op.f("ck_change_log_source")),
        sa.ForeignKeyConstraint(
            ["import_batch_id"],
            ["import_batch.id"],
            name=op.f("fk_change_log_import_batch_id_import_batch"),
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participant.id"],
            name=op.f("fk_change_log_participant_id_participant"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["staff_user.id"], name=op.f("fk_change_log_user_id_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_change_log")),
    )
    op.create_index(
        "ix_change_log_participant_created",
        "change_log",
        ["participant_id", "created_at"],
        unique=False,
    )
    # ER-03: журнал изменений только для добавления
    op.execute(
        """
        CREATE FUNCTION change_log_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'change_log is append-only (% not allowed)', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER change_log_append_only
        BEFORE UPDATE OR DELETE ON change_log
        FOR EACH ROW EXECUTE FUNCTION change_log_append_only()
        """
    )
    op.create_table(
        "event_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=True),
        sa.Column("participant_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("terminal_id", sa.BigInteger(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_code", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"], ["conference.id"], name=op.f("fk_event_log_conference_id_conference")
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participant.id"],
            name=op.f("fk_event_log_participant_id_participant"),
        ),
        sa.ForeignKeyConstraint(
            ["terminal_id"], ["terminal.id"], name=op.f("fk_event_log_terminal_id_terminal")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["staff_user.id"], name=op.f("fk_event_log_user_id_staff_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_event_log")),
    )
    op.create_index(
        "ix_event_log_conference_type_created",
        "event_log",
        ["conference_id", "type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_event_log_participant_created",
        "event_log",
        ["participant_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "print_job",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("conference_id", sa.BigInteger(), nullable=False),
        sa.Column("participant_id", sa.BigInteger(), nullable=True),
        sa.Column("badge_token_id", sa.BigInteger(), nullable=True),
        sa.Column("printer_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("sides", sa.SmallInteger(), nullable=False),
        sa.Column("template_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by_terminal_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("done_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "kind IN ('first', 'reprint', 'foreign', 'test')", name=op.f("ck_print_job_kind")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'done', 'error')", name=op.f("ck_print_job_status")
        ),
        sa.CheckConstraint("sides IN (1, 2)", name=op.f("ck_print_job_sides")),
        sa.ForeignKeyConstraint(
            ["badge_token_id"],
            ["badge_token.id"],
            name=op.f("fk_print_job_badge_token_id_badge_token"),
        ),
        sa.ForeignKeyConstraint(
            ["conference_id"], ["conference.id"], name=op.f("fk_print_job_conference_id_conference")
        ),
        sa.ForeignKeyConstraint(
            ["created_by_terminal_id"],
            ["terminal.id"],
            name=op.f("fk_print_job_created_by_terminal_id_terminal"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["staff_user.id"],
            name=op.f("fk_print_job_created_by_user_id_staff_user"),
        ),
        sa.ForeignKeyConstraint(
            ["participant_id"],
            ["participant.id"],
            name=op.f("fk_print_job_participant_id_participant"),
        ),
        sa.ForeignKeyConstraint(
            ["printer_id"], ["printer.id"], name=op.f("fk_print_job_printer_id_printer")
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["label_template.id"],
            name=op.f("fk_print_job_template_id_label_template"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_print_job")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_print_job_idempotency_key")),
    )
    op.create_index(
        "ix_print_job_printer_status_created",
        "print_job",
        ["printer_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    for column in (
        "front_template_id",
        "back_template_id",
        "changed_template_id",
        "changed_back_template_id",
    ):
        op.drop_constraint(
            op.f(f"fk_conference_{column}_label_template"), "conference", type_="foreignkey"
        )
    op.execute("DROP TRIGGER IF EXISTS change_log_append_only ON change_log")
    op.execute("DROP FUNCTION IF EXISTS change_log_append_only()")
    op.drop_index("ix_print_job_printer_status_created", table_name="print_job")
    op.drop_table("print_job")
    op.drop_index("ix_event_log_participant_created", table_name="event_log")
    op.drop_index("ix_event_log_conference_type_created", table_name="event_log")
    op.drop_table("event_log")
    op.drop_index("ix_change_log_participant_created", table_name="change_log")
    op.drop_table("change_log")
    op.drop_index(
        "uq_badge_token_participant_active",
        table_name="badge_token",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table("badge_token")
    op.drop_index("ix_staff_session_user_id", table_name="staff_session")
    op.drop_table("staff_session")
    op.drop_index("ix_participant_conference_status", table_name="participant")
    op.drop_index(
        "ix_participant_conference_search_norm",
        table_name="participant",
        postgresql_ops={"search_norm": "text_pattern_ops"},
    )
    op.drop_table("participant")
    op.drop_table("import_batch")
    op.drop_table("terminal")
    op.drop_index("uq_staff_user_login_lower", table_name="staff_user")
    op.drop_table("staff_user")
    op.drop_table("role_permission")
    op.drop_table("label_template")
    op.drop_table("extra_field_def")
    op.drop_table("role")
    op.drop_table("printer")
    op.drop_table("idempotency_record")
    op.drop_index(
        "uq_conference_single_active",
        table_name="conference",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_table("conference")
