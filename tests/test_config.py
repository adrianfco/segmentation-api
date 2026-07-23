from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"

REQUIRED = {
    "database_url": "postgresql+psycopg://user:pw-that-must-not-leak@localhost:5432/postgres",
    "supabase_url": "https://example.supabase.co/",
    "supabase_service_role_key": "service-role-key",
}


def build(**overrides: object) -> Settings:
    """Construct Settings hermetically, ignoring any .env on disk."""
    return Settings(_env_file=None, **{**REQUIRED, **overrides})


def test_defaults_apply_when_optional_vars_absent():
    settings = build()

    assert settings.app_env == "development"
    assert settings.log_level == "INFO"
    assert settings.supabase_storage_bucket == "segmentation"
    assert settings.worker_concurrency == 2
    assert settings.max_upload_size_mb == 10


def test_required_fields_are_enforced():
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_numeric_values_coerce_from_strings():
    settings = build(worker_concurrency="5", max_upload_size_mb="25")

    assert settings.worker_concurrency == 5
    assert settings.max_upload_size_mb == 25


@pytest.mark.parametrize("value", [0, -1, 65])
def test_worker_concurrency_must_be_within_bounds(value):
    with pytest.raises(ValidationError):
        build(worker_concurrency=value)


@pytest.mark.parametrize("value", [0, 51])
def test_max_upload_size_must_be_within_bounds(value):
    with pytest.raises(ValidationError):
        build(max_upload_size_mb=value)


def test_invalid_app_env_is_rejected():
    with pytest.raises(ValidationError):
        build(app_env="staging")


def test_invalid_log_level_is_rejected():
    with pytest.raises(ValidationError):
        build(log_level="TRACE")


@pytest.mark.parametrize(
    "value",
    ["not-a-url", "mysql://user:pw@localhost:3306/db", ""],
)
def test_malformed_database_url_is_rejected(value):
    with pytest.raises(ValidationError):
        build(database_url=value)


def test_malformed_supabase_url_is_rejected():
    with pytest.raises(ValidationError):
        build(supabase_url="not-a-url")


def test_database_url_str_round_trips_the_connection_string():
    assert build().database_url_str == REQUIRED["database_url"]


def test_secrets_are_masked_when_settings_are_serialized():
    """Guards against leaking the DB password or service key into logs."""
    settings = build()
    dumped = settings.model_dump_json()

    assert "pw-that-must-not-leak" not in dumped
    assert "service-role-key" not in dumped
    assert "pw-that-must-not-leak" not in repr(settings)
    assert "service-role-key" not in repr(settings)


def test_max_upload_size_bytes_is_derived():
    assert build(max_upload_size_mb=10).max_upload_size_bytes == 10 * 1024 * 1024


def test_env_example_is_a_loadable_template(monkeypatch):
    """.env.example must stay valid, so `cp .env.example .env` boots the app.

    Tightening a field type is the usual way this breaks.
    """
    for key in Settings.model_fields:
        monkeypatch.delenv(key.upper(), raising=False)

    settings = Settings(_env_file=ENV_EXAMPLE)

    assert settings.app_env == "development"
    assert settings.supabase_storage_bucket == "segmentation"


def test_get_settings_reads_environment_and_caches(monkeypatch):
    for key, value in REQUIRED.items():
        monkeypatch.setenv(key.upper(), value)
    monkeypatch.setenv("WORKER_CONCURRENCY", "7")

    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.worker_concurrency == 7
        assert settings is get_settings()
    finally:
        get_settings.cache_clear()
