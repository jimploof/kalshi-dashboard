import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    logger.info("Connecting to PostgreSQL at %s…", settings.asyncpg_dsn)
    try:
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_dsn,
            min_size=1,
            max_size=5,
        )
        logger.info("PostgreSQL connection pool ready.")
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL: %s", exc)
        raise

    logger.info("Connecting to Redis at %s…", settings.redis_url)
    try:
        app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await app.state.redis.ping()
        logger.info("Redis connection ready.")
    except Exception as exc:
        logger.error("Failed to connect to Redis: %s", exc)
        await app.state.pg_pool.close()
        raise

    logger.info("Startup complete — all connections established.")
    yield

    logger.info("Shutting down connections…")
    await app.state.pg_pool.close()
    await app.state.redis.aclose()
    logger.info("Shutdown complete.")
