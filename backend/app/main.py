import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.lifespan import lifespan
from app.routers import (
    catalog,
    debug,
    health,
    kalshi,
    market,
    markets,
    orders,
    ready,
    replay,
    sessions,
    signal_events,
)

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(
    title="Kalshi Dashboard API",
    version="0.1.0",
    description="Backend for the Kalshi trading workstation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(ready.router, prefix="/api")
app.include_router(kalshi.router, prefix="/api")
app.include_router(catalog.router, prefix="/api", tags=["catalog"])
app.include_router(debug.router, prefix="/api")
app.include_router(market.router_rest, prefix="/api", tags=["market"])
app.include_router(markets.router, prefix="/api/markets", tags=["markets"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(replay.router, prefix="/api/replay", tags=["replay"])
app.include_router(signal_events.router, prefix="/api", tags=["signal-events"])
app.include_router(sessions.router, prefix="/ws", tags=["sessions"])
app.include_router(market.router_ws, prefix="/ws", tags=["market"])
