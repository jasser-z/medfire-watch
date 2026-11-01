from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

import api.main as api_module
import cv2
import numpy as np
import pytest
from alerts.manager import AlertManager
from api.main import (
    app,
    get_alert_manager,
    get_detection_service,
)
from fastapi.testclient import TestClient
from PIL import Image


class FakeDetectionService:
    confidence_threshold = 0.3
    consecutive_alert_frames = 5
    max_video_upload_bytes = 100 * 1024 * 1024
    max_video_duration_seconds = 120

    def predict(self, image: np.ndarray) -> dict[str, object]:
        assert image.shape == (12, 16, 3)
        return {
            "detections": [
                {"class": "fire", "confidence": 0.8, "xyxy": [1.0, 2.0, 8.0, 9.0]}
            ],
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






def test_detect_accepts_valid_image_and_rejects_unsupported_type(client: TestClient) -> None:
    image = Image.new("RGB", (16, 12), color="black")
    payload = BytesIO()
    image.save(payload, format="PNG")

    response = client.post(
        "/detect",
        files={"image": ("frame.png", payload.getvalue(), "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["detections"][0]["class"] == "fire"
    assert base64.b64decode(response.json()["annotated_image_base64"])

    unsupported = client.post(
        "/detect",
        files={"image": ("frame.txt", b"not an image", "text/plain")},
    )
    assert unsupported.status_code == 415

    unreadable = client.post(
        "/detect",
        files={"image": ("frame.png", b"not an image", "image/png")},
    )
    assert unreadable.status_code == 400




def test_current_video_flow_keeps_source_detections_and_all_export_frames(client: TestClient, tmp_path: Path) -> None:
    import time

    video_path = tmp_path / "live.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 12))
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 encoder is unavailable.")
    for _ in range(5):
        writer.write(np.zeros((12, 16, 3), dtype=np.uint8))
    writer.release()
    response = client.post(
        "/video-inputs", files={"video": ("live.mp4", video_path.read_bytes(), "video/mp4")}
    )
    assert response.status_code == 200
    job_id = response.json()["input_id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        job = client.get(f"/video-jobs/{job_id}").json()
        if job["status"] in {"complete", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "complete", job.get("error")
    assert job["result"]["frames_processed"] == 5
    source = client.get(f"/video-jobs/{job_id}/source")
    assert source.content == video_path.read_bytes()
    detections = client.get(f"/video-jobs/{job_id}/frames").json()["frames"]
    assert len(detections) == 5
    api_module.VIDEO_RESULT_PATHS.pop(job_id).unlink(missing_ok=True)
    api_module.VIDEO_SOURCE_PATHS.pop(job_id).unlink(missing_ok=True)


def test_telegram_sender_records_only_confirmed_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import alerts.manager as manager_module

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(manager_module.requests, "post", lambda *args, **kwargs: Response())
    manager = AlertManager(state_path=tmp_path / "state.json")
    sent = manager.send("Test", "test", "unique-test")
    assert sent["sent"] is True
    assert manager.sent_log()[0]["message_id"] == 7
    assert manager.send("Duplicate", "test", "unique-test") == {"sent": False, "reason": "cooldown"}


def test_prepared_video_starts_without_upload_and_reuses_initial_predictions(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    video_path = tmp_path / "prepared.mp4"
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 12))
    if not writer.isOpened():
        pytest.skip("OpenCV MP4 encoder is unavailable.")
    for _ in range(3):
        writer.write(np.zeros((12, 16, 3), dtype=np.uint8))
    writer.release()
    predictions = []
    original = FakeDetectionService.predict

    def count_prediction(self, frame):
        predictions.append(frame.shape)
        return original(self, frame)

    monkeypatch.setattr(FakeDetectionService, "predict", count_prediction)
    prepared = client.post("/video-inputs", files={"video": ("prepared.mp4", video_path.read_bytes(), "video/mp4")})
    assert prepared.status_code == 200
    payload = prepared.json()
    assert len(payload["initial_frames"]) == 3
    assert len(predictions) == 3
    input_id = payload["input_id"]
    assert input_id in api_module.VIDEO_JOB_STATUS  # File selection now starts analysis.
    started = client.post(f"/video-inputs/{input_id}/predict")
    assert started.status_code == 200
    assert started.json()["video_id"] == input_id
    assert client.post(f"/video-inputs/{input_id}/predict").json()["video_id"] == input_id
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status = client.get(f"/video-jobs/{input_id}").json()
        if status["status"] in {"complete", "failed"}:
            break
        time.sleep(0.02)
    assert status["status"] == "complete", status.get("error")
    assert len(predictions) == 3  # Prepared frames are encoded, without repeating their inference.
    assert status["result"]["input_frames"] == status["result"]["frames_encoded"] == 3
    api_module.VIDEO_RESULT_PATHS.pop(input_id).unlink(missing_ok=True)
    api_module.VIDEO_SOURCE_PATHS.pop(input_id).unlink(missing_ok=True)
    api_module.VIDEO_PREPARED_INPUTS.pop(input_id)


def test_retired_video_and_regional_alert_routes_are_absent(client):
    paths = client.get('/openapi.json').json()['paths']
    retired = ['/detect-video', '/alerts/settings', '/video-jobs/{video_id}/live',
               '/videos/{video_id}/previews/{preview_index}', '/video-jobs/{video_id}/player']
    for path in retired:
        assert path not in paths
    assert '/video-jobs' not in paths
    assert 'settings' not in client.get('/alerts').json()
