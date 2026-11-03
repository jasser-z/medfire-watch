import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import pytest
from alerts.manager import AlertManager
from api import services
from api.main import app
from api.routers import storage, video
from fastapi import HTTPException
from fastapi.testclient import TestClient
from medfire_watch.browser_camera import BrowserCameraMonitor
from medfire_watch.video import iter_video_detections
from medfire_watch.video_analysis import analyse_video


@pytest.fixture
def runtime(tmp_path, monkeypatch):
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
    folder = tmp_path / "runs" / "video_results"
    folder.mkdir(parents=True)
    monkeypatch.setattr(services, "VIDEO_RESULT_DIR", folder)
    monkeypatch.setattr(video, "VIDEO_RESULT_DIR", folder)
    monkeypatch.setattr(storage, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr("medfire_watch.browser_camera.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(BrowserCameraMonitor, "_send", lambda self: None)
    monitor = BrowserCameraMonitor()
    monkeypatch.setattr("api.routers.detection._browser_camera_monitor", monitor)
    manager = AlertManager(state_path=tmp_path / "runs" / "alerts" / "state.json")
    app.dependency_overrides[services.get_alert_manager] = lambda: manager
    yield tmp_path, manager, monitor
    app.dependency_overrides.clear()


def make_video(path):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 24))
    assert writer.isOpened()
    for _ in range(24):
        writer.write(np.zeros((24, 32, 3), dtype=np.uint8))
    writer.release()


def test_pause_holds_analysis_and_resume_preserves_all_frames(runtime):
    root, _, _ = runtime
    source = root / "clip.mp4"
    make_video(source)
    paused, cancelled = threading.Event(), threading.Event()
    paused.set()
    calls = []

    class Detector:
        def predict_batch(self, images):
            calls.append(len(images))
            return [{"detections": []} for _ in images]

    published = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(
            analyse_video, source, Detector(), lambda d, i, fps: published.append(i), paused=paused, cancelled=cancelled
        )
        try:
            time.sleep(0.05)
            assert not work.done() and not calls and not published
        finally:
            paused.clear()
        result = work.result(timeout=5)
    assert sorted(published) == list(range(24)) and len(published) == 24
    assert result["frames"] == 24


def test_cancel_wakes_paused_analysis(runtime):
    root, _, _ = runtime
    source = root / "clip.mp4"
    make_video(source)
    paused, cancelled = threading.Event(), threading.Event()
    paused.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(analyse_video, source, object(), lambda *args: None, paused=paused, cancelled=cancelled)
        cancelled.set()
        with pytest.raises(RuntimeError, match="cancelled"):
            work.result(timeout=5)
    source.unlink()  # Decoder handles must have closed on Windows.


@pytest.mark.parametrize("cancel", [False, True])
def test_export_can_resume_or_cancel_from_paused_state(runtime, cancel):
    root, _, _ = runtime
    source, output = root / "clip.mp4", root / "annotated.mp4"
    make_video(source)
    paused, cancelled = threading.Event(), threading.Event()
    paused.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        work = pool.submit(
            lambda: list(
                iter_video_detections(
                    source,
                    output,
                    lambda image: {"detections": []},
                    paused=paused,
                    cancelled=cancelled,
                )
            )
        )
        try:
            time.sleep(0.1)
            assert not work.done()
        finally:
            cancelled.set() if cancel else paused.clear()
        if cancel:
            with pytest.raises(RuntimeError, match="cancelled"):
                work.result(timeout=10)
            assert not output.exists() and not output.with_name("annotated.video-only.mp4").exists()
        else:
            result = work.result(timeout=10)[-1]
            assert result["frames_encoded"] == result["input_frames"] == 24
            assert result["output_video_ready"]


def test_control_endpoints_pause_resume_cancel_and_preserve_capacity(runtime, monkeypatch):
    monkeypatch.setenv("MEDFIRE_MAX_VIDEO_JOBS", "1")
    job_id, path = video._reserve_video_job(".mp4")
    path.write_bytes(b"source")
    services.VIDEO_JOB_STATUS[job_id].update(status="processing", worker_active=True)
    client = TestClient(app)
    assert client.post(f"/video-jobs/{job_id}/pause").json() == {"paused": True}
    assert client.get(f"/video-jobs/{job_id}").json()["paused"]
    with pytest.raises(HTTPException) as exc:
        video._reserve_video_job(".mp4")
    assert exc.value.status_code == 429
    assert client.post(f"/video-jobs/{job_id}/resume").json() == {"paused": False}
    client.post(f"/video-jobs/{job_id}/pause")
    assert client.post(f"/video-jobs/{job_id}/cancel").status_code == 200
    assert services.VIDEO_JOB_CANCEL_EVENTS[job_id].is_set()
    assert not services.VIDEO_JOB_PAUSE_EVENTS[job_id].is_set()
    assert client.post(f"/video-jobs/{job_id}/resume").status_code == 409
    assert client.post("/video-jobs/missing/pause").status_code == 404


def test_cleanup_removes_generated_data_protecting_active_jobs_settings_and_datasets(runtime):
    root, manager, monitor = runtime
    terminal = services.VIDEO_RESULT_DIR / "done.mp4"
    terminal.write_bytes(b"export")
    services.VIDEO_JOB_STATUS["done"] = {"status": "complete", "finished_at": time.time()}
    services.VIDEO_FRAME_DETECTIONS["done"] = [{"detections": []}]
    services.VIDEO_JOB_PAUSE_EVENTS["done"] = threading.Event()
    active = services.VIDEO_RESULT_DIR / "active_input.mp4"
    active.write_bytes(b"active")
    services.VIDEO_JOB_STATUS["active"] = {"status": "processing", "worker_active": True, "paused": True}
    services.VIDEO_SOURCE_PATHS["active"] = active
    leased = services.VIDEO_RESULT_DIR / "leased.mp4"
    leased.write_bytes(b"download")
    services.VIDEO_JOB_STATUS["leased"] = {"status": "complete"}
    services.VIDEO_DOWNLOAD_LEASES["leased"] = 1
    photo = root / "runs" / "webcam_alerts" / "alert_old.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"photo")
    manager.record_failure("live_camera", 1, "mock failure", photo.name)
    manager.set_camera_cooldown(12)
    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monitor._queue.put((frame, [], {"generation": 0}))
    monitor._queued_bytes = frame.nbytes
    protected = [root / "data/geospatial/places.json", root / "models/weights.pt", root / ".env"]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"keep")
    for name in ("data/satellite/world_hotspots.json", "data/fire_weather/tiles/one.png"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cache")
    client = TestClient(app)
    before = client.get("/runtime-cache").json()
    assert before["storage"]["videos"]["files"] == 3
    result = client.delete("/runtime-cache").json()
    assert result["deleted_video_files"] == 1 and result["deleted_provider_files"] == 2
    assert result["deleted_snapshots"] == 1 and result["deleted_attempts"] == 1
    assert not terminal.exists() and active.exists() and leased.exists()
    assert "done" not in services.VIDEO_FRAME_DETECTIONS and "done" not in services.VIDEO_JOB_PAUSE_EVENTS
    assert monitor._queue.empty() and monitor._queue.unfinished_tasks == 0 and monitor._queued_bytes == 0
    assert manager.attempt_log() == [] and manager.camera_cooldown() == 12
    assert all(path.read_bytes() == b"keep" for path in protected)
    assert client.delete("/runtime-cache").json()["deleted_video_files"] == 0


def test_cleanup_options_and_authentication(runtime, monkeypatch):
    root, _, _ = runtime
    photo = root / "runs/webcam_alerts/alert_keep.jpg"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"photo")
    cached = root / "data/fire_weather/metadata.json"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cache")
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "storage-test-token")
    client = TestClient(app)
    assert client.get("/runtime-cache").status_code == 401
    assert client.delete("/runtime-cache").status_code == 401
    result = client.delete(
        "/runtime-cache?include_snapshots=false&include_provider_cache=false",
        headers={"X-MedFire-Token": "storage-test-token"},
    )
    assert result.status_code == 200 and photo.exists() and cached.exists()


def test_provider_refresh_is_skipped_without_blocking_cleanup(runtime):
    from medfire_watch import world_hotspots

    root, _, _ = runtime
    cached = root / "data/satellite/world_hotspots.json"
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"cache")
    assert world_hotspots._LOCK.acquire(timeout=5)
    try:
        result = TestClient(app).delete("/runtime-cache?include_snapshots=false").json()
        assert result["busy_cache_entries"] >= 1 and cached.exists()
    finally:
        world_hotspots._LOCK.release()


def test_cleanup_during_photo_delivery_does_not_restore_photo_or_history(tmp_path, monkeypatch):
    from types import SimpleNamespace

    manager = AlertManager(state_path=tmp_path / "alerts" / "state.json")
    monkeypatch.setattr("medfire_watch.browser_camera.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(AlertManager, "from_config", lambda path: manager)
    monkeypatch.setattr("alerts.manager.get_setting", lambda name: "mock-credential")
    finished = threading.Event()
    monitor = BrowserCameraMonitor()

    def deliver(*args, **kwargs):
        result = monitor.clear_snapshots(manager)
        assert result["deleted_snapshots"] == 1
        finished.set()
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("alerts.manager.requests.post", deliver)
    detection = {"class": "fire", "confidence": 0.9, "xyxy": [0, 0, 8, 8]}
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    monitor._queue.put((image, [detection], {"generation": 0, "detection": detection}))
    assert finished.wait(5)
    deadline = time.monotonic() + 5
    while monitor._queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)
    assert monitor._queue.unfinished_tasks == 0
    assert not list((tmp_path / "runs" / "webcam_alerts").glob("*.jpg"))
    assert manager.attempt_log() == []


@pytest.mark.parametrize("cancel_task", [False, True])
def test_aborted_preparation_does_not_launch_an_orphan_job(runtime, monkeypatch, cancel_task):
    job_id, path = video._reserve_video_job(".mp4")
    path.write_bytes(b"source")

    async def prepared(*args):
        return {"input_id": job_id}

    class Request:
        async def is_disconnected(self):
            if cancel_task:
                raise asyncio.CancelledError()
            return True

    monkeypatch.setattr(video, "_run_video_thread", prepared)
    with pytest.raises(asyncio.CancelledError if cancel_task else HTTPException) as exc:
        asyncio.run(video._prepare_saved_video(job_id, path, object(), request=Request()))
    if not cancel_task:
        assert exc.value.status_code == 400
    assert not path.exists() and job_id not in services.VIDEO_JOB_STATUS
