from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ConnectionStatus(BaseModel):
    postgres: bool
    redis: bool


class MarketsPlaceholderResponse(BaseModel):
    status: str
    message: str
    markets: list[str]
    connections: ConnectionStatus


@router.get("/", response_model=MarketsPlaceholderResponse)
async def list_markets(request: Request) -> MarketsPlaceholderResponse:
    """Placeholder endpoint — returns scaffold status and connection health."""
    state = request.app.state
    return MarketsPlaceholderResponse(
        status="scaffold",
        message="Market data not yet connected. Kalshi integration coming in a future phase.",
        markets=[],
        connections=ConnectionStatus(
            postgres=getattr(state, "pg_pool", None) is not None,
            redis=getattr(state, "redis", None) is not None,
        ),
    )
