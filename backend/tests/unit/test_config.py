"""Settings from PMP_* variables (ARC-001 §10.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pmp.core import LogFormat, Settings

REQUIRED = {
    "PMP_DATABASE_URL": "postgresql+psycopg://u:secret-db-pw@localhost/db",
    "PMP_SECRET_KEY": "secret-key-value",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def _settings() -> Settings:
    return Settings(_env_file=None)


def test_defaults_match_the_architecture(env: pytest.MonkeyPatch) -> None:
    settings = _settings()
    assert settings.scoring_grace_s == 20
    assert settings.late_data_days == 7
    assert settings.retention_months == 24
    assert settings.artefact_dir == Path("/data/artefacts")
    assert settings.log_level == "INFO"
    assert settings.log_format is LogFormat.JSON


def test_environment_overrides_defaults(env: pytest.MonkeyPatch) -> None:
    env.setenv("PMP_SCORING_GRACE_S", "5")
    env.setenv("PMP_LOG_FORMAT", "text")
    settings = _settings()
    assert settings.scoring_grace_s == 5
    assert settings.log_format is LogFormat.TEXT


def test_missing_required_settings_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in REQUIRED:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError) as error:
        _settings()
    message = str(error.value)
    assert "database_url" in message
    assert "secret_key" in message


def test_invalid_values_are_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("PMP_RETENTION_MONTHS", "0")
    with pytest.raises(ValidationError):
        _settings()


def test_secrets_never_appear_in_repr(env: pytest.MonkeyPatch) -> None:
    text = repr(_settings())
    assert "secret-db-pw" not in text
    assert "secret-key-value" not in text
