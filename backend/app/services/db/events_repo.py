"""Events and markets repository — typed async queries against events + markets tables.

All functions accept an asyncpg.Pool injected from app.state.pg_pool.
Upserts use INSERT ... ON CONFLICT DO UPDATE so they are safe to call
repeatedly during hydration refreshes.

Cursor-based pagination for list queries uses an opaque base64-encoded
offset string so callers never see raw integers in the API.
"""

import base64
import logging
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _encode_cursor(offset: int) -> str:
    return base64.b64encode(str(offset).encode()).decode()


def _decode_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        return int(base64.b64decode(cursor.encode()).decode())
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def upsert_events(pool: asyncpg.Pool, records: list[dict[str, Any]]) -> int:
    """Bulk-upsert event dicts into the events table.

    The series_ticker FK is allowed to be NULL when the series row does not
    yet exist — ON DELETE SET NULL handles future series deletions.
    """
    if not records:
        return 0

    sql = """
        INSERT INTO events (
            event_ticker, series_ticker, title, sub_title,
            category, mutually_exclusive, status, fetched_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, now())
        ON CONFLICT (event_ticker) DO UPDATE SET
            series_ticker      = EXCLUDED.series_ticker,
            title              = EXCLUDED.title,
            sub_title          = EXCLUDED.sub_title,
            category           = EXCLUDED.category,
            mutually_exclusive = EXCLUDED.mutually_exclusive,
            status             = EXCLUDED.status,
            fetched_at         = now()
    """

    rows: list[tuple[Any, ...]] = [
        (
            r["event_ticker"],
            r.get("series_ticker"),
            r.get("title"),
            r.get("sub_title"),
            r.get("category"),
            r.get("mutually_exclusive"),
            r.get("status"),
        )
        for r in records
    ]

    async with pool.acquire() as conn:
        await conn.executemany(sql, rows)

    logger.debug("upsert_events: %d rows processed", len(rows))
    return len(rows)


async def get_events(
    pool: asyncpg.Pool,
    *,
    series_ticker: str | None = None,
    status: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    min_close_ts: int | None = None,
    min_updated_ts: int | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return a paginated list of event rows.

    Returns (rows, next_cursor).  next_cursor is None when there are no more
    pages.  min_updated_ts maps to fetched_at for REST-hydrated rows (which is
    the closest available local proxy for 'updated at' before WS ingest exists).
    min_close_ts requires a join to markets; rows where all markets have
    close_time < min_close_ts are excluded.
    """
    offset = _decode_cursor(cursor)
    params: list[Any] = []
    conditions: list[str] = []
    idx = 1

    if series_ticker is not None:
        conditions.append(f"e.series_ticker = ${idx}")
        params.append(series_ticker)
        idx += 1

    if status is not None:
        conditions.append(f"e.status = ${idx}")
        params.append(status)
        idx += 1

    if min_updated_ts is not None:
        min_updated_dt = datetime.utcfromtimestamp(min_updated_ts)
        conditions.append(f"e.fetched_at >= ${idx}")
        params.append(min_updated_dt)
        idx += 1

    if min_close_ts is not None:
        min_close_dt = datetime.utcfromtimestamp(min_close_ts)
        conditions.append(
            f"EXISTS (SELECT 1 FROM markets m2 WHERE m2.event_ticker = e.event_ticker AND m2.close_time >= ${idx})"
        )
        params.append(min_close_dt)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT e.event_ticker, e.series_ticker, e.title, e.sub_title,
               e.category, e.mutually_exclusive, e.status, e.fetched_at
        FROM events e
        {where}
        ORDER BY e.event_ticker
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit + 1, offset])

    async with pool.acquire() as conn:
        raw_rows = await conn.fetch(sql, *params)

    rows = [dict(r) for r in raw_rows]
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor = _encode_cursor(offset + limit) if has_more else None
    return rows, next_cursor


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

async def upsert_markets(pool: asyncpg.Pool, records: list[dict[str, Any]]) -> int:
    """Bulk-upsert market dicts into the markets table."""
    if not records:
        return 0

    sql = """
        INSERT INTO markets (
            ticker, event_ticker, market_type, yes_sub_title, no_sub_title,
            title, subtitle, status, open_time, close_time,
            yes_bid_dollars, yes_ask_dollars, last_price_dollars,
            volume_fp, volume_24h_fp, open_interest_fp, fetched_at
        )
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,now())
        ON CONFLICT (ticker) DO UPDATE SET
            event_ticker       = EXCLUDED.event_ticker,
            market_type        = EXCLUDED.market_type,
            yes_sub_title      = EXCLUDED.yes_sub_title,
            no_sub_title       = EXCLUDED.no_sub_title,
            title              = EXCLUDED.title,
            subtitle           = EXCLUDED.subtitle,
            status             = EXCLUDED.status,
            open_time          = EXCLUDED.open_time,
            close_time         = EXCLUDED.close_time,
            yes_bid_dollars    = EXCLUDED.yes_bid_dollars,
            yes_ask_dollars    = EXCLUDED.yes_ask_dollars,
            last_price_dollars = EXCLUDED.last_price_dollars,
            volume_fp          = EXCLUDED.volume_fp,
            volume_24h_fp      = EXCLUDED.volume_24h_fp,
            open_interest_fp   = EXCLUDED.open_interest_fp,
            fetched_at         = now()
    """

    def _parse_dt(v: Any) -> datetime | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        try:
            from datetime import timezone
            return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except Exception:
            return None

    rows: list[tuple[Any, ...]] = [
        (
            r["ticker"],
            r.get("event_ticker"),
            r.get("market_type"),
            r.get("yes_sub_title"),
            r.get("no_sub_title"),
            r.get("title"),
            r.get("subtitle"),
            r.get("status"),
            _parse_dt(r.get("open_time")),
            _parse_dt(r.get("close_time")),
            r.get("yes_bid_dollars"),
            r.get("yes_ask_dollars"),
            r.get("last_price_dollars"),
            r.get("volume_fp"),
            r.get("volume_24h_fp"),
            r.get("open_interest_fp"),
        )
        for r in records
    ]

    async with pool.acquire() as conn:
        await conn.executemany(sql, rows)

    logger.debug("upsert_markets: %d rows processed", len(rows))
    return len(rows)


async def get_markets(
    pool: asyncpg.Pool,
    *,
    event_ticker: str | None = None,
    status: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return a paginated list of market rows."""
    offset = _decode_cursor(cursor)
    params: list[Any] = []
    conditions: list[str] = []
    idx = 1

    if event_ticker is not None:
        conditions.append(f"event_ticker = ${idx}")
        params.append(event_ticker)
        idx += 1

    if status is not None:
        conditions.append(f"status = ${idx}")
        params.append(status)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = f"""
        SELECT ticker, event_ticker, market_type, yes_sub_title, no_sub_title,
               title, subtitle, status, open_time, close_time,
               yes_bid_dollars, yes_ask_dollars, last_price_dollars,
               volume_fp, volume_24h_fp, open_interest_fp, fetched_at
        FROM markets
        {where}
        ORDER BY ticker
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    params.extend([limit + 1, offset])

    async with pool.acquire() as conn:
        raw_rows = await conn.fetch(sql, *params)

    rows = [dict(r) for r in raw_rows]
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor = _encode_cursor(offset + limit) if has_more else None
    return rows, next_cursor


async def get_market(
    pool: asyncpg.Pool,
    ticker: str,
) -> dict[str, Any] | None:
    """Fetch a single market row by ticker. Returns None if not found."""
    sql = """
        SELECT ticker, event_ticker, market_type, yes_sub_title, no_sub_title,
               title, subtitle, status, open_time, close_time,
               yes_bid_dollars, yes_ask_dollars, last_price_dollars,
               volume_fp, volume_24h_fp, open_interest_fp, fetched_at
        FROM markets
        WHERE ticker = $1
    """
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, ticker)
    return dict(row) if row else None
