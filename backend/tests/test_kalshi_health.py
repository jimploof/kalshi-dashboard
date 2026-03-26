"""
Tests for GET /api/kalshi/health.

All tests mock the KalshiRestClient via FastAPI dependency overrides so that
no real keys or network connections are needed.

Key assertions:
- The route never returns account financial data (balance_cents, portfolio_value_cents).
- The route always returns the sanitized set of connectivity metadata fields.
"""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import AsyncClient

from app.dependencies import get_kalshi_client
from app.main import app
from app.services.kalshi.rest_client import KalshiRestClient

# Fields that must NOT appear anywhere in the response regardless of status.
_FORBIDDEN_FIELDS = {"balance_cents", "portfolio_value_cents", "balance", "portfolio_value"}

# Fields that must always be present regardless of status.
_REQUIRED_FIELDS = {"status", "message", "provider", "authenticated", "probe", "base_url", "environment"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(*, configured: bool = True) -> MagicMock:
    """Return a MagicMock wrapping KalshiRestClient with is_configured pre-set."""
    client = MagicMock(spec=KalshiRestClient)
    client.is_configured.return_value = configured
    return client


def _assert_no_account_data(data: dict) -> None:
    for field in _FORBIDDEN_FIELDS:
        assert field not in data, f"Response must not contain account field {field!r}"


def _assert_required_fields(data: dict) -> None:
    for field in _REQUIRED_FIELDS:
        assert field in data, f"Response missing required field {field!r}"


# ---------------------------------------------------------------------------
# missing_config — no credentials available
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_health_missing_config(async_client: AsyncClient) -> None:
    """Returns 503 when the client is not configured; no account data in response."""
    mock = _mock_client(configured=False)
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/health")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "missing_config"
    assert data["authenticated"] is False
    assert data["provider"] == "kalshi"
    assert data["probe"] == "get_balance"
    assert "base_url" in data
    assert "environment" in data
    _assert_no_account_data(data)
    _assert_required_fields(data)


# ---------------------------------------------------------------------------
# success — Kalshi responds with a valid balance (upstream payload discarded)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_health_success(async_client: AsyncClient) -> None:
    """Returns 200 with sanitized metadata; upstream account values are not exposed."""
    mock = _mock_client(configured=True)
    mock.get_balance = AsyncMock(
        return_value={"balance": 10000, "portfolio_value": 15500, "updated_ts": 1711400000000}
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/health")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["authenticated"] is True
    assert data["provider"] == "kalshi"
    assert data["probe"] == "get_balance"
    assert data["message"] == "Kalshi connectivity and authentication verified via balance probe."
    assert "base_url" in data
    assert "environment" in data
    # Critical: upstream account values must not appear in the response.
    _assert_no_account_data(data)
    _assert_required_fields(data)


# ---------------------------------------------------------------------------
# auth_failure — Kalshi returns 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_health_auth_failure(async_client: AsyncClient) -> None:
    """Returns 502 + status=auth_failure when Kalshi responds with 401."""
    mock = _mock_client(configured=True)
    _req = httpx.Request("GET", "https://demo-api.kalshi.co/trade-api/v2/portfolio/balance")
    _resp = httpx.Response(401, request=_req)
    mock.get_balance = AsyncMock(
        side_effect=httpx.HTTPStatusError("401 Unauthorized", request=_req, response=_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/health")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "auth_failure"
    assert data["authenticated"] is False
    _assert_no_account_data(data)
    _assert_required_fields(data)


# ---------------------------------------------------------------------------
# upstream_failure — network error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_health_upstream_failure_network(async_client: AsyncClient) -> None:
    """Returns 502 + status=upstream_failure on network/timeout errors."""
    mock = _mock_client(configured=True)
    _req = httpx.Request("GET", "https://demo-api.kalshi.co/trade-api/v2/portfolio/balance")
    mock.get_balance = AsyncMock(
        side_effect=httpx.ConnectTimeout("timed out", request=_req)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/health")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["authenticated"] is False
    _assert_no_account_data(data)
    _assert_required_fields(data)


# ---------------------------------------------------------------------------
# upstream_failure — unexpected non-401 HTTP error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kalshi_health_upstream_failure_http500(async_client: AsyncClient) -> None:
    """Returns 502 + status=upstream_failure on unexpected upstream HTTP errors."""
    mock = _mock_client(configured=True)
    _req = httpx.Request("GET", "https://demo-api.kalshi.co/trade-api/v2/portfolio/balance")
    _resp = httpx.Response(500, request=_req)
    mock.get_balance = AsyncMock(
        side_effect=httpx.HTTPStatusError("500 Internal Server Error", request=_req, response=_resp)
    )
    app.dependency_overrides[get_kalshi_client] = lambda: mock

    try:
        response = await async_client.get("/api/kalshi/health")
    finally:
        app.dependency_overrides.pop(get_kalshi_client, None)

    assert response.status_code == 502
    data = response.json()
    assert data["status"] == "upstream_failure"
    assert data["authenticated"] is False
    _assert_no_account_data(data)
    _assert_required_fields(data)
