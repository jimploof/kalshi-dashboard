"""Series repository — typed async queries against the `series` table.

All functions accept an asyncpg.Pool (injected from app.state.pg_pool via
the DbDep dependency) and return plain dicts that match the SeriesDTO shape
used in browse routes.

Upserts use INSERT ... ON CONFLICT (ticker) DO UPDATE SET so they are safe
to call repeatedly during hydration refreshes.
"""

import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def upsert_series(pool: asyncpg.Pool, records: list[dict[str, Any]]) -> int:
    """Bulk-upsert a list of raw series dicts into the series table.

    Returns the number of rows inserted or updated.
    All fields are optional except ticker.
    """
    if not records:
        return 0

    sql = """
        INSERT INTO series (ticker, title, category, tags, frequency, fetched_at)
        VALUES ($1, $2, $3, $4, $5, now())
        ON CONFLICT (ticker) DO UPDATE SET
            title      = EXCLUDED.title,
            category   = EXCLUDED.category,
            tags       = EXCLUDED.tags,
            frequency  = EXCLUDED.frequency,
            fetched_at = now()
    """

    rows: list[tuple[Any, ...]] = [
        (
            r["ticker"],
            r.get("title"),
            r.get("category"),
            r.get("tags") or [],
            r.get("frequency"),
        )
        for r in records
    ]

    async with pool.acquire() as conn:
        await conn.executemany(sql, rows)

    logger.debug("upsert_series: %d rows processed", len(rows))
    return len(rows)


async def get_series(
    pool: asyncpg.Pool,
    *,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Return series rows as plain dicts, optionally filtered by category."""
    if category is not None:
        sql = """
            SELECT ticker, title, category, tags, frequency, fetched_at
            FROM series
            WHERE category = $1
            ORDER BY ticker
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, category)
    else:
        sql = """
            SELECT ticker, title, category, tags, frequency, fetched_at
            FROM series
            ORDER BY ticker
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)

    return [dict(r) for r in rows]
