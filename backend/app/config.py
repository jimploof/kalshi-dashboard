from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def asyncpg_dsn(self) -> str:
        """Return a bare postgresql:// DSN suitable for asyncpg (strips SQLAlchemy driver prefix)."""
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
