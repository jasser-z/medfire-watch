from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import requests
import shapefile
from shapely.geometry import shape

DEST = Path(__file__).resolve().parents[1] / "data" / "geospatial"


def main() -> None:
    files = [DEST / f"country_{kind}.json" for kind in ("labels", "boundaries")]
    if all(path.exists() for path in files):
        print("Country labels and boundaries already cached.")
        return
    response = requests.get(
        "https://naturalearth.s3.amazonaws.com/110m_cultural/ne_110m_admin_0_countries.zip", timeout=60
    )
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read("ne_110m_admin_0_countries.shp")),
            dbf=io.BytesIO(archive.read("ne_110m_admin_0_countries.dbf")),
        )
        labels, boundaries = [], []
        for record in reader.iterShapeRecords():
            props = record.record.as_dict()
            name = props.get("NAME_EN") or props["NAME"]
            geometry = record.shape.__geo_interface__
            point = shape(geometry).representative_point()
            labels.append(
                {
                    "type": "Feature",
                    "properties": {"name": name},
                    "geometry": {"type": "Point", "coordinates": [point.x, point.y]},
                }
            )
            boundaries.append({"type": "Feature", "properties": {"name": name}, "geometry": geometry})
    DEST.mkdir(parents=True, exist_ok=True)
    for file, features in zip(files, (labels, boundaries)):
        file.write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    print(f"Cached {len(labels)} country labels and boundaries.")


if __name__ == "__main__":
    main()
