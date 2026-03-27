"""Standalone script to apply backend/db/schema.sql to the configured PostgreSQL instance.

Reads DATABASE_URL from the environment (or backend/.env via pydantic-settings).
All statements in schema.sql use CREATE TABLE IF NOT EXISTS, so this script is
fully idempotent — safe to run against an existing database.

Usage (from project root):
    docker compose exec backend python -m scripts.init_db
    docker compose run --rm backend python -m scripts.init_db
"""

import asyncio
import logging
import pathlib

import asyncpg

from app.config import get_settings

logger = logging.getLogger(__name__)

_SCHEMA_PATH = pathlib.Path(__file__).parent.parent / "db" / "schema.sql"


async def _apply_schema() -> None:
    settings = get_settings()
    dsn = settings.asyncpg_dsn

    logger.info("Connecting to %s …", settings.safe_database_url())
    conn: asyncpg.Connection = await asyncpg.connect(dsn=dsn)
    try:
        sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        logger.info("Applying schema from %s …", _SCHEMA_PATH)
        await conn.execute(sql)
        logger.info("Schema applied successfully.")
    finally:
        await conn.close()


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    asyncio.run(_apply_schema())
