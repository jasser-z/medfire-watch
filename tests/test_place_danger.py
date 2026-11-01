import io

from medfire_watch import place_danger
from PIL import Image


def test_place_category_is_provider_class_and_weather_is_separate(monkeypatch):
    import medfire_watch.map_information as info

    picture = io.BytesIO()
    Image.new("RGBA", (256, 256), (*place_danger.PALETTE[2], 255)).save(picture, format="PNG")
    monkeypatch.setattr(
        place_danger, "metadata", lambda *a: {"dates": ["2026-10-29"], "source": "provider", "checked_utc": "now"}
    )
    monkeypatch.setattr(place_danger, "tile", lambda *a: picture.getvalue())
    weather_calls = []
    monkeypatch.setattr(place_danger, "local_weather", lambda *a: weather_calls.append(a) or {"available": False})
    monkeypatch.setattr(info, "nearest_town", lambda *a: {"available": False})
    result = place_danger.inspect_place(36, 10, "2026-10-29")
    assert result["weather_danger"] == "High"
    assert result["probability"] is None
    assert "vegetation" not in result
    assert not result["weather"]["available"]
    assert weather_calls[0][-1] == "auto"  # Selected place, never the viewer's timezone.


def test_dateline_tile_coordinates_stay_in_range():
    for lon in [-180, 180]:
        x, y, px, py = place_danger.pixel_location(0, lon)
        assert x == 0
        assert 0 <= y < 128 and 0 <= px < 256 and 0 <= py < 256


def test_current_weather_has_timestamps_and_timezone_separated_cache(tmp_path, monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "daily": {"time": ["2026-10-31"]},
                "daily_units": {"time": "iso8601"},
                "current": {"time": "2026-10-31T10:00", "temperature_2m": 22, "interval": 900},
                "current_units": {"temperature_2m": "°C"},
                "timezone": calls[-1]["timezone"],
            }

    monkeypatch.setattr(place_danger, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(place_danger.requests, "get", lambda *a, **kw: calls.append(kw["params"]) or Response())
    first = place_danger.local_weather(36.75, 10.25, "2026-10-31", "Africa/Tunis")
    assert first["current"]["time"] == "2026-10-31T10:00"
    assert first["current_units"]["temperature_2m"] == "°C"
    assert first["timezone"] == "Africa/Tunis"
    assert first["checked_utc"]
    place_danger.local_weather(36.75, 10.25, "2026-10-31", "Africa/Tunis")
    assert len(calls) == 1
    second = place_danger.local_weather(36.75, 10.25, "2026-10-31", "UTC")
    assert len(calls) == 2
    assert second["timezone"] == "UTC"
    assert calls[0]["timezone"] == "Africa/Tunis"
    assert "temperature_2m" in calls[0]["current"]


def test_selected_place_weather_uses_its_local_day_not_the_viewers_date(tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local_day = datetime.now(ZoneInfo("Asia/Almaty")).date().isoformat()
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "timezone": "Asia/Almaty",
                "utc_offset_seconds": 18000,
                "daily": {"time": [local_day]},
                "daily_units": {},
                "current": {"time": local_day + "T06:00"},
                "current_units": {},
            }

    monkeypatch.setattr(place_danger, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(place_danger.requests, "get", lambda *a, **kw: calls.append(kw["params"]) or Response())
    # The map's date is deliberately different from the selected location's local day.
    result = place_danger.local_weather(51, 78, "2026-10-01", "auto")
    assert calls[0]["timezone"] == "auto"
    assert calls[0]["forecast_days"] == 1
    assert "start_date" not in calls[0]
    assert result["timezone"] == "Asia/Almaty"
    assert result["daily"]["time"] == [local_day]
    place_danger.local_weather(51, 78, "2026-10-01", "auto")
    assert len(calls) == 1
