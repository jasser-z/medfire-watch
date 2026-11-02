from __future__ import annotations

import base64
from io import BytesIO
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from medfire_watch.browser_camera import BrowserCameraMonitor
from medfire_watch.config import PROJECT_ROOT
from medfire_watch.drawing import draw_detections
from pydantic import BaseModel, Field

from api.services import (
    DETECTION_WEIGHTS_PATH,
    MAX_IMAGE_PIXELS,
    MAX_UPLOAD_BYTES,
    DetectionService,
    get_alert_manager,
    get_detection_service,
)

router = APIRouter()
_browser_camera_monitor = BrowserCameraMonitor(detector_width=960)


@router.get("/live-camera", response_class=HTMLResponse)
def live_camera_page() -> str:
    """Serve the native browser camera page."""
    return (PROJECT_ROOT / "dashboard" / "live_camera.html").read_text(encoding="utf-8")


@router.get("/live-camera/coordinates.mjs")
def camera_coordinate_module() -> FileResponse:
    """Serve detector-to-source coordinate conversion."""
    return FileResponse(PROJECT_ROOT / "dashboard" / "camera_coordinates.mjs", media_type="text/javascript")


@router.get("/live-camera/app.mjs")
def camera_app_module() -> FileResponse:
    """Serve the native camera controller."""
    return FileResponse(PROJECT_ROOT / "dashboard" / "live_camera.mjs", media_type="text/javascript")


def _decode_camera_upload(image: UploadFile) -> np.ndarray:
    import cv2
    from PIL import Image, UnidentifiedImageError

    payload = image.file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Camera frame exceeds the 10 MiB upload limit.")
    try:
        with Image.open(BytesIO(payload)) as decoded_image:
            if decoded_image.format not in {"JPEG", "PNG"}:
                raise HTTPException(status_code=400, detail="Camera frame is not a readable JPEG or PNG image.")
            if decoded_image.width * decoded_image.height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Camera frame exceeds the 25-megapixel limit.")
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Camera frame is not a readable JPEG or PNG image.") from exc
    decoded = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is None or decoded.size == 0:
        raise HTTPException(status_code=400, detail="Camera frame is not a readable JPEG or PNG image.")

    return decoded


@router.post("/live-camera/detect")
def detect_camera_frame(
    image: UploadFile = File(...),
    session_id: str = Header("default", alias="x-camera-session"),
    service: Any = Depends(lambda: get_detection_service()),
) -> dict[str, Any]:
    """Detect a reduced browser frame; the native video element is never throttled."""
    return _browser_camera_monitor.process(_decode_camera_upload(image), service, session_id=session_id)


@router.post("/live-camera/alert/{alert_id}")
def queue_camera_alert(alert_id: str, image: UploadFile = File(...)) -> dict[str, bool]:
    """Queue the full-resolution frame for a pending camera alert."""
    queued = _browser_camera_monitor.submit_full_resolution_snapshot(alert_id, _decode_camera_upload(image))
    if not queued:
        raise HTTPException(409, "The alert snapshot expired or could not be queued.")
    return {"queued": True}


@router.get("/live-camera/status")
def live_camera_status() -> dict[str, Any]:
    """Report camera photo delivery counts and the latest failure."""
    return _browser_camera_monitor.status()


class CameraCooldownSettings(BaseModel):
    minutes: int = Field(ge=0, le=1440, strict=True)


@router.get("/live-camera/cooldown")
def camera_cooldown() -> dict[str, int]:
    """Return the active camera alert interval in minutes."""
    return {"minutes": get_alert_manager().camera_cooldown()}


@router.put("/live-camera/cooldown")
def edit_camera_cooldown(settings: CameraCooldownSettings) -> dict[str, int]:
    """Save a camera-only alert interval across restarts."""
    try:
        return {"minutes": get_alert_manager().set_camera_cooldown(settings.minutes)}
    except OSError:
        raise HTTPException(503, "The camera cooldown could not be saved.") from None


@router.post("/live-camera/cooldown/reset")
def reset_camera_cooldown() -> dict[str, bool]:
    """Clear only the camera timer so the next qualifying alert can be sent."""
    try:
        get_alert_manager().reset_camera_cooldown()
    except (OSError, RuntimeError):
        raise HTTPException(503, "The camera cooldown could not be reset.") from None
    if _browser_camera_monitor.last_error == "Camera alert was suppressed by cooldown.":
        _browser_camera_monitor.last_error = None
    return {"reset": True}


@router.get("/health")
def health() -> dict[str, Any]:
    """Report model availability and Telegram configuration."""
    detection_ready = DETECTION_WEIGHTS_PATH.is_file()
    return {
        "status": "ok" if detection_ready else "degraded",
        "project": "MedFire Watch",
        "detection_model_ready": detection_ready,
        "alerts_mode": "telegram" if get_alert_manager().status()["configured"] else "not_configured",
    }


@router.post("/detect")
async def detect(
    image: UploadFile = File(...),
    service: DetectionService = Depends(get_detection_service),
) -> dict[str, Any]:
    """Validate an uploaded image and return boxes and an annotated PNG."""
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
    from starlette.concurrency import run_in_threadpool

    def _process_inference() -> dict[str, Any]:
        import cv2

        decoded = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)
        result = service.predict(decoded)
        annotated = draw_detections(decoded, result["detections"])
        success, encoded = cv2.imencode(".png", annotated)
        if not success:
            raise RuntimeError("Could not encode the annotated image.")
        result["annotated_image_base64"] = base64.b64encode(encoded.tobytes()).decode("ascii")
        return result

    return await run_in_threadpool(_process_inference)
