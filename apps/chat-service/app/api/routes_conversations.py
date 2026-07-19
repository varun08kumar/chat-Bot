"""Conversation management endpoints: list, fetch, delete."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.schemas import (
    ConversationDetailOut,
    ConversationOut,
    DeleteResponse,
    MessageOut,
)
from app.dependencies import Identity, get_db, get_identity
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from llm_obs_shared.db.session import Database

router = APIRouter(tags=["conversations"])


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    identity: Identity = Depends(get_identity),
    db: Database = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    search: str | None = Query(None, max_length=100),
) -> list[ConversationOut]:
    async with db.session() as session:
        repo = ConversationRepository(session)
        conversations = await repo.list_for_user(
            user_id=identity.user_id, limit=limit, offset=offset, search=search
        )
        return [ConversationOut.model_validate(c, from_attributes=True) for c in conversations]


@router.get("/conversation/{conversation_id}", response_model=ConversationDetailOut)
async def get_conversation(
    conversation_id: str,
    identity: Identity = Depends(get_identity),
    db: Database = Depends(get_db),
) -> ConversationDetailOut:
    async with db.session() as session:
        conv_repo = ConversationRepository(session)
        msg_repo = MessageRepository(session)
        conversation = await conv_repo.get(conversation_id, user_id=identity.user_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = await msg_repo.history(conversation_id, limit=1000)
        return ConversationDetailOut(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[MessageOut.model_validate(m, from_attributes=True) for m in messages],
        )


@router.delete("/conversation/{conversation_id}", response_model=DeleteResponse)
async def delete_conversation(
    conversation_id: str,
    identity: Identity = Depends(get_identity),
    db: Database = Depends(get_db),
) -> DeleteResponse:
    async with db.session() as session:
        repo = ConversationRepository(session)
        deleted = await repo.soft_delete(conversation_id, user_id=identity.user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return DeleteResponse(deleted=True)
