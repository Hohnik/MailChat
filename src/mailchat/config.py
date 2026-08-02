from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    # `extra="ignore"` because the .env also carries scratch values (mailbox
    # login/password) that aren't settings; without it they'd fail validation.
    # Real environment variables still win over the file.
    model_config = SettingsConfigDict(
        env_prefix="MAILCHAT_", env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "sqlite+aiosqlite:///./mailchat.db"
    credentials_master_key: str
    sync_poll_interval_seconds: float = 60.0


@lru_cache
def get_settings() -> Settings:
    """The configuration, read once and on first use rather than at import.
    Importing a module therefore never demands an environment — only starting
    the app, or reaching for the master key, does.
    """
    return Settings()  # pyright: ignore[reportCallIssue] — fields are populated from the environment
