"""Configuration split by domain.

The legacy system had a single 538-line dataclass with ~150 parameters from 18
different concerns. Here each concern owns its settings object and validates itself.
"""

from __future__ import annotations

from functools import lru_cache

from .database import DatabaseSettings
from .odds import OddsCaptureSettings
from .providers import ApiFootballSettings
from .runtime import RuntimeSettings

__all__ = [
    "ApiFootballSettings",
    "DatabaseSettings",
    "OddsCaptureSettings",
    "RuntimeSettings",
    "settings",
]


class _Settings:
    """Lazy aggregate so importing a module never forces every env var to exist."""

    @property
    def runtime(self) -> RuntimeSettings:
        return _runtime()

    @property
    def database(self) -> DatabaseSettings:
        return _database()

    @property
    def api_football(self) -> ApiFootballSettings:
        return _api_football()

    @property
    def odds(self) -> OddsCaptureSettings:
        return _odds()


@lru_cache(maxsize=1)
def _runtime() -> RuntimeSettings:
    return RuntimeSettings()


@lru_cache(maxsize=1)
def _database() -> DatabaseSettings:
    # Values come from the environment; pydantic-settings fills them at runtime.
    return DatabaseSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def _api_football() -> ApiFootballSettings:
    return ApiFootballSettings()  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def _odds() -> OddsCaptureSettings:
    return OddsCaptureSettings()


def reset_cache() -> None:
    for fn in (_runtime, _database, _api_football, _odds):
        fn.cache_clear()


settings = _Settings()
