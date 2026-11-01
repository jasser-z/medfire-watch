from __future__ import annotations

from typing import Any

from alerts.manager import AlertManager
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from medfire_watch.config import PROJECT_ROOT

from api.services import (
    get_alert_manager,
)

router = APIRouter()


@router.get("/alerts")
def alert_status(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, Any]:
    """Report Telegram configuration and delivery state."""
    return manager.status()


@router.get("/alerts/log")
def alert_log(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, Any]:
    """List camera photo attempts without text-message history."""
    return {"messages": manager.attempt_log(kind="live_camera")}


@router.get("/alerts/snapshots/{name}")
def camera_snapshot(name: str) -> FileResponse:
    """Serve a validated local camera snapshot filename."""
    directory = (PROJECT_ROOT / "runs" / "webcam_alerts").resolve()
    path = (directory / name).resolve()
    if path.parent != directory or not name.startswith("alert_") or path.suffix.lower() != ".jpg" or not path.is_file():
        raise HTTPException(404, "Camera snapshot is unavailable.")
    return FileResponse(path, media_type="image/jpeg")


@router.delete("/alerts/history")
def delete_alert_history(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, int]:
    """Clear local photo attempts and saved camera snapshots."""
    try:
        return manager.clear_history(PROJECT_ROOT / "runs" / "webcam_alerts")
    except OSError:
        raise HTTPException(503, "Local snapshot history could not be fully cleared; please retry.") from None


@router.post("/telegram/detect")
def detect_telegram_chat(manager: AlertManager = Depends(get_alert_manager)) -> dict[str, str]:
    """Discover a chat from the configured bot updates."""
    try:
        return {"chat_id": manager.detect_chat()}
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
