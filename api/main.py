"""Application lifecycle, shared middleware and feature router registration."""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import Response
from medfire_watch.config import load_env

from api.routers import alerts, detection, map, video
from api.services import get_detection_service


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Warm inference and manage the satellite refresh worker."""
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(get_detection_service().warmup)
    stop_refresh = threading.Event()
    refresh_worker = threading.Thread(
        target=map._world_refresh_loop, args=(stop_refresh,), daemon=True, name="satellite-refresh"
    )
    refresh_worker.start()
    try:
        yield
    finally:
        stop_refresh.set()
        await run_in_threadpool(refresh_worker.join, 1)


app = FastAPI(title="MedFire Watch API", version="1.0.0", lifespan=lifespan)
load_env()


@app.middleware("http")
async def fresh_map_assets(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Prevent stale map documents, modules and place metadata."""
    response = await call_next(request)
    path = request.url.path
    if (
        path == "/world-map"
        or path.endswith(".mjs")
        or path
        in {
            "/fire-weather/metadata",
            "/fire-weather/place",
        }
    ):
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


for router in (map.router, detection.router, video.router, alerts.router):
    app.include_router(router)
