from api.main import app


def test_only_provider_weather_and_satellite_map_routes_remain():
    routes = set(app.openapi()["paths"])
    assert "/fire-weather/metadata" in routes
    assert "/fire-weather/place" in routes
    assert "/world-map/data" in routes
    retired = {
        "/predict-risk",
        "/risk-backtest",
        "/zones",
        "/zones/dates",
        "/live-risk",
        "/live-risk/refresh",
        "/world-map/forecast",
    }
    assert not retired & routes


def test_runtime_has_no_archive_modules_loaded():
    # Application import must not transitively import the retired model pipeline.
    # Other legacy tests may import these modules themselves, so inspect the API source dependencies.
    import ast
    import sys
    from pathlib import Path

    source = ast.parse(Path(sys.modules["api.main"].__file__).read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(source) if isinstance(node, ast.ImportFrom)}
    assert not {"etl.risk_data", "medfire_watch.risk_models", "medfire_watch.tracking"} & imports
