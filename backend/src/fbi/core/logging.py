"""Structured JSON logging with a run_id that travels through the whole pipeline."""

from __future__ import annotations

import logging
import re
import sys
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

_run_id: ContextVar[str] = ContextVar("run_id", default="-")

_SECRET_KEYS = {"key", "token", "password", "secret", "apikey", "api_key", "authorization"}
# Credentials that travel inside strings: a Telegram bot token is part of the
# URL path, an LLM key has a recognisable prefix, a connection string can
# carry a password.
_SECRET_PATTERNS = (
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]+"), "/bot[REDACTED]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[REDACTED]"),
    (re.compile(r"(postgres(?:ql)?(?:\+psycopg)?://[^:/@\s]+):[^@\s]+@"), r"\1:[REDACTED]@"),
)


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
        elif isinstance(event_dict[k], str):
            event_dict[k] = redact_text(event_dict[k])
    return event_dict


def redact_text(text: str) -> str:
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# What names a person or opens a door, as it can turn up inside an error message or a traceback: an email address, an
# IP address, a session token (secrets.token_urlsafe: letters of both cases and digits) and a long hex digest. Function
# names, paths, line numbers and versions are left alone (plan UX, A1: the trace of an unexpected error is logged).
_PERSONAL_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), "<email>"),
    (re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"), "<ip>"),
    (re.compile(r"(?<![\w:.])(?=[0-9A-Fa-f:]*::|(?:[0-9A-Fa-f]{1,4}:){3})"
                r"[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?<=[0-9A-Fa-f])(?![\w:])"), "<ip>"),
    (re.compile(r"(?<![\w-])(?=[\w-]*\d)(?=[\w-]*[A-Z])(?=[\w-]*[a-z])[\w-]{32,}(?![\w-])"), "<token>"),
    (re.compile(r"(?<![\w-])[0-9a-f]{32,}(?![\w-])"), "<hex>"),
)


def scrub_personal(text: str) -> str:
    """The text without credentials (redact_text) and without personal data: what an error may carry before it is
    written to a log."""
    text = redact_text(text)
    for pattern, replacement in _PERSONAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def configure(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # httpx logs every request URL at INFO. A Telegram bot token is in the URL
    # path, so those lines never reach the log: warnings and errors only.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
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
