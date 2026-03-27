"""Tests for app/services/hydration/hydration_service.py.

All external dependencies (KalshiRestClient, asyncpg.Pool, Redis) are mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.hydration.hydration_service import HydrationService


def _make_pool():
    conn = AsyncMock()
    conn.executemany = AsyncMock(return_value=None)
    conn.execute = AsyncMock(return_value=None)

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _make_redis(lock_acquired: bool = True) -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=lock_acquired)
    redis.delete = AsyncMock(return_value=None)
    redis.get = AsyncMock(return_value=None)
    return redis


def _make_client(
    series_payload: dict | None = None,
    events_payload: dict | None = None,
) -> AsyncMock:
    client = AsyncMock()
    client.get_series = AsyncMock(return_value=series_payload or {"series": []})
    client.get_events = AsyncMock(return_value=events_payload or {"events": [], "cursor": None})
    return client


# ---------------------------------------------------------------------------
# run_once — full happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_once_upserts_series_and_events() -> None:
    client = _make_client(
        series_payload={"series": [{"ticker": "KXBTCD", "title": "BTC"}]},
        events_payload={
            "events": [
                {
                    "event_ticker": "KXBTCD-26MAR",
                    "series_ticker": "KXBTCD",
                    "status": "open",
                    "markets": [
                        {"ticker": "KXBTCD-26MAR-T95000", "event_ticker": "KXBTCD-26MAR"}
                    ],
                }
            ],
            "cursor": None,
        },
    )
    redis = _make_redis(lock_acquired=True)
    pool = _make_pool()

    with (
        patch("app.services.hydration.hydration_service.series_repo.upsert_series", new_callable=AsyncMock, return_value=1) as mock_upsert_series,
        patch("app.services.hydration.hydration_service.events_repo.upsert_events", new_callable=AsyncMock, return_value=1) as mock_upsert_events,
        patch("app.services.hydration.hydration_service.events_repo.upsert_markets", new_callable=AsyncMock, return_value=1) as mock_upsert_markets,
        patch("app.services.hydration.hydration_service.raw_events_repo.insert_raw_batch", new_callable=AsyncMock) as mock_raw,
    ):
        service = HydrationService(client=client, pool=pool, redis=redis)
        result = await service.run_once()

    assert result.series_upserted == 1
    assert result.events_upserted == 1
    assert result.markets_upserted == 1
    assert result.errors == []
    mock_upsert_series.assert_called_once()
    mock_upsert_events.assert_called_once()
    mock_upsert_markets.assert_called_once()


# ---------------------------------------------------------------------------
# run_once — Redis lock already held → skip
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_once_skips_when_lock_held() -> None:
    client = _make_client()
    redis = _make_redis(lock_acquired=False)
    pool = _make_pool()

    with (
        patch("app.services.hydration.hydration_service.series_repo.upsert_series", new_callable=AsyncMock) as mock_upsert,
    ):
        service = HydrationService(client=client, pool=pool, redis=redis)
        result = await service.run_once()

    mock_upsert.assert_not_called()
    assert result.series_upserted == 0
    assert result.errors == []


# ---------------------------------------------------------------------------
# run_once — partial httpx failure on events page, continues without crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_once_tolerates_events_httpx_error() -> None:
    import httpx

    client = _make_client(
        series_payload={"series": [{"ticker": "KXBTCD"}]},
    )
    client.get_events = AsyncMock(side_effect=httpx.RequestError("connection refused"))
    redis = _make_redis(lock_acquired=True)
    pool = _make_pool()

    with (
        patch("app.services.hydration.hydration_service.series_repo.upsert_series", new_callable=AsyncMock, return_value=1),
        patch("app.services.hydration.hydration_service.raw_events_repo.insert_raw_batch", new_callable=AsyncMock),
    ):
        service = HydrationService(client=client, pool=pool, redis=redis)
        result = await service.run_once()

    assert result.series_upserted == 1
    assert len(result.errors) == 1
    assert "get_events" in result.errors[0]


# ---------------------------------------------------------------------------
# run_once — Redis last_run keys are set after success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_once_sets_redis_last_run_keys() -> None:
    client = _make_client(
        series_payload={"series": [{"ticker": "KXBTCD"}]},
        events_payload={"events": [], "cursor": None},
    )
    redis = _make_redis(lock_acquired=True)
    pool = _make_pool()

    with (
        patch("app.services.hydration.hydration_service.series_repo.upsert_series", new_callable=AsyncMock, return_value=1),
        patch("app.services.hydration.hydration_service.events_repo.upsert_events", new_callable=AsyncMock, return_value=0),
        patch("app.services.hydration.hydration_service.events_repo.upsert_markets", new_callable=AsyncMock, return_value=0),
        patch("app.services.hydration.hydration_service.raw_events_repo.insert_raw_batch", new_callable=AsyncMock),
    ):
        service = HydrationService(client=client, pool=pool, redis=redis)
        await service.run_once()

    set_calls = [call.args[0] for call in redis.set.call_args_list]
    assert "hydration:series:last_run" in set_calls
    assert "hydration:events:last_run" in set_calls
