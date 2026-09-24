"""Entry point: ``uvicorn apps.api.main:app``. The application lives in fbi.api."""

from __future__ import annotations

from fbi.api.app import create_app

app = create_app()
