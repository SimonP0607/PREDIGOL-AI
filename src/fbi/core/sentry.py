"""Errors of the API and the worker to Sentry (the free Developer plan) - only when FBI_SENTRY_DSN is set.

What leaves the server is the error: its type, message and stack trace, the endpoint, the release. Never what a
person sent or is: no cookies, no request bodies (the sign-in form carries a password), no IP, no user, and no local
variables (a frame can hold a key or a token). No performance tracing.

    FBI_SENTRY_DSN           empty = off (the default)
    FBI_SENTRY_ENVIRONMENT   default FBI_ENV (production on the server)
"""

from __future__ import annotations

import os
from typing import Any

from fbi.core.version import code_version


def options(component: str) -> dict[str, Any] | None:
    dsn = os.environ.get("FBI_SENTRY_DSN", "").strip()
    if not dsn:
        return None
    return {
        "dsn": dsn,
        "environment": os.environ.get("FBI_SENTRY_ENVIRONMENT") or os.environ.get("FBI_ENV") or "development",
        "release": f"predigol-backend@{code_version()}",
        "server_name": component,  # "api" or "worker", not the host's name
        "send_default_pii": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "traces_sample_rate": 0.0,
        "profiles_sample_rate": 0.0,
        "attach_stacktrace": False,
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
