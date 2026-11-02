from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import requests
from alerts.manager import AlertManager
from api.main import app
from api.services import DetectionService
from fastapi.testclient import TestClient
from medfire_watch import map_information, secrets, world_hotspots

client = TestClient(app)


def test_detection_service_fake_model() -> None:
    service = DetectionService()

    # Create a mock YOLO model
    mock_model = MagicMock()
    mock_model.names = {0: "fire", 1: "smoke"}

    # Mock boxes
    mock_boxes = MagicMock()
    mock_boxes.xyxy.cpu().tolist.return_value = [[10.0, 20.0, 50.0, 60.0]]
    mock_boxes.cls.cpu().tolist.return_value = [0]
    mock_boxes.conf.cpu().tolist.return_value = [0.92]

    mock_result = MagicMock()
    mock_result.names = {0: "fire", 1: "smoke"}
    mock_result.boxes = mock_boxes
    mock_result.speed = {"inference": 5.2}

    def mock_predict(*args, **kwargs):
        source = kwargs.get("source", args[0] if args else None)
        count = len(source) if isinstance(source, list) else 1
        return [mock_result] * count

    mock_model.predict.side_effect = mock_predict

    service._model = mock_model
    img = np.zeros((100, 100, 3), dtype=np.uint8)

    res = service.predict(img)
    assert len(res["detections"]) == 1
    assert res["detections"][0]["class"] == "fire"
    assert res["detections"][0]["confidence"] == 0.92

    batch_res = service.predict_batch([img, img])
    assert len(batch_res) == 2

    # Test _format_result when boxes is None
    empty_result = MagicMock()
    empty_result.boxes = None
    formatted = service._format_result(empty_result, "cpu")
    assert formatted["detections"] == []


def test_map_routes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A fresh CI checkout has neither private provider keys nor an ignored feed cache.
    # Exercise the real cache reader with a fixture, without contacting NASA.
    world_path = tmp_path / "world_hotspots.json"
    world = {
        "observations": 1,
        "detections": [{"latitude": 36.8, "longitude": 10.2, "confidence": "nominal"}],
    }
    world_path.write_text(json.dumps(world), encoding="utf-8")
    load_world = world_hotspots.load_world_hotspots
    monkeypatch.setattr(world_hotspots, "WORLD_PATH", world_path)
    monkeypatch.setattr(world_hotspots, "_WORLD_CACHE", None)
    monkeypatch.setattr(world_hotspots, "load_world_hotspots", lambda: load_world(world_path))
    monkeypatch.setattr(world_hotspots, "refresh_if_old", lambda: False)
    monkeypatch.setattr(world_hotspots, "refresh_in_progress", lambda: False)
    monkeypatch.setattr("api.routers.map._world_refresh_error", None)

    def reject_network(*args, **kwargs):
        raise AssertionError("Map route checks must not contact external providers.")

    monkeypatch.setattr(requests.sessions.Session, "request", reject_network)
    # /world-map HTML
    resp = client.get("/world-map")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

    # /world-map/data
    resp = client.get("/world-map/data")
    assert resp.status_code == 200
    assert resp.json()["world"] == world

    # /world-map/countries
    resp = client.get("/world-map/countries/labels")
    assert resp.status_code == 200
    resp = client.get("/world-map/countries/boundaries")
    assert resp.status_code == 200
    resp = client.get("/world-map/countries/unknown_layer")
    assert resp.status_code == 404

    # Versioned JS assets
    for endpoint in [
        "/world-map/style.mjs",
        "/world-map/logic.mjs",
        "/world-map/app.mjs",
        "/fire-weather/module.mjs",
    ]:
        resp = client.get(endpoint)
        assert resp.status_code == 200
        assert "javascript" in resp.headers["content-type"]

    # /fire-weather/metadata invalid timezone
    resp = client.get("/fire-weather/metadata?timezone=Invalid/Timezone_XYZ")
    assert resp.status_code == 400

    # /fire-weather/tiles invalid format
    resp = client.get("/fire-weather/tiles/bad-date/0/0/0.png")
    assert resp.status_code == 400

    # /world-map/nearest-town
    resp = client.get("/world-map/nearest-town?latitude=36.8&longitude=10.2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["available"] is True


def test_map_information_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(map_information, "places", lambda: [])
    map_information._places_coordinates.cache_clear()
    res = map_information.nearest_town(35.0, 10.0)
    assert res == {"available": False}
    map_information._places_coordinates.cache_clear()


def test_world_hotspots_logic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Missing key raises RuntimeError
    monkeypatch.setenv("FIRMS_MAP_KEY", "")
    with pytest.raises(RuntimeError, match="NASA FIRMS key is not configured"):
        world_hotspots.refresh_world_hotspots()

    # Network error
    monkeypatch.setenv("FIRMS_MAP_KEY", "dummy_key")
    with patch("requests.get", side_effect=requests.RequestException("Network down")):
        with pytest.raises(RuntimeError, match="NASA FIRMS global request failed"):
            world_hotspots.refresh_world_hotspots()

    # HTTP error
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="HTTP 403"):
            world_hotspots.refresh_world_hotspots()

    # Missing CSV columns
    mock_resp.ok = True
    mock_resp.text = "latitude,longitude\n36.5,10.2\n"
    with patch("requests.get", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="expected columns"):
            world_hotspots.refresh_world_hotspots()

    # Valid CSV
    observed = datetime.now(timezone.utc) - timedelta(minutes=10)
    csv_data = (
        "latitude,longitude,acq_date,acq_time,frp,confidence,satellite\n"
        f"36.5,10.2,{observed:%Y-%m-%d},{observed:%H%M},15.5,nominal,VIIRS SNPP\n"
        f"36.6,10.3,{observed:%Y-%m-%d},{observed:%H%M},8.0,low,VIIRS SNPP\n"
    )
    mock_resp.text = csv_data
    dest_path = tmp_path / "hotspots.json"

    # Default filters out low confidence
    monkeypatch.setenv("MEDFIRE_INCLUDE_LOW_CONFIDENCE", "0")
    with patch("requests.get", return_value=mock_resp):
        result = world_hotspots.refresh_world_hotspots(dest_path)
        assert dest_path.is_file()
        assert result["observations"] == 1
        assert result["detections"][0]["confidence"] == "nominal"

    # Including low confidence
    monkeypatch.setenv("MEDFIRE_INCLUDE_LOW_CONFIDENCE", "1")
    with patch("requests.get", return_value=mock_resp):
        result = world_hotspots.refresh_world_hotspots(dest_path)
        assert result["observations"] == 2


def test_telegram_detect_chat_branches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mgr = AlertManager(cooldown_minutes=10, camera_cooldown_minutes=5, state_path=tmp_path / "state.json")
    mgr.log_path = tmp_path / "sent.jsonl"
    mgr.failure_log_path = tmp_path / "failed.jsonl"

    # No token
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(RuntimeError, match="bot token is not configured"):
        mgr.detect_chat()

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_bot_token")

    # API returns ok=False
    with patch("requests.get") as mock_get:
        mock_get.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"ok": False},
        )
        with pytest.raises(RuntimeError, match="rejected the chat lookup"):
            mgr.detect_chat()

    # API returns no private chats
    with patch("requests.get") as mock_get:
        mock_get.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "ok": True,
                "result": [{"message": {"chat": {"type": "group", "id": 123}}}],
            },
        )
        with pytest.raises(LookupError, match="No private chat was found"):
            mgr.detect_chat()


def test_telegram_send_and_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    mgr = AlertManager(cooldown_minutes=10, camera_cooldown_minutes=5, state_path=tmp_path / "state.json")
    mgr.log_path = tmp_path / "sent.jsonl"
    mgr.failure_log_path = tmp_path / "failed.jsonl"

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake_token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    # Mock successful photo send
    dummy_photo = tmp_path / "test.jpg"
    dummy_photo.write_bytes(b"dummy image bytes")

    with patch("requests.post") as mock_post:
        mock_post.return_value = SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"ok": True, "result": {"message_id": 999}},
        )
        res = mgr.send("Alert message", kind="live_camera", dedupe_key="live_camera", photo=dummy_photo)
        assert res["sent"] is True
        assert res["message_id"] == 999

        # Cooldown prevents repeat send
        res2 = mgr.send("Alert message 2", kind="live_camera", dedupe_key="live_camera")
        assert res2["sent"] is False
        assert res2["reason"] == "cooldown"

    # Record failure and check attempt log
    mgr.record_failure(kind="live_camera", attempt=1, reason="Network timeout")
    attempts = mgr.attempt_log(kind="live_camera")
    assert len(attempts) >= 2


def test_secrets_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Missing env file
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    assert secrets.read_firms_key(tmp_path / "nonexistent.env") is None

    # Env file with quotes and comments
    env_file = tmp_path / ".env"
    env_file.write_text('FIRMS_MAP_KEY="my_secret_key"\n', encoding="utf-8")
    assert secrets.read_firms_key(env_file) == "my_secret_key"

    # Mask secret
    assert secrets.mask_secret("Key is 12345", "12345") == "Key is [REDACTED]"
    assert secrets.mask_secret("No secret here", None) == "No secret here"


def test_telegram_detect_router(monkeypatch: pytest.MonkeyPatch) -> None:
    # Test POST /telegram/detect
    with patch("alerts.manager.AlertManager.detect_chat", return_value="98765"):
        resp = client.post("/telegram/detect")
        assert resp.status_code == 200
        assert resp.json()["chat_id"] == "98765"

    with patch("alerts.manager.AlertManager.detect_chat", side_effect=LookupError("No chat")):
        resp = client.post("/telegram/detect")
        assert resp.status_code == 409

    with patch("alerts.manager.AlertManager.detect_chat", side_effect=RuntimeError("Bot error")):
        resp = client.post("/telegram/detect")
        assert resp.status_code == 503
