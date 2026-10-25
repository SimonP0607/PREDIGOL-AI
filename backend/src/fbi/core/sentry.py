"""Errors of the API, the worker and the web to Sentry (the free Developer plan) - only when a DSN is set.

What leaves the server is the error: its type, a summary of its message without values, its frames, the endpoint,
the release, the request id and - for a signed-in account - a pseudonym (an HMAC of the account's id under the
server's key, fbi.auth.crypto.observability_id), never the id itself. Never what a person sent or is: no cookies, no
request bodies or query strings (the sign-in form carries a password), no headers but the browser's name, no IP, no
email, and no local variables (a frame can hold a key or a token). No performance tracing, no session replay.

Every event and every breadcrumb goes through ``scrub_event`` / ``scrub_breadcrumb`` before it is sent (plan UX,
A2): the filter of personal data and credentials of fbi.core.logging, quoted values replaced, and the fields where
libraries put request data dropped. The browser's events take the same filter on the server, which forwards them
(fbi.api.routers.monitoring: the browser never talks to Sentry itself).

    FBI_SENTRY_DSN           the backend project; empty = off (the default)
    FBI_SENTRY_WEB_DSN       the web project, served to the browser and checked on every event it sends; empty = off
    FBI_SENTRY_ENVIRONMENT   default FBI_ENV (production on the server)
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Mapping, MutableMapping
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fbi.core.logging import scrub_value
from fbi.core.version import code_version

USER_ID = re.compile(r"[0-9a-f]{20}")
"""The shape of fbi.auth.crypto.observability_id: anything else in an event's user is dropped."""

_SENSITIVE = re.compile(
    r"(pass(word|wd)?|secret|token|cookie|authori[sz]ation|session|e-?mail|phone|dsn|csrf|totp|otp|recovery|"
    r"api[-_]?key|x-forwarded-for|x-real-ip|remote[-_]addr|ip[-_]?addr(ess)?|^ip$|^key$|^code$|^body$|^data$)",
    re.IGNORECASE)
"""Keys whose values are never sent, whatever they hold."""

DROPPED_BREADCRUMBS = frozenset({"query", "console", "ui.click", "ui.input", "ui.keypress", "sentry.event"})
"""SQL (it can carry literals), console lines and what a person clicked or typed: never sent."""

KEPT_HTTP_DATA = ("method", "status_code", "url", "reason")
_DEPTH = 6


def environment() -> str:
    return os.environ.get("FBI_SENTRY_ENVIRONMENT") or os.environ.get("FBI_ENV") or "development"


def web_dsn() -> str | None:
    """The web project's DSN (public by design: it goes to the browser), or None when the web reports nothing."""
    dsn = os.environ.get("FBI_SENTRY_WEB_DSN", "").strip()
    return dsn or None


def options(component: str) -> dict[str, Any] | None:
    dsn = os.environ.get("FBI_SENTRY_DSN", "").strip()
    if not dsn:
        return None
    return {
        "dsn": dsn,
        "environment": environment(),
        "release": f"predigol-backend@{code_version()}",
        "server_name": component,  # "api" or "worker", not the host's name
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "traces_sample_rate": 0.0,
        "profiles_sample_rate": 0.0,
        "attach_stacktrace": False,
        "max_breadcrumbs": 30,
        "send_client_reports": False,
        "before_send": scrub_event,
        "before_breadcrumb": scrub_breadcrumb,
    }


def init(component: str) -> bool:
    """True when Sentry was switched on. Never fails the caller: errors reporting is not worth a crash."""
    opts = options(component)
    if opts is None:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(**opts)
        sentry_sdk.set_tag("component", component)
    except Exception:  # a broken DSN or SDK must not stop the API or the worker
        return False
    return True


def enabled() -> bool:
    try:
        import sentry_sdk

        return bool(sentry_sdk.is_initialized())
    except Exception:
        return False


# ── the filter ──────────────────────────────────────────────────────────────────────────────────────────────


def clean_url(url: object) -> str | None:
    """A URL without its query string, its fragment and any user:password - where a request carries its data."""
    if not isinstance(url, str) or not url:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    netloc = parts.netloc.rsplit("@", 1)[-1]
    return scrub_value(urlunsplit((parts.scheme, netloc, parts.path, "", "")), limit=500)


def _clean(value: Any, depth: int = 0) -> Any:
    """Strings through the filter, sensitive keys out, at most _DEPTH levels deep."""
    if depth > _DEPTH:
        return None
    if isinstance(value, str):
        return scrub_value(value)
    if isinstance(value, Mapping):
        return {str(k): _clean(v, depth + 1) for k, v in value.items() if not _SENSITIVE.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [_clean(v, depth + 1) for v in value[:50]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return scrub_value(str(value))


def _clean_frames(stacktrace: Any) -> None:
    if not isinstance(stacktrace, MutableMapping):
        return
    frames = stacktrace.get("frames")
    if not isinstance(frames, list):
        return
    for frame in frames:
        if not isinstance(frame, MutableMapping):
            continue
        frame.pop("vars", None)
        # source lines: code, not data - the filter of personal data, but quoted text stays readable
        if isinstance(frame.get("context_line"), str):
            frame["context_line"] = scrub_value(frame["context_line"], limit=300, quoted=False)
        for key in ("pre_context", "post_context"):
            if isinstance(frame.get(key), list):
                frame[key] = [scrub_value(str(line), limit=300, quoted=False) for line in frame[key][:5]]


def _clean_request(request: Any, *, keep_agent: bool) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        return {}
    out: dict[str, Any] = {}
    if isinstance(request.get("method"), str):
        out["method"] = request["method"][:10]
    url = clean_url(request.get("url"))
    if url:
        out["url"] = url
    headers = request.get("headers")
    if keep_agent and isinstance(headers, Mapping):
        agent = next((v for k, v in headers.items() if str(k).lower() == "user-agent"), None)
        if isinstance(agent, str):
            out["headers"] = {"User-Agent": agent[:300]}
    return out


def scrub_event(event: dict[str, Any], hint: Any = None, *, keep_agent: bool = True) -> dict[str, Any] | None:
    """The event as it may leave the server (``before_send``). Never raises: an event the filter cannot read is
    dropped rather than sent as it came."""
    try:
        return _scrub_event(event, keep_agent=keep_agent)
    except Exception:
        return None


def _scrub_event(event: dict[str, Any], *, keep_agent: bool) -> dict[str, Any]:
    if "request" in event:
        event["request"] = _clean_request(event.get("request"), keep_agent=keep_agent)
    user = event.get("user")
    if isinstance(user, Mapping) and isinstance(user.get("id"), str) and USER_ID.fullmatch(user["id"]):
        event["user"] = {"id": user["id"]}
    else:
        event.pop("user", None)
    for holder in ("exception", "threads"):
        values = (event.get(holder) or {}).get("values") if isinstance(event.get(holder), Mapping) else None
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, MutableMapping):
                continue
            if holder == "exception":
                if item.get("type") in ("KeyError",):
                    item["value"] = ""
                elif isinstance(item.get("value"), str):
                    item["value"] = scrub_value(item["value"])
                mechanism = item.get("mechanism")
                if isinstance(mechanism, MutableMapping):
                    mechanism.pop("data", None)
            _clean_frames(item.get("stacktrace"))
    logentry = event.get("logentry")
    if isinstance(logentry, MutableMapping):
        message = logentry.get("message") or logentry.get("formatted")
        event["logentry"] = {"message": scrub_value(str(message or ""))}
    if isinstance(event.get("message"), str):
        event["message"] = scrub_value(event["message"])
    crumbs = event.get("breadcrumbs")
    values = crumbs.get("values") if isinstance(crumbs, Mapping) else crumbs
    if isinstance(values, list):
        kept = [c for c in (scrub_breadcrumb(dict(v)) for v in values if isinstance(v, Mapping)) if c is not None]
        event["breadcrumbs"] = {"values": kept}
    for key in ("extra", "contexts", "tags"):
        if key in event:
            event[key] = _clean(event[key])
    for key in ("cookies", "server_name_full", "spans", "_meta"):
        event.pop(key, None)
    return event


def scrub_breadcrumb(crumb: dict[str, Any], hint: Any = None) -> dict[str, Any] | None:
    """A breadcrumb as it may leave (``before_breadcrumb``): SQL, console lines and clicks never; a request's
    method, status and address without its query string; any other text through the filter."""
    try:
        category = str(crumb.get("category") or "")
        if category in DROPPED_BREADCRUMBS:
            return None
        out: dict[str, Any] = {k: crumb[k] for k in ("timestamp", "type", "category", "level") if k in crumb}
        if isinstance(crumb.get("message"), str):
            out["message"] = scrub_value(crumb["message"])
        data = crumb.get("data")
        if isinstance(data, Mapping):
            if crumb.get("type") == "http" or category in ("httplib", "fetch", "xhr", "http"):
                kept = {k: data[k] for k in KEPT_HTTP_DATA if k in data}
                if "url" in kept:
                    kept["url"] = clean_url(kept["url"])
                out["data"] = _clean(kept)
            elif category == "navigation":
                out["data"] = {k: clean_url(data.get(k)) for k in ("from", "to") if data.get(k)}
            else:
                out["data"] = _clean(data)
        return out
    except Exception:
        return None


# ── reporting ───────────────────────────────────────────────────────────────────────────────────────────────


def capture_exception(exc: BaseException, *, user: str | None = None, **tags: str | None) -> str | None:
    """Report an error the caller handled (the API's last line of defence answers 500 and calls this), with its
    tags (request_id, path, ...) and the account's pseudonym. The event id, or None when Sentry is off. Never
    raises."""
    if not enabled():
        return None
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            for key, value in tags.items():
                if value:
                    scope.set_tag(key, str(value)[:200])
            if user and USER_ID.fullmatch(user):
                scope.set_user({"id": user})
            return sentry_sdk.capture_exception(exc)
    except Exception:
        return None


class _ReportLimit:
    """At most one report of the same log event every ``gap_s`` seconds and ``per_hour`` reports an hour, per
    process: a noisy error must not spend the plan's month (5,000 errors) in a day."""

    def __init__(self, *, gap_s: float = 600.0, per_hour: int = 60) -> None:
        self._gap = gap_s
        self._per_hour = per_hour
        self._last: dict[str, float] = {}
        self._hour: list[float] = []
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            self._hour = [s for s in self._hour if t - s < 3600.0]
            if len(self._hour) >= self._per_hour or t - self._last.get(key, -1e18) < self._gap:
                return False
            self._last[key] = t
            self._hour.append(t)
            if len(self._last) > 1000:
                self._last = {k: v for k, v in self._last.items() if t - v < self._gap}
            return True


ERROR_LOGS = _ReportLimit()
CAPTURED_ELSEWHERE = frozenset({"api.unhandled"})
"""Log events whose error is reported with its exception where it happens (fbi.api.app._contain)."""
_LOG_FIELDS = ("job", "job_type", "logger", "component", "status", "step", "path", "method", "error", "run_id",
               "request_id")


def report_error_logs(logger: Any, method_name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """A structlog processor: an error the code logged and handled (the worker's jobs catch their own: a failing
    pass must not stop the capture) is also a Sentry event - its name, its job and a few short fields through the
    filter. Without Sentry, or past the limit, it does nothing. Never raises, never changes the log line."""
    if method_name not in ("error", "critical", "exception"):
        return event_dict
    try:
        name = str(event_dict.get("event", ""))
        if not name or name in CAPTURED_ELSEWHERE or not enabled() or not ERROR_LOGS.allow(name):
            return event_dict
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("log_event", name[:120])
            for key in _LOG_FIELDS:
                value = event_dict.get(key)
                if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                    scope.set_extra(key, scrub_value(str(value), limit=300))
            sentry_sdk.capture_message(name[:200], level="fatal" if method_name == "critical" else "error")
    except Exception:
        pass
    return event_dict
