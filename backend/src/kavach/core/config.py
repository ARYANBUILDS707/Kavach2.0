"""Explicit environment configuration without requiring unused service secrets."""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read process environment; dotenv loading is explicit in the run command."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: Literal["development", "test", "pilot"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
