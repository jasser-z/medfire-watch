"""Periodic retention and cache cleanup for ephemeral runs and fire-weather data."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from medfire_watch.config import PROJECT_ROOT

LOGGER = logging.getLogger(__name__)


def get_video_ttl_hours() -> float:
    """Read video TTL in hours from environment (default 24 hours)."""
    try:
        return float(os.getenv("MEDFIRE_VIDEO_TTL_HOURS", "24"))
    except ValueError:
        return 24.0


def sweep_video_results(
    video_dir: Path | None = None,
    ttl_hours: float | None = None,
) -> int:
    """Delete video_results files older than TTL and clear matching entries in VIDEO_* dicts."""
    from api import services

    if ttl_hours is None:
        ttl_hours = get_video_ttl_hours()
    if video_dir is None:
        video_dir = services.VIDEO_RESULT_DIR

    deleted_count = 0
    now = time.time()
    cutoff_seconds = ttl_hours * 3600.0
    expired_job_ids: set[str] = set()

    if video_dir.is_dir():
        for file_path in video_dir.iterdir():
            if not file_path.is_file():
                continue
            try:
                age = now - file_path.stat().st_mtime
                if age > cutoff_seconds:
                    stem = file_path.stem
                    job_id = stem.replace("_input", "").split(".")[0]
                    expired_job_ids.add(job_id)
                    file_path.unlink(missing_ok=True)
                    deleted_count += 1
            except OSError as exc:
                LOGGER.warning("Could not delete expired video file %s: %s", file_path, exc)

    with services.VIDEO_JOB_LOCK:
        for job_id in list(services.VIDEO_JOB_STATUS.keys()):
            res_path = services.VIDEO_RESULT_PATHS.get(job_id)
            src_path = services.VIDEO_SOURCE_PATHS.get(job_id)
            is_expired = job_id in expired_job_ids
            if not is_expired:
                for path in (res_path, src_path):
                    if path and path.is_file() and (now - path.stat().st_mtime > cutoff_seconds):
                        is_expired = True
                        break
            if is_expired:
                expired_job_ids.add(job_id)
                services.VIDEO_JOB_STATUS.pop(job_id, None)
                services.VIDEO_RESULT_PATHS.pop(job_id, None)
                services.VIDEO_SOURCE_PATHS.pop(job_id, None)
                services.VIDEO_FRAME_DETECTIONS.pop(job_id, None)
                services.VIDEO_PREPARED_INPUTS.pop(job_id, None)
                services.VIDEO_SEEK_REQUESTS.pop(job_id, None)

    return deleted_count


def sweep_fire_weather_cache(
    base_dir: Path | None = None,
    max_age_hours: float = 24.0,
) -> int:
    """Prune data/fire_weather/tiles and data/fire_weather/place_weather files older than 24h."""
    if base_dir is None:
        base_dir = PROJECT_ROOT / "data" / "fire_weather"

    now = time.time()
    cutoff_seconds = max_age_hours * 3600.0
    deleted_count = 0

    for sub in ("tiles", "place_weather"):
        target_dir = base_dir / sub
        if not target_dir.is_dir():
            continue
        for file_path in target_dir.rglob("*"):
            if not file_path.is_file():
                continue
            try:
                age = now - file_path.stat().st_mtime
                if age > cutoff_seconds:
                    file_path.unlink(missing_ok=True)
                    deleted_count += 1
            except OSError as exc:
                LOGGER.warning("Could not prune fire-weather cache file %s: %s", file_path, exc)

    return deleted_count


def sweep_retention() -> dict[str, int]:
    """Execute all retention sweeps. Never touches runs/webcam_alerts."""
    video_deleted = sweep_video_results()
    cache_pruned = sweep_fire_weather_cache()
    return {"video_results_deleted": video_deleted, "fire_weather_pruned": cache_pruned}

