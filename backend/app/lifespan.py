import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import get_settings
from app.services.kalshi.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # Initialise readiness flags — /api/ready reads these without touching pool objects.
    app.state.pg_ready = False
    app.state.redis_ready = False

    logger.info(
        "Starting up — log_level=%s cors_origins=%s",
        settings.log_level,
        settings.cors_origins,
    )

    logger.info("Connecting to PostgreSQL at %s…", settings.safe_database_url())
    try:
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_dsn,
            min_size=1,
            max_size=5,
        )
        app.state.pg_ready = True
        logger.info("PostgreSQL connection pool ready.")
    except Exception as exc:
        logger.error("Failed to connect to PostgreSQL: %s", exc)
        raise

    logger.info("Connecting to Redis at %s…", settings.safe_redis_url())
    try:
        app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        await app.state.redis.ping()
        app.state.redis_ready = True
        logger.info("Redis connection ready.")
    except Exception as exc:
        logger.error("Failed to connect to Redis: %s", exc)
        await app.state.pg_pool.close()
        raise

    # Shared rate limiter — injected into every KalshiRestClient across all
    # route handlers so they share the same token budget.
    app.state.rate_limiter = RateLimiter(
        max_calls=settings.kalshi_rest_max_calls_per_second
    )
    logger.info(
        "Rate limiter ready — max_calls=%d/s.",
        settings.kalshi_rest_max_calls_per_second,
    )

    logger.info("Startup complete — all dependencies ready.")
    yield

    logger.info("Shutting down — closing connections…")
    app.state.pg_ready = False
    app.state.redis_ready = False
    await app.state.pg_pool.close()
    await app.state.redis.aclose()
    logger.info("Shutdown complete.")
