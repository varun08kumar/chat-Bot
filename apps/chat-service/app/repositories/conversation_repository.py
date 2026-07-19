"""Data-access for conversations and messages.

The repository is the *only* place that speaks SQL, keeping the service layer
persistence-agnostic (repository pattern).
"""

from __future__ import annotations

from datetime import datetime, timezone

from llm_obs_shared.db.models import Conversation, ConversationStatus, Message
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession


class ConversationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, user_id: str, title: str) -> Conversation:
        conversation = Conversation(user_id=user_id, title=title, status=ConversationStatus.ACTIVE.value)
        self._session.add(conversation)
        await self._session.flush()
        return conversation

    async def get(self, conversation_id: str, *, user_id: str) -> Conversation | None:
        stmt = select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
            Conversation.status != ConversationStatus.DELETED.value,
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_for_user(
        self, *, user_id: str, limit: int = 50, offset: int = 0, search: str | None = None
    ) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(
                Conversation.user_id == user_id,
                Conversation.status != ConversationStatus.DELETED.value,
            )
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if search:
            stmt = stmt.where(Conversation.title.ilike(f"%{search}%"))
        return list((await self._session.execute(stmt)).scalars().all())

    async def soft_delete(self, conversation_id: str, *, user_id: str) -> bool:
        stmt = (
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(status=ConversationStatus.DELETED.value, updated_at=datetime.now(timezone.utc))
        )
        result = await self._session.execute(stmt)
        return result.rowcount > 0

    async def touch(self, conversation_id: str) -> None:
        await self._session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(timezone.utc))
        )

    async def set_title(self, conversation_id: str, title: str) -> None:
        await self._session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(title=title)
        )

    async def count_active(self) -> int:
        stmt = select(func.count()).select_from(Conversation).where(
            Conversation.status == ConversationStatus.ACTIVE.value
        )
        return int((await self._session.execute(stmt)).scalar_one())


class MessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, *, conversation_id: str, role: str, content: str) -> Message:
        message = Message(conversation_id=conversation_id, role=role, content=content)
        self._session.add(message)
        await self._session.flush()
        return message

    async def history(self, conversation_id: str, *, limit: int = 30) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())
