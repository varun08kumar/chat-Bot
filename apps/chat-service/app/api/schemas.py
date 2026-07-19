"""Request/response DTOs for the chat API (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    conversation_id: str | None = None
    model: str | None = None
    stream: bool = True


class TokenUsageOut(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatResponse(BaseModel):
    conversation_id: str
    request_id: str
    message: str
    model: str
    provider: str
    usage: TokenUsageOut
    latency_ms: float


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    created_at: datetime


class ConversationOut(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class ModelOut(BaseModel):
    id: str
    label: str
    context_window: int


class ProviderOut(BaseModel):
    id: str
    label: str
    enabled: bool
    models: list[ModelOut]


class DeleteResponse(BaseModel):
    deleted: bool
