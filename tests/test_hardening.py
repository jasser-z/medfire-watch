"""Regression coverage for lifecycle, admission control and authentication boundaries."""

import asyncio
import os
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from alerts.manager import AlertManager
from api import services
from api.main import app
from api.routers import video
from fastapi import HTTPException
from fastapi.testclient import TestClient
from medfire_watch.browser_camera import BrowserCameraMonitor, CameraCapacityError
from medfire_watch.retention import get_video_ttl_hours, sweep_video_results


@pytest.fixture
def jobs(monkeypatch, tmp_path):
    for name in (
        "VIDEO_JOB_STATUS",
        "VIDEO_SOURCE_PATHS",
        "VIDEO_RESULT_PATHS",
        "VIDEO_FRAME_DETECTIONS",
        "VIDEO_PREPARED_INPUTS",
        "VIDEO_SEEK_REQUESTS",
        "VIDEO_JOB_CANCEL_EVENTS",
        "VIDEO_JOB_PAUSE_EVENTS",
        "VIDEO_DOWNLOAD_LEASES",
    ):
        mapping = {}
        monkeypatch.setattr(services, name, mapping)
        monkeypatch.setattr(video, name, mapping)
    monkeypatch.setattr(services, "VIDEO_RESULT_DIR", tmp_path)
    monkeypatch.setattr(video, "VIDEO_RESULT_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("status", ["queued", "processing", "exporting", "uploading", "preparing"])
def test_retention_never_deletes_active_job_with_old_input(jobs, status):
    path = jobs / "active_input.mp4"
    path.write_bytes(b"source")
    old = time.time() - 90000
    os.utime(path, (old, old))
    services.VIDEO_JOB_STATUS["active"] = {"status": status, "created_at": old}
    services.VIDEO_SOURCE_PATHS["active"] = path
    assert sweep_video_results(ttl_hours=24) == 0
    assert path.exists()
    assert services.VIDEO_JOB_STATUS["active"]["status"] == status


def test_retention_uses_completion_time_and_expires_fileless_failures(jobs):
    path = jobs / "recent_input.mp4"
    path.write_bytes(b"source")
    os.utime(path, (1, 1))
    services.VIDEO_JOB_STATUS["recent"] = {"status": "complete", "finished_at": time.time()}
    services.VIDEO_JOB_STATUS["failed"] = {"status": "failed", "finished_at": 1}
    services.VIDEO_SOURCE_PATHS["recent"] = path
    sweep_video_results(ttl_hours=24)
    assert path.exists()
    assert "failed" not in services.VIDEO_JOB_STATUS
    assert sweep_video_results(ttl_hours=24) == 0


@pytest.mark.parametrize("value", ["-1", "nan", "inf", "invalid"])
def test_invalid_retention_configuration_rejected(monkeypatch, value):
    monkeypatch.setenv("MEDFIRE_VIDEO_TTL_HOURS", value)
    with pytest.raises(ValueError, match="MEDFIRE_VIDEO_TTL_HOURS"):
        get_video_ttl_hours()


def test_parallel_admission_reserves_exact_capacity(jobs, monkeypatch):
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", "2")

    def reserve(_):
        try:
            return video._reserve_video_job(".mp4")
        except HTTPException as exc:
            assert exc.status_code == 429
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        admitted = [item for item in pool.map(reserve, range(24)) if item is not None]
    assert len(admitted) == len(services.VIDEO_JOB_STATUS) == 2


@pytest.mark.parametrize(
    "path",
    [
        "/alerts",
        "/alerts/log",
        "/alerts/snapshots/alert_test.jpg",
        "/live-camera/status",
        "/live-camera/cooldown",
        "/video-jobs/missing",
        "/video-jobs/missing/source",
        "/video-jobs/missing/frames",
        "/videos/missing/download",
    ],
)
def test_sensitive_reads_require_authentication(monkeypatch, path):
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "regression-token")
    with TestClient(app) as client:
        assert client.get(path).status_code == 401
        assert client.head(path).status_code == 401
        assert client.get(path, headers={"X-MedFire-Token": "regression-token"}).status_code != 401


def test_browser_login_download_logout_and_csrf(monkeypatch, jobs):
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "browser-secret")
    source = jobs / "example.mp4"
    source.write_bytes(b"video")
    services.VIDEO_SOURCE_PATHS["example"] = source
    services.VIDEO_RESULT_PATHS["example"] = source
    with TestClient(app) as client:
        assert client.get("/live-camera", follow_redirects=False).status_code == 303
        assert "browser-secret" not in client.get("/auth/login").text
        bad = client.post("/auth/session", data={"token": "wrong"}, follow_redirects=False)
        assert "error=true" in bad.headers["location"]
        logged = client.post(
            "/auth/session", data={"token": "browser-secret", "next": "https://evil.example"}, follow_redirects=False
        )
        assert logged.headers["location"] == "/live-camera"
        cookie = logged.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "browser-secret" not in cookie
        assert client.get("/live-camera").status_code == 200
        assert client.get("/video-test/app.mjs").status_code == 200
        assert client.get("/video-jobs/example/source").content == b"video"
        assert client.get("/videos/example/download").content == b"video"
        assert client.get("/videos/example/download").headers["cache-control"] == "no-store"
        assert client.post("/video-jobs/example/seek?seconds=0").status_code == 403
        assert (
            client.post("/video-jobs/example/seek?seconds=0", headers={"Origin": "http://evil.example"}).status_code
            == 403
        )
        assert (
            client.post("/auth/logout", headers={"Origin": "http://testserver"}, follow_redirects=False).status_code
            == 303
        )
        assert client.get("/videos/example/download").status_code == 401


def test_session_expiry_tampering_rotation_and_secure_cookie(monkeypatch):
    from api import auth

    monkeypatch.setenv("MEDFIRE_API_TOKEN", "session-secret")
    with TestClient(app, base_url="https://testserver") as client:
        response = client.post("/auth/session", data={"token": "session-secret"}, follow_redirects=False)
        assert "Secure" in response.headers["set-cookie"]
        session = client.cookies.get(auth.COOKIE_NAME)
        assert auth.valid_session(session, "session-secret")
        assert not auth.valid_session(session + "x", "session-secret")
        assert not auth.valid_session(session, "rotated-secret")
        monkeypatch.setattr(auth.time, "time", lambda: float(session.split(".")[0]) + 1)
        assert not auth.valid_session(session, "session-secret")


def test_upload_failure_and_disconnect_release_reservation(jobs, monkeypatch):
    service = SimpleNamespace(max_video_upload_bytes=3)

    class Upload:
        content_type = "video/mp4"
        filename = "../../outside.mp4"
        closed = False

        async def read(self, size):
            return b"oversized"

        async def close(self):
            self.closed = True

    upload = Upload()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(video._save_video_upload(upload, service))
    assert exc.value.status_code == 413
    assert upload.closed and not services.VIDEO_JOB_STATUS and not list(jobs.iterdir())

    class Disconnected:
        async def stream(self):
            yield b"a"
            raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(video.stream_video_upload(Disconnected(), service=service))
    assert not services.VIDEO_JOB_STATUS and not list(jobs.iterdir())


def test_failed_preparation_releases_capacity(jobs, monkeypatch):
    import medfire_watch.video_hardware as hardware

    job_id, path = video._reserve_video_job(".mp4")
    path.write_bytes(b"broken")

    def fail(*args, **kwargs):
        raise ValueError("corrupt media")

    monkeypatch.setattr(hardware, "VideoReader", fail)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(video._prepare_saved_video(job_id, path, SimpleNamespace()))
    assert exc.value.status_code == 422
    assert not services.VIDEO_JOB_STATUS and not path.exists()


def test_camera_sessions_expire_and_reset_rearms(monkeypatch):
    monkeypatch.setattr(BrowserCameraMonitor, "_send", lambda self: None)
    monkeypatch.setenv("MEDFIRE_MAX_CAMERA_SESSIONS", "2")
    monitor = BrowserCameraMonitor()
    first = monitor._get_tracker("one", 0)
    assert monitor._get_tracker("one", 1) is first
    monitor._get_tracker("two", 1)
    with pytest.raises(CameraCapacityError):
        monitor._get_tracker("three", 2)
    monitor._get_tracker("three", 302)
    assert set(monitor._trackers) == {"three"}
    monitor.reset_persistence()
    assert not monitor._trackers and not monitor._pending


def test_expired_snapshot_is_rejected_without_detection_request(monkeypatch):
    import numpy as np

    monkeypatch.setattr(BrowserCameraMonitor, "_send", lambda self: None)
    monitor = BrowserCameraMonitor()
    monitor._pending["expired"] = {"expires": time.monotonic() - 1}
    assert not monitor.submit_full_resolution_snapshot("expired", np.zeros((8, 8, 3)))
    assert not monitor._pending


def test_telegram_concurrent_send_and_reset_during_network_wait(tmp_path, monkeypatch):
    monkeypatch.setattr("alerts.manager.get_setting", lambda name: "mock-credential")
    first = AlertManager(state_path=tmp_path / "state.json")
    other = AlertManager(state_path=first.state_path)
    entered, release = threading.Event(), threading.Event()

    def deliver(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("alerts.manager.requests.post", deliver)
    with ThreadPoolExecutor(max_workers=1) as pool:
        sending = pool.submit(first.send, "test", "live_camera", "live_camera")
        try:
            assert entered.wait(5)
            assert other.send("test", "live_camera", "live_camera")["reason"] == "in_flight"
            other.reset_camera_cooldown()
        finally:
            release.set()
        assert sending.result(timeout=5)["sent"] is True
    assert "live_camera" not in first._read_state()
    assert len(first.sent_log()) == 1


def test_telegram_http_error_traceback_redacts_credentials(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr("alerts.manager.get_setting", lambda name: "sensitive-test-token")

    def fail(*args, **kwargs):
        raise requests.HTTPError("https://api.telegram.org/botsensitive-test-token/sendMessage")

    monkeypatch.setattr("alerts.manager.requests.post", fail)
    with pytest.raises(RuntimeError) as exc:
        AlertManager(state_path=tmp_path / "state.json").send("test", "test", "test")
    assert "sensitive-test-token" not in "".join(traceback.format_exception(exc.value))


def test_analysis_decoder_failure_and_wrong_batch_count(tmp_path, monkeypatch):
    import medfire_watch.video_analysis as analysis
    import numpy as np

    closed = []

    class Reader:
        fps = 25
        width = source_width = 8
        height = source_height = 8

        def __init__(self, *args, **kwargs):
            pass

        def read(self):
            raise ValueError("decoder failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(analysis, "VideoReader", Reader)
    with pytest.raises(ValueError, match="decoder failed"):
        analysis.analyse_video(tmp_path / "bad.mp4", SimpleNamespace(), lambda *a: None)
    assert closed
    frames = [np.zeros((8, 8, 3)), None]
    monkeypatch.setattr(Reader, "read", lambda self: (True, frames.pop(0)) if len(frames) > 1 else (False, None))
    with pytest.raises(RuntimeError, match="result count"):
        analysis.analyse_video(tmp_path / "bad.mp4", SimpleNamespace(predict_batch=lambda batch: []), lambda *a: None)


def test_download_lease_survives_sweep_and_releases_on_disconnect(jobs, monkeypatch):
    from fastapi.responses import FileResponse

    path = jobs / "leased.mp4"
    path.write_bytes(b"video")
    services.VIDEO_JOB_STATUS["leased"] = {"status": "complete", "finished_at": 1}
    response = video.LeasedVideoResponse("leased", path)
    assert sweep_video_results(ttl_hours=0) == 0
    assert path.exists()

    async def disconnected(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(FileResponse, "__call__", disconnected)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(response({}, None, None))
    assert not services.VIDEO_DOWNLOAD_LEASES
    assert sweep_video_results(ttl_hours=0) == 1
    assert not services.VIDEO_JOB_STATUS


def test_simultaneous_upload_requests_and_validation_failure(jobs, monkeypatch):
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", "1")
    entered, release = threading.Event(), threading.Event()

    def invalid(*args):
        entered.set()
        assert release.wait(5)
        raise HTTPException(400, "Invalid video")

    monkeypatch.setattr(video, "_validate_video_file", invalid)
    app.dependency_overrides[services.get_detection_service] = lambda: SimpleNamespace(max_video_upload_bytes=1024)

    def upload():
        return TestClient(app).post("/video-upload", content=b"video")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(upload)
            try:
                assert entered.wait(5)
                assert upload().status_code == 429
            finally:
                release.set()
            assert first.result(timeout=5).status_code == 400
        assert not services.VIDEO_JOB_STATUS and not list(jobs.iterdir())
    finally:
        app.dependency_overrides.clear()


def test_cancelled_worker_releases_capacity_after_acknowledgement(jobs, monkeypatch):
    import medfire_watch.video_analysis as analysis

    entered, release = threading.Event(), threading.Event()

    def analyse(*args, cancelled, **kwargs):
        entered.set()
        assert release.wait(5)
        assert cancelled.is_set()
        raise RuntimeError("cancelled")

    monkeypatch.setattr(analysis, "analyse_video", analyse)
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", "1")
    job_id, path = video._reserve_video_job(".mp4")
    path.write_bytes(b"source")
    service = SimpleNamespace(consecutive_alert_frames=5, max_video_duration_seconds=600)
    video._launch_video_job(job_id, path, service, 5)
    try:
        assert entered.wait(5)
        video.cancel_video_job(job_id)
        assert sweep_video_results(ttl_hours=0) == 0
        with pytest.raises(HTTPException) as exc:
            video._reserve_video_job(".mp4")
        assert exc.value.status_code == 429
    finally:
        release.set()
    deadline = time.monotonic() + 5
    while services.VIDEO_JOB_STATUS[job_id].get("worker_active") and time.monotonic() < deadline:
        time.sleep(0.01)
    assert services.VIDEO_JOB_STATUS[job_id]["status"] == "cancelled"
    assert not services.VIDEO_JOB_STATUS[job_id]["worker_active"] and not path.exists()
    sweep_video_results(ttl_hours=0)
    assert not services.VIDEO_JOB_STATUS


@pytest.mark.parametrize("value", ["0", "-1", "nan", "1.5", "invalid"])
def test_invalid_job_limit_rejected(monkeypatch, value):
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", value)
    with pytest.raises(ValueError, match="MEDFIRE_MAX_VIDEO_JOBS"):
        video._get_max_video_jobs()


def test_world_cache_separates_paths_with_identical_mtime(tmp_path):
    import json

    from medfire_watch.world_hotspots import load_world_hotspots

    first, second = tmp_path / "first.json", tmp_path / "second.json"
    first.write_text(json.dumps({"detections": [{"confidence": "n", "latitude": 1}]}))
    second.write_text(json.dumps({"detections": [{"confidence": "n", "latitude": 2}]}))
    for path in (first, second):
        os.utime(path, (100, 100))
    assert load_world_hotspots(first)["detections"][0]["latitude"] == 1
    assert load_world_hotspots(second)["detections"][0]["latitude"] == 2


def test_truncated_image_returns_client_error():
    from io import BytesIO

    from PIL import Image

    payload = BytesIO()
    Image.new("RGB", (64, 64), "red").save(payload, format="PNG")
    with TestClient(app) as client:
        response = client.post("/detect", files={"image": ("truncated.png", payload.getvalue()[:60], "image/png")})
    assert response.status_code == 400


def test_concurrent_camera_snapshots_reserve_byte_budget_atomically(monkeypatch, tmp_path):
    import medfire_watch.browser_camera as camera
    import numpy as np

    monkeypatch.setattr(BrowserCameraMonitor, "_send", lambda self: None)
    manager = AlertManager(state_path=tmp_path / "state.json")
    monkeypatch.setattr(AlertManager, "from_config", lambda path: manager)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monkeypatch.setattr(camera, "MAX_QUEUE_BYTES", frame.nbytes + 1)
    monitor = BrowserCameraMonitor()
    detection = {"class": "fire", "confidence": 0.9, "xyxy": [0, 0, 8, 8]}
    for key in ("one", "two"):
        monitor._pending[key] = {
            "expires": time.monotonic() + 10,
            "image_width": 8,
            "image_height": 8,
            "detections": [detection],
            "alert": {"detection": detection},
        }
    with ThreadPoolExecutor(max_workers=2) as pool:
        admitted = list(pool.map(lambda key: monitor.submit_full_resolution_snapshot(key, frame), ["one", "two"]))
    assert sorted(admitted) == [False, True]
    assert monitor._queued_bytes == frame.nbytes and monitor._queue.qsize() == 1


@pytest.mark.parametrize("status, retryable", [(400, False), (401, False), (403, False), (429, True), (503, True)])
def test_telegram_retry_policy_for_http_failures(tmp_path, monkeypatch, status, retryable):
    import requests
    from alerts.manager import TelegramDeliveryError

    monkeypatch.setattr("alerts.manager.get_setting", lambda name: "mock-credential")
    response = requests.Response()
    response.status_code = status

    def fail(*args, **kwargs):
        raise requests.HTTPError("private details", response=response)

    monkeypatch.setattr("alerts.manager.requests.post", fail)
    with pytest.raises(TelegramDeliveryError) as exc:
        AlertManager(state_path=tmp_path / "state.json").send("test", "test", "test")
    assert exc.value.retryable is retryable


def test_inference_failure_closes_export_and_removes_partial_files(tmp_path):
    import cv2
    import numpy as np
    from medfire_watch.video import iter_video_detections

    source, output = tmp_path / "source.mp4", tmp_path / "export.mp4"
    writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (16, 16))
    assert writer.isOpened()
    for _ in range(10):
        writer.write(np.zeros((16, 16, 3), dtype=np.uint8))
    writer.release()

    def fail(frame):
        raise ValueError("inference failed")

    with pytest.raises(ValueError, match="inference failed"):
        list(iter_video_detections(source, output, fail))
    assert not output.exists() and not output.with_name("export.video-only.mp4").exists()
    source.unlink()  # OpenCV/FFmpeg handles must be released on Windows.


@pytest.mark.parametrize("payload", [b"", b"not video", b"#EXTM3U\nhttps://example.invalid/private\n"])
def test_fake_video_containers_rejected_before_decode(tmp_path, payload):
    source = tmp_path / "fake.mp4"
    source.write_bytes(payload)
    with pytest.raises(HTTPException) as exc:
        video._validate_video_file(source, SimpleNamespace(max_video_duration_seconds=600))
    assert exc.value.status_code == 400


def test_exif_image_orientation_is_preserved_by_inference(monkeypatch):
    from io import BytesIO

    import numpy as np
    from PIL import Image

    shapes = []

    class Detector:
        def predict(self, image):
            shapes.append(image.shape[:2])
            return {"detections": []}

    image = Image.new("RGB", (40, 20), "red")
    exif = image.getexif()
    exif[274] = 6
    payload = BytesIO()
    image.save(payload, format="JPEG", exif=exif)
    app.dependency_overrides[services.get_detection_service] = Detector
    try:
        response = TestClient(app).post("/detect", files={"image": ("rotated.jpg", payload.getvalue(), "image/jpeg")})
        assert response.status_code == 200
        assert shapes == [(40, 20)]
        assert np.asarray(image).shape[:2] == (20, 40)
    finally:
        app.dependency_overrides.clear()


def test_model_output_drops_nonfinite_inverted_unknown_and_clips_boxes():
    class Values:
        def __init__(self, value):
            self.value = value

        def cpu(self):
            return self

        def tolist(self):
            return self.value

    result = SimpleNamespace(
        boxes=SimpleNamespace(
            xyxy=Values([[-5, -5, 50, 50], [5, 5, 1, 1], [0, 0, float("nan"), 4], [0, 0, 2, 2]]),
            cls=Values([0, 0, 0, 9]),
            conf=Values([0.9, 0.9, 0.9, 0.9]),
        ),
        names={0: "fire", 1: "smoke"},
        orig_shape=(20, 30),
        speed={},
    )
    detections = services.DetectionService._format_result(result, "cpu")["detections"]
    assert len(detections) == 1 and detections[0]["xyxy"] == [0, 0, 30, 20]


@pytest.mark.parametrize(
    "section,key,value",
    [
        ("video", "maximum_upload_mb", -1),
        ("video", "maximum_upload_mb", 1.5),
        ("video", "maximum_duration_seconds", float("nan")),
        ("video", "maximum_duration_seconds", 0),
        ("temporal_alert", "consecutive_frames", 0),
        ("temporal_alert", "consecutive_frames", 1.5),
        ("live_alert", "min_iou", 2),
        ("live_alert", "persistence_seconds", float("inf")),
        ("live_alert", "confidence", "invalid"),
    ],
)
def test_invalid_detector_configuration_fails_with_setting_name(tmp_path, monkeypatch, section, key, value):
    import yaml

    config = yaml.safe_load(services.DETECTION_CONFIG_PATH.read_text())
    config[section][key] = value
    path = tmp_path / "detection.yaml"
    path.write_text(yaml.safe_dump(config))
    monkeypatch.setattr(services, "DETECTION_CONFIG_PATH", path)
    with pytest.raises(ValueError, match=key):
        services.DetectionService()


def test_authenticated_browser_camera_inference_and_telegram_controls(tmp_path, monkeypatch):
    from io import BytesIO

    from api.routers import detection
    from PIL import Image

    monkeypatch.setenv("MEDFIRE_API_TOKEN", "operator-test-token")
    manager = AlertManager(state_path=tmp_path / "state.json")
    monkeypatch.setattr(manager, "detect_chat", lambda: "mock-chat")
    app.dependency_overrides[services.get_alert_manager] = lambda: manager
    captured = []
    monitor = SimpleNamespace(
        process=lambda image, service, session_id: captured.append(session_id) or {"detections": []}
    )
    monkeypatch.setattr(detection, "_browser_camera_monitor", monitor)
    monkeypatch.setattr(detection, "get_detection_service", lambda: SimpleNamespace())
    payload = BytesIO()
    Image.new("RGB", (16, 16)).save(payload, format="JPEG")
    try:
        client = TestClient(app)
        files = {"image": ("frame.jpg", payload.getvalue(), "image/jpeg")}
        assert client.post("/live-camera/detect", files=files).status_code == 401
        assert client.post("/telegram/detect").status_code == 401
        assert not captured
        client.post("/auth/session", data={"token": "operator-test-token"}, follow_redirects=False)
        headers = {"Origin": "http://testserver", "X-Camera-Session": "browser-test"}
        assert client.post("/live-camera/detect", files=files, headers=headers).status_code == 200
        assert captured == ["browser-test"]
        assert client.post("/telegram/detect", headers=headers).json() == {"chat_id": "mock-chat"}
        assert client.get("/alerts/log").json() == {"messages": []}
    finally:
        app.dependency_overrides.clear()


def test_cancelled_preparation_keeps_input_reserved_until_thread_exits(jobs, monkeypatch):
    import medfire_watch.video_hardware as hardware

    entered, release = threading.Event(), threading.Event()
    job_id, path = video._reserve_video_job(".mp4")
    path.write_bytes(b"source")

    def blocked_reader(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        raise ValueError("preparation finished after cancellation")

    monkeypatch.setattr(hardware, "VideoReader", blocked_reader)

    async def scenario():
        task = asyncio.create_task(video._prepare_saved_video(job_id, path, SimpleNamespace()))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(0.02)
            assert path.exists() and job_id in services.VIDEO_JOB_STATUS
            assert not task.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not path.exists() and job_id not in services.VIDEO_JOB_STATUS

    asyncio.run(scenario())
