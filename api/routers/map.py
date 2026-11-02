from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from medfire_watch.config import PROJECT_ROOT

router = APIRouter()
_world_refresh_error: str | None = None
logger = logging.getLogger(__name__)


def _world_refresh_loop(stop: threading.Event) -> None:
    """Keep the feed current even when browsers throttle or close their tabs."""
    last_retention = 0.0
    while not stop.is_set():
        # Check once a minute; refresh_if_old gates network requests on the ten-minute cache.
        _refresh_map_data()
        now = time.monotonic()
        if now - last_retention >= 600:
            try:
                from medfire_watch.retention import sweep_retention

                sweep_retention()
            except Exception as exc:
                logger.warning("Retention sweep failed (%s).", type(exc).__name__)
            last_retention = now
        if stop.wait(60):
            break


def _refresh_map_data() -> None:
    global _world_refresh_error
    from medfire_watch.world_hotspots import refresh_if_old

    try:
        result = refresh_if_old()
        if result is not None:  # A second request must not clear the active worker's failure state.
            _world_refresh_error = None
    except Exception as exc:
        _world_refresh_error = f"Latest update failed ({type(exc).__name__}); showing cached data."
        logger.warning("Satellite refresh failed (%s); cached observations retained.", type(exc).__name__)


@router.get("/world-map", response_class=HTMLResponse)
def satellite_map() -> str:
    """Serve the map document with versioned browser assets."""
    from medfire_watch.map_assets import map_asset_version

    html = (PROJECT_ROOT / "dashboard" / "satellite_map.html").read_text(encoding="utf-8")
    return html.replace("/world-map/app.mjs", "/world-map/app.mjs?v=" + map_asset_version())


@router.get("/world-map/data")
def satellite_map_data() -> dict[str, Any]:
    """Return cached observations and satellite refresh status."""
    from medfire_watch.world_hotspots import WORLD_PATH, load_world_hotspots, refresh_in_progress

    world = load_world_hotspots()
    if not WORLD_PATH.exists() and not refresh_in_progress():
        threading.Thread(target=_refresh_map_data, daemon=True).start()

    return {
        "world": world,
        "refresh_error": _world_refresh_error,
        "refresh_in_progress": refresh_in_progress(),
    }


_COUNTRIES_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_COUNTRIES_LOCK = threading.Lock()


@router.get("/world-map/countries/{kind}")
def countries(kind: str) -> dict[str, Any]:
    """Load the requested country boundaries or label catalogue, cached by file mtime."""
    if kind not in {"labels", "boundaries"}:
        raise HTTPException(404, "Country layer not found.")
    path = PROJECT_ROOT / "data" / "geospatial" / f"country_{kind}.json"
    if not path.is_file():
        raise HTTPException(503, "Country data is unavailable.")
    mtime = path.stat().st_mtime
    with _COUNTRIES_LOCK:
        if kind in _COUNTRIES_CACHE and _COUNTRIES_CACHE[kind][0] == mtime:
            return _COUNTRIES_CACHE[kind][1]
        data = json.loads(path.read_text(encoding="utf-8"))
        _COUNTRIES_CACHE[kind] = (mtime, data)
        return data


@router.get("/world-map/style.mjs")
def world_map_style() -> Response:
    """Serve versioned cartographic styling."""
    from medfire_watch.map_assets import map_module

    return Response(map_module("map_style.mjs"), media_type="text/javascript")


@router.get("/world-map/logic.mjs")
def world_map_logic() -> Response:
    """Serve observation-window and playback helper functions."""
    from medfire_watch.map_assets import map_module

    return Response(map_module("map_logic.mjs"), media_type="text/javascript")


@router.get("/world-map/app.mjs")
def world_map_app() -> Response:
    """Serve the versioned globe controller."""
    from medfire_watch.map_assets import map_module

    return Response(map_module("earth_watch.mjs"), media_type="text/javascript")


@router.get("/fire-weather/module.mjs")
def fire_weather_module() -> Response:
    """Serve current-day weather-layer behaviour."""
    from medfire_watch.map_assets import map_module

    return Response(map_module("fire_weather_layer.mjs"), media_type="text/javascript")


@router.get("/fire-weather/metadata")
def fire_weather_metadata(timezone_name: str = Query(default="UTC", alias="timezone", max_length=80)) -> dict:
    """Return provider issue dates for the requested timezone."""
    from medfire_watch.fire_weather import metadata

    try:
        return metadata(timezone_name)
    except (ValueError, KeyError):
        raise HTTPException(400, "Unknown weather timezone.") from None
    except Exception:
        raise HTTPException(503, "Fire-weather provider unavailable; no danger category can be inferred.") from None


@router.get("/fire-weather/place")
def fire_weather_place(
    date: str,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    timezone_name: str = Query(default="UTC", alias="timezone", max_length=80),
) -> dict:
    """Return current-day weather context for a coordinate."""
    from medfire_watch.place_danger import inspect_place

    try:
        return inspect_place(latitude, longitude, date, timezone_name)
    except (ValueError, KeyError):
        raise HTTPException(400, "Current-day weather/date or timezone unavailable.") from None
    except Exception:
        raise HTTPException(503, "Place forecast unavailable; no safe category inferred.") from None


@router.get("/fire-weather/tiles/{date}/{z}/{x}/{y}.png")
def fire_weather_tile(date: str, z: int, x: int, y: int) -> Response:
    """Return a cached provider danger tile."""
    from medfire_watch.fire_weather import tile

    try:
        return Response(tile(date, z, x, y), media_type="image/png", headers={"Cache-Control": "public,max-age=900"})
    except ValueError:
        raise HTTPException(400, "Invalid fire-weather tile.") from None
    except Exception:
        raise HTTPException(503, "Fire-weather tile unavailable; missing data is not low danger.") from None


@router.get("/world-map/nearest-town")
def nearest_map_town(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180)) -> dict:
    """Find the nearest catalogue town for a coordinate."""
    from medfire_watch.map_information import nearest_town

    return nearest_town(latitude, longitude)