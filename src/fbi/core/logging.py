"""Structured JSON logging with a run_id that travels through the whole pipeline."""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

_SECRET_KEYS = {"key", "token", "password", "secret", "apikey", "api_key", "authorization"}


def new_run_id() -> str:
    rid = uuid.uuid4().hex[:12]
    _run_id.set(rid)
    return rid


def get_run_id() -> str:
    return _run_id.get()


def bind_run_id(run_id: str) -> None:
    """Attach an existing run id (e.g. raw.ingestion_runs.id) to every log line
    emitted from here on in this task."""
    _run_id.set(run_id)


def _add_run_id(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    event_dict["run_id"] = _run_id.get()
    return event_dict


def _redact(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Never let a credential reach a log line, whatever the caller passes."""
    for k in list(event_dict):
        if any(s in k.lower() for s in _SECRET_KEYS):
            event_dict[k] = "[REDACTED]"
    return event_dict


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_run_id,
            _redact,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper())),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
