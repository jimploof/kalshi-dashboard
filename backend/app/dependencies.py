from typing import Annotated

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.services.kalshi.rate_limiter import RateLimiter
from app.services.kalshi.rest_client import KalshiRestClient

# Reusable type alias: inject(SettingsDep) in any route handler
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool  # type: ignore[no-any-return]


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


def get_kalshi_client(request: Request, settings: SettingsDep) -> KalshiRestClient:
    """Construct a KalshiRestClient from current settings.

    Injects the shared RateLimiter from app.state so that all route-handler
    Kalshi calls share the same token budget as each other.

    A new KalshiRestClient wrapper is created per-request so that tests can
    freely override this dependency via app.dependency_overrides without
    module-level state.  The constructor only reads a file from disk.
    """
    rate_limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    debug_metrics = getattr(request.app.state, "debug_metrics", None)
    return KalshiRestClient(settings, rate_limiter=rate_limiter, debug_metrics=debug_metrics)


DbDep = Annotated[asyncpg.Pool, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
KalshiClientDep = Annotated[KalshiRestClient, Depends(get_kalshi_client)]
