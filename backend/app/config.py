import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_VALID_DB_PREFIXES = ("postgresql+asyncpg://", "postgresql://")
_VALID_REDIS_PREFIXES = ("redis://", "rediss://")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://kalshi:changeme@postgres:5432/kalshi_dashboard"
    redis_url: str = "redis://redis:6379/0"
    cors_origins: list[str] = ["http://localhost:4200", "http://127.0.0.1:4200"]
    log_level: str = "INFO"

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not any(v.startswith(p) for p in _VALID_DB_PREFIXES):
            raise ValueError(
                f"DATABASE_URL must start with one of {_VALID_DB_PREFIXES}. Got: {v[:40]!r}"
            )
        return v

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        if not any(v.startswith(p) for p in _VALID_REDIS_PREFIXES):
            raise ValueError(
                f"REDIS_URL must start with one of {_VALID_REDIS_PREFIXES}. Got: {v[:40]!r}"
            )
        return v

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        return v

    @property
    def asyncpg_dsn(self) -> str:
        """Return a bare postgresql:// DSN suitable for asyncpg (strips SQLAlchemy driver prefix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    def safe_database_url(self) -> str:
        """Return asyncpg DSN with the password masked — safe for logging."""
        return re.sub(r"(://)([^:@]+):([^@]+)@", r"\1\2:***@", self.asyncpg_dsn)

    def safe_redis_url(self) -> str:
        """Return Redis URL with any password masked — safe for logging."""
        return re.sub(r"(://)([^:@]+):([^@]+)@", r"\1\2:***@", self.redis_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
