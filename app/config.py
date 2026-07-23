from functools import lru_cache
from typing import Literal

from pydantic import Field, HttpUrl, PostgresDsn, Secret, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_BYTES_PER_MB = 1024 * 1024


class Settings(BaseSettings):
    """Load and validate .env environment variables"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="forbid")

    # Application
    app_env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Database
    database_url: Secret[PostgresDsn]

    # Supabase Storage
    supabase_url: HttpUrl
    supabase_service_role_key: SecretStr
    supabase_storage_bucket: str = Field(default="segmentation", min_length=1)

    # Workers
    worker_concurrency: int = Field(default=2, ge=1, le=64)

    # Uploads
    max_upload_size_mb: int = Field(default=10, ge=1, le=50)

    @property
    def database_url_str(self) -> str:
        return str(self.database_url.get_secret_value())

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * _BYTES_PER_MB


@lru_cache
def get_settings() -> Settings:
    return Settings()
