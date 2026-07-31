from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MAILCHAT_")

    database_url: str = "sqlite+aiosqlite:///./mailchat.db"
    credentials_master_key: str


settings = Settings()  # pyright: ignore[reportCallIssue] — fields are populated from the environment
