from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from alerts.manager import AlertManager
from api import services as api_services
from api.main import app
from api.services import get_alert_manager
from fastapi.testclient import TestClient
from medfire_watch import world_hotspots
from medfire_watch.browser_camera import MAX_QUEUE_BYTES, BrowserCameraMonitor


class FakeDetector:
    def __init__(self) -> None:
        self.live_alert_confidence = 0.5
        self.live_alert_min_box_fraction = 0.01

    def predict(self, image: np.ndarray) -> dict:
        return {
            "detections": [
                {"class": "fire", "confidence": 0.8, "xyxy": [10.0, 10.0, 200.0, 200.0]}
            ]
        }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("alerts.manager.get_setting", lambda name: None)
    app.dependency_overrides[get_alert_manager] = lambda: AlertManager(state_path=tmp_path / "state.json")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_api_version_single_source():
    assert app.version == "0.1.0"


def test_video_source_media_types(client: TestClient, tmp_path: Path):
    for suffix, expected_type in [
        (".mp4", "video/mp4"),
        (".mov", "video/quicktime"),
        (".avi", "video/x-msvideo"),
        (".webm", "video/webm"),
    ]:
        job_id = f"test_{suffix[1:]}"
        dummy_file = tmp_path / f"{job_id}{suffix}"
        dummy_file.write_bytes(b"dummy-video-data")
        api_services.VIDEO_SOURCE_PATHS[job_id] = dummy_file
        try:
            res = client.get(f"/video-jobs/{job_id}/source")
            assert res.status_code == 200
            assert expected_type in res.headers["content-type"]
        finally:
            api_services.VIDEO_SOURCE_PATHS.pop(job_id, None)


def test_per_session_camera_trackers():
    monitor = BrowserCameraMonitor(detector_width=960, persistence_seconds=1.0, min_iou=0.3)
    detector = FakeDetector()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    # First update for session A
    res_a1 = monitor.process(frame, detector, session_id="session_A")
    assert not res_a1["alert_active"]

    # First update for session B
    res_b1 = monitor.process(frame, detector, session_id="session_B")
    assert not res_b1["alert_active"]

    # Verify session A and session B have different tracker instances
    trk_a = monitor._trackers["session_A"][0]
    trk_b = monitor._trackers["session_B"][0]
    assert trk_a is not trk_b


def test_camera_queue_memory_budget_bounded(monkeypatch: pytest.MonkeyPatch):
    monitor = BrowserCameraMonitor()
    # Add a pending alert item
    detection = {"class": "fire", "confidence": 0.9, "xyxy": [10, 10, 50, 50]}
    monitor._pending["alert1"] = {
        "detections": [detection],
        "alert": {"detection": detection},
        "image_width": 640,
        "image_height": 480,
    }

    # Simulate already used bytes near max
    monitor._queued_bytes = MAX_QUEUE_BYTES - 100

    # Large frame that would exceed budget
    large_frame = np.zeros((100, 100, 3), dtype=np.uint8)  # 30,000 bytes > 100 bytes remaining
    assert large_frame.nbytes > 100

    # Should be rejected
    rejected = monitor.submit_full_resolution_snapshot("alert1", large_frame)
    assert not rejected
    assert monitor.failure_count == 1
    assert "byte budget exceeded" in (monitor.last_error or "")


def test_camera_cooldown_minutes_used_for_live_camera(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import alerts.manager as manager_module

    class DummyResponse:
        def raise_for_status(self):
            pass
        def json(self):
            return {"ok": True, "result": {"message_id": 100}}

    monkeypatch.setattr(manager_module.requests, "post", lambda *a, **k: DummyResponse())
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    # Manager with 60m general cooldown and 5m camera cooldown
    manager = AlertManager(cooldown_minutes=60, camera_cooldown_minutes=5, state_path=tmp_path / "state.json")

    # First live_camera send succeeds
    first = manager.send("Alert 1", kind="live_camera", dedupe_key="live_camera")
    assert first.get("sent") is True

    # Immediate second live_camera send blocked by cooldown
    second = manager.send("Alert 2", kind="live_camera", dedupe_key="live_camera")
    assert second.get("sent") is False
    assert second.get("reason") == "cooldown"

    # Status reports both cooldowns
    st = manager.status()
    assert st["cooldown_minutes"] == 60
    assert st["camera_cooldown_minutes"] == 5


def test_world_hotspots_low_confidence_filter_env_control(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "world.json"
    path.write_text(
        json.dumps(
            {
                "observations": 3,
                "detections": [
                    {"confidence": "low", "latitude": 10.0, "longitude": 10.0},
                    {"confidence": "l", "latitude": 20.0, "longitude": 20.0},
                    {"confidence": "nominal", "latitude": 30.0, "longitude": 30.0},
                ],
            }
        ),
        encoding="utf-8",
    )

    # 1. By default, low confidence is excluded
    monkeypatch.delenv("MEDFIRE_INCLUDE_LOW_CONFIDENCE", raising=False)
    data_default = world_hotspots.load_world_hotspots(path)
    assert len(data_default["detections"]) == 1
    assert data_default["detections"][0]["confidence"] == "nominal"

    # 2. When MEDFIRE_INCLUDE_LOW_CONFIDENCE=1, low confidence is retained
    monkeypatch.setenv("MEDFIRE_INCLUDE_LOW_CONFIDENCE", "1")
    data_included = world_hotspots.load_world_hotspots(path)
    assert len(data_included["detections"]) == 3
