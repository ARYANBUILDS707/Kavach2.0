"""Explicit environment configuration without requiring unused service secrets."""

import ipaddress
import json
import re
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

MIN_SECRET_LENGTH = 32
KEY_VERSION = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
LOOPBACK_HOSTS = {"localhost"}


def is_loopback(host: str) -> bool:
    if host in LOOPBACK_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Settings(BaseSettings):
    """Read process environment; dotenv loading is explicit in the run command."""

    # Validation errors must never echo connection strings or keys.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", hide_input_in_errors=True)

    app_env: Literal["development", "test", "pilot"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr | None = None
    redis_url: SecretStr | None = None

    # Authentication (M2.3). All-or-nothing: setting any of these requires the full group, and
    # the pilot environment always requires it. Without it the auth routes answer 503.
    app_origin: str | None = None
    rate_limit_hmac_key: SecretStr | None = None
    audit_hmac_keys: SecretStr | None = None
    audit_hmac_active_version: str | None = None
    session_idle_minutes: int = Field(default=30, ge=1, le=24 * 60)
    session_max_hours: int = Field(default=8, ge=1, le=24)
    audit_retention_days: int = Field(default=30, ge=1, le=3650)

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

    @field_validator("app_origin")
    @classmethod
    def require_serialized_origin(cls, value: str | None) -> str | None:
        """Accept only the exact form browsers send in the Origin header."""
        if value is None:
            return None
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError:
            raise ValueError("APP_ORIGIN is not a valid origin") from None
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("APP_ORIGIN must be an http or https origin")
        default_port = {"http": 80, "https": 443}[parts.scheme]
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        expected = f"{parts.scheme}://{host}" + (
            f":{port}" if port not in (None, default_port) else ""
        )
        if value != expected:
            raise ValueError(
                "APP_ORIGIN must be scheme://host[:port] with no path or trailing slash"
            )
        return value

    @field_validator("rate_limit_hmac_key")
    @classmethod
    def require_long_rate_limit_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MIN_SECRET_LENGTH:
            raise ValueError(f"RATE_LIMIT_HMAC_KEY must be at least {MIN_SECRET_LENGTH} characters")
        return value

    @field_validator("audit_hmac_keys")
    @classmethod
    def require_versioned_audit_keys(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            parse_audit_keys(value)
        return value

    @model_validator(mode="after")
    def require_complete_auth_configuration(self) -> Self:
        auth_specific = {
            "APP_ORIGIN": self.app_origin,
            "RATE_LIMIT_HMAC_KEY": self.rate_limit_hmac_key,
            "AUDIT_HMAC_KEYS": self.audit_hmac_keys,
            "AUDIT_HMAC_ACTIVE_VERSION": self.audit_hmac_active_version,
        }
        if self.app_env == "pilot" or any(value is not None for value in auth_specific.values()):
            required = auth_specific | {
                "DATABASE_URL": self.database_url,
                "REDIS_URL": self.redis_url,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(f"Authentication requires: {', '.join(missing)}")
        if self.audit_hmac_keys is not None and self.audit_hmac_active_version is not None:
            if self.audit_hmac_active_version not in parse_audit_keys(self.audit_hmac_keys):
                raise ValueError("AUDIT_HMAC_ACTIVE_VERSION is not a key in AUDIT_HMAC_KEYS")
        if self.app_origin is not None and self.app_origin.startswith("http://"):
            host = urlsplit(self.app_origin).hostname or ""
            if self.app_env != "development" or not is_loopback(host):
                raise ValueError("Plain-HTTP APP_ORIGIN is allowed only for local development")
        if self.session_idle_minutes >= self.session_max_hours * 60:
            raise ValueError("SESSION_IDLE_MINUTES must be shorter than SESSION_MAX_HOURS")
        return self

    @property
    def auth_configured(self) -> bool:
        return self.app_origin is not None


def parse_audit_keys(value: SecretStr) -> dict[str, bytes]:
    """AUDIT_HMAC_KEYS is a JSON object mapping key versions to secrets."""
    try:
        raw = json.loads(value.get_secret_value())
    except json.JSONDecodeError:
        raise ValueError("AUDIT_HMAC_KEYS must be a JSON object") from None
    if not isinstance(raw, dict) or not raw:
        raise ValueError("AUDIT_HMAC_KEYS must be a non-empty JSON object")
    keys: dict[str, bytes] = {}
    for version, secret in raw.items():
        if not KEY_VERSION.fullmatch(version):
            raise ValueError("AUDIT_HMAC_KEYS versions must be 1-32 safe characters")
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"Each AUDIT_HMAC_KEYS secret needs {MIN_SECRET_LENGTH}+ characters")
        keys[version] = secret.encode()
    return keys
