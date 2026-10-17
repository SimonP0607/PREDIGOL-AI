from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FBI_", env_file=".env", extra="ignore")

    database_url: str = Field(...)
    echo_sql: bool = Field(default=False)
    pool_size: int = Field(default=5, ge=1, le=50)

    @field_validator("database_url")
    @classmethod
    def _must_be_postgres(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("FBI_DATABASE_URL must be a PostgreSQL URL")
        return v

    def __repr__(self) -> str:  # never leak the password
        return f"DatabaseSettings(database_url='{self.masked_url}', pool_size={self.pool_size})"

    __str__ = __repr__

    @property
    def psycopg_url(self) -> str:
        """The plain libpq URL. SQLAlchemy's +psycopg dialect marker is not
        understood by psycopg.connect()."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")

    @property
    def masked_url(self) -> str:
        url = self.database_url
        if "@" not in url or "//" not in url:
            return url
        scheme, rest = url.split("//", 1)
        creds, host = rest.split("@", 1)
        user = creds.split(":", 1)[0]
        return f"{scheme}//{user}:[SECRETO DETECTADO — NO MOSTRADO]@{host}"
