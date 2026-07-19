"""Structured JSON logging shared by every service.

All services emit newline-delimited JSON so logs can be shipped to Loki/ELK and
queried by field. The correlation id (when present) is injected automatically.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from pythonjsonlogger import jsonlogger

from llm_obs_shared.correlation import get_correlation_id

_CONFIGURED = False


class _CorrelationFilter(logging.Filter):
    """Attach the current correlation id to every record."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib name
        record.correlation_id = get_correlation_id()
        return True


class _JsonFormatter(jsonlogger.JsonFormatter):
    """JSON formatter that always includes a stable set of top-level fields."""

    def add_fields(
        self,
        log_record: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("level", record.levelname)
        log_record.setdefault("logger", record.name)
        log_record.setdefault("service", getattr(record, "service", None))
        log_record["correlation_id"] = getattr(record, "correlation_id", None)


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """Configure root logging once per process.

    Safe to call multiple times; only the first call installs handlers.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        _JsonFormatter(
            "%(timestamp)s %(level)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp"},
            timestamp=True,
        )
    )
    handler.addFilter(_CorrelationFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Tame noisy third-party loggers so our structured output stays readable.
    for noisy in ("aiokafka", "uvicorn.access", "httpx", "LiteLLM"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Bind the service name onto every record produced in this process.
    logging.setLogRecordFactory(_record_factory_with_service(service_name))
    _CONFIGURED = True


def _record_factory_with_service(service_name: str):
    base_factory = logging.getLogRecordFactory()

    def factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = base_factory(*args, **kwargs)
        record.service = service_name
        return record

    return factory


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""

    return logging.getLogger(name)
