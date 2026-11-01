from __future__ import annotations

import base64
import json
import logging
import threading
import uuid
from contextlib import asynccontextmanager
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from alerts.manager import AlertManager
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from medfire_watch.browser_camera import BrowserCameraMonitor
from medfire_watch.config import PROJECT_ROOT, load_env
from medfire_watch.drawing import draw_detections
from medfire_watch.video import iter_video_detections

DETECTION_WEIGHTS_PATH = (
    PROJECT_ROOT / "models" / "detection" / "weights" / "best.pt"
)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
DETECTION_CONFIG_PATH = PROJECT_ROOT / "configs" / "detection.yaml"
VIDEO_RESULT_DIR = PROJECT_ROOT / "runs" / "video_results"
VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
}
VIDEO_RESULT_PATHS: dict[str, Path] = {}
VIDEO_JOB_STATUS: dict[str, dict[str, Any]] = {}
VIDEO_JOB_LOCK = threading.Lock()
VIDEO_SOURCE_PATHS: dict[str, Path] = {}
VIDEO_FRAME_DETECTIONS: dict[str, list[dict[str, Any]]] = {}
VIDEO_PREPARED_INPUTS: dict[str, dict[str, Any]] = {}
VIDEO_SEEK_REQUESTS: dict[str, float] = {}
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(application: FastAPI):
    from starlette.concurrency import run_in_threadpool

    await run_in_threadpool(get_detection_service().warmup)
    stop_refresh = threading.Event()
    refresh_worker = threading.Thread(target=_world_refresh_loop, args=(stop_refresh,), daemon=True, name="satellite-refresh")
    refresh_worker.start()
    try:
        yield
    finally:
        stop_refresh.set()
        await run_in_threadpool(refresh_worker.join, 1)


app = FastAPI(title="MedFire Watch API", version="1.0.0", lifespan=lifespan)
load_env()


@app.middleware('http')
async def fresh_map_assets(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == '/world-map' or path.endswith('.mjs') or path in {
        '/fire-weather/metadata', '/fire-weather/place',
    }:
        response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response

_world_refresh_error: str | None = None
_browser_camera_monitor = BrowserCameraMonitor(detector_width=960)


def _world_refresh_loop(stop: threading.Event) -> None:
    """Keep the feed current even when browsers throttle or close their tabs."""
    while not stop.is_set():
        _refresh_map_data()
        if stop.wait(60):
            break


def _refresh_map_data() -> None:
    global _world_refresh_error
    from medfire_watch.world_hotspots import refresh_if_old
    try:
        result = refresh_if_old()
        if result is not None:  # A second request must not clear the active worker's failure state.
            _world_refresh_error = None
    except Exception as exc:
        _world_refresh_error = f"Latest update failed ({type(exc).__name__}); showing cached data."
        logger.warning("Satellite refresh failed (%s); cached observations retained.", type(exc).__name__)


@app.get("/world-map", response_class=HTMLResponse)
def satellite_map() -> str:
    from medfire_watch.map_assets import map_asset_version
    threading.Thread(target=_refresh_map_data, daemon=True).start()
    html = (PROJECT_ROOT / "dashboard" / "satellite_map.html").read_text(encoding="utf-8")
    return html.replace('/world-map/app.mjs', '/world-map/app.mjs?v=' + map_asset_version())


@app.get("/world-map/data")
def satellite_map_data() -> dict[str, Any]:
    from medfire_watch.world_hotspots import WORLD_PATH, load_world_hotspots, refresh_in_progress
    threading.Thread(target=_refresh_map_data, daemon=True).start()
    if not WORLD_PATH.exists():
        raise HTTPException(503, "Satellite data is loading.")
    return {"world": load_world_hotspots(),
            "refresh_error": _world_refresh_error, "refresh_in_progress": refresh_in_progress()}


@app.get("/world-map/countries/{kind}")
def countries(kind: str) -> dict[str, Any]:
    if kind not in {"labels", "boundaries"}:
        raise HTTPException(404, "Country layer not found.")
    path = PROJECT_ROOT / "data" / "geospatial" / f"country_{kind}.json"
    if not path.is_file():
        raise HTTPException(503, "Country data is unavailable.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/world-map/style.mjs")
def world_map_style() -> Response:
    from medfire_watch.map_assets import map_module
    return Response(map_module('map_style.mjs'), media_type='text/javascript')


@app.get("/world-map/logic.mjs")
def world_map_logic() -> Response:
    from medfire_watch.map_assets import map_module
    return Response(map_module('map_logic.mjs'), media_type='text/javascript')


@app.get("/world-map/app.mjs")
def world_map_app() -> Response:
    from medfire_watch.map_assets import map_module
    return Response(map_module('earth_watch.mjs'), media_type='text/javascript')


@app.get("/fire-weather/module.mjs")
def fire_weather_module() -> Response:
    from medfire_watch.map_assets import map_module
    return Response(map_module('fire_weather_layer.mjs'), media_type='text/javascript')


@app.get("/fire-weather/metadata")
def fire_weather_metadata(timezone_name: str = Query(default='UTC', alias='timezone', max_length=80)) -> dict:
    from medfire_watch.fire_weather import metadata
    try:
        return metadata(timezone_name)
    except (ValueError, KeyError):
        raise HTTPException(400, 'Unknown weather timezone.') from None
    except Exception:
        raise HTTPException(503, 'Fire-weather provider unavailable; no danger category can be inferred.') from None


@app.get('/fire-weather/place')
def fire_weather_place(date: str, latitude: float = Query(ge=-90, le=90),
                       longitude: float = Query(ge=-180, le=180),
                       timezone_name: str = Query(default='UTC', alias='timezone', max_length=80)) -> dict:
    from medfire_watch.place_danger import inspect_place
    try:
        return inspect_place(latitude, longitude, date, timezone_name)
    except (ValueError, KeyError):
        raise HTTPException(400, 'Current-day weather/date or timezone unavailable.') from None
    except Exception:
        raise HTTPException(503, 'Place forecast unavailable; no safe category inferred.') from None


@app.get("/fire-weather/tiles/{date}/{z}/{x}/{y}.png")
def fire_weather_tile(date: str, z: int, x: int, y: int) -> Response:
    from medfire_watch.fire_weather import tile
    try:
        return Response(tile(date, z, x, y), media_type='image/png', headers={'Cache-Control': 'public,max-age=900'})
    except ValueError:
        raise HTTPException(400, 'Invalid fire-weather tile.') from None
    except Exception:
        raise HTTPException(503, 'Fire-weather tile unavailable; missing data is not low danger.') from None




@app.get("/world-map/nearest-town")
def nearest_map_town(latitude: float = Query(ge=-90, le=90), longitude: float = Query(ge=-180, le=180)) -> dict:
    from medfire_watch.map_information import nearest_town

    return nearest_town(latitude, longitude)




@app.get("/video-test", response_class=HTMLResponse)
def local_video_test() -> str:
    return (PROJECT_ROOT / "dashboard" / "video_player.html").read_text(encoding="utf-8").replace("JOB", "local")


@app.get("/live-camera", response_class=HTMLResponse)
def live_camera_page() -> str:
    return (PROJECT_ROOT / "dashboard" / "live_camera.html").read_text(encoding="utf-8")


@app.get("/live-camera/coordinates.mjs")
def camera_coordinate_module() -> FileResponse:
    return FileResponse(PROJECT_ROOT / "dashboard" / "camera_coordinates.mjs", media_type="text/javascript")


def _decode_camera_upload(image: UploadFile) -> np.ndarray:
    import cv2

    payload = image.file.read()
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise HTTPException(400, "Camera frame is not a readable JPEG or PNG image.")
    if decoded.shape[0] * decoded.shape[1] > 25_000_000:
        raise HTTPException(413, "Camera frame exceeds the 25-megapixel limit.")
    return decoded


@app.post("/live-camera/detect")
def detect_camera_frame(
    image: UploadFile = File(...), service: Any = Depends(lambda: get_detection_service()),
) -> dict[str, Any]:
    """Detect a reduced browser frame; the native video element is never throttled."""
    return _browser_camera_monitor.process(_decode_camera_upload(image), service)


@app.post("/live-camera/alert/{alert_id}")
def queue_camera_alert(alert_id: str, image: UploadFile = File(...)) -> dict[str, bool]:
    queued = _browser_camera_monitor.submit_full_resolution_snapshot(alert_id, _decode_camera_upload(image))
    if not queued:
        raise HTTPException(409, "The alert snapshot expired or could not be queued.")
    return {"queued": True}


@app.get("/live-camera/status")
def live_camera_status() -> dict[str, Any]:
    return _browser_camera_monitor.status()


@app.post("/video-test/prepare")
def prepare_video_detector(service: Any = Depends(lambda: get_detection_service())) -> dict[str, Any]:
    from medfire_watch.video_hardware import nvenc_available
    if hasattr(service, "warmup"):
        service.warmup()
    return {"status": "ready", "video_encoder": "h264_nvenc" if nvenc_available() else "libx264",
            "maximum_upload_bytes": getattr(service, "max_video_upload_bytes", 1024**3),
            "maximum_duration_seconds": getattr(service, "max_video_duration_seconds", 600)}








class DetectionService:
    def __init__(self) -> None:
        if not DETECTION_WEIGHTS_PATH.is_file():
            raise FileNotFoundError(f"Detection weights are missing: {DETECTION_WEIGHTS_PATH}")
        detection_config = yaml.safe_load(DETECTION_CONFIG_PATH.read_text(encoding="utf-8"))
        self.confidence_threshold = float(detection_config["confidence_threshold"])
        if not 0 < self.confidence_threshold < 1:
            raise ValueError("Detector confidence threshold must be between zero and one.")
        self.consecutive_alert_frames = int(
            detection_config.get("temporal_alert", {}).get("consecutive_frames", 5)
        )
        self.max_video_upload_bytes = int(
            detection_config.get("video", {}).get("maximum_upload_mb", 100)
        ) * 1024 * 1024
        self.max_video_duration_seconds = float(
            detection_config.get("video", {}).get("maximum_duration_seconds", 120)
        )
        self._model: Any | None = None
        self._lock = threading.Lock()
        self._warm_lock = threading.Lock()
        self._warmed = False

    def warmup(self) -> None:
        with self._warm_lock:
            if not self._warmed:
                self.predict(np.zeros((360, 640, 3), dtype=np.uint8))
                self._warmed = True

    def _ensure_model(self):
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from ultralytics import YOLO

                    self._model = YOLO(str(DETECTION_WEIGHTS_PATH))
        return self._model

    @staticmethod
    def _format_result(result: Any, device: str) -> dict[str, Any]:
        boxes = result.boxes
        detections = []
        if boxes is not None:
            for xyxy, class_id, confidence in zip(
                boxes.xyxy.cpu().tolist(),
                boxes.cls.cpu().tolist(),
                boxes.conf.cpu().tolist(),
            ):
                detections.append(
                    {
                        "class": result.names[int(class_id)],
                        "confidence": float(confidence),
                        "xyxy": [float(value) for value in xyxy],
                    }
                )
        return {
            "detections": detections,
            "speed_ms": result.speed,
            "device": device,
            "confidence_threshold": 0.0,
        }

    def predict(self, image: np.ndarray) -> dict[str, Any]:
        import torch
        from ultralytics.cfg import DEFAULT_CFG_DICT

        device = 0 if torch.cuda.is_available() else "cpu"
        precision = ({"quantize": 16 if device == 0 else 32} if "quantize" in DEFAULT_CFG_DICT
                     else {"half": device == 0})
        model = self._ensure_model()
        with self._lock:
            result = model.predict(
                source=image,
                imgsz=640,
                conf=self.confidence_threshold,
                device=device,
                **precision,
                verbose=False,
            )[0]
        formatted = self._format_result(result, str(device))
        formatted["confidence_threshold"] = self.confidence_threshold
        formatted["precision"] = "fp16" if model.predictor.model.fp16 else "fp32"
        return formatted

    def predict_batch(self, images: list[np.ndarray]) -> list[dict[str, Any]]:
        if not images:
            return []
        import torch
        from ultralytics.cfg import DEFAULT_CFG_DICT

        device = 0 if torch.cuda.is_available() else "cpu"
        precision = ({"quantize": 16 if device == 0 else 32} if "quantize" in DEFAULT_CFG_DICT
                     else {"half": device == 0})
        model = self._ensure_model()
        with self._lock:
            results = model.predict(
                source=images,
                imgsz=640,
                conf=self.confidence_threshold,
                device=device,
                **precision,
                batch=len(images),
                verbose=False,
            )
        formatted = [self._format_result(result, str(device)) for result in results]
        for item in formatted:
            item["confidence_threshold"] = self.confidence_threshold
            item["precision"] = "fp16" if model.predictor.model.fp16 else "fp32"
        return formatted




@lru_cache(maxsize=1)
def _detection_service() -> DetectionService:
    return DetectionService()




def get_detection_service() -> DetectionService:
    return _detection_service()


def get_alert_manager() -> AlertManager:
    return AlertManager.from_config(PROJECT_ROOT / "configs" / "alerts.yaml")


@app.get("/health")
def health() -> dict[str, Any]:
    detection_ready = DETECTION_WEIGHTS_PATH.is_file()
    return {
        "status": "ok" if detection_ready else "degraded",
        "project": "MedFire Watch",
        "detection_model_ready": detection_ready,
        "alerts_mode": "telegram" if get_alert_manager().status()["configured"] else "not_configured",
    }












@app.post("/detect")
async def detect(
    image: UploadFile = File(...),
    service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(status_code=415, detail="Upload a JPEG or PNG image.")
    payload = await image.read(MAX_UPLOAD_BYTES + 1)
    await image.close()
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds the 10 MiB upload limit.")
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(BytesIO(payload)) as decoded_image:
            if decoded_image.format not in {"JPEG", "PNG"}:
                raise HTTPException(status_code=400, detail="Uploaded file is not a JPEG or PNG image.")
            if decoded_image.width * decoded_image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image exceeds the 25-megapixel limit.")
            decoded_image.load()
            rgb_image = np.asarray(decoded_image.convert("RGB"))
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Uploaded file is not a readable image.") from exc
    import cv2

    decoded = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
    result = service.predict(decoded)
    annotated = draw_detections(decoded, result["detections"])
    success, encoded = cv2.imencode(".png", annotated)
    if not success:
        raise RuntimeError("Could not encode the annotated image.")
    result["annotated_image_base64"] = base64.b64encode(encoded.tobytes()).decode("ascii")
    return result


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


@app.post("/video-inputs")
async def prepare_video_input(
    video: UploadFile = File(...), service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    video_id, input_path = await _save_video_upload(video, service)
    return await _prepare_saved_video(video_id, input_path, service)


@app.post("/video-upload")
async def stream_video_upload(
    request: Request, suffix: str = ".mp4", service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    if suffix not in {".mp4", ".mov", ".avi", ".webm"}:
        raise HTTPException(415, "Unsupported video extension.")
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
        reader = VideoReader(input_path, inference_width=640)
        try:
            batch = []
            for index in range(min(reader.frame_count or round(reader.fps), max(1, round(reader.fps)))):
                ok, frame = reader.read()
                if not ok:
                    break
                batch.append(frame)
                if len(batch) == 8:
                    cached_results.extend(service.predict_batch(batch) if hasattr(service, "predict_batch")
                                          else [service.predict(image) for image in batch])
                    batch = []
            if batch:
                cached_results.extend(service.predict_batch(batch) if hasattr(service, "predict_batch")
                                      else [service.predict(image) for image in batch])
            if not cached_results:
                raise ValueError("Video contains no decodable frames.")
            for result in cached_results:
                for detection in result["detections"]:
                    detection["xyxy"] = [value * (reader.source_width / reader.width if i % 2 == 0
                                                  else reader.source_height / reader.height)
                                         for i, value in enumerate(detection["xyxy"])]
            return {"input_id": video_id, "width": reader.source_width, "height": reader.source_height, "source_fps": reader.fps,
                    "video_decoder": reader.backend, "video_encoder": encoder_arguments(reader.width, reader.height)[0],
                    "detector_device": cached_results[0].get("device", "unknown"),
                    "detector_precision": cached_results[0].get("precision", "unknown"),
                    "initial_frames": [{"time": i / reader.fps, "detections": result["detections"]}
                                       for i, result in enumerate(cached_results)],
                    "prepared_seconds": time.perf_counter() - started}
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


@app.post("/video-inputs/{input_id}/predict")
def predict_prepared_video(input_id: str, service: DetectionService = Depends(get_detection_service)) -> dict[str, str]:
    with VIDEO_JOB_LOCK:
        prepared = VIDEO_PREPARED_INPUTS.get(input_id)
    if prepared is None or not prepared["path"].is_file():
        raise HTTPException(404, "Prepared video is unavailable. Choose the file again.")
    return _launch_video_job(input_id, prepared["path"], service, service.consecutive_alert_frames)


def _launch_video_job(
    video_id: str, input_path: Path, service: DetectionService, consecutive_frames: int,
) -> dict[str, str]:
    output_path = VIDEO_RESULT_DIR / f"{video_id}.mp4"
    with VIDEO_JOB_LOCK:
        if video_id in VIDEO_JOB_STATUS:
            return {"video_id": video_id, "status": VIDEO_JOB_STATUS[video_id]["status"]}
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
        with VIDEO_JOB_LOCK:
            VIDEO_FRAME_DETECTIONS[video_id].append({"time": index / fps, "frame_index": index, "detections": detections})

    def take_priority():
        with VIDEO_JOB_LOCK:
            return VIDEO_SEEK_REQUESTS.pop(video_id, None)


    def run_job() -> None:
        try:
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id]["status"] = "processing"
            from medfire_watch.video_analysis import analyse_video

            # Analysis uses only small GPU-scaled images. The original-resolution
            # export starts afterwards and reuses these results without inference.
            with VIDEO_JOB_LOCK:
                VIDEO_FRAME_DETECTIONS[video_id] = []
            analysis = analyse_video(
                input_path, service, publish_detections,
                initial_results=VIDEO_PREPARED_INPUTS.get(video_id, {}).get("initial_results"),
                priority=take_priority,
            )
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {"status": "exporting", "analysis_complete": True,
                     "analysis_fps": analysis["analysis_fps"], "analysis_seconds": analysis["analysis_seconds"],
                     "frames_processed": analysis["frames"], "fraction": 1.0}
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
                            {"status": "complete", "fraction": 1.0,
                             "frames_processed": event["frames_processed"], "result": event}
                        )
        except Exception as exc:
            logger.exception("Background video job %s failed.", video_id)
            output_path.unlink(missing_ok=True)
            with VIDEO_JOB_LOCK:
                VIDEO_JOB_STATUS[video_id].update(
                    {"status": "failed", "error": f"Video processing failed ({type(exc).__name__})."}
                )
        finally:
            pass  # Retain the source for native browser playback while the job is inspected.

    threading.Thread(target=run_job, name=f"video-job-{video_id[:8]}", daemon=True).start()
    return {"video_id": video_id, "status": "queued"}




@app.get("/video-jobs/{video_id}/source")
def video_source(video_id: str) -> FileResponse:
    path = VIDEO_SOURCE_PATHS.get(video_id)
    if path is None or not path.is_file():
        raise HTTPException(404, "Source video is unavailable.")
    return FileResponse(path, media_type="video/mp4")


@app.get("/video-jobs/{video_id}/frames")
def video_detections(video_id: str, since: int = 0) -> dict[str, Any]:
    with VIDEO_JOB_LOCK:
        if video_id not in VIDEO_FRAME_DETECTIONS:
            raise HTTPException(404, "Video job is unavailable.")
        return {"frames": VIDEO_FRAME_DETECTIONS[video_id][max(0, since):max(0, since) + 300]}


@app.post("/video-jobs/{video_id}/seek")
def prioritise_video_playhead(video_id: str, seconds: float = Query(ge=0, le=600)) -> dict:
    with VIDEO_JOB_LOCK:
        if video_id not in VIDEO_JOB_STATUS:
            raise HTTPException(404, "Video job unavailable.")
        VIDEO_SEEK_REQUESTS[video_id] = seconds
    return {"prioritised_seconds": seconds}





@app.get("/video-jobs/{video_id}")
def video_job_status(video_id: str) -> dict[str, Any]:
    with VIDEO_JOB_LOCK:
        status = VIDEO_JOB_STATUS.get(video_id)
        if status is None:
            raise HTTPException(status_code=404, detail="Video job was not found or has expired.")
        return dict(status)




@app.get("/videos/{video_id}/download")
def download_detected_video(video_id: str) -> FileResponse:
    path = VIDEO_RESULT_PATHS.get(video_id)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Annotated video was not found or has expired.")
    return FileResponse(
        path,
        media_type="video/mp4",
        filename=f"medfire_annotated_{video_id[:8]}.mp4",
    )


@app.get("/alerts")
def alert_status(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, Any]:
    return manager.status()




@app.get("/alerts/log")
def alert_log(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, Any]:
    return {"messages": manager.attempt_log(kind="live_camera")}


@app.get("/alerts/snapshots/{name}")
def camera_snapshot(name: str) -> FileResponse:
    directory = (PROJECT_ROOT / "runs" / "webcam_alerts").resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not name.startswith("alert_") or path.suffix.lower() != ".jpg" or not path.is_file():
        raise HTTPException(404, "Camera snapshot is unavailable.")
    return FileResponse(path, media_type="image/jpeg")


@app.delete('/alerts/history')
def delete_alert_history(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, int]:
    try:
        return manager.clear_history(PROJECT_ROOT / 'runs' / 'webcam_alerts')
    except OSError:
        raise HTTPException(503, 'Local snapshot history could not be fully cleared; please retry.') from None


@app.post("/telegram/detect")
def detect_telegram_chat(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, str]:
    try:
        return {"chat_id": manager.detect_chat()}
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


