"""Version local map assets so embedded pages cannot reuse obsolete JavaScript."""

from hashlib import sha256

from medfire_watch.config import PROJECT_ROOT

ASSETS = (
    "satellite_map.html",
    "earth_watch.mjs",
    "map_style.mjs",
    "map_logic.mjs",
    "fire_weather_layer.mjs",
)


def map_asset_version() -> str:
    """Hash local map assets to invalidate the entire module chain."""
    digest = sha256()
    for name in ASSETS:
        digest.update((PROJECT_ROOT / "dashboard" / name).read_bytes())
    return digest.hexdigest()[:16]


def map_module(name: str) -> str:
    """Load a map module and version its local dependencies."""
    source = (PROJECT_ROOT / "dashboard" / name).read_text(encoding="utf-8")
    version = map_asset_version()
    for path in ("/world-map/style.mjs", "/world-map/logic.mjs", "/fire-weather/module.mjs"):
        source = source.replace("from '" + path + "'", "from '" + path + "?v=" + version + "'")
    return source
