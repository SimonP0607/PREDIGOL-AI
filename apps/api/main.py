"""Entry point: ``uvicorn apps.api.main:app``. The application lives in fbi.api."""

from __future__ import annotations

from fbi.api.app import create_app
from fbi.core import sentry

sentry.init("api")  # only with FBI_SENTRY_DSN set
app = create_app()
