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


# What names a person or opens a door, as it can turn up inside an error message or a traceback: a byte string, a
# password hash, an email address (any script), an IP address, a session token (secrets.token_urlsafe: letters of
# both cases, digits mostly) and a long hex digest. Function names, paths, line numbers and versions are left alone
# (plan UX, A1: the trace of an unexpected error is logged).
_PERSONAL_PATTERNS = (
    (re.compile(r"""\bb(?:'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*")"""), "<bytes>"),
    (re.compile(r"\$argon2(?:id|i|d)\$[^\s'\"]*"), "<hash>"),
    (re.compile(r"[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}"), "<email>"),
    (re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])"), "<ip>"),
    (re.compile(r"(?<![\w:.])(?=[0-9A-Fa-f:]*::|(?:[0-9A-Fa-f]{1,4}:){3})"
                r"[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?<=[0-9A-Fa-f])(?![\w:])"), "<ip>"),
    (re.compile(r"(?<![\w-])(?=[\w-]*[A-Z])(?=[\w-]*[a-z])[\w-]{32,}(?![\w-])"), "<token>"),
    (re.compile(r"(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])"), "<hex>"),
)


# A value quoted inside a message - Python's own repr ('...') or a library's ("...") - is what a caller passed: int()
# and float() quote the text they could not read, fromisoformat() the date, a KeyError the key (third review of A1).
_QUOTED = re.compile(r"'(?:[^'\\\n]|\\.)*'" r'|"(?:[^"\\\n]|\\.)*"')
_FIRST_LINE_MAX = 1000
"""A message is cut BEFORE the filter runs: the filter's patterns over a 16 KB line cost more than a second."""


def scrub_personal(text: str) -> str:
    """The text without credentials (redact_text) and without personal data: what an error may carry before it is
    written to a log."""
    text = redact_text(text)
    for pattern, replacement in _PERSONAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def error_summary(exc: BaseException) -> str:
    """What an unexpected error says, safe for a log (plan UX, A1; reviews of A1), at most 300 characters:

    - a validation error (pydantic, FastAPI): where it failed and how - the fields and the kinds of error - never the
      input it was given;
    - a database error (psycopg): its SQLSTATE and the constraint, table and column it names - never the values its
      messages quote;
    - a group of errors: how many, and their types;
    - a KeyError: nothing - its message is the key it did not find;
    - any other: the first line of its message - the lines after it are where libraries put the data - with every
      quoted value replaced by <value>, through the filter of personal data (third review of A1: int() and float()
      quote the text they could not read, fromisoformat() the date).
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            found = errors()
        except Exception:  # an error that cannot say its errors falls back to its first line
            found = None
        if isinstance(found, list) and all(isinstance(e, dict) and "loc" in e for e in found):
            where = "; ".join(f"{'.'.join(str(x) for x in e['loc']) or '-'} ({e.get('type', '?')})" for e in found[:10])
            return scrub_personal(f"{len(found)} validation error(s): {where}"[:_FIRST_LINE_MAX])[:300]
    sqlstate = getattr(exc, "sqlstate", None)
    diag = getattr(exc, "diag", None)
    if isinstance(sqlstate, str) and diag is not None:
        parts = [f"sqlstate {sqlstate}"]
        for label in ("schema_name", "table_name", "column_name", "constraint_name"):
            value = getattr(diag, label, None)
            if value:
                parts.append(f"{label.removesuffix('_name')} {value}")
        return scrub_personal(", ".join(parts))[:300]
    if isinstance(exc, BaseExceptionGroup):
        kinds = ", ".join(type(e).__name__ for e in exc.exceptions[:10])
        return f"{len(exc.exceptions)} errors: {kinds}"[:300]
    if isinstance(exc, KeyError):
        return ""
    text = str(exc).strip()
    first = text.splitlines()[0][:_FIRST_LINE_MAX] if text else ""
    return scrub_personal(_QUOTED.sub("<value>", first))[:300]


def error_trace(exc: BaseException) -> str:
    """Where an unexpected error came from, safe for a log: the frames (file, line, function, the source line) and
    the types - never a message's data or a frame's values - through the filter of personal data. Each link of the
    chain of causes keeps its own end (the frames nearest the error), within 6,000 characters in all."""
    import traceback

    chain: list[BaseException] = []
    link: BaseException | None = exc
    while link is not None and link not in chain and len(chain) < 4:
        chain.append(link)
        link = link.__cause__ or link.__context__
    budget = 6000 // len(chain)
    parts = []
    for link in reversed(chain):
        frames = "".join(traceback.format_tb(link.__traceback__))[-(budget - 80):]
        role = "" if link is exc else " (a cause)"
        parts.append(f"{frames}{type(link).__name__}{role}")
    return scrub_personal("\n".join(parts))[-6000:]


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
