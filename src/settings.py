"""Every environment variable the API reads, declared once.

Loaded from `.env` at the working directory (the repository root) so `uv run uvicorn src.main:app`
and `docker compose` see the same values. `BRANDS` accepts a comma-separated string or a JSON list.
"""

import json
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    APP_NAME: str = "alert-bot-demo"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # Brands this instance serves. Each has its own `alert_bot_<brand>` database; the checker rows of
    # every brand share `alert_bot_system.checkers_configs`.
    BRANDS: Annotated[list[str], NoDecode] = []

    # The Bearer token cadmin sends on every admin call. Empty refuses every admin call (403).
    ADMIN_API_SECRET_KEY: str = ""

    MONGO_URI: str = "mongodb://localhost:27017"

    # Seed demo rows for a brand that has none yet. A production service would leave that to
    # operators; this one does it, because an empty demo shows nothing.
    SEED_ON_STARTUP: bool = True

    @field_validator("BRANDS", mode="before")
    @classmethod
    def _parse_brands(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                value = json.loads(text)
            else:
                value = text.split(",")
        return [str(brand).strip().upper() for brand in value if str(brand).strip()]


settings = Settings()
