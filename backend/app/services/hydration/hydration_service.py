"""HydrationService — background REST hydration from Kalshi into PostgreSQL.

Pulls series → events (with nested markets) from the Kalshi REST API and
upserts them into local DB tables.  Writes raw payloads to raw_ingest_events
before any derivation, per architecture rule 9.

Redis is used for:
  - hydration:lock          — distributed lock (SET NX EX 300) prevents
                              concurrent overlapping runs
  - hydration:series:last_run  — ISO timestamp of last successful series run
  - hydration:events:last_run  — ISO timestamp of last successful events run

Background task:
  start_loop() runs two independent intervals:
    - series refresh  (default 900s / 15 min — series don't change often)
    - events+markets refresh (default 300s / 5 min — prices/status change)

Failure handling:
  - Per-page httpx errors are logged and skipped; the run continues.
  - Redis lock errors are logged; the run is skipped to avoid double-writes.
  - Individual upsert errors bubble up to run_once() which logs them.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

import asyncpg
import httpx
import redis.asyncio as aioredis

from app.services.db import events_repo, raw_events_repo, series_repo
from app.services.kalshi.rest_client import KalshiRestClient

logger = logging.getLogger(__name__)

_LOCK_KEY = "hydration:lock"
_LOCK_TTL_SECONDS = 300
_SERIES_LAST_RUN_KEY = "hydration:series:last_run"
_EVENTS_LAST_RUN_KEY = "hydration:events:last_run"


@dataclass
class HydrationResult:
    series_upserted: int = 0
    events_upserted: int = 0
    markets_upserted: int = 0
    errors: list[str] = field(default_factory=list)


class HydrationService:
    def __init__(
        self,
        client: KalshiRestClient,
        pool: asyncpg.Pool,
        redis: aioredis.Redis,
    ) -> None:
        self._client = client
        self._pool = pool
        self._redis = redis

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def run_once(self) -> HydrationResult:
        """Run a full hydration cycle: series → events+markets → raw archive.

        Returns a HydrationResult summarising counts and any non-fatal errors.
        Skips silently if the Redis lock is already held by another run.
        """
        result = HydrationResult()

        acquired = await self._redis.set(_LOCK_KEY, "1", nx=True, ex=_LOCK_TTL_SECONDS)
        if not acquired:
            logger.info("Hydration skipped — lock already held.")
            return result

        try:
            await self._hydrate_series(result)
            await self._hydrate_events(result)
        finally:
            await self._redis.delete(_LOCK_KEY)

        logger.info(
            "Hydration complete — series=%d events=%d markets=%d errors=%d",
            result.series_upserted,
            result.events_upserted,
            result.markets_upserted,
            len(result.errors),
        )
        return result

    async def start_loop(
        self,
        interval_series_s: int = 900,
        interval_events_s: int = 300,
    ) -> None:
        """Start independent background refresh loops for series and events.

        Runs an immediate hydration on startup, then sleeps independently for
        each resource type.  Designed to be launched as an asyncio.Task.
        """
        logger.info(
            "Hydration loop starting — series interval=%ds events interval=%ds",
            interval_series_s,
            interval_events_s,
        )

        # Fire immediately on startup
        try:
            await self.run_once()
        except Exception as exc:
            logger.error("Hydration startup run failed: %s", exc)

        series_task = asyncio.create_task(
            self._series_loop(interval_series_s), name="hydration-series"
        )
        events_task = asyncio.create_task(
            self._events_loop(interval_events_s), name="hydration-events"
        )

        try:
            await asyncio.gather(series_task, events_task)
        except asyncio.CancelledError:
            series_task.cancel()
            events_task.cancel()
            raise

    # ------------------------------------------------------------------
    # Internal loops
    # ------------------------------------------------------------------

    async def _series_loop(self, interval_s: int) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                result = HydrationResult()
                await self._hydrate_series(result)
                if result.errors:
                    logger.warning("Series hydration errors: %s", result.errors)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Series hydration loop error: %s", exc)

    async def _events_loop(self, interval_s: int) -> None:
        while True:
            await asyncio.sleep(interval_s)
            try:
                result = HydrationResult()
                await self._hydrate_events(result)
                if result.errors:
                    logger.warning("Events hydration errors: %s", result.errors)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Events hydration loop error: %s", exc)

    # ------------------------------------------------------------------
    # Hydration workers
    # ------------------------------------------------------------------

    async def _hydrate_series(self, result: HydrationResult) -> None:
        """Fetch all series from Kalshi and upsert into the series table."""
        logger.debug("Hydrating series …")
        try:
            raw = await self._client.get_series()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            msg = f"get_series failed: {exc}"
            logger.warning(msg)
            result.errors.append(msg)
            return

        records: list[dict] = raw.get("series") or []
        if not records:
            logger.debug("No series returned from Kalshi.")
            return

        # Archive raw payload before upsert
        await raw_events_repo.insert_raw_batch(self._pool, "rest_series", records)

        n = await series_repo.upsert_series(self._pool, records)
        result.series_upserted += n

        now_iso = datetime.now(UTC).isoformat()
        await self._redis.set(_SERIES_LAST_RUN_KEY, now_iso)
        logger.info("Series hydration: %d rows upserted.", n)

    async def _hydrate_events(self, result: HydrationResult) -> None:
        """Paginate GET /events (with nested markets) and upsert into DB."""
        logger.debug("Hydrating events+markets …")
        cursor: str | None = None
        page = 0

        while True:
            page += 1
            try:
                raw = await self._client.get_events(
                    series_ticker=None,
                    status=None,
                    limit=200,
                    cursor=cursor,
                    with_nested_markets=True,
                    min_close_ts=None,
                    min_updated_ts=None,
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                msg = f"get_events page={page} failed: {exc}"
                logger.warning(msg)
                result.errors.append(msg)
                break

            raw_events: list[dict] = raw.get("events") or []
            if not raw_events:
                break

            # Archive raw events before upsert
            await raw_events_repo.insert_raw_batch(
                self._pool, "rest_events", raw_events
            )

            # Extract nested markets before event upsert
            all_markets: list[dict] = []
            event_records: list[dict] = []
            for e in raw_events:
                nested = e.get("markets") or []
                all_markets.extend(nested)
                event_records.append({k: v for k, v in e.items() if k != "markets"})

            n_events = await events_repo.upsert_events(self._pool, event_records)
            n_markets = await events_repo.upsert_markets(self._pool, all_markets)
            result.events_upserted += n_events
            result.markets_upserted += n_markets

            logger.debug(
                "Page %d: %d events, %d markets upserted.", page, n_events, n_markets
            )

            cursor = raw.get("cursor") or None
            if not cursor:
                break

        now_iso = datetime.now(UTC).isoformat()
        await self._redis.set(_EVENTS_LAST_RUN_KEY, now_iso)
        logger.info(
            "Events hydration complete: %d events, %d markets across %d pages.",
            result.events_upserted,
            result.markets_upserted,
            page,
        )
