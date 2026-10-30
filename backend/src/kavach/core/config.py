"""Explicit environment configuration without requiring unused service secrets."""

from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    """Read process environment; dotenv loading is explicit in the run command."""

    # Validation errors must never echo connection strings, which carry credentials.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "pilot"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # Optional until a route depends on them (M2.3); when set, they are validated here.
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None

    @field_validator("database_url")
    @classmethod
    def require_psycopg_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("DATABASE_URL is not a valid database URL") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use the postgresql+psycopg scheme")
        if not url.host or not url.database:
            raise ValueError("DATABASE_URL must name a host and a database")
        return value

    @field_validator("redis_url")
    @classmethod
    def require_redis_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = urlsplit(value.get_secret_value())
            has_host = bool(url.hostname)
        except ValueError:
            raise ValueError("REDIS_URL is not a valid URL") from None
        if url.scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use the redis or rediss scheme")
        if not has_host:
            raise ValueError("REDIS_URL must name a host")
        return value
