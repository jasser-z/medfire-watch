import io
from datetime import datetime, timezone

import pytest
from medfire_watch import fire_weather
from PIL import Image


def test_metadata_is_weather_index_never_probability_and_dates_are_explicit(tmp_path, monkeypatch):
    class Response:
        content = b'<WMS><Layer><Name>ecmwf.fwi</Name><Extent name="time" default="2099-12-31"/></Layer></WMS>'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fire_weather, "CACHE", tmp_path)
    monkeypatch.setattr(fire_weather.requests, "get", lambda *a, **kw: Response())
    result = fire_weather.metadata()
    assert result["probability"] is False
    assert result["occurrence_model_active"] is False
    assert result["forecast_issue_time"] is None
    assert result["dates"] == [datetime.now(timezone.utc).date().isoformat()]
    assert result["today"] == result["dates"][0]
    assert result["timezone"] == "UTC"
    assert [c["upper"] for c in result["classes"]] == [11.2, 21.3, 38, 50, 70, None]


def test_tile_rejects_invalid_coordinates_before_network():
    with pytest.raises(ValueError):
        fire_weather.tile(datetime.now(timezone.utc).date().isoformat(), 1, 3, 0)


def test_tile_preserves_provider_pixels_and_uses_web_mercator(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.new("RGBA", (256, 256), (156, 255, 192, 255)).save(image, format="PNG")
    calls = []

    class Response:
        content = image.getvalue()

        def raise_for_status(self):
            pass

    def fetch(*args, **kwargs):
        calls.append(kwargs["params"])
        return Response()

    monkeypatch.setattr(fire_weather, "CACHE", tmp_path)
    monkeypatch.setattr(fire_weather.requests, "get", fetch)
    day = datetime.now(timezone.utc).date().isoformat()
    assert fire_weather.tile(day, 0, 0, 0) == image.getvalue()
    assert fire_weather.tile(day, 0, 0, 0) == image.getvalue()
    assert len(calls) == 1
    assert calls[0]["srs"] == "EPSG:3857"
    assert calls[0]["time"] == day


def test_provider_xml_error_cannot_be_cached_as_a_safe_map(tmp_path, monkeypatch):
    class Response:
        content = b"<ServiceException>No data</ServiceException>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fire_weather, "CACHE", tmp_path)
    monkeypatch.setattr(fire_weather.requests, "get", lambda *a, **kw: Response())
    with pytest.raises(OSError):
        fire_weather.tile(datetime.now(timezone.utc).date().isoformat(), 0, 0, 0)
    assert not list(tmp_path.rglob("*.png"))


def test_current_local_day_rolls_over_without_reusing_yesterdays_date(tmp_path, monkeypatch):
    class Clock(datetime):
        instant = datetime(2026, 10, 30, 22, 59, tzinfo=timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    class Response:
        content = b'<WMS><Layer><Name>ecmwf.fwi</Name><Extent name="time" default="2026-11-02"/></Layer></WMS>'

        def raise_for_status(self):
            pass

    calls = []
    monkeypatch.setattr(fire_weather, "CACHE", tmp_path)
    monkeypatch.setattr(fire_weather, "datetime", Clock)
    monkeypatch.setattr(fire_weather.requests, "get", lambda *a, **kw: calls.append(kw) or Response())
    assert fire_weather.metadata("Africa/Tunis")["dates"] == ["2026-10-30"]
    Clock.instant = datetime(2026, 10, 30, 23, 1, tzinfo=timezone.utc)
    assert fire_weather.metadata("Africa/Tunis")["dates"] == ["2026-10-31"]
    assert fire_weather.metadata("UTC")["dates"] == ["2026-10-30"]
    assert len(calls) == 1  # Shared availability cache; local date is recalculated on every read.
    Clock.instant = datetime(2026, 10, 31, 0, 1, tzinfo=timezone.utc)
    assert fire_weather.metadata("America/Los_Angeles")["dates"] == ["2026-10-30"]
    assert fire_weather.metadata("Africa/Tunis")["dates"] == ["2026-10-31"]
    assert len(calls) == 2  # UTC provider-day boundary forces a new availability check.


def test_missing_today_never_falls_back_to_an_old_forecast(tmp_path, monkeypatch):
    class Response:
        content = b'<WMS><Layer><Name>ecmwf.fwi</Name><Extent name="time" default="2000-01-01"/></Layer></WMS>'

        def raise_for_status(self):
            pass

    monkeypatch.setattr(fire_weather, "CACHE", tmp_path)
    monkeypatch.setattr(fire_weather.requests, "get", lambda *a, **kw: Response())
    assert fire_weather.metadata("Africa/Tunis")["dates"] == []
