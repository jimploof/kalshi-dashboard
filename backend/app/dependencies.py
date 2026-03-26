from typing import Annotated

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.services.kalshi.rest_client import KalshiRestClient

# Reusable type alias: inject(SettingsDep) in any route handler
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool  # type: ignore[no-any-return]


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


def get_kalshi_client(settings: SettingsDep) -> KalshiRestClient:
    """Construct a KalshiRestClient from current settings.

    A new instance is created per-request so that tests can freely override
    this dependency via app.dependency_overrides without module-level state.
    The constructor only reads a file from disk; it is fast enough for a
    low-frequency health probe.
    """
    return KalshiRestClient(settings)


DbDep = Annotated[asyncpg.Pool, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
KalshiClientDep = Annotated[KalshiRestClient, Depends(get_kalshi_client)]
