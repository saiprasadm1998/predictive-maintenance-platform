"""Settings from PMP_* variables (ARC-001 §10.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from pmp.core import LogFormat, Settings
from pmp.core.config import BACKEND_DIR

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
    assert settings.scoring_grace_s == 5  # AC-05: one cycle plus 5 s (plan 6.7)
    assert settings.late_data_days == 7
    assert settings.retention_months == 24
    assert settings.artefact_dir == Path("/data/artefacts")
    assert settings.log_level == "INFO"
    assert settings.log_format is LogFormat.JSON


def test_environment_overrides_defaults(env: pytest.MonkeyPatch) -> None:
    env.setenv("PMP_SCORING_GRACE_S", "30")
    env.setenv("PMP_LOG_FORMAT", "text")
    settings = _settings()
    assert settings.scoring_grace_s == 30
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


def test_backend_env_file_is_found_from_any_folder() -> None:
    env_files = Settings.model_config["env_file"]
    assert isinstance(env_files, tuple)
    assert env_files[0] == BACKEND_DIR / ".env"
    assert (BACKEND_DIR / "pyproject.toml").exists()


def test_relative_artefact_dir_is_anchored_to_the_backend_folder(
    env: pytest.MonkeyPatch,
) -> None:
    env.setenv("PMP_ARTEFACT_DIR", "./.artefacts")
    assert _settings().artefact_dir == BACKEND_DIR / ".artefacts"
    env.setenv("PMP_ARTEFACT_DIR", "/data/artefacts")
    assert _settings().artefact_dir == Path("/data/artefacts")
