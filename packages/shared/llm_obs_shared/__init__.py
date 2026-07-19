"""Shared building blocks for the LLM Observability platform.

This package is intentionally dependency-light so it can be imported by every
service and by the SDK without pulling in a web framework or a database driver.
"""

from llm_obs_shared.correlation import (
    correlation_id_var,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)
from llm_obs_shared.logging import configure_logging, get_logger
from llm_obs_shared.schemas import (
    InferenceLogEvent,
    InferenceStatus,
    ProcessedLogEvent,
    TokenUsage,
)
from llm_obs_shared.topics import Topics

__all__ = [
    "Topics",
    "InferenceLogEvent",
    "ProcessedLogEvent",
    "InferenceStatus",
    "TokenUsage",
    "configure_logging",
    "get_logger",
    "correlation_id_var",
    "get_correlation_id",
    "set_correlation_id",
    "new_correlation_id",
]
