"""Application lifecycle, shared middleware and feature router registration."""

from __future__ import annotations

import os
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from medfire_watch.config import env_number, load_env

from api import auth
from api.routers import alerts, detection, map, storage, video
from api.services import get_detection_service


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Warm inference and manage the satellite refresh worker."""
    from starlette.concurrency import run_in_threadpool

    env_number("MEDFIRE_VIDEO_TTL_HOURS", 24, 0, 8760)
    env_number("MEDFIRE_MAX_VIDEO_JOBS", 2, 1, 16, integer=True)
    env_number("MEDFIRE_MAX_CAMERA_SESSIONS", 64, 1, 1024, integer=True)
    env_number("MEDFIRE_MAX_STORED_VIDEO_JOBS", 64, 1, 4096, integer=True)
    env_number("MEDFIRE_VIDEO_UPLOAD_TIMEOUT_SECONDS", 300, 1, 3600)
    if os.getenv("MEDFIRE_SKIP_WARMUP") != "1":
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


try:
    API_VERSION = version("medfire-watch")
except PackageNotFoundError:
    API_VERSION = "0.1.0"

app = FastAPI(title="MedFire Watch API", version=API_VERSION, lifespan=lifespan)
load_env()


def _extract_hostname(host_str: str) -> str:
    host_str = host_str.strip()
    if host_str.startswith("["):
        closing = host_str.find("]")
        if closing != -1:
            return host_str[1:closing].lower()
    if ":" in host_str:
        return host_str.split(":", 1)[0].lower()
    return host_str.lower()


def _get_allowed_hosts() -> set[str]:
    # Default allowed hosts: 127.0.0.1, localhost, [::1], plus testserver for Starlette TestClient
    allowed = {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
    extra = os.getenv("MEDFIRE_ALLOWED_HOSTS", "").strip()
    if extra:
        for item in extra.split(","):
            val = item.strip()
            if val:
                allowed.add(val.lower())
                allowed.add(_extract_hostname(val))
    return allowed


def _get_allowed_origins(request: Request) -> set[str]:
    allowed: set[str] = set()
    host = request.headers.get("host", "").strip().lower()
    if host:
        allowed.add(f"http://{host}")
        allowed.add(f"https://{host}")
        if request.url.scheme:
            allowed.add(f"{request.url.scheme}://{host}")
    hostname = _extract_hostname(host) if host else "localhost"
    dashboard_port = os.getenv("STREAMLIT_SERVER_PORT", "8501")
    for h in ("127.0.0.1", "localhost", "[::1]", hostname):
        allowed.add(f"http://{h}:{dashboard_port}")
        allowed.add(f"https://{h}:{dashboard_port}")
        allowed.add(f"http://{h}:8501")
        allowed.add(f"https://{h}:8501")
    if host == "testserver":
        allowed.add("http://testserver")
        allowed.add("https://testserver")
    extra = os.getenv("MEDFIRE_ALLOWED_ORIGINS", "").strip()
    if extra:
        for item in extra.split(","):
            val = item.strip().rstrip("/").lower()
            if val:
                allowed.add(val)
    return allowed


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


@app.middleware("http")
async def api_guard_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Validate host header, cross-origin requests, and optional authentication token."""
    host_header = request.headers.get("host", "").strip()
    if not host_header:
        return JSONResponse(status_code=400, content={"detail": "Missing Host header."})
    hostname = _extract_hostname(host_header)
    allowed_hosts = _get_allowed_hosts()
    if hostname not in allowed_hosts and host_header.lower() not in allowed_hosts:
        return JSONResponse(status_code=400, content={"detail": f"Host '{host_header}' is not allowed."})

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin:
            clean_origin = origin.strip().rstrip("/").lower()
            allowed_origins = _get_allowed_origins(request)
            if clean_origin not in allowed_origins:
                return JSONResponse(status_code=403, content={"detail": "Cross-origin request forbidden."})

    public_read = False
    api_token = os.getenv("MEDFIRE_API_TOKEN", "").strip()
    if api_token:
        path = request.url.path
        public_read = path in {
            "/health",
            "/auth/login",
            "/world-map",
            "/world-map/data",
            "/world-map/nearest-town",
            "/world-map/style.mjs",
            "/world-map/logic.mjs",
            "/world-map/app.mjs",
            "/world-map/countries/labels",
            "/world-map/countries/boundaries",
            "/fire-weather/metadata",
            "/fire-weather/place",
            "/fire-weather/module.mjs",
        } or path.startswith("/fire-weather/tiles/")
        requires_token = path != "/auth/session" and not (request.method in {"GET", "HEAD", "OPTIONS"} and public_read)
        if requires_token:
            by_header = auth.valid_token(request.headers.get("x-medfire-token", ""), api_token)
            by_cookie = auth.valid_session(request.cookies.get(auth.COOKIE_NAME, ""), api_token)
            if not by_header and not by_cookie:
                if request.method == "GET" and path in {"/live-camera", "/video-test"}:
                    return RedirectResponse(f"/auth/login?next={path}", status_code=303)
                return JSONResponse(status_code=401, content={"detail": "Invalid or missing X-MedFire-Token."})
            if by_cookie and not by_header and request.method not in {"GET", "HEAD", "OPTIONS"}:
                # Browser writes always send Origin. No cookie-authenticated blind CSRF requests.
                if not request.headers.get("origin"):
                    return JSONResponse(status_code=403, content={"detail": "Session writes require an Origin header."})

    response = await call_next(request)
    if api_token and not public_read:
        response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


for router in (auth.router, map.router, detection.router, video.router, alerts.router, storage.router):
    app.include_router(router)
