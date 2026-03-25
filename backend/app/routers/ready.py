from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

router = APIRouter(tags=["readiness"])


class DependencyChecks(BaseModel):
    postgres: bool
    redis: bool


class ReadinessResponse(BaseModel):
    ready: bool
    checks: DependencyChecks


@router.get("/ready", response_model=ReadinessResponse)
async def readiness(request: Request, response: Response) -> ReadinessResponse:
    """
    Readiness probe — returns 200 when all dependencies are up, 503 otherwise.

    Reads the explicit state flags set by the lifespan manager. Safe to call
    at any point without touching connection pool objects directly.
    """
    state = request.app.state
    pg_ok = getattr(state, "pg_ready", False)
    redis_ok = getattr(state, "redis_ready", False)
    is_ready = pg_ok and redis_ok

    if not is_ready:
        response.status_code = 503

    return ReadinessResponse(
        ready=is_ready,
        checks=DependencyChecks(postgres=pg_ok, redis=redis_ok),
    )
