"""Configuration from PMP_* environment variables (ARC-001 §10.2, NFR-MAIN-02).

Values come from the environment, or from a `.env` file in the working directory
for local development. Secrets are held as SecretStr so they never appear in logs
or reprs.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class LogFormat(StrEnum):
    JSON = "json"
    TEXT = "text"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PMP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr
    secret_key: SecretStr
    artefact_dir: Path = Path("/data/artefacts")
    scoring_grace_s: int = Field(default=20, ge=0)
    late_data_days: int = Field(default=7, ge=0)
    retention_months: int = Field(default=24, ge=1)
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1, le=65535)


@lru_cache
def get_settings() -> Settings:
    """Settings for this process, read once."""
    return Settings()  # values come from the environment
