"""Shared SQLAlchemy models and async session management.

Imported only by services that talk to PostgreSQL (chat, consumer, metrics).
Requires the ``db`` extra (``pip install llm-obs-shared[db]``).
"""

from llm_obs_shared.db.base import Base
from llm_obs_shared.db.models import (
    Conversation,
    ConversationStatus,
    InferenceLog,
    Message,
    ProviderStats,
)
from llm_obs_shared.db.session import Database

__all__ = [
    "Base",
    "Database",
    "Conversation",
    "ConversationStatus",
    "Message",
    "InferenceLog",
    "ProviderStats",
]
