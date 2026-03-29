"""
Tests for GET /api/catalog/categories and GET /api/catalog/series.

All tests mock KalshiRestClient and Redis via FastAPI dependency overrides;
no real network calls or Redis connections are made.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client, get_redis
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SERIES_FIXTURE = [
    {"ticker": "KXNBA", "title": "NBA Game", "category": "Sports", "tags": ["basketball"], "frequency": "daily"},
    {"ticker": "KXNFL", "title": "NFL Game", "category": "Sports", "tags": ["football"], "frequency": "daily"},
    {"ticker": "KXBTC", "title": "Bitcoin Daily", "category": "Crypto", "tags": ["btc"], "frequency": "daily"},
    {"ticker": "KXPOL", "title": "US Senate", "category": "Politics", "tags": [], "frequency": "once"},
]

_SERIES_WITH_VOLUME_FIXTURE = [
    {"ticker": "KXNBA", "title": "NBA Game", "category": "Sports", "tags": ["basketball"], "frequency": "daily", "volume_fp": "1500.00"},
    {"ticker": "KXNFL", "title": "NFL Game", "category": "Sports", "tags": ["football"], "frequency": "daily", "volume_fp": "2500.00"},
    {"ticker": "KXBTC", "title": "Bitcoin Daily", "category": "Crypto", "tags": ["btc"], "frequency": "daily", "volume_fp": "900.00"},
    {"ticker": "KXPOL", "title": "US Senate", "category": "Politics", "tags": [], "frequency": "once", "volume_fp": "100.00"},
]

_SERIES_KALSHI_RESPONSE = {"series": _SERIES_FIXTURE}
_SERIES_KALSHI_RESPONSE_WITH_VOLUME = {"series": _SERIES_WITH_VOLUME_FIXTURE}


def _mock_kalshi_client(*, result: dict = _SERIES_KALSHI_RESPONSE) -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.get_series = AsyncMock(return_value=result)
    return client


def _mock_redis_miss() -> AsyncMock:
    """Redis returns None on get → cache miss → Kalshi is called."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.set = AsyncMock(return_value=True)
    r.ttl = AsyncMock(return_value=850)
    return r


def _mock_redis_hit(payload: str) -> AsyncMock:
    """Redis returns a JSON-encoded payload → cache hit → Kalshi is NOT called."""
    r = AsyncMock()
    r.get = AsyncMock(return_value=payload.encode())
    r.set = AsyncMock(return_value=True)
    r.ttl = AsyncMock(return_value=750)
    return r


# ---------------------------------------------------------------------------
# /api/catalog/categories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_categories_returns_correct_counts(async_client: AsyncClient) -> None:
    """Categories aggregated from cached series with correct series_count values."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    mock_client = _mock_kalshi_client()

    app.dependency_overrides[get_kalshi_client] = lambda: mock_client
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/categories")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    data = response.json()
    assert "categories" in data

    by_name = {c["name"]: c["series_count"] for c in data["categories"]}
    assert by_name["Sports"] == 2
    assert by_name["Crypto"] == 1
    assert by_name["Politics"] == 1
    # Kalshi not called — cache hit
    mock_client.get_series.assert_not_called()


@pytest.mark.asyncio
async def test_categories_sorted_alphabetically(async_client: AsyncClient) -> None:
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/categories")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    names = [c["name"] for c in response.json()["categories"]]
    assert names == sorted(names)


# ---------------------------------------------------------------------------
# /api/catalog/series — cache hit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_cache_hit_skips_kalshi(async_client: AsyncClient) -> None:
    """When Redis has the series key, get_series() on the client is never called."""
    import json

    mock_client = _mock_kalshi_client()
    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))

    app.dependency_overrides[get_kalshi_client] = lambda: mock_client
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    mock_client.get_series.assert_not_called()
    data = response.json()
    assert data["total"] == 4


@pytest.mark.asyncio
async def test_series_cache_miss_calls_kalshi_and_stores(async_client: AsyncClient) -> None:
    """Cache miss → get_series() called once; result is written to Redis."""
    mock_client = _mock_kalshi_client()
    mock_redis = _mock_redis_miss()

    app.dependency_overrides[get_kalshi_client] = lambda: mock_client
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    mock_client.get_series.assert_called_once()
    mock_redis.set.assert_called_once()
    assert response.json()["total"] == 4


@pytest.mark.asyncio
async def test_series_include_volume_uses_bulk_series_and_maps_volume(async_client: AsyncClient) -> None:
    """include_volume=true uses one bulk series call and maps volume_fp into SeriesDTO.volume."""
    mock_client = _mock_kalshi_client(result=_SERIES_KALSHI_RESPONSE_WITH_VOLUME)
    mock_redis = _mock_redis_miss()

    app.dependency_overrides[get_kalshi_client] = lambda: mock_client
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series?include_volume=true&sort_by=volume&sort_order=desc")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    assert response.status_code == 200
    mock_client.get_series.assert_called_once_with(category=None, tags=None, include_volume=True)

    data = response.json()
    assert data["series"][0]["ticker"] == "KXNFL"
    assert data["series"][0]["volume"] == 2500.0
    assert data["series"][-1]["volume"] == 100.0


# ---------------------------------------------------------------------------
# /api/catalog/series — filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_filter_by_category(async_client: AsyncClient) -> None:
    """?category=Sports returns only Sports series."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series?category=Sports")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    data = response.json()
    assert data["total"] == 2
    for s in data["series"]:
        assert s["category"] == "Sports"


@pytest.mark.asyncio
async def test_series_filter_case_insensitive(async_client: AsyncClient) -> None:
    """Category filter is case-insensitive: 'sports' matches 'Sports'."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series?category=sports")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    assert response.json()["total"] == 2


@pytest.mark.asyncio
async def test_series_filter_unknown_category_returns_empty(async_client: AsyncClient) -> None:
    """?category=Unknown yields empty list with total=0 (not 404)."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series?category=Unknown")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    data = response.json()
    assert response.status_code == 200
    assert data["total"] == 0
    assert data["series"] == []


# ---------------------------------------------------------------------------
# /api/catalog/series — sorting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_default_sort_by_title_asc(async_client: AsyncClient) -> None:
    """Default sort is title ascending."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    titles = [s["title"] for s in response.json()["series"]]
    assert titles == sorted(t.lower() for t in titles) or titles == sorted(titles, key=str.lower)


@pytest.mark.asyncio
async def test_series_sort_desc(async_client: AsyncClient) -> None:
    """sort_order=desc reverses the title sort."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series?sort_order=desc")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    titles = [s["title"] for s in response.json()["series"]]
    assert titles == sorted(titles, key=str.lower, reverse=True)


@pytest.mark.asyncio
async def test_series_includes_cache_ttl(async_client: AsyncClient) -> None:
    """Response includes cache_ttl_seconds from Redis TTL."""
    import json

    mock_redis = _mock_redis_hit(json.dumps(_SERIES_FIXTURE))
    app.dependency_overrides[get_kalshi_client] = lambda: _mock_kalshi_client()
    app.dependency_overrides[get_redis] = lambda: mock_redis

    try:
        response = await async_client.get("/api/catalog/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)
        app.dependency_overrides.pop(get_redis, None)

    data = response.json()
    assert "cache_ttl_seconds" in data
    assert isinstance(data["cache_ttl_seconds"], int)
    assert data["cache_ttl_seconds"] > 0
