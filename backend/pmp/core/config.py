"""Configuration from PMP_* environment variables (ARC-001 §10.2, NFR-MAIN-02).

Values come from the environment, or for local development from `backend/.env`
(found wherever a command is run from) or a `.env` in the working directory, which wins.
A relative PMP_ARTEFACT_DIR is taken relative to the backend folder. Secrets are held
as SecretStr so they never appear in logs or reprs.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class LogFormat(StrEnum):
    JSON = "json"
    TEXT = "text"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PMP_",
        env_file=(BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr
    secret_key: SecretStr
    artefact_dir: Path = Path("/data/artefacts")
    scoring_grace_s: int = Field(default=20, ge=0)
    late_data_days: int = Field(default=7, ge=0)
    ingest_rate_limit: float = Field(default=50.0, gt=0)  # requests per second per API key
    backfill_max_mb: int = Field(default=2048, ge=1)  # largest history file accepted
    retention_months: int = Field(default=24, ge=1)
    alert_max_shelve_days: int = Field(default=7, ge=1)  # UCS §6.6: configurable maximum
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.JSON
    web_host: str = "127.0.0.1"
    web_port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("artefact_dir")
    @classmethod
    def _anchor_relative_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else BACKEND_DIR / value


@lru_cache
def get_settings() -> Settings:
    """Settings for this process, read once."""
    return Settings()  # values come from the environment
