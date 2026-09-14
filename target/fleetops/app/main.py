from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .api.devices import router as devices_router
from .api.telemetry import router as telemetry_router
from .database import create_schema


def create_app(*, initialize_schema: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if initialize_schema:
            create_schema()
        yield

    application = FastAPI(title="FleetOps API", version="0.1.0", lifespan=lifespan)
    application.include_router(devices_router)
    application.include_router(telemetry_router)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
