from datetime import UTC, datetime

from fastapi import APIRouter

from backend.api.schemas import HealthOut, to_utc_z


def build_router() -> APIRouter:
    router = APIRouter()

    @router.get("/", response_model=HealthOut)
    async def health() -> HealthOut:
        return HealthOut(current_time=to_utc_z(datetime.now(UTC)))

    return router
