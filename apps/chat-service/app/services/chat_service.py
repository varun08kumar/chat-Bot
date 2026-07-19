"""Chat orchestration: conversation state + inference + streaming.

This is the service layer. It coordinates repositories, the cache and the LLM
client but contains no framework or SQL details itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator

from llm_obs_sdk import observation_context
from llm_obs_shared.logging import get_logger
from llm_obs_shared.db.session import Database

from app.config import Settings
from app.repositories.conversation_repository import (
    ConversationRepository,
    MessageRepository,
)
from app.services.cache import ConversationCache
from app.services.llm_client import LLMClient, LLMError
from app.services.providers import provider_for_model

logger = get_logger(__name__)

SYSTEM_PROMPT = "You are a helpful, concise assistant."


class ConversationNotFound(Exception):
    pass


@dataclass
class PreparedChat:
    conversation_id: str
    request_id: str
    model: str
    provider: str
    messages: list[dict[str, Any]]
    is_new: bool


class ChatService:
    def __init__(
        self,
        *,
        db: Database,
        cache: ConversationCache,
        llm: LLMClient,
        settings: Settings,
    ) -> None:
        self._db = db
        self._cache = cache
        self._llm = llm
        self._settings = settings

    async def _load_history(
        self, repo: MessageRepository, conversation_id: str
    ) -> list[dict[str, Any]]:
        cached = await self._cache.get_messages(conversation_id)
        if cached is not None:
            return cached
        messages = await repo.history(conversation_id, limit=self._settings.max_history_messages)
        history = [{"role": m.role, "content": m.content} for m in messages]
        await self._cache.set_messages(conversation_id, history)
        return history

    async def prepare(self, *, user_id: str, message: str, conversation_id: str | None, model: str | None) -> PreparedChat:
        """Resolve conversation, persist the user turn, and assemble the prompt."""

        model = model or self._settings.default_model
        provider = provider_for_model(model)
        request_id = uuid.uuid4().hex

        async with self._db.session() as session:
            conv_repo = ConversationRepository(session)
            msg_repo = MessageRepository(session)

            is_new = False
            if conversation_id:
                conversation = await conv_repo.get(conversation_id, user_id=user_id)
                if conversation is None:
                    raise ConversationNotFound(conversation_id)
            else:
                title = _derive_title(message)
                conversation = await conv_repo.create(user_id=user_id, title=title)
                conversation_id = conversation.id
                is_new = True

            history = [] if is_new else await self._load_history(msg_repo, conversation_id)
            await msg_repo.add(conversation_id=conversation_id, role="user", content=message)
            await conv_repo.touch(conversation_id)

        prompt_messages = (
            [{"role": "system", "content": SYSTEM_PROMPT}]
            + history
            + [{"role": "user", "content": message}]
        )
        # Refresh cache with the appended user message.
        await self._cache.set_messages(conversation_id, history + [{"role": "user", "content": message}])

        return PreparedChat(
            conversation_id=conversation_id,
            request_id=request_id,
            model=model,
            provider=provider,
            messages=prompt_messages,
            is_new=is_new,
        )

    async def _persist_assistant(self, conversation_id: str, content: str) -> None:
        async with self._db.session() as session:
            msg_repo = MessageRepository(session)
            conv_repo = ConversationRepository(session)
            await msg_repo.add(conversation_id=conversation_id, role="assistant", content=content)
            await conv_repo.touch(conversation_id)
        await self._cache.invalidate(conversation_id)

    async def complete(self, prepared: PreparedChat, *, user_id: str, session_id: str) -> dict[str, Any]:
        """Non-streaming completion."""

        with observation_context(
            session_id=session_id,
            conversation_id=prepared.conversation_id,
            user_id=user_id,
            endpoint="/chat",
            request_id=prepared.request_id,
        ):
            content, usage = await self._llm.complete(model=prepared.model, messages=prepared.messages)
        await self._persist_assistant(prepared.conversation_id, content)
        return {"content": content, "usage": usage}

    async def stream(
        self, prepared: PreparedChat, *, user_id: str, session_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a completion as semantic events; persists the final message.

        Client cancellation propagates as ``GeneratorExit``/``CancelledError``;
        we still persist whatever was generated so the conversation stays
        consistent, and the SDK records the call as cancelled.
        """

        collected: list[str] = []
        usage: dict[str, Any] = {}
        errored = False
        yield {"event": "start", "data": {
            "conversation_id": prepared.conversation_id,
            "request_id": prepared.request_id,
            "model": prepared.model,
            "provider": prepared.provider,
        }}
        try:
            with observation_context(
                session_id=session_id,
                conversation_id=prepared.conversation_id,
                user_id=user_id,
                endpoint="/chat/stream",
                request_id=prepared.request_id,
            ):
                async for event in self._llm.stream(model=prepared.model, messages=prepared.messages):
                    if event["type"] == "token":
                        collected.append(event["content"])
                        yield {"event": "token", "data": {"content": event["content"]}}
                    elif event["type"] == "usage":
                        usage = {k: v for k, v in event.items() if k != "type"}
                        yield {"event": "usage", "data": usage}
        except LLMError as exc:
            errored = True
            yield {"event": "error", "data": {"message": str(exc)}}
        finally:
            text = "".join(collected)
            if text:
                await self._persist_assistant(prepared.conversation_id, text)
        if not errored:
            yield {"event": "done", "data": {
                "conversation_id": prepared.conversation_id,
                "usage": usage,
            }}


def _derive_title(message: str) -> str:
    title = " ".join(message.strip().split())
    return (title[:60] + "…") if len(title) > 60 else (title or "New conversation")
