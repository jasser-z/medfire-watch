"""Periodic retention and cache cleanup for ephemeral runs and fire-weather data."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from medfire_watch.config import PROJECT_ROOT, bounded_number, env_number

LOGGER = logging.getLogger(__name__)


def get_video_ttl_hours() -> float:
    """Read video TTL in hours from environment (default 24 hours)."""
    return env_number("MEDFIRE_VIDEO_TTL_HOURS", 24, 0, 8760)


def sweep_video_results(
    video_dir: Path | None = None,
    ttl_hours: float | None = None,
    *,
    force: bool = False,
) -> int:
    """Expire terminal jobs by completion time; never unlink active-worker artifacts.

    The job lock serializes reservations, transitions and deletion. After restart,
    unregistered artifacts expire together by their newest mtime (jobs are not persisted).
    """
    from api import services

    if ttl_hours is None:
        ttl_hours = get_video_ttl_hours()
    if video_dir is None:
        video_dir = services.VIDEO_RESULT_DIR

    cutoff = time.time() - bounded_number("MEDFIRE_VIDEO_TTL_HOURS", ttl_hours, 0, 8760) * 3600
    deleted_count = 0
    with services.VIDEO_JOB_LOCK:
        groups: dict[str, list[Path]] = {}
        if video_dir.is_dir():
            for path in video_dir.iterdir():
                if path.is_file() and not path.is_symlink():
                    job_id = path.name.split(".")[0].removesuffix("_input")
                    groups.setdefault(job_id, []).append(path)
        for job_id in set(groups) | set(services.VIDEO_JOB_STATUS):
            if services.VIDEO_DOWNLOAD_LEASES.get(job_id, 0):
                continue
            status = services.VIDEO_JOB_STATUS.get(job_id, {})
            if status and (
                status.get("status") not in {"complete", "failed", "cancelled"} or status.get("worker_active")
            ):
                continue
            paths = groups.get(job_id, [])
            try:
                newest = max((p.stat().st_mtime for p in paths), default=time.time())
                finished = status.setdefault("finished_at", status.get("created_at", newest))
                if not force and finished >= cutoff:
                    continue
                for path in paths:
                    path.unlink(missing_ok=True)
                    deleted_count += 1
            except OSError as exc:
                LOGGER.warning("Could not expire video job %s (%s).", job_id, type(exc).__name__)
                continue  # Keep state so a Windows sharing violation can be retried.
            for mapping in (
                services.VIDEO_JOB_STATUS,
                services.VIDEO_RESULT_PATHS,
                services.VIDEO_SOURCE_PATHS,
                services.VIDEO_FRAME_DETECTIONS,
                services.VIDEO_PREPARED_INPUTS,
                services.VIDEO_SEEK_REQUESTS,
                services.VIDEO_JOB_CANCEL_EVENTS,
                services.VIDEO_JOB_PAUSE_EVENTS,
            ):
                mapping.pop(job_id, None)

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
