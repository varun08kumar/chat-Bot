"""LLM Observability SDK — automatic inference instrumentation.

Typical wiring in a FastAPI service::

    from llm_obs_sdk import configure_sdk, shutdown_sdk, observe_llm

    @asynccontextmanager
    async def lifespan(app):
        await configure_sdk()
        yield
        await shutdown_sdk()
"""

from llm_obs_sdk.config import SdkConfig
from llm_obs_sdk.context import observation_context
from llm_obs_sdk.decorator import observe_llm
from llm_obs_sdk.runtime import configure_sdk, get_producer, shutdown_sdk
from llm_obs_sdk.stream import observe_stream

__all__ = [
    "SdkConfig",
    "observe_llm",
    "observe_stream",
    "observation_context",
    "configure_sdk",
    "shutdown_sdk",
    "get_producer",
]
