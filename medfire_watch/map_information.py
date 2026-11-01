"""Nearest catalogued GeoNames place for map point labels."""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

from medfire_watch.config import PROJECT_ROOT


@lru_cache(maxsize=1)
def places() -> list:
    path = PROJECT_ROOT / 'data/geospatial/places.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []


def nearest_town(latitude: float, longitude: float) -> dict:
    rows = places()
    if not rows:
        return {'available': False}
    lat = np.radians([r['latitude'] for r in rows])
    lon = np.radians([r['longitude'] for r in rows])
    p, q = np.radians(latitude), np.radians(longitude)
    hav = np.sin((lat-p)/2)**2 + np.cos(p)*np.cos(lat)*np.sin((lon-q)/2)**2
    index = int(np.argmin(hav))
    return {'available': True, **rows[index], 'km': float(6371*2*np.arcsin(np.sqrt(hav[index]))),
            'source': 'GeoNames cities1000, CC BY; nearest catalogued populated place'}


