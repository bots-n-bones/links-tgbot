"""add channel parser tables

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-07-12 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b4c5d6e7f8a9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    job_status = sa.Enum(
        "pending",
        "validating",
        "scraping",
        "storing",
        "analyzing",
        "done",
        "failed",
        name="channel_parse_job_status",
    )
    report_status = sa.Enum("pending", "done", "failed", name="channel_voice_report_status")

    op.create_table(
        "channel_parse_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", job_status, nullable=False, server_default="pending"),
        sa.Column("channel_username", sa.String(length=32), nullable=False),
        sa.Column("channel_title", sa.Text(), nullable=True),
        sa.Column("channel_meta_json", postgresql.JSONB(), nullable=True),
        sa.Column("params_json", postgresql.JSONB(), nullable=False),
        sa.Column("progress_current", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("posts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("date_range_from", sa.Date(), nullable=True),
        sa.Column("date_range_to", sa.Date(), nullable=True),
        sa.Column("avg_views", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_channel_parse_jobs_username_created",
        "channel_parse_jobs",
        ["channel_username", "created_at"],
    )

    op.create_table(
        "channel_parsed_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("channel_parse_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("post_url", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("views", sa.Integer(), nullable=True),
        sa.Column("reactions_json", postgresql.JSONB(), nullable=True),
        sa.Column("reactions_total", sa.Integer(), nullable=True),
        sa.Column("comments_count", sa.Integer(), nullable=True),
        sa.Column("commenters_json", postgresql.JSONB(), nullable=True),
        sa.Column("is_forward", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("has_media", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("word_count", sa.Integer(), nullable=True),
        sa.Column("urls_in_post", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "message_id", name="uq_channel_posts_job_message"),
    )

    op.create_table(
        "channel_voice_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("channel_parse_jobs.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", report_status, nullable=False, server_default="pending"),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=True),
        sa.Column("post_analyses_json", postgresql.JSONB(), nullable=True),
        sa.Column("profile_json", postgresql.JSONB(), nullable=True),
        sa.Column("chart_data_json", postgresql.JSONB(), nullable=True),
        sa.Column("report_sections_json", postgresql.JSONB(), nullable=True),
        sa.Column("report_md", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model", sa.String(length=50), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("channel_voice_reports")
    op.drop_table("channel_parsed_posts")
    op.drop_index("ix_channel_parse_jobs_username_created", table_name="channel_parse_jobs")
    op.drop_table("channel_parse_jobs")
    sa.Enum(name="channel_voice_report_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="channel_parse_job_status").drop(op.get_bind(), checkfirst=True)
