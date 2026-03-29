"""Series catalog cache backed by Redis.

The Kalshi GET /series endpoint returns all series in a single response
with no pagination. Calling it on every frontend request is wasteful, so
this module wraps the call with a Redis TTL cache.

Two cache variants are maintained:

    - base series list
    - base series list with include_volume=true

That keeps the fast navigation list and the volume-enriched list isolated,
while still serving both from a single upstream request on cache miss.
"""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.services.kalshi.rest_client import KalshiRestClient

logger = logging.getLogger(__name__)

_SERIES_CACHE_KEY = "catalog:series:base"
_SERIES_WITH_VOLUME_CACHE_KEY = "catalog:series:with-volume"
_SERIES_CACHE_TTL_SECONDS = 900  # 15 minutes


async def get_series_cached(
    redis: aioredis.Redis,
    client: KalshiRestClient,
    *,
    category: str | None = None,
    tags: str | None = None,
    include_volume: bool = False,
    ttl: int = _SERIES_CACHE_TTL_SECONDS,
) -> list[dict[str, Any]]:
    """Return series list, serving from Redis cache when available.

    The full unfiltered series list is cached. Filtering by category or tags is
    intentionally deferred to the caller (the catalog router) so the cache is a
    single shared key regardless of what filters the caller applies.

    Args:
        redis:    aioredis.Redis connection.
        client:   KalshiRestClient to use on a cache miss.
        category: Optional category to pass to Kalshi on a cache miss.
                  Has no effect on cache key — only used when fetching.
        tags:     Optional tags filter to pass to Kalshi on cache miss.
        include_volume: When True, fetches GET /series?include_volume=true and
                stores that enriched list under a separate cache key.
        ttl:            Redis TTL in seconds (default: 15 minutes).

    Returns:
        List of raw series dicts as returned by Kalshi (not normalized).
    """
    cache_key = _SERIES_WITH_VOLUME_CACHE_KEY if include_volume else _SERIES_CACHE_KEY

    try:
        cached = await redis.get(cache_key)
    except Exception as exc:
        logger.warning("Redis GET %s failed: %s — fetching live.", cache_key, exc)
        cached = None

    if cached is not None:
        try:
            records: list[dict[str, Any]] = json.loads(cached)
            logger.debug("Series cache HIT (%s) — %d records.", cache_key, len(records))
            return records
        except json.JSONDecodeError as exc:
            logger.warning("Series cache value corrupt (%s) — refetching.", exc)

    logger.debug("Series cache MISS (%s) — fetching from Kalshi.", cache_key)
    raw = await client.get_series(
        category=category,
        tags=tags,
        include_volume=include_volume,
    )
    records = raw.get("series") or []

    try:
        await redis.set(cache_key, json.dumps(records), ex=ttl)
        logger.debug("Series cache populated (%s) — %d records, TTL=%ds.", cache_key, len(records), ttl)
    except Exception as exc:
        logger.warning("Redis SET %s failed: %s — continuing without caching.", cache_key, exc)

    return records


async def invalidate_series_cache(redis: aioredis.Redis) -> None:
    """Delete the series cache key, forcing the next request to re-fetch."""
    try:
        await redis.delete(_SERIES_CACHE_KEY)
        await redis.delete(_SERIES_WITH_VOLUME_CACHE_KEY)
        logger.info("Series cache invalidated.")
    except Exception as exc:
        logger.warning("Series cache invalidation failed: %s", exc)


async def get_cache_ttl(redis: aioredis.Redis, *, include_volume: bool = False) -> int | None:
    """Return remaining TTL in seconds, or None if the key does not exist."""
    cache_key = _SERIES_WITH_VOLUME_CACHE_KEY if include_volume else _SERIES_CACHE_KEY
    try:
        ttl = await redis.ttl(cache_key)
        return ttl if ttl >= 0 else None
    except Exception as exc:
        logger.warning("Redis TTL %s failed: %s", cache_key, exc)
        return None
