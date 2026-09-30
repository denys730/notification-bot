"""The admin API cadmin talks to — the surface of an alerting service, without its pipeline.

Nothing here schedules a checker or delivers an alert. The routers read and write the collections
cadmin's Alert Bot proxy expects, so it needs no changes, and the MCP server (`src/mcp_server`) reads
them alongside.
"""

import sys
from pathlib import Path

# Modules under `src/` import each other as top-level packages. `uvicorn main:app --app-dir src` and
# the Docker image (`PYTHONPATH=/app/src`) already provide that; this keeps `src.main:app` working too.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging  # noqa: E402
from contextlib import asynccontextmanager  # noqa: E402
from http import HTTPStatus

from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from api.admin.alert_journal import router as alert_journal_router
from api.admin.checkers import router as checkers_router
from api.admin.global_settings import router as global_settings_router
from api.admin.segmentations import router as segmentations_router
from seed import seed_demo_data
from settings import settings
from storage.mongo import MongoStore

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app_: FastAPI):
    if not settings.BRANDS:
        raise ValueError("Environment variable BRANDS is not set")
    logger.info("Starting %s for brands %s", settings.APP_NAME, ", ".join(settings.BRANDS))
    client = AsyncIOMotorClient(settings.MONGO_URI, serverSelectionTimeoutMS=5000)
    store = MongoStore(client)
    app_.state.store = store
    await store.ensure_indexes(settings.BRANDS)
    if settings.SEED_ON_STARTUP:
        for brand, outcome in (await seed_demo_data(store, settings.BRANDS)).items():
            logger.info("seed %s: %s", brand, outcome)
    yield
    client.close()
    logger.info("Shutting down")


app = FastAPI(
    debug=settings.DEBUG,
    title=settings.APP_NAME,
    description="Alert Bot API for the cadmin service — demo with abstract alerts and no live data",
    version="1.0.0",
    lifespan=lifespan,
    redoc_url=None,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"loc": error["loc"], "message": error["msg"], "type": error["type"]} for error in exc.errors()]
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content=jsonable_encoder({"detail": details}))


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled exception: %s", exc, exc_info=True)
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": "Internal server error"})


class HealthCheckResponse(BaseModel):
    status: bool = Field(..., description="Overall health status of the application")
    mongo: bool = Field(..., description="MongoDB connection status")


@app.get("/api/healthcheck", response_model=HealthCheckResponse, tags=["system"], summary="Health Check")
async def health_check(request: Request, response: Response) -> HealthCheckResponse:
    """cadmin probes this when a service is registered; only the status code matters to it."""
    store: MongoStore | None = getattr(request.app.state, "store", None)
    mongo_ok = await store.ping() if store is not None else False
    if not mongo_ok:
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return HealthCheckResponse(status=mongo_ok, mongo=mongo_ok)


app.include_router(checkers_router)
app.include_router(segmentations_router)
app.include_router(global_settings_router)
app.include_router(alert_journal_router)
