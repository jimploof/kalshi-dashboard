from collections.abc import Sequence
from typing import Any

import asyncpg

CREATE_SIGNAL_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS market_signal_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_ticker TEXT NOT NULL,
    event_ticker TEXT,
    mode TEXT NOT NULL DEFAULT 'strict',
    signal_direction TEXT NOT NULL,
    confidence SMALLINT NOT NULL,
    buy_score SMALLINT NOT NULL,
    sell_score SMALLINT NOT NULL,
    entry_note TEXT,
    stop_note TEXT,
    target_note TEXT,
    conditions_met JSONB NOT NULL DEFAULT '{}'::jsonb,
    diagnostics JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'frontend-market-view'
);
"""

CREATE_SIGNAL_EVENTS_MODE_COLUMN_SQL = """
ALTER TABLE market_signal_events
ADD COLUMN IF NOT EXISTS mode TEXT NOT NULL DEFAULT 'strict';
"""

CREATE_SIGNAL_LIFECYCLE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS market_signal_lifecycle_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    market_ticker TEXT NOT NULL,
    event_ticker TEXT,
    mode TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL,
    signal_direction TEXT,
    position_side TEXT NOT NULL,
    trigger_price_cents INTEGER,
    elapsed_ms INTEGER,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'frontend-market-view'
);
"""

CREATE_SIGNAL_EVENTS_INDEXES_SQL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_market_signal_events_market_created ON market_signal_events (market_ticker, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_market_signal_events_event_created ON market_signal_events (event_ticker, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_market_signal_events_direction_created ON market_signal_events (signal_direction, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_market_signal_events_mode_created ON market_signal_events (mode, created_at DESC);",
)

CREATE_SIGNAL_LIFECYCLE_INDEXES_SQL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_market_signal_lifecycle_market_created ON market_signal_lifecycle_events (market_ticker, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_market_signal_lifecycle_mode_created ON market_signal_lifecycle_events (mode, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_market_signal_lifecycle_state_created ON market_signal_lifecycle_events (lifecycle_state, created_at DESC);",
)


async def ensure_signal_events_schema(pool: asyncpg.Pool) -> None:
    """Create signal-event table and indexes if they do not exist."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_SIGNAL_EVENTS_TABLE_SQL)
        await conn.execute(CREATE_SIGNAL_EVENTS_MODE_COLUMN_SQL)
        await conn.execute(CREATE_SIGNAL_LIFECYCLE_TABLE_SQL)
        for stmt in CREATE_SIGNAL_EVENTS_INDEXES_SQL:
            await conn.execute(stmt)
        for stmt in CREATE_SIGNAL_LIFECYCLE_INDEXES_SQL:
            await conn.execute(stmt)


async def insert_signal_event(
    pool: asyncpg.Pool,
    *,
    market_ticker: str,
    event_ticker: str | None,
    mode: str,
    signal_direction: str,
    confidence: int,
    buy_score: int,
    sell_score: int,
    entry_note: str | None,
    stop_note: str | None,
    target_note: str | None,
    conditions_met: dict[str, Any],
    diagnostics: dict[str, Any],
    source: str,
) -> int:
    """Insert a signal event and return the generated row id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO market_signal_events (
                market_ticker,
                event_ticker,
                mode,
                signal_direction,
                confidence,
                buy_score,
                sell_score,
                entry_note,
                stop_note,
                target_note,
                conditions_met,
                diagnostics,
                source
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12::jsonb, $13)
            RETURNING id
            """,
            market_ticker,
            event_ticker,
            mode,
            signal_direction,
            confidence,
            buy_score,
            sell_score,
            entry_note,
            stop_note,
            target_note,
            conditions_met,
            diagnostics,
            source,
        )
    return int(row["id"])


async def fetch_signal_events(
    pool: asyncpg.Pool,
    *,
    market_ticker: str | None,
    event_ticker: str | None,
    mode: str | None,
    direction: str | None,
    limit: int,
) -> Sequence[asyncpg.Record]:
    """Fetch recent signal events with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if market_ticker:
        params.append(market_ticker)
        conditions.append(f"market_ticker = ${len(params)}")

    if event_ticker:
        params.append(event_ticker)
        conditions.append(f"event_ticker = ${len(params)}")

    if mode:
        params.append(mode)
        conditions.append(f"mode = ${len(params)}")

    if direction:
        params.append(direction)
        conditions.append(f"signal_direction = ${len(params)}")

    params.append(limit)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            id,
            created_at,
            market_ticker,
            event_ticker,
            mode,
            signal_direction,
            confidence,
            buy_score,
            sell_score,
            entry_note,
            stop_note,
            target_note,
            conditions_met,
            diagnostics,
            source
        FROM market_signal_events
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
    """

    async with pool.acquire() as conn:
        return await conn.fetch(query, *params)


async def insert_signal_lifecycle_event(
    pool: asyncpg.Pool,
    *,
    market_ticker: str,
    event_ticker: str | None,
    mode: str,
    lifecycle_state: str,
    signal_direction: str | None,
    position_side: str,
    trigger_price_cents: int | None,
    elapsed_ms: int | None,
    payload: dict[str, Any],
    source: str,
) -> int:
    """Insert a lifecycle transition event and return its id."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO market_signal_lifecycle_events (
                market_ticker,
                event_ticker,
                mode,
                lifecycle_state,
                signal_direction,
                position_side,
                trigger_price_cents,
                elapsed_ms,
                payload,
                source
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            RETURNING id
            """,
            market_ticker,
            event_ticker,
            mode,
            lifecycle_state,
            signal_direction,
            position_side,
            trigger_price_cents,
            elapsed_ms,
            payload,
            source,
        )
    return int(row["id"])


async def fetch_signal_lifecycle_events(
    pool: asyncpg.Pool,
    *,
    market_ticker: str | None,
    event_ticker: str | None,
    mode: str | None,
    lifecycle_state: str | None,
    limit: int,
) -> Sequence[asyncpg.Record]:
    """Fetch lifecycle transition events with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []

    if market_ticker:
        params.append(market_ticker)
        conditions.append(f"market_ticker = ${len(params)}")

    if event_ticker:
        params.append(event_ticker)
        conditions.append(f"event_ticker = ${len(params)}")

    if mode:
        params.append(mode)
        conditions.append(f"mode = ${len(params)}")

    if lifecycle_state:
        params.append(lifecycle_state)
        conditions.append(f"lifecycle_state = ${len(params)}")

    params.append(limit)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    query = f"""
        SELECT
            id,
            created_at,
            market_ticker,
            event_ticker,
            mode,
            lifecycle_state,
            signal_direction,
            position_side,
            trigger_price_cents,
            elapsed_ms,
            payload,
            source
        FROM market_signal_lifecycle_events
        {where_clause}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
    """

    async with pool.acquire() as conn:
        return await conn.fetch(query, *params)
