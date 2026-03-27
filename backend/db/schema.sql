-- Kalshi Dashboard — initial schema
-- All statements use CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
-- so this file is safe to re-run (idempotent).
--
-- Tables
--   series            — Kalshi series (template for recurring events)
--   events            — Kalshi events (real-world occurrences with markets)
--   markets           — Individual outcome markets belonging to an event
--   raw_ingest_events — Raw payload archive before any derivation
--                       (REST hydration now; WebSocket events added in next slice)
--
-- Price / volume fields are stored as TEXT to match the upstream Kalshi API
-- string representations and avoid floating-point precision issues.

-- ---------------------------------------------------------------------------
-- series
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS series (
    ticker      TEXT        PRIMARY KEY,
    title       TEXT,
    category    TEXT,
    tags        TEXT[]      NOT NULL DEFAULT '{}',
    frequency   TEXT,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_series_category ON series (category);

-- ---------------------------------------------------------------------------
-- events
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_ticker        TEXT        PRIMARY KEY,
    series_ticker       TEXT        REFERENCES series (ticker) ON DELETE SET NULL,
    title               TEXT,
    sub_title           TEXT,
    category            TEXT,
    mutually_exclusive  BOOLEAN,
    status              TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_series_ticker ON events (series_ticker);
CREATE INDEX IF NOT EXISTS idx_events_status        ON events (status);
CREATE INDEX IF NOT EXISTS idx_events_category      ON events (category);

-- ---------------------------------------------------------------------------
-- markets
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS markets (
    ticker              TEXT        PRIMARY KEY,
    event_ticker        TEXT        REFERENCES events (event_ticker) ON DELETE SET NULL,
    market_type         TEXT,
    yes_sub_title       TEXT,
    no_sub_title        TEXT,
    title               TEXT,
    subtitle            TEXT,
    status              TEXT,
    open_time           TIMESTAMPTZ,
    close_time          TIMESTAMPTZ,
    yes_bid_dollars     TEXT,
    yes_ask_dollars     TEXT,
    last_price_dollars  TEXT,
    volume_fp           TEXT,
    volume_24h_fp       TEXT,
    open_interest_fp    TEXT,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_markets_event_ticker ON markets (event_ticker);
CREATE INDEX IF NOT EXISTS idx_markets_status       ON markets (status);
CREATE INDEX IF NOT EXISTS idx_markets_close_time   ON markets (close_time);

-- ---------------------------------------------------------------------------
-- raw_ingest_events
-- Authoritative archive of all raw payloads received from the exchange.
-- REST hydration writes here now; WebSocket events will route here in the
-- next architecture slice.  Derived state (bars, ladders, positions) must be
-- rebuildable from this table plus documented recovery flows.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw_ingest_events (
    id           BIGSERIAL   PRIMARY KEY,
    source       TEXT        NOT NULL,
    payload      JSONB       NOT NULL,
    exchange_ts  TIMESTAMPTZ,
    ingest_ts    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_raw_ingest_source    ON raw_ingest_events (source);
CREATE INDEX IF NOT EXISTS idx_raw_ingest_ingest_ts ON raw_ingest_events (ingest_ts);
