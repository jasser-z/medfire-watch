"""User-requested cleanup of generated data; never remove source/research/settings."""

import os
import time
from pathlib import Path

from alerts.manager import AlertManager
from fastapi import APIRouter, Depends, HTTPException
from medfire_watch.config import PROJECT_ROOT
from medfire_watch.retention import sweep_video_results

from api import services
from api.services import get_alert_manager

router = APIRouter()


def _files(directory: Path):
    """Enumerate only real files in an explicitly configured runtime directory."""
    root = directory.absolute()
    if root.resolve() != root.parent.resolve() / root.name:
        return
    if not root.resolve().is_relative_to(PROJECT_ROOT.resolve()) or not root.is_dir():
        return
    for current, directories, names in os.walk(root, followlinks=False):
        folder = Path(current)
        directories[:] = [name for name in directories if (folder / name).resolve() == folder.resolve() / name]
        for name in names:
            path = folder / name
            if not path.is_symlink() and path.resolve() == folder.resolve() / name and path.is_file():
                yield path


@router.get("/runtime-cache")
def runtime_cache_status() -> dict:
    groups = {
        "videos": services.VIDEO_RESULT_DIR,
        "snapshots": PROJECT_ROOT / "runs" / "webcam_alerts",
        "provider_cache": PROJECT_ROOT / "data" / "fire_weather",
        "satellite_cache": PROJECT_ROOT / "data" / "satellite",
    }
    usage = {}
    for name, folder in groups.items():
        count = size = 0
        for path in _files(folder):
            try:
                size += path.stat().st_size
                count += 1
            except OSError:
                continue
        usage[name] = {"files": count, "bytes": size}
    with services.VIDEO_JOB_LOCK:
        active = sum(
            bool(
                s.get("worker_active")
                or s.get("status") in {"uploading", "preparing", "queued", "processing", "exporting"}
            )
            for s in services.VIDEO_JOB_STATUS.values()
        )
    return {"storage": usage, "active_video_jobs": active}


@router.delete("/runtime-cache")
def clear_runtime_cache(
    include_snapshots: bool = True,
    include_provider_cache: bool = True,
    manager: AlertManager = Depends(get_alert_manager),
) -> dict:
    """Remove terminal videos/results and selected generated caches, retaining active jobs."""
    deleted = sweep_video_results(force=True)
    snapshots = {"deleted_snapshots": 0, "deleted_attempts": 0, "remaining_snapshots": 0}
    if include_snapshots:
        from api.routers.detection import _browser_camera_monitor

        try:
            snapshots = _browser_camera_monitor.clear_snapshots(manager)
        except OSError:
            raise HTTPException(
                503, "Some local history files are in use; retry cleanup after activity stops."
            ) from None
    provider_deleted = busy = 0
    if include_provider_cache:
        from medfire_watch import fire_weather, world_hotspots

        for folder, lock, is_busy in (
            (PROJECT_ROOT / "data" / "satellite", world_hotspots._LOCK, lambda: False),
            (PROJECT_ROOT / "data" / "fire_weather", fire_weather.LOCK, lambda: fire_weather._FETCH_IN_PROGRESS),
        ):
            if not lock.acquire(blocking=False):
                busy += 1
                continue
            try:
                if is_busy():
                    busy += 1
                    continue
                for path in _files(folder):
                    try:
                        if path.suffix == ".part" and time.time() - path.stat().st_mtime < 60:
                            busy += 1
                            continue
                        path.unlink(missing_ok=True)
                        provider_deleted += 1
                    except OSError:
                        busy += 1
            finally:
                lock.release()
        with world_hotspots._WORLD_CACHE_LOCK:
            world_hotspots._WORLD_CACHE = None
    return {
        "deleted_video_files": deleted,
        "deleted_provider_files": provider_deleted,
        "busy_cache_entries": busy,
        **snapshots,
        **runtime_cache_status(),
    }
