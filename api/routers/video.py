from __future__ import annotations

import asyncio
import logging
import math
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from medfire_watch.config import PROJECT_ROOT, env_number
from medfire_watch.video import iter_video_detections

from api.services import (
    DEFAULT_VIDEO_DURATION_SECONDS,
    DEFAULT_VIDEO_UPLOAD_MB,
    VIDEO_CONTENT_TYPES,
    VIDEO_DOWNLOAD_LEASES,
    VIDEO_FRAME_DETECTIONS,
    VIDEO_JOB_CANCEL_EVENTS,
    VIDEO_JOB_LOCK,
    VIDEO_JOB_STATUS,
    VIDEO_PREPARED_INPUTS,
    VIDEO_RESULT_DIR,
    VIDEO_RESULT_PATHS,
    VIDEO_SEEK_REQUESTS,
    VIDEO_SOURCE_PATHS,
    DetectionService,
    get_detection_service,
)

VIDEO_SUFFIX_MEDIA_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".webm": "video/webm",
}
router = APIRouter()
logger = logging.getLogger(__name__)


ACTIVE_VIDEO_STATES = {"uploading", "preparing", "queued", "processing", "exporting"}


def _get_max_video_jobs() -> int:
    return env_number("MEDFIRE_MAX_VIDEO_JOBS", 2, 1, 16, integer=True)


def _check_video_job_capacity() -> None:
    # Caller must hold VIDEO_JOB_LOCK when registering a reservation.
    active = sum(
        1 for s in VIDEO_JOB_STATUS.values() if s.get("status") in ACTIVE_VIDEO_STATES or s.get("worker_active")
    )
    if active >= _get_max_video_jobs():
        raise HTTPException(429, "Maximum concurrent video jobs reached. Please retry later.")
    maximum = env_number("MEDFIRE_MAX_STORED_VIDEO_JOBS", 64, 1, 4096, integer=True)
    if len(VIDEO_JOB_STATUS) >= maximum:
        raise HTTPException(429, "Video retention storage is full. Retry after expired jobs are cleaned up.")


def _reserve_video_job(suffix: str) -> tuple[str, Path]:
    with VIDEO_JOB_LOCK:
        _check_video_job_capacity()
        video_id = uuid.uuid4().hex
        VIDEO_RESULT_DIR.mkdir(parents=True, exist_ok=True)
        path = VIDEO_RESULT_DIR / f"{video_id}_input{suffix}"
        VIDEO_JOB_STATUS[video_id] = {"status": "uploading", "created_at": time.time()}
        VIDEO_SOURCE_PATHS[video_id] = path
        VIDEO_JOB_CANCEL_EVENTS[video_id] = threading.Event()
        return video_id, path


def _discard_video_job(video_id: str) -> None:
    with VIDEO_JOB_LOCK:
        path = VIDEO_SOURCE_PATHS.get(video_id)
        if path:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                VIDEO_JOB_STATUS[video_id].update(status="failed", worker_active=False, finished_at=time.time())
                logger.warning("Deferred cleanup for video job %s; file remains in use.", video_id)
                return
        for mapping in (
            VIDEO_JOB_STATUS,
            VIDEO_SOURCE_PATHS,
            VIDEO_RESULT_PATHS,
            VIDEO_FRAME_DETECTIONS,
            VIDEO_PREPARED_INPUTS,
            VIDEO_SEEK_REQUESTS,
            VIDEO_JOB_CANCEL_EVENTS,
        ):
            mapping.pop(video_id, None)


async def _write_video_stream(path: Path, chunks: Any, maximum_bytes: int) -> int:
    received = 0
    try:
        async with asyncio.timeout(env_number("MEDFIRE_VIDEO_UPLOAD_TIMEOUT_SECONDS", 300, 1, 3600)):
            with path.open("wb") as output:
                async for chunk in chunks:
                    received += len(chunk)
                    if received > maximum_bytes:
                        raise HTTPException(413, "Video exceeds the configured upload limit.")
                    output.write(chunk)
    except TimeoutError:
        raise HTTPException(408, "Video upload timed out.") from None
    return received


async def _run_video_thread(function: Any, *args: Any) -> Any:
    """Keep reservation/files alive until native preparation exits after cancellation."""
    from anyio import CancelScope
    from starlette.concurrency import run_in_threadpool

    task = asyncio.create_task(run_in_threadpool(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()  # Retrieve a late worker failure while preserving request cancellation.
        raise


class LeasedVideoResponse(FileResponse):
    """Keep retention from unlinking a file while Starlette streams its body."""

    def __init__(self, video_id: str, path: Path, **kwargs: Any):
        with VIDEO_JOB_LOCK:
            if not path.is_file():
                raise HTTPException(404, "Video is unavailable or has expired.")
            super().__init__(path, **kwargs)
            VIDEO_DOWNLOAD_LEASES[video_id] = VIDEO_DOWNLOAD_LEASES.get(video_id, 0) + 1
        self.video_id = video_id

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            with VIDEO_JOB_LOCK:
                remaining = VIDEO_DOWNLOAD_LEASES.get(self.video_id, 1) - 1
                if remaining:
                    VIDEO_DOWNLOAD_LEASES[self.video_id] = remaining
                else:
                    VIDEO_DOWNLOAD_LEASES.pop(self.video_id, None)


@router.get("/video-test", response_class=HTMLResponse)
def local_video_test() -> str:
    """Serve the local-upload video studio."""
    return (PROJECT_ROOT / "dashboard" / "video_player.html").read_text(encoding="utf-8").replace("JOB", "local")


@router.get("/video-test/app.mjs")
def video_app_module() -> Response:
    """Serve the local video controller with the same initial job selection."""
    source = (PROJECT_ROOT / "dashboard" / "video_player.mjs").read_text(encoding="utf-8")
    return Response(source.replace("JOB", "local"), media_type="text/javascript")


@router.post("/video-test/prepare")
def prepare_video_detector(service: Any = Depends(lambda: get_detection_service())) -> dict[str, Any]:
    """Warm inference and report configured video capabilities."""
    from medfire_watch.video_hardware import nvenc_available

    if hasattr(service, "warmup"):
        service.warmup()
    return {
        "status": "ready",
        "video_encoder": "h264_nvenc" if nvenc_available() else "libx264",
        "maximum_upload_bytes": getattr(service, "max_video_upload_bytes", DEFAULT_VIDEO_UPLOAD_MB * 1024 * 1024),
        "maximum_duration_seconds": getattr(service, "max_video_duration_seconds", DEFAULT_VIDEO_DURATION_SECONDS),
    }


def _validate_video_file(path: Path, service: DetectionService) -> None:
    with path.open("rb") as handle:
        header = handle.read(16)
    is_iso_media = len(header) >= 12 and header[4:8] in {b"ftyp", b"moov", b"mdat", b"wide", b"free"}
    is_avi = header[:4] == b"RIFF" and header[8:12] == b"AVI "
    is_webm = header[:4] == b"\x1a\x45\xdf\xa3"
    if not (is_iso_media or is_avi or is_webm):
        raise HTTPException(400, "Uploaded file is not a supported video container.")
    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise HTTPException(status_code=400, detail="Uploaded video is not readable by OpenCV.")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if not all(math.isfinite(v) for v in (fps, frame_count, width, height)) or fps <= 0 or fps > 240:
            raise HTTPException(400, "Video frame-rate metadata is invalid or exceeds 240 fps.")
        if width < 1 or height < 1 or frame_count < 0:
            raise HTTPException(400, "Video dimensions or frame count are invalid.")
        if width * height > 8_294_400:
            raise HTTPException(413, "Video resolution exceeds the 4K limit.")
        if frame_count / fps > service.max_video_duration_seconds:
            raise HTTPException(413, f"Video duration exceeds {service.max_video_duration_seconds:g} seconds.")
        readable, _ = capture.read()
        if not readable:
            raise HTTPException(400, "Uploaded video has no decodable frames.")
    finally:
        capture.release()


async def _save_video_upload(video: UploadFile, service: DetectionService) -> tuple[str, Path]:
    if video.content_type not in VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Upload an MP4, MOV, AVI, or WebM video.")
    suffix = Path(video.filename or "upload.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".webm"}:
        suffix = ".mp4"
    video_id, input_path = _reserve_video_job(suffix)

    async def chunks():
        while chunk := await video.read(4 * 1024 * 1024):
            yield chunk

    try:
        await _write_video_stream(input_path, chunks(), service.max_video_upload_bytes)
    except BaseException:
        _discard_video_job(video_id)
        raise
    finally:
        await video.close()
    try:
        await _run_video_thread(_validate_video_file, input_path, service)
    except BaseException:
        _discard_video_job(video_id)
        raise
    return video_id, input_path


@router.post("/video-inputs")
async def prepare_video_input(
    video: UploadFile = File(...),
    service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    """Save a multipart video and prepare its first predictions."""
    video_id, input_path = await _save_video_upload(video, service)
    return await _prepare_saved_video(video_id, input_path, service)


@router.post("/video-upload")
async def stream_video_upload(
    request: Request,
    suffix: str = ".mp4",
    service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    """Save a streamed video and start background preparation."""
    if suffix not in {".mp4", ".mov", ".avi", ".webm"}:
        raise HTTPException(415, "Unsupported video extension.")
    video_id, path = _reserve_video_job(suffix)
    started = time.perf_counter()
    try:
        received = await _write_video_stream(path, request.stream(), service.max_video_upload_bytes)
        upload_seconds = time.perf_counter() - started
        await _run_video_thread(_validate_video_file, path, service)
        prepared = await _prepare_saved_video(video_id, path, service)
        prepared.update({"upload_seconds": upload_seconds, "upload_bytes": received})
        return prepared
    except BaseException:
        _discard_video_job(video_id)
        raise


async def _prepare_saved_video(video_id: str, input_path: Path, service: DetectionService) -> dict[str, Any]:
    import time

    from medfire_watch.video_hardware import VideoReader, encoder_arguments

    started = time.perf_counter()
    with VIDEO_JOB_LOCK:
        VIDEO_JOB_STATUS[video_id]["status"] = "preparing"

    cached_results: list[dict[str, Any]] = []

    def prepare() -> dict[str, Any]:
        """Decode and infer the initial second for playback preparation."""
        reader = VideoReader(input_path, inference_width=640)
        try:
            batch = []
            for index in range(min(reader.frame_count or round(reader.fps), max(1, round(reader.fps)))):
                ok, frame = reader.read()
                if not ok:
                    break
                batch.append(frame)
                if len(batch) == 8:
                    cached_results.extend(
                        service.predict_batch(batch)
                        if hasattr(service, "predict_batch")
                        else [service.predict(image) for image in batch]
                    )
                    batch = []
            if batch:
                cached_results.extend(
                    service.predict_batch(batch)
                    if hasattr(service, "predict_batch")
                    else [service.predict(image) for image in batch]
                )
            if not cached_results:
                raise ValueError("Video contains no decodable frames.")
            for result in cached_results:
                for detection in result["detections"]:
                    detection["xyxy"] = [
                        value
                        * (reader.source_width / reader.width if i % 2 == 0 else reader.source_height / reader.height)
                        for i, value in enumerate(detection["xyxy"])
                    ]
            return {
                "input_id": video_id,
                "width": reader.source_width,
                "height": reader.source_height,
                "source_fps": reader.fps,
                "source_frames": reader.frame_count,
                "video_decoder": reader.backend,
                "video_encoder": encoder_arguments(reader.width, reader.height)[0],
                "detector_device": cached_results[0].get("device", "unknown"),
                "detector_precision": cached_results[0].get("precision", "unknown"),
                "initial_frames": [
                    {"time": i / reader.fps, "detections": result["detections"]}
                    for i, result in enumerate(cached_results)
                ],
                "prepared_seconds": time.perf_counter() - started,
            }
        finally:
            reader.close()

    try:
        prepared = await _run_video_thread(prepare)
    except Exception:
        logger.exception("Video preparation failed for %s.", video_id)
        _discard_video_job(video_id)
        raise HTTPException(422, "The video could not be prepared for prediction.") from None
    except BaseException:
        _discard_video_job(video_id)
        raise
    with VIDEO_JOB_LOCK:
        VIDEO_PREPARED_INPUTS[video_id] = {"path": input_path, "response": prepared, "initial_results": cached_results}
    _launch_video_job(video_id, input_path, service, service.consecutive_alert_frames)
    return prepared


@router.post("/video-inputs/{input_id}/predict")
def predict_prepared_video(input_id: str, service: DetectionService = Depends(get_detection_service)) -> dict[str, str]:
    """Start or reuse analysis for an existing prepared input."""
    with VIDEO_JOB_LOCK:
        prepared = VIDEO_PREPARED_INPUTS.get(input_id)
    if prepared is None or not prepared["path"].is_file():
        raise HTTPException(404, "Prepared video is unavailable. Choose the file again.")
    return _launch_video_job(input_id, prepared["path"], service, service.consecutive_alert_frames)


def _launch_video_job(
    video_id: str,
    input_path: Path,
    service: DetectionService,
    consecutive_frames: int,
) -> dict[str, str]:
    output_path = VIDEO_RESULT_DIR / f"{video_id}.mp4"
    with VIDEO_JOB_LOCK:
        existing = VIDEO_JOB_STATUS.get(video_id)
        if existing and existing["status"] not in {"uploading", "preparing"}:
            return {"video_id": video_id, "status": existing["status"]}
        if existing is None:
            _check_video_job_capacity()
        VIDEO_JOB_STATUS[video_id] = {
            "status": "queued",
            "fraction": 0.0,
            "frames_processed": 0,
            "error": None,
            "result": None,
            "worker_active": True,
            "created_at": (existing or {}).get("created_at", time.time()),
        }
        cancel = VIDEO_JOB_CANCEL_EVENTS.setdefault(video_id, threading.Event())
        VIDEO_SOURCE_PATHS[video_id] = input_path
        VIDEO_FRAME_DETECTIONS[video_id] = []

    def publish_detections(detections: list[dict[str, Any]], index: int, fps: float) -> None:
        """Append indexed detections under the shared job lock."""
        with VIDEO_JOB_LOCK:
            VIDEO_FRAME_DETECTIONS[video_id].append(
                {"time": index / fps, "frame_index": index, "detections": detections}
            )
            count = len(VIDEO_FRAME_DETECTIONS[video_id])
            total = VIDEO_PREPARED_INPUTS.get(video_id, {}).get("response", {}).get("source_frames", 0)
            VIDEO_JOB_STATUS[video_id].update(
                frames_processed=count, fraction=min(0.5, 0.5 * count / total) if total else 0.0
            )

    def take_priority() -> float | None:
        """Consume the latest requested playhead position."""
        with VIDEO_JOB_LOCK:
            return VIDEO_SEEK_REQUESTS.pop(video_id, None)

    def run_job() -> None:
        """Analyse frames and export the annotated video in the background."""
        try:
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id]["status"] = "processing"
            from medfire_watch.video_analysis import analyse_video

            # Analysis uses only small GPU-scaled images. The original-resolution
            # export starts afterwards and reuses these results without inference.
            with VIDEO_JOB_LOCK:
                VIDEO_FRAME_DETECTIONS[video_id] = []
            analysis = analyse_video(
                input_path,
                service,
                publish_detections,
                initial_results=VIDEO_PREPARED_INPUTS.get(video_id, {}).get("initial_results"),
                priority=take_priority,
                cancelled=cancel,
                max_duration_seconds=service.max_video_duration_seconds,
            )
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {
                        "status": "exporting",
                        "analysis_complete": True,
                        "analysis_fps": analysis["analysis_fps"],
                        "analysis_seconds": analysis["analysis_seconds"],
                        "frames_processed": analysis["frames"],
                        "fraction": 0.5,
                    }
                )
            for event in iter_video_detections(
                input_path=input_path,
                output_path=output_path,
                infer=service.predict,
                consecutive_frames=consecutive_frames,
                max_duration_seconds=service.max_video_duration_seconds,
                infer_batch=getattr(service, "predict_batch", None),
                initial_results=analysis["results"],
                cancelled=cancel,
            ):
                if event["type"] == "progress":
                    with VIDEO_JOB_LOCK:
                        VIDEO_JOB_STATUS[video_id].update(
                            {
                                "fraction": 0.5 + event["fraction"] * 0.5,
                                "frames_exported": event["frames_processed"],
                                "clip_seconds": event["timestamp_seconds"],
                            }
                        )
                elif event["type"] == "complete":
                    if cancel.is_set():
                        raise RuntimeError("Video job cancelled.")
                    event["video_id"] = video_id
                    event["download_url"] = f"/videos/{video_id}/download"
                    event["confidence_threshold"] = service.confidence_threshold
                    with VIDEO_JOB_LOCK:
                        VIDEO_RESULT_PATHS[video_id] = output_path
                        VIDEO_JOB_STATUS[video_id].update(
                            {
                                "status": "complete",
                                "fraction": 1.0,
                                "frames_processed": event["frames_processed"],
                                "result": event,
                            }
                        )
        except Exception as exc:
            logger.exception("Background video job %s failed.", video_id)
            try:
                output_path.unlink(missing_ok=True)
            except OSError:
                logger.warning("Deferred partial-export cleanup for video job %s.", video_id)
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {
                        "status": "cancelled" if cancel.is_set() else "failed",
                        "error": f"Video processing failed ({type(exc).__name__}).",
                    }
                )
        finally:
            with VIDEO_JOB_LOCK:
                status_info = VIDEO_JOB_STATUS.get(video_id, {})
                if status_info.get("status") not in {"complete", "failed", "cancelled"}:
                    status_info.update(status="failed", error="Video worker ended without a result.")
                status_val = status_info.get("status")
                keep_source = status_val == "complete" and video_id in VIDEO_SOURCE_PATHS
                if not keep_source:
                    try:
                        input_path.unlink(missing_ok=True)
                        VIDEO_SOURCE_PATHS.pop(video_id, None)
                    except OSError:
                        logger.warning("Deferred source cleanup for video job %s.", video_id)
                if video_id in VIDEO_PREPARED_INPUTS:
                    VIDEO_PREPARED_INPUTS[video_id].pop("initial_results", None)
                status_info.update(worker_active=False, finished_at=time.time())

    try:
        threading.Thread(target=run_job, name=f"video-job-{video_id[:8]}", daemon=True).start()
    except BaseException:
        _discard_video_job(video_id)
        raise

    return {"video_id": video_id, "status": "queued"}


@router.get("/video-jobs/{video_id}/source")
def video_source(video_id: str) -> FileResponse:
    """Serve the original video for native playback."""
    path = VIDEO_SOURCE_PATHS.get(video_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Source video is unavailable.")
    media_type = VIDEO_SUFFIX_MEDIA_TYPES.get(path.suffix.lower(), "video/mp4")
    return LeasedVideoResponse(video_id, path, media_type=media_type)


@router.get("/video-jobs/{video_id}/frames")
def video_detections(video_id: str, since: int = 0) -> dict[str, Any]:
    """Return the next bounded page of frame detections."""
    with VIDEO_JOB_LOCK:
        if video_id not in VIDEO_FRAME_DETECTIONS:
            raise HTTPException(404, "Video job is unavailable.")
        return {"frames": VIDEO_FRAME_DETECTIONS[video_id][max(0, since) : max(0, since) + 300]}


@router.post("/video-jobs/{video_id}/seek")
def prioritise_video_playhead(video_id: str, seconds: float = Query(ge=0, le=600)) -> dict:
    """Request analysis near the current playback position."""
    with VIDEO_JOB_LOCK:
        if video_id not in VIDEO_JOB_STATUS:
            raise HTTPException(404, "Video job unavailable.")
        VIDEO_SEEK_REQUESTS[video_id] = seconds
    return {"prioritised_seconds": seconds}


@router.get("/video-jobs/{video_id}")
def video_job_status(video_id: str) -> dict[str, Any]:
    """Return a snapshot of background analysis and export state."""
    with VIDEO_JOB_LOCK:
        status = VIDEO_JOB_STATUS.get(video_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Video job was not found or has expired.")
        return dict(status)


@router.get("/videos/{video_id}/download")
def download_detected_video(video_id: str) -> FileResponse:
    """Serve a completed annotated video export."""
    path = VIDEO_RESULT_PATHS.get(video_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Annotated video was not found or has expired.")
    return LeasedVideoResponse(
        video_id,
        path,
        media_type="video/mp4",
        filename=f"medfire_annotated_{video_id[:8]}.mp4",
    )


@router.post("/video-jobs/{video_id}/cancel")
def cancel_video_job(video_id: str) -> dict[str, bool]:
    """Request cancellation; admission capacity releases only after worker cleanup."""
    with VIDEO_JOB_LOCK:
        if video_id not in VIDEO_JOB_STATUS:
            raise HTTPException(404, "Video job unavailable.")
        event = VIDEO_JOB_CANCEL_EVENTS.get(video_id)
        if event:
            event.set()
    return {"cancellation_requested": True}
