"""Raw ingest events repository — append-only archive of upstream payloads.

Per copilot-instructions rule 9: raw inbound exchange events must be preserved
before or alongside deeper derived processing.  REST hydration writes batches
here now; WebSocket events will route here in the next architecture slice.

The table is append-only.  Do not update or delete rows.
"""

import logging
from datetime import datetime
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)


async def insert_raw(
    pool: asyncpg.Pool,
    source: str,
    payload: dict[str, Any],
    exchange_ts: datetime | None = None,
) -> None:
    """Insert a single raw payload into raw_ingest_events."""
    sql = """
        INSERT INTO raw_ingest_events (source, payload, exchange_ts)
        VALUES ($1, $2, $3)
    """
    async with pool.acquire() as conn:
        import json
        await conn.execute(sql, source, json.dumps(payload), exchange_ts)


async def insert_raw_batch(
    pool: asyncpg.Pool,
    source: str,
    payloads: list[dict[str, Any]],
    exchange_ts: datetime | None = None,
) -> None:
    """Insert a batch of raw payloads in a single transaction.

    All rows in the batch share the same source and exchange_ts.
    """
    if not payloads:
        return

    import json

    sql = """
        INSERT INTO raw_ingest_events (source, payload, exchange_ts)
        VALUES ($1, $2, $3)
    """
    rows: list[tuple[str, str, datetime | None]] = [
        (source, json.dumps(p), exchange_ts) for p in payloads
    ]

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(sql, rows)

    logger.debug("insert_raw_batch: %d rows written for source=%r", len(rows), source)
