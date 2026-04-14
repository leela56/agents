"""Application configuration using Pydantic Settings.

All secrets and configuration are loaded from environment variables
with strict validation. No raw os.getenv calls anywhere in the codebase.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class Settings(BaseSettings):
    """Application settings loaded from .env file with validation."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- LLM Provider ---
    llm_provider: str = Field(
        default="ollama",
        description="LLM provider: 'gemini' or 'ollama'",
    )
    ollama_model: str = Field(
        default="gemma4",
        description="Ollama model name",
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama API base URL",
    )

    # --- Google Gemini ---
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API key from aistudio.google.com (optional if using ollama)",
    )

    # --- Gmail OAuth2 ---
    gmail_client_id: str = Field(
        ...,
        min_length=10,
        description="Gmail OAuth2 client ID",
    )
    gmail_client_secret: str = Field(
        ...,
        min_length=5,
        description="Gmail OAuth2 client secret",
    )
    gmail_redirect_uri: str = Field(
        default="http://localhost:8000/auth/callback",
        description="OAuth2 redirect URI",
    )
    gmail_scopes: list[str] = Field(
        default=["https://www.googleapis.com/auth/gmail.readonly"],
        description="Gmail API scopes",
    )

    # --- Security ---
    encryption_key: str = Field(
        ...,
        min_length=32,
        description="Fernet encryption key for token storage",
    )

    # --- Application ---
    app_env: AppEnvironment = Field(
        default=AppEnvironment.DEVELOPMENT,
        description="Application environment",
    )
    allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        description="CORS allowed origins",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/email_agent.db",
        description="Database connection string",
    )

    # --- Rate Limiting ---
    rate_limit_general: str = Field(
        default="60/minute",
        description="General API rate limit",
    )
    rate_limit_processing: str = Field(
        default="10/minute",
        description="AI processing rate limit",
    )

    # --- Paths ---
    data_dir: Path = Field(
        default=Path("./data"),
        description="Directory for persistent data",
    )
    token_file: Path = Field(
        default=Path("./data/token.json.enc"),
        description="Path to encrypted OAuth token file",
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid_levels:
            msg = f"Invalid log level: {v}. Must be one of {valid_levels}"
            raise ValueError(msg)
        return upper

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @property
    def is_development(self) -> bool:
        return self.app_env == AppEnvironment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnvironment.PRODUCTION

    def ensure_data_dir(self) -> None:
        """Create data directory if it doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get cached application settings (singleton)."""
    settings = Settings()
    settings.ensure_data_dir()
    return settings
