from __future__ import annotations

import io
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
from alerts.manager import AlertManager
from api import services as api_services
from api.main import app
from api.services import get_alert_manager, get_detection_service
from fastapi.testclient import TestClient
from medfire_watch import fire_weather
from medfire_watch.retention import sweep_retention
from PIL import Image


class FakeDetectionService:
    confidence_threshold = 0.3
    consecutive_alert_frames = 5
    max_video_upload_bytes = 100 * 1024 * 1024
    max_video_duration_seconds = 120

    def predict(self, image: np.ndarray) -> dict[str, object]:
        return {
            "detections": [],
            "speed_ms": {"inference": 5.0},
            "device": "cpu",
            "confidence_threshold": self.confidence_threshold,
        }


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("alerts.manager.get_setting", lambda name: None)
    app.dependency_overrides[get_detection_service] = FakeDetectionService
    app.dependency_overrides[get_alert_manager] = lambda: AlertManager(state_path=tmp_path / "state.json")
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_sweep_deletes_old_files_and_dict_entries_keeps_fresh_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_dir = tmp_path / "runs" / "video_results"
    video_dir.mkdir(parents=True, exist_ok=True)
    fw_dir = tmp_path / "data" / "fire_weather"
    tiles_dir = fw_dir / "tiles" / "2026-11-01" / "7" / "1"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    pw_dir = fw_dir / "place_weather"
    pw_dir.mkdir(parents=True, exist_ok=True)
    webcam_alerts_dir = tmp_path / "runs" / "webcam_alerts"
    webcam_alerts_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(api_services, "VIDEO_RESULT_DIR", video_dir)
    monkeypatch.setattr("medfire_watch.retention.PROJECT_ROOT", tmp_path)

    # 1. Create old and fresh video files
    old_video_file = video_dir / "oldjob123.mp4"
    old_video_file.write_bytes(b"old-video")
    fresh_video_file = video_dir / "freshjob456.mp4"
    fresh_video_file.write_bytes(b"fresh-video")

    now = time.time()
    os.utime(old_video_file, (now - 90000, now - 90000))  # 25 hours old
    os.utime(fresh_video_file, (now - 3600, now - 3600))  # 1 hour old

    # Populate VIDEO_* dicts
    with api_services.VIDEO_JOB_LOCK:
        api_services.VIDEO_JOB_STATUS["oldjob123"] = {"status": "complete"}
        api_services.VIDEO_RESULT_PATHS["oldjob123"] = old_video_file
        api_services.VIDEO_SOURCE_PATHS["oldjob123"] = old_video_file
        api_services.VIDEO_FRAME_DETECTIONS["oldjob123"] = [{"time": 0.0}]
        api_services.VIDEO_PREPARED_INPUTS["oldjob123"] = {"path": old_video_file}
        api_services.VIDEO_SEEK_REQUESTS["oldjob123"] = 1.0

        api_services.VIDEO_JOB_STATUS["freshjob456"] = {"status": "complete"}
        api_services.VIDEO_RESULT_PATHS["freshjob456"] = fresh_video_file
        api_services.VIDEO_SOURCE_PATHS["freshjob456"] = fresh_video_file
        api_services.VIDEO_FRAME_DETECTIONS["freshjob456"] = [{"time": 0.0}]
        api_services.VIDEO_PREPARED_INPUTS["freshjob456"] = {"path": fresh_video_file}
        api_services.VIDEO_SEEK_REQUESTS["freshjob456"] = 1.0

    # 2. Create old and fresh fire-weather files
    old_tile = tiles_dir / "1.png"
    old_tile.write_bytes(b"old-tile")
    os.utime(old_tile, (now - 90000, now - 90000))

    fresh_tile = tiles_dir / "2.png"
    fresh_tile.write_bytes(b"fresh-tile")
    os.utime(fresh_tile, (now - 1800, now - 1800))

    old_pw = pw_dir / "current_36.75_10.25_2026-11-01_abcdef.json"
    old_pw.write_bytes(b"{}")
    os.utime(old_pw, (now - 90000, now - 90000))

    fresh_pw = pw_dir / "current_36.80_10.30_2026-11-01_abcdef.json"
    fresh_pw.write_bytes(b"{}")
    os.utime(fresh_pw, (now - 600, now - 600))

    # 3. Create webcam alert file (must never be touched)
    webcam_alert_file = webcam_alerts_dir / "alert_20261101_120000_123456.jpg"
    webcam_alert_file.write_bytes(b"webcam-alert-photo")
    os.utime(webcam_alert_file, (now - 90000, now - 90000))

    # Run sweep
    result = sweep_retention()
    assert result["video_results_deleted"] >= 1
    assert result["fire_weather_pruned"] >= 2

    # Assert old video results deleted, fresh preserved
    assert not old_video_file.exists()
    assert fresh_video_file.exists()

    # Assert old dict entries deleted, fresh preserved
    with api_services.VIDEO_JOB_LOCK:
        assert "oldjob123" not in api_services.VIDEO_JOB_STATUS
        assert "oldjob123" not in api_services.VIDEO_RESULT_PATHS
        assert "oldjob123" not in api_services.VIDEO_SOURCE_PATHS
        assert "oldjob123" not in api_services.VIDEO_FRAME_DETECTIONS
        assert "oldjob123" not in api_services.VIDEO_PREPARED_INPUTS
        assert "oldjob123" not in api_services.VIDEO_SEEK_REQUESTS

        assert "freshjob456" in api_services.VIDEO_JOB_STATUS
        assert "freshjob456" in api_services.VIDEO_RESULT_PATHS
        assert "freshjob456" in api_services.VIDEO_SOURCE_PATHS
        assert "freshjob456" in api_services.VIDEO_FRAME_DETECTIONS

    # Assert fire-weather cache pruned
    assert not old_tile.exists()
    assert fresh_tile.exists()
    assert not old_pw.exists()
    assert fresh_pw.exists()

    # Assert webcam alert file NEVER deleted
    assert webcam_alert_file.exists()

    # Clean up test dict entries
    with api_services.VIDEO_JOB_LOCK:
        api_services.VIDEO_JOB_STATUS.pop("freshjob456", None)
        api_services.VIDEO_RESULT_PATHS.pop("freshjob456", None)
        api_services.VIDEO_SOURCE_PATHS.pop("freshjob456", None)
        api_services.VIDEO_FRAME_DETECTIONS.pop("freshjob456", None)
        api_services.VIDEO_PREPARED_INPUTS.pop("freshjob456", None)
        api_services.VIDEO_SEEK_REQUESTS.pop("freshjob456", None)


def test_video_job_cap_returns_429(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", "2")

    with api_services.VIDEO_JOB_LOCK:
        api_services.VIDEO_JOB_STATUS["job1"] = {"status": "processing"}
        api_services.VIDEO_JOB_STATUS["job2"] = {"status": "queued"}

    try:
        # Extra video input request should get 429
        dummy_video = b"fake-video-content"
        response = client.post(
            "/video-inputs",
            files={"video": ("test.mp4", dummy_video, "video/mp4")},
        )
        assert response.status_code == 429
        assert "Maximum concurrent video jobs reached" in response.json()["detail"]

        # Streamed upload also gets 429
        response_stream = client.post(
            "/video-upload?suffix=.mp4",
            content=dummy_video,
            headers={"content-type": "application/octet-stream"},
        )
        assert response_stream.status_code == 429

    finally:
        with api_services.VIDEO_JOB_LOCK:
            api_services.VIDEO_JOB_STATUS.pop("job1", None)
            api_services.VIDEO_JOB_STATUS.pop("job2", None)


def test_tile_write_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "fire_weather"
    monkeypatch.setattr(fire_weather, "CACHE", cache_dir)

    # Create a small valid PNG in memory
    img = Image.new("RGBA", (256, 256), color=(255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    class MockResponse:
        content = png_bytes
        def raise_for_status(self):
            pass

    monkeypatch.setattr(fire_weather.requests, "get", lambda *a, **k: MockResponse())

    date = datetime.now(timezone.utc).date().isoformat()
    # Call tile(date, z, x, y)
    result = fire_weather.tile(date, 7, 64, 48)
    assert result == png_bytes

    tile_path = cache_dir / "tiles" / date / "7" / "64" / "48.png"
    assert tile_path.is_file()
    assert tile_path.read_bytes() == png_bytes

    # Ensure no temporary .part files remained in the directory
    part_files = list((cache_dir / "tiles" / date / "7" / "64").glob("*.part"))
    assert part_files == []
