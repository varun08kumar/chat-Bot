"""Process-wide SDK runtime: a single producer and config instance.

Applications call :func:`configure_sdk` at startup and :func:`shutdown_sdk` at
teardown. The decorator and streaming helpers pull the active producer from
here so callers never manage the wiring themselves.
"""

from __future__ import annotations

from typing import Optional

from llm_obs_sdk.config import SdkConfig
from llm_obs_sdk.producer import KafkaLogProducer

_config: SdkConfig = SdkConfig()
_producer: Optional[KafkaLogProducer] = None


def get_config() -> SdkConfig:
    return _config


def get_producer() -> KafkaLogProducer:
    """Return the active producer, lazily constructing a (not-yet-started) one.

    A producer that has not been ``start``-ed still accepts ``emit`` calls; they
    are buffered and silently dropped only if the app never starts it — which is
    the correct no-op behaviour for tests.
    """

    global _producer
    if _producer is None:
        _producer = KafkaLogProducer(_config)
    return _producer


async def configure_sdk(config: SdkConfig | None = None) -> KafkaLogProducer:
    """Install configuration and start the background producer."""

    global _config, _producer
    if config is not None:
        _config = config
    _producer = KafkaLogProducer(_config)
    await _producer.start()
    return _producer


async def shutdown_sdk() -> None:
    """Flush and stop the producer, if one is running."""

    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None
