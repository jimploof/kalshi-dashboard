"""
Tests for GET /api/kalshi/series (series list with category filter).

All tests mock KalshiRestClient via FastAPI dependency overrides.

Key assertions:
- Returns 200 with correct SeriesDTO shape on success.
- category, tags, ticker, title, frequency are forwarded correctly.
- Raw upstream fields (fee_multiplier, settlement_sources, contract_url,
  additional_prohibitions, product_metadata) do NOT leak into SeriesDTO.
- An empty series list is valid.
- category and tags query params are forwarded to the client method.
- When neither category nor tags are provided, None is forwarded for both.
- Returns 502 (upstream_failure) on HTTP errors.
- Returns 502 (upstream_failure) on network errors.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

_FORBIDDEN_SERIES_FIELDS = {
    "fee_type",
    "fee_multiplier",
    "settlement_sources",
    "contract_url",
    "contract_terms_url",
    "additional_prohibitions",
    "product_metadata",
    "last_updated_ts",
}

# ---------------------------------------------------------------------------
# Sample upstream payloads
# ---------------------------------------------------------------------------

_SAMPLE_SERIES_RESPONSE = {
    "series": [
        {
            "ticker": "KXBTC",
            "title": "Bitcoin Daily",
            "category": "crypto",
            "frequency": "daily",
            "tags": ["bitcoin", "crypto"],
            # Raw fields that must be stripped:
            "fee_type": "quadratic",
            "fee_multiplier": 1,
            "settlement_sources": [{"name": "Coinbase", "url": "https://coinbase.com"}],
            "contract_url": "https://kalshi.com/contract/kxbtc",
            "contract_terms_url": "https://kalshi.com/terms/kxbtc",
            "additional_prohibitions": [],
            "product_metadata": {"domain": "crypto"},
            "last_updated_ts": "2024-01-01T00:00:00Z",
        },
        {
            "ticker": "KXETH",
            "title": "Ethereum Daily",
            "category": "crypto",
            "frequency": "daily",
            "tags": [],
            "fee_type": "quadratic",
            "fee_multiplier": 1,
            "last_updated_ts": "2024-01-01T00:00:00Z",
        },
    ]
}

_SAMPLE_SERIES_EMPTY = {"series": []}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, result: dict) -> MagicMock:
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = True
    client.get_series = AsyncMock(return_value=result)
    return client


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_series_success_shape(async_client: AsyncClient) -> None:
    """Returns 200 with correct wrapper shape."""
    mock = _mock_client(result=_SAMPLE_SERIES_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "Kalshi series retrieved" in data["message"]
    assert isinstance(data["series"], list)
    assert len(data["series"]) == 2


@pytest.mark.asyncio
async def test_kalshi_series_dto_fields(async_client: AsyncClient) -> None:
    """SeriesDTO fields are correctly populated."""
    mock = _mock_client(result=_SAMPLE_SERIES_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    s = response.json()["series"][0]
    assert s["ticker"] == "KXBTC"
    assert s["title"] == "Bitcoin Daily"
    assert s["category"] == "crypto"
    assert s["frequency"] == "daily"
    assert s["tags"] == ["bitcoin", "crypto"]


@pytest.mark.asyncio
async def test_kalshi_series_empty_tags_becomes_list(async_client: AsyncClient) -> None:
    """An empty tags list from upstream is returned as an empty list, not null."""
    mock = _mock_client(result=_SAMPLE_SERIES_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    s = response.json()["series"][1]
    assert s["ticker"] == "KXETH"
    assert s["tags"] == []


@pytest.mark.asyncio
async def test_kalshi_series_no_raw_fields_leaked(async_client: AsyncClient) -> None:
    """Raw upstream series fields must not appear in any SeriesDTO."""
    mock = _mock_client(result=_SAMPLE_SERIES_RESPONSE)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    for s in response.json()["series"]:
        for field in _FORBIDDEN_SERIES_FIELDS:
            assert field not in s, f"SeriesDTO must not contain raw field {field!r}"


@pytest.mark.asyncio
async def test_kalshi_series_empty_upstream(async_client: AsyncClient) -> None:
    """An empty series list from upstream is valid and returns 200."""
    mock = _mock_client(result=_SAMPLE_SERIES_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["series"] == []


# ---------------------------------------------------------------------------
# Query parameter forwarding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_series_default_params_forwarded(async_client: AsyncClient) -> None:
    """Without query params, None is forwarded for category and tags."""
    mock = _mock_client(result=_SAMPLE_SERIES_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_series.assert_called_once_with(category=None, tags=None)


@pytest.mark.asyncio
async def test_kalshi_series_category_param_forwarded(async_client: AsyncClient) -> None:
    """category query param is forwarded to the client method."""
    mock = _mock_client(result=_SAMPLE_SERIES_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/series?category=crypto")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_series.assert_called_once_with(category="crypto", tags=None)


@pytest.mark.asyncio
async def test_kalshi_series_tags_param_forwarded(async_client: AsyncClient) -> None:
    """tags query param is forwarded to the client method."""
    mock = _mock_client(result=_SAMPLE_SERIES_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/series?tags=bitcoin,crypto")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_series.assert_called_once_with(category=None, tags="bitcoin,crypto")


@pytest.mark.asyncio
async def test_kalshi_series_both_params_forwarded(async_client: AsyncClient) -> None:
    """Both category and tags are forwarded when provided together."""
    mock = _mock_client(result=_SAMPLE_SERIES_EMPTY)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        await async_client.get("/api/kalshi/series?category=sports&tags=nba")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    mock.get_series.assert_called_once_with(category="sports", tags="nba")


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_series_upstream_http_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when Kalshi responds with an HTTP error."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    http_response = MagicMock()
    http_response.status_code = 500
    mock.get_series = AsyncMock(
        side_effect=httpx.HTTPStatusError(
            "Internal Server Error", request=MagicMock(), response=http_response
        )
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["series"] == []


@pytest.mark.asyncio
async def test_kalshi_series_network_error(async_client: AsyncClient) -> None:
    """Returns 502 with upstream_failure when the network call fails."""
    mock = MagicMock(spec=KalshiRestClient)
    mock.is_configured.return_value = True
    mock.get_series = AsyncMock(
        side_effect=httpx.ConnectError("Connection refused")
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/series")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["series"] == []
