"""SQLAlchemy 2.0 ORM models — the single source of truth for the schema.

Tables:
    * conversations   — chat threads (owned by chat-service)
    * messages        — individual turns within a conversation
    * inference_logs  — persisted, redacted inference events (owned by consumer)
    * provider_stats  — rolling aggregate per provider (maintained by consumer)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from llm_obs_shared.db.base import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New conversation")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ConversationStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_conversations_status", "status"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # system|user|assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)


class InferenceLog(Base):
    __tablename__ = "inference_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str | None] = mapped_column(String(128), nullable=True)

    latency_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    prompt_preview: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    response_preview: Mapped[str] = mapped_column(String(256), nullable=False, default="")

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    meta: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    timestamp: Mapped[datetime] = mapped_column(nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, server_default=func.now())

    __table_args__ = (
        Index("ix_inference_logs_provider_ts", "provider", "timestamp"),
        Index("ix_inference_logs_model_ts", "model", "timestamp"),
        Index("ix_inference_logs_status_ts", "status", "timestamp"),
        Index("ix_inference_logs_conversation", "conversation_id"),
    )


class ProviderStats(Base):
    __tablename__ = "provider_stats"

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)
    requests: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    errors: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    avg_latency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow, server_default=func.now(), onupdate=_utcnow
    )
