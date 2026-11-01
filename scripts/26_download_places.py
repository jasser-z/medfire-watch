"""Cache public GeoNames populated places for local nearest-town lookups."""
import io
import json
import zipfile
from pathlib import Path

import requests

root = Path(__file__).resolve().parents[1]
destination = root / 'data/geospatial/places.json'
if destination.is_file():
    print('Reusing cached GeoNames places.')
else:
    response = requests.get('https://download.geonames.org/export/dump/cities1000.zip', timeout=(10, 120))
    response.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    rows = []
    for line in archive.read('cities1000.txt').decode('utf-8').splitlines():
        fields = line.split('\t')
        rows.append({'name': fields[1], 'country': fields[8], 'latitude': float(fields[4]), 'longitude': float(fields[5])})
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(rows, ensure_ascii=False), encoding='utf-8')
    print('Cached GeoNames populated places:', len(rows))
