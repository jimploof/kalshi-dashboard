from typing import Annotated

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, Request

from app.config import Settings, get_settings

# Reusable type alias: inject(SettingsDep) in any route handler
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_db(request: Request) -> asyncpg.Pool:
    return request.app.state.pg_pool  # type: ignore[no-any-return]


def get_redis(request: Request) -> aioredis.Redis:
    return request.app.state.redis  # type: ignore[no-any-return]


DbDep = Annotated[asyncpg.Pool, Depends(get_db)]
RedisDep = Annotated[aioredis.Redis, Depends(get_redis)]
