import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
import asyncio

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI

from app.config import get_settings
from app.services.catalog.event_card_cache import set_event_card_snapshot
from app.services.catalog.event_card_snapshot import build_event_card_snapshot
from app.services.kalshi.rate_limiter import RateLimiter
from app.services.kalshi.rest_client import KalshiRestClient

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

    # Debug metrics — only allocated when DEBUG_MODE=true; zero cost otherwise.
    if settings.debug_mode:
        from app.services.debug_metrics import DebugMetrics
        app.state.debug_metrics = DebugMetrics()
        logger.info("Debug mode enabled — metrics collection active.")
    else:
        app.state.debug_metrics = None

    # Shared rate limiter — injected into every KalshiRestClient across all
    # route handlers so they share the same token budget.
    app.state.rate_limiter = RateLimiter(
        max_calls=settings.kalshi_rest_max_calls_per_second
    )
    app.state.event_card_refresh_in_progress = False
    app.state.event_card_refresh_task = None
    logger.info(
        "Rate limiter ready — max_calls=%d/s.",
        settings.kalshi_rest_max_calls_per_second,
    )

    async def prewarm_event_cards() -> None:
        try:
            debug_metrics = getattr(app.state, "debug_metrics", None)
            client = KalshiRestClient(
                settings,
                rate_limiter=app.state.rate_limiter,
                debug_metrics=debug_metrics,
            )
            snapshot = await build_event_card_snapshot(client, debug_metrics=debug_metrics)
            await set_event_card_snapshot(app.state.redis, snapshot)
            logger.info("Event-card snapshot prewarm complete.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Event-card snapshot prewarm failed: %s", exc)

    app.state.event_card_prewarm_task = asyncio.create_task(prewarm_event_cards())

    logger.info("Startup complete — all dependencies ready.")
    yield

    logger.info("Shutting down — closing connections…")
    app.state.pg_ready = False
    app.state.redis_ready = False
    prewarm_task = getattr(app.state, "event_card_prewarm_task", None)
    if prewarm_task is not None and not prewarm_task.done():
        prewarm_task.cancel()
    refresh_task = getattr(app.state, "event_card_refresh_task", None)
    if refresh_task is not None and not refresh_task.done():
        refresh_task.cancel()
    await app.state.pg_pool.close()
    await app.state.redis.aclose()
    logger.info("Shutdown complete.")
