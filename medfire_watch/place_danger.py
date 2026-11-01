"""Small on-demand place context for the public weather-danger baseline."""

from __future__ import annotations

import io
import json
import math
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from medfire_watch.config import PROJECT_ROOT
from medfire_watch.fire_weather import CLASSES, metadata, tile

PALETTE = [(156, 255, 192), (205, 226, 78), (230, 172, 0), (217, 112, 16), (173, 6, 14), (58, 0, 21)]


def pixel_location(latitude: float, longitude: float, zoom: int = 7) -> tuple[int, int, int, int]:
    """Convert a coordinate into tile indices and its pixel position."""
    lat = max(-85.05112878, min(85.05112878, latitude))
    x = ((longitude + 180) % 360) / 360 * 2**zoom
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2**zoom
    return int(x), min(2**zoom - 1, int(y)), int((x % 1) * 256), min(255, int((y % 1) * 256))


def local_weather(latitude: float, longitude: float, date: str, timezone_name: str = "auto") -> dict[str, Any]:
    """Load current-day model weather with a fifteen-minute cache."""
    folder = PROJECT_ROOT / "data/fire_weather/place_weather"
    folder.mkdir(parents=True, exist_ok=True)
    zone_key = sha256(timezone_name.encode()).hexdigest()[:12]
    path = folder / f"current_{latitude:.3f}_{longitude:.3f}_{date}_{zone_key}.json"
    if path.exists() and datetime.now(timezone.utc).timestamp() - path.stat().st_mtime < 900:
        # Local-date validation prevents a warm cache from presenting yesterday as today.
        saved = json.loads(path.read_text(encoding="utf-8"))
        if (
            timezone_name != "auto"
            or saved["daily"]["time"][0] == datetime.now(ZoneInfo(saved["timezone"])).date().isoformat()
        ):
            return saved
    try:
        period = {"forecast_days": 1} if timezone_name == "auto" else {"start_date": date, "end_date": date}
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                **period,
                "daily": "temperature_2m_max,relative_humidity_2m_min,wind_speed_10m_max,precipitation_sum",
                "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation",
                "wind_speed_unit": "kmh",
                "timezone": timezone_name,
            },
            timeout=(5, 12),
        )
        response.raise_for_status()
        source = response.json()
        payload = {
            "available": True,
            "daily": source["daily"],
            "units": source["daily_units"],
            "current": source.get("current", {}),
            "current_units": source.get("current_units", {}),
            "timezone": source.get("timezone", timezone_name),
            "utc_offset_seconds": source.get("utc_offset_seconds", 0),
            "source": "Open-Meteo",
            "checked_utc": datetime.now(timezone.utc).isoformat(),
            "meaning": (
                "Current model-based conditions and today summary; not live sensor readings or Copernicus attribution."
            ),
        }
        temporary = path.with_name(path.name + "." + uuid4().hex + ".part")
        temporary.write_text(json.dumps(payload), encoding="utf-8")
        temporary.replace(path)
        return payload
    except Exception as exc:
        return {"available": False, "reason": type(exc).__name__}


def inspect_place(latitude: float, longitude: float, date: str, timezone_name: str = "UTC") -> dict[str, Any]:
    """Combine provider danger class, place name and local weather."""
    meta = metadata(timezone_name)
    if date not in meta["dates"]:
        raise ValueError("Forecast date unavailable")
    x, y, px, py = pixel_location(latitude, longitude)
    category = None
    if abs(latitude) <= 85.05112878:
        with Image.open(io.BytesIO(tile(date, 7, x, y))) as image:
            red, green, blue, alpha = image.convert("RGBA").getpixel((px, py))
        if alpha and (red, green, blue) in PALETTE:
            category = CLASSES[PALETTE.index((red, green, blue))]["name"]
    from medfire_watch.map_information import nearest_town

    return {
        "latitude": latitude,
        "longitude": longitude,
        "valid_date": date,
        "weather_danger": category,
        "category_method": "Class read from the official forecast display; no numeric FWI inferred.",
        "probability": None,
        "source": meta["source"],
        "checked_utc": meta["checked_utc"],
        "forecast_issue_time": None,
        "weather": local_weather(latitude, longitude, date, "auto"),
        "nearest_town": nearest_town(latitude, longitude),
        "meaning": "Conditions favourable to vegetation fires; not a prediction that this place will ignite.",
    }
