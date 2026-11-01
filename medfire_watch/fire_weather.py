"""Public Copernicus/GWIS fire-weather baseline, independent of trained probabilities."""
from __future__ import annotations

import io
import json
import threading
import xml.etree.ElementTree as ET
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests
from PIL import Image

from medfire_watch.config import PROJECT_ROOT

SERVICE = 'https://maps.effis.emergency.copernicus.eu/gwis'
CACHE = PROJECT_ROOT / 'data/fire_weather'
LOCK = threading.Lock()
CLASSES = [{'name': name, 'upper': upper} for name, upper in [
    ('Low', 11.2), ('Moderate', 21.3), ('High', 38), ('Very high', 50), ('Extreme', 70), ('Very extreme', None)]]


def _today_metadata(saved: dict, timezone_name: str) -> dict:
    today = datetime.now(ZoneInfo(timezone_name)).date()
    maximum = Date.fromisoformat(saved['latest_available_date'])
    return {**saved, 'today': today.isoformat(), 'timezone': timezone_name,
            'dates': [today.isoformat()] if today <= maximum else []}


def metadata(timezone_name: str = 'UTC') -> dict:
    # Validate before network access; the shared provider cache is timezone-independent.
    ZoneInfo(timezone_name)
    path = CACHE / 'metadata.json'
    with LOCK:
        if path.exists():
            try:
                saved = json.loads(path.read_text(encoding='utf-8'))
                checked = datetime.fromisoformat(saved['checked_utc']).astimezone(timezone.utc)
                now = datetime.now(timezone.utc)
                if 0 <= (now-checked).total_seconds() < 900 and checked.date() == now.date() and saved.get('latest_available_date'):
                    return _today_metadata(saved, timezone_name)
            except (KeyError, TypeError, ValueError, OSError):
                pass  # Old or corrupt cache is not evidence that today's forecast is available.
        response = requests.get(SERVICE, params={'service': 'WMS', 'version': '1.1.1', 'request': 'GetCapabilities'},
                                timeout=(8, 30))
        response.raise_for_status()
        root = ET.fromstring(response.content)
        layer = next(item for item in root.findall('.//Layer') if item.findtext('Name') == 'ecmwf.fwi')
        extent = next(item for item in layer.findall('Extent') if item.get('name') == 'time')
        maximum = Date.fromisoformat(extent.attrib['default'])
        payload = {'source': 'Copernicus EMS / GWIS · ECMWF', 'kind': 'fire_weather_index', 'probability': False,
                   'checked_utc': datetime.now(timezone.utc).isoformat(), 'forecast_issue_time': None,
                   'latest_available_date': maximum.isoformat(),
                   'classes': CLASSES, 'occurrence_model_active': False,
                   'meaning': 'Weather conditions favouring ignition and fire behaviour; not an active-fire report.',
                   'attribution': '© European Union, Copernicus EMS / GWIS, ECMWF'}
        CACHE.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix('.part')
        temporary.write_text(json.dumps(payload), encoding='utf-8')
        temporary.replace(path)
        return _today_metadata(payload, timezone_name)


def tile(date: str, z: int, x: int, y: int) -> bytes:
    requested = Date.fromisoformat(date)
    today = datetime.now(timezone.utc).date()
    # A viewer's current local date may be one day either side of UTC at midnight.
    if not today-timedelta(days=1) <= requested <= today+timedelta(days=1) or not 0 <= z <= 10 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        raise ValueError('Invalid forecast tile/date.')
    path = CACHE / 'tiles' / date / str(z) / str(x) / f'{y}.png'
    if path.exists() and datetime.now(timezone.utc).timestamp()-path.stat().st_mtime < 900:
        return path.read_bytes()
    size = 40075016.68557849 / 2**z
    west, north = -20037508.342789244+x*size, 20037508.342789244-y*size
    response = requests.get(SERVICE, params={
        'service': 'WMS', 'version': '1.1.1', 'request': 'GetMap', 'layers': 'ecmwf.fwi',
        'styles': '', 'srs': 'EPSG:3857', 'bbox': f'{west},{north-size},{west+size},{north}',
        'width': 256, 'height': 256, 'time': date, 'format': 'image/png', 'transparent': 'true',
    }, timeout=(8, 30))
    response.raise_for_status()
    with Image.open(io.BytesIO(response.content)) as image:
        image.verify()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return response.content
