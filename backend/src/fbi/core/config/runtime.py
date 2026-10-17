from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FBI_", env_file=".env", extra="ignore")

    env: str = Field(default="local")
    log_level: str = Field(default="INFO")
    raw_store_dir: str = Field(default="data/raw")

    @property
    def is_test(self) -> bool:
        return self.env == "test"
