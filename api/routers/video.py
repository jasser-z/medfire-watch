from __future__ import annotations

import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from medfire_watch.config import PROJECT_ROOT
from medfire_watch.video import iter_video_detections

from api.services import (
    DEFAULT_VIDEO_DURATION_SECONDS,
    DEFAULT_VIDEO_UPLOAD_MB,
    VIDEO_CONTENT_TYPES,
    VIDEO_FRAME_DETECTIONS,
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


def _get_max_video_jobs() -> int:
    try:
        return int(os.getenv("MEDFIRE_MAX_VIDEO_JOBS", "2"))
    except ValueError:
        return 2


def _check_video_job_capacity() -> None:
    with VIDEO_JOB_LOCK:
        active = sum(
            1
            for status in VIDEO_JOB_STATUS.values()
            if status.get("status") in {"queued", "processing", "exporting"}
        )
        if active >= _get_max_video_jobs():
            raise HTTPException(status_code=429, detail="Maximum concurrent video jobs reached. Please retry later.")


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
    import cv2

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise HTTPException(status_code=400, detail="Uploaded video is not readable by OpenCV.")
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    readable, _ = capture.read()
    capture.release()
    if not readable or width < 1 or height < 1:
        raise HTTPException(status_code=400, detail="Uploaded video has no decodable frames.")
    if width * height > 8_294_400:
        raise HTTPException(status_code=413, detail="Video resolution exceeds the 4K limit.")
    if fps > 0 and frame_count / fps > service.max_video_duration_seconds:
        raise HTTPException(
            status_code=413,
            detail=f"Video duration exceeds {service.max_video_duration_seconds:g} seconds.",
        )


async def _save_video_upload(video: UploadFile, service: DetectionService) -> tuple[str, Path]:
    if video.content_type not in VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Upload an MP4, MOV, AVI, or WebM video.")
    suffix = Path(video.filename or "upload.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".avi", ".webm"}:
        suffix = ".mp4"
    _check_video_job_capacity()
    video_id = uuid.uuid4().hex
    VIDEO_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    input_path = VIDEO_RESULT_DIR / f"{video_id}_input{suffix}"
    received = 0
    try:
        with input_path.open("wb") as output:
            while chunk := await video.read(4 * 1024 * 1024):
                received += len(chunk)
                if received > service.max_video_upload_bytes:
                    raise HTTPException(413, "Video exceeds the configured upload limit.")
                output.write(chunk)
    except Exception:
        input_path.unlink(missing_ok=True)
        raise
    finally:
        await video.close()
    try:
        _validate_video_file(input_path, service)
    except Exception:
        input_path.unlink(missing_ok=True)
        raise
    return video_id, input_path


@router.post("/video-inputs")
async def prepare_video_input(
    video: UploadFile = File(...),
    service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    """Save a multipart video and prepare its first predictions."""
    _check_video_job_capacity()
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
    _check_video_job_capacity()
    video_id = uuid.uuid4().hex
    VIDEO_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    path = VIDEO_RESULT_DIR / f"{video_id}_input{suffix}"
    received = 0
    import time

    started = time.perf_counter()
    try:
        with path.open("wb") as output:
            async for chunk in request.stream():
                received += len(chunk)
                if received > service.max_video_upload_bytes:
                    raise HTTPException(413, "Video exceeds the configured upload limit.")
                output.write(chunk)
        upload_seconds = time.perf_counter() - started
        _validate_video_file(path, service)
        prepared = await _prepare_saved_video(video_id, path, service)
        prepared.update({"upload_seconds": upload_seconds, "upload_bytes": received})
        return prepared
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def _prepare_saved_video(video_id: str, input_path: Path, service: DetectionService) -> dict[str, Any]:
    import time

    from medfire_watch.video_hardware import VideoReader, encoder_arguments
    from starlette.concurrency import run_in_threadpool

    started = time.perf_counter()

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
        prepared = await run_in_threadpool(prepare)
    except Exception:
        input_path.unlink(missing_ok=True)
        raise HTTPException(422, "The video could not be prepared for prediction.") from None
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
        if video_id in VIDEO_JOB_STATUS:
            return {"video_id": video_id, "status": VIDEO_JOB_STATUS[video_id]["status"]}
        active = sum(
            1
            for status in VIDEO_JOB_STATUS.values()
            if status.get("status") in {"queued", "processing", "exporting"}
        )
        if active >= _get_max_video_jobs():
            raise HTTPException(status_code=429, detail="Maximum concurrent video jobs reached. Please retry later.")
        VIDEO_JOB_STATUS[video_id] = {
            "status": "queued",
            "fraction": 0.0,
            "frames_processed": 0,
            "error": None,
            "result": None,
        }
        VIDEO_SOURCE_PATHS[video_id] = input_path
        VIDEO_FRAME_DETECTIONS[video_id] = []

    def publish_detections(detections: list[dict[str, Any]], index: int, fps: float) -> None:
        """Append indexed detections under the shared job lock."""
        with VIDEO_JOB_LOCK:
            VIDEO_FRAME_DETECTIONS[video_id].append(
                {"time": index / fps, "frame_index": index, "detections": detections}
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
            )
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {
                        "status": "exporting",
                        "analysis_complete": True,
                        "analysis_fps": analysis["analysis_fps"],
                        "analysis_seconds": analysis["analysis_seconds"],
                        "frames_processed": analysis["frames"],
                        "fraction": 1.0,
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
            ):
                if event["type"] == "progress":
                    with VIDEO_JOB_LOCK:
                        VIDEO_JOB_STATUS[video_id].update(
                            {
                                "fraction": event["fraction"],
                                "frames_processed": event["frames_processed"],
                                "clip_seconds": event["timestamp_seconds"],
                            }
                        )
                elif event["type"] == "complete":
                    VIDEO_RESULT_PATHS[video_id] = output_path
                    event["video_id"] = video_id
                    event["download_url"] = f"/videos/{video_id}/download"
                    event["confidence_threshold"] = service.confidence_threshold
                    with VIDEO_JOB_LOCK:
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
            output_path.unlink(missing_ok=True)
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {"status": "failed", "error": f"Video processing failed ({type(exc).__name__})."}
                )
        finally:
            with VIDEO_JOB_LOCK:
                status_info = VIDEO_JOB_STATUS.get(video_id, {})
                status_val = status_info.get("status")
                keep_source = status_val == "complete" and video_id in VIDEO_SOURCE_PATHS
            if not keep_source:
                input_path.unlink(missing_ok=True)
                with VIDEO_JOB_LOCK:
                    VIDEO_SOURCE_PATHS.pop(video_id, None)

    threading.Thread(target=run_job, name=f"video-job-{video_id[:8]}", daemon=True).start()
    return {"video_id": video_id, "status": "queued"}


@router.get("/video-jobs/{video_id}/source")
def video_source(video_id: str) -> FileResponse:
    """Serve the original video for native playback."""
    path = VIDEO_SOURCE_PATHS.get(video_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Source video is unavailable.")
    media_type = VIDEO_SUFFIX_MEDIA_TYPES.get(path.suffix.lower(), "video/mp4")
    return FileResponse(path, media_type=media_type)


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
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"medfire_annotated_{video_id[:8]}.mp4",
    )
