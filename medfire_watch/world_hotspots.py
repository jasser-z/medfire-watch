from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from medfire_watch.config import PROJECT_ROOT, get_setting

WORLD_PATH = PROJECT_ROOT / "data" / "satellite" / "world_hotspots.json"
_LOCK = threading.Lock()


def refresh_world_hotspots(path: Path = WORLD_PATH) -> dict:
    """Fetch and aggregate recent global satellite observations, without logging credentials."""
    key = get_setting("FIRMS_MAP_KEY")
    if not key:
        raise RuntimeError("NASA FIRMS key is not configured.")
    try:
        response = requests.get(
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/VIIRS_SNPP_NRT/world/2",
            timeout=(15, 180),
        )
    except requests.RequestException:
        raise RuntimeError("NASA FIRMS global request failed; check network and key.") from None
    if not response.ok:
        raise RuntimeError(f"NASA FIRMS global request returned HTTP {response.status_code}.")
    frame = pd.read_csv(io.StringIO(response.text), dtype={"acq_time": str})
    required = {"latitude", "longitude", "acq_date", "acq_time", "frp"}
    if not required.issubset(frame.columns):
        raise RuntimeError("NASA FIRMS global response did not contain the expected columns.")
    times = pd.to_datetime(
        frame["acq_date"].astype(str) + " " + frame["acq_time"].fillna("0").str.zfill(4),
        format="%Y-%m-%d %H%M", errors="coerce", utc=True,
    )
    now = datetime.now(timezone.utc)
    frame = frame.loc[(times >= now - timedelta(hours=24)) & (times <= now)].copy()
    frame["observation_utc"] = times.loc[frame.index]
    for col in ("latitude", "longitude", "frp"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["latitude", "longitude"])
    # Keep individual FIRMS observations. MapLibre clusters these only at low zoom;
    # storing one-degree aggregates here would make a displayed 24-hour point false.
    confidence = frame.get("confidence", pd.Series("unknown", index=frame.index)).astype(str).str.lower()
    frame = frame.loc[~confidence.isin(["low", "l"])].copy()
    frame["observation_utc"] = frame["observation_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    detections = [
        {
            "latitude": float(row.latitude), "longitude": float(row.longitude),
            "frp": float(row.frp) if pd.notna(row.frp) else 0.0,
            "confidence": str(getattr(row, "confidence", "unknown")),
            "satellite": str(getattr(row, "satellite", "VIIRS SNPP")),
            "observed_at": str(row.observation_utc),
        }
        for row in frame.itertuples(index=False)
    ]
    result = {
        "updated_utc": now.isoformat(), "source": "NASA FIRMS VIIRS SNPP NRT",
        "observations": int(len(frame)), "detections": detections,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    tmp.replace(path)
    return result


def refresh_in_progress() -> bool:
    return _LOCK.locked()


def refresh_if_old() -> bool | None:
    if not _LOCK.acquire(blocking=False):
        return
    try:
        if WORLD_PATH.exists():
            age = datetime.now(timezone.utc).timestamp() - WORLD_PATH.stat().st_mtime
            if age < 600:
                return False
        refresh_world_hotspots()
        return True
    finally:
        _LOCK.release()


def load_world_hotspots(path: Path = WORLD_PATH) -> dict:
    """Filter legacy cached VIIRS low-confidence shorthand as well as new data."""
    saved = json.loads(path.read_text(encoding='utf-8'))
    if 'detections' in saved:
        saved['detections'] = [d for d in saved['detections'] if str(d.get('confidence', '')).lower() not in {'l', 'low'}]
        saved['observations'] = len(saved['detections'])
    return saved
