"""initial schema: conversations, messages, inference_logs, provider_stats

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_user_updated", "conversations", ["user_id", "updated_at"])
    op.create_index("ix_conversations_status", "conversations", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("conversation_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"],
            name="fk_messages_conversation_id_conversations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at"])

    op.create_table(
        "inference_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.String(length=32), nullable=True),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.String(length=64), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_preview", sa.String(length=256), nullable=False),
        sa.Column("response_preview", sa.String(length=256), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_inference_logs"),
        sa.UniqueConstraint("request_id", name="uq_inference_logs_request_id"),
    )
    op.create_index("ix_inference_logs_timestamp", "inference_logs", ["timestamp"])
    op.create_index("ix_inference_logs_provider_ts", "inference_logs", ["provider", "timestamp"])
    op.create_index("ix_inference_logs_model_ts", "inference_logs", ["model", "timestamp"])
    op.create_index("ix_inference_logs_status_ts", "inference_logs", ["status", "timestamp"])
    op.create_index("ix_inference_logs_conversation", "inference_logs", ["conversation_id"])

    op.create_table(
        "provider_stats",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("requests", sa.BigInteger(), nullable=False),
        sa.Column("errors", sa.BigInteger(), nullable=False),
        sa.Column("avg_latency", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("provider", name="pk_provider_stats"),
    )


def downgrade() -> None:
    op.drop_table("provider_stats")
    op.drop_index("ix_inference_logs_conversation", table_name="inference_logs")
    op.drop_index("ix_inference_logs_status_ts", table_name="inference_logs")
    op.drop_index("ix_inference_logs_model_ts", table_name="inference_logs")
    op.drop_index("ix_inference_logs_provider_ts", table_name="inference_logs")
    op.drop_index("ix_inference_logs_timestamp", table_name="inference_logs")
    op.drop_table("inference_logs")
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_user_updated", table_name="conversations")
    op.drop_table("conversations")
