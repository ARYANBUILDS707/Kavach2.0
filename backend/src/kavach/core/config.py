"""Explicit environment configuration without requiring unused service secrets."""

import ipaddress
import json
import re
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

MIN_SECRET_LENGTH = 32
SMS_COMMIT_RESERVE_SECONDS = 2.0  # kept free for the commit after inference (design §6.2)
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
    # Only the operator retention command uses this (kavach_retention role).
    retention_database_url: SecretStr | None = None
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

    # Event ingestion (M3.1). All-or-nothing like authentication, which it requires; pilot
    # requires it. Key maps use the AUDIT_HMAC_KEYS format: {"<version>": "<32+ chars>"}.
    subscriber_hmac_keys: SecretStr | None = None
    subscriber_hmac_active_version: str | None = None
    payload_hmac_keys: SecretStr | None = None
    payload_hmac_active_version: str | None = None
    event_retention_days: int = Field(default=7, ge=1, le=3650)
    # Total ingestion deadline in seconds (API.md INFERENCE_TIMEOUT_SECONDS; D08: 30).
    inference_timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    # Pretrained SMS worker (M4-I.2, docs/M4_SMS_INFERENCE_ARCHITECTURE.md §10). Off by default:
    # without it every SMS is stored with the classifier stage unavailable (model_not_deployed).
    # When enabled, the three paths are required and must be absolute; the worker runs from its
    # own environment, offline, on CPU only.
    sms_worker_enabled: bool = False
    sms_worker_python: Path | None = None
    sms_worker_lock_path: Path | None = None
    model_dir: Path | None = None
    model_manifest_path: Path | None = None
    max_inflight_analyses: int = Field(default=2, ge=1, le=2)
    sms_inference_timeout_ms: int = Field(default=2000, ge=100, le=10_000)
    sms_worker_threads: int = Field(default=2, ge=1, le=8)
    sms_worker_max_rss_mb: int = Field(default=1536, ge=512, le=8192)
    sms_worker_start_timeout_seconds: float = Field(default=90.0, ge=10, le=600)
    inference_device: Literal["cpu"] = "cpu"
    # Why the worker may run at all. M4-Q has no GO verdict (preflight NOT READY, 12 Nov 2026), so
    # the only accepted value is the owner-authorized local experiment (decision C-13):
    # development on a loopback origin only. It changes nothing the model returns: native outputs
    # stay uncalibrated, sms_score null and the tier unknown.
    sms_model_authorization: Literal["experimental-local-unvalidated"] | None = None

    # Anonymous analyzer: disabled by default. C-13 permits local fictional tests only.
    # Hosted mode and its reserved approval token remain blocked until C-15 is approved.
    public_analyzer_only: bool = False
    public_frontend_dir: Path | None = None
    public_analyzer_mode: Literal["disabled", "local-experimental", "hosted"] = "disabled"
    public_analyzer_hosted_approval: Literal["c15-owner-approved"] | None = None
    public_analyzer_max_chars: int = Field(default=500, ge=1, le=4096)
    public_analyzer_ip_limit_per_minute: int = Field(default=5, ge=1, le=600)
    public_analyzer_global_limit_per_minute: int = Field(default=60, ge=1, le=6000)

    @field_validator("database_url", "retention_database_url")
    @classmethod
    def require_psycopg_database_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        try:
            url = make_url(value.get_secret_value())
        except ArgumentError:
            raise ValueError("Database URLs must be valid database URLs") from None
        if url.drivername != "postgresql+psycopg":
            raise ValueError("Database URLs must use the postgresql+psycopg scheme")
        if not url.host or not url.database:
            raise ValueError("Database URLs must name a host and a database")
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

    @field_validator("audit_hmac_keys", "subscriber_hmac_keys", "payload_hmac_keys")
    @classmethod
    def require_versioned_keys(
        cls, value: SecretStr | None, info: ValidationInfo
    ) -> SecretStr | None:
        if value is not None:
            parse_key_map(value, (info.field_name or "").upper())
        return value

    @model_validator(mode="after")
    def require_complete_auth_configuration(self) -> Self:
        # C-15 remains unapproved: even an operator-supplied token cannot enable hosting.
        if self.public_analyzer_mode == "hosted":
            raise ValueError("Hosted inference is blocked pending C-15 and release-gate approval")
        if self.sms_worker_lock_path is not None and not self.sms_worker_lock_path.is_absolute():
            raise ValueError("SMS_WORKER_LOCK_PATH must be absolute")
        if self.public_frontend_dir is not None:
            if not self.public_analyzer_only or not self.public_frontend_dir.is_absolute():
                raise ValueError(
                    "PUBLIC_FRONTEND_DIR requires public-only mode and an absolute path"
                )
            if not (self.public_frontend_dir / "index.html").is_file():
                raise ValueError("PUBLIC_FRONTEND_DIR requires a built frontend")
        if self.public_analyzer_only:
            private_settings = (
                self.database_url,
                self.retention_database_url,
                self.audit_hmac_keys,
                self.audit_hmac_active_version,
                self.subscriber_hmac_keys,
                self.subscriber_hmac_active_version,
                self.payload_hmac_keys,
                self.payload_hmac_active_version,
            )
            if any(value is not None for value in private_settings):
                raise ValueError(
                    "Public-only service must not have database or admin configuration"
                )
        auth_specific = {
            "APP_ORIGIN": self.app_origin,
            "RATE_LIMIT_HMAC_KEY": self.rate_limit_hmac_key,
            "AUDIT_HMAC_KEYS": self.audit_hmac_keys,
            "AUDIT_HMAC_ACTIVE_VERSION": self.audit_hmac_active_version,
        }
        if not self.public_analyzer_only and (
            self.app_env == "pilot" or any(value is not None for value in auth_specific.values())
        ):
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
        ingestion = {
            "SUBSCRIBER_HMAC_KEYS": self.subscriber_hmac_keys,
            "SUBSCRIBER_HMAC_ACTIVE_VERSION": self.subscriber_hmac_active_version,
            "PAYLOAD_HMAC_KEYS": self.payload_hmac_keys,
            "PAYLOAD_HMAC_ACTIVE_VERSION": self.payload_hmac_active_version,
        }
        if not self.public_analyzer_only and (
            self.app_env == "pilot" or any(value is not None for value in ingestion.values())
        ):
            missing = sorted(name for name, value in ingestion.items() if value is None)
            if missing:
                raise ValueError(f"Event ingestion requires: {', '.join(missing)}")
            if not self.auth_configured:
                raise ValueError("Event ingestion requires the authentication configuration")
            for keys, version, name in (
                (self.subscriber_hmac_keys, self.subscriber_hmac_active_version, "SUBSCRIBER"),
                (self.payload_hmac_keys, self.payload_hmac_active_version, "PAYLOAD"),
            ):
                if keys is not None and version not in parse_key_map(keys, f"{name}_HMAC_KEYS"):
                    raise ValueError(f"{name}_HMAC_ACTIVE_VERSION is not a key in {name}_HMAC_KEYS")
        if self.sms_worker_enabled:
            worker_paths = {
                "SMS_WORKER_PYTHON": self.sms_worker_python,
                "MODEL_DIR": self.model_dir,
                "MODEL_MANIFEST_PATH": self.model_manifest_path,
            }
            missing = sorted(name for name, value in worker_paths.items() if value is None)
            if missing:
                raise ValueError(f"The SMS worker requires: {', '.join(missing)}")
            if any(not value.is_absolute() for value in worker_paths.values() if value):
                raise ValueError("SMS worker paths must be absolute")
            if not self.ingestion_configured and not self.public_analyzer_only:
                raise ValueError("The SMS worker requires the event ingestion configuration")
            if self.sms_model_authorization is None:
                raise ValueError(
                    "SMS_WORKER_ENABLED requires SMS_MODEL_AUTHORIZATION="
                    "experimental-local-unvalidated (no M4-Q GO verdict exists)"
                )
            origin_host = urlsplit(self.app_origin or "").hostname or ""
            if self.app_env != "development" or not is_loopback(origin_host):
                raise ValueError(
                    "Experimental SMS analysis runs only with APP_ENV=development "
                    "and a loopback APP_ORIGIN"
                )
            # The inference budget plus the commit reserve must fit inside the request deadline.
            if self.sms_inference_timeout_ms / 1000 + SMS_COMMIT_RESERVE_SECONDS >= (
                self.inference_timeout_seconds
            ):
                raise ValueError(
                    "SMS_INFERENCE_TIMEOUT_MS plus the 2 s commit reserve must be shorter "
                    "than INFERENCE_TIMEOUT_SECONDS"
                )
        if self.public_analyzer_mode != "disabled":
            if not self.sms_worker_enabled:
                raise ValueError("PUBLIC_ANALYZER_MODE requires SMS_WORKER_ENABLED=true")
            if self.redis_url is None or self.rate_limit_hmac_key is None:
                raise ValueError("The public analyzer requires REDIS_URL and RATE_LIMIT_HMAC_KEY")
        if self.public_analyzer_hosted_approval is not None and (
            self.public_analyzer_mode != "hosted"
        ):
            raise ValueError(
                "PUBLIC_ANALYZER_HOSTED_APPROVAL applies only to PUBLIC_ANALYZER_MODE=hosted"
            )
        return self

    @property
    def auth_configured(self) -> bool:
        return self.app_origin is not None and not self.public_analyzer_only

    @property
    def ingestion_configured(self) -> bool:
        return self.payload_hmac_keys is not None


def parse_key_map(value: SecretStr, name: str) -> dict[str, bytes]:
    """A versioned key map is a JSON object mapping key versions to secrets."""
    try:
        raw = json.loads(value.get_secret_value())
    except json.JSONDecodeError:
        raise ValueError(f"{name} must be a JSON object") from None
    if not isinstance(raw, dict) or not raw:
        raise ValueError(f"{name} must be a non-empty JSON object")
    keys: dict[str, bytes] = {}
    for version, secret in raw.items():
        if not KEY_VERSION.fullmatch(version):
            raise ValueError(f"{name} versions must be 1-32 safe characters")
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            raise ValueError(f"Each {name} secret needs {MIN_SECRET_LENGTH}+ characters")
        keys[version] = secret.encode()
    return keys


def parse_audit_keys(value: SecretStr) -> dict[str, bytes]:
    return parse_key_map(value, "AUDIT_HMAC_KEYS")
