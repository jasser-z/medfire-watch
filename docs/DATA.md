# Data

## Operational map sources

| Source | Use | Local cache |
| --- | --- | --- |
| NASA FIRMS VIIRS SNPP NRT | Observed thermal anomalies in the last 24 hours | data/satellite/world_hotspots.json |
| Copernicus EMS / GWIS / ECMWF | Current official fire-weather classes | data/fire_weather |
| Open-Meteo forecast API | Current model-based temperature, humidity, wind, precipitation and today's summary | data/fire_weather/place_weather |
| EOX Sentinel-2 cloudless 2025 | Dated satellite background mosaic | Remote map tiles |
| OpenFreeMap / OpenStreetMap | Streets, labels and 3D buildings | Remote map tiles |
| GeoNames | Place search and nearest town | data/geospatial |

The application does not load training weather archives, old fire-frequency features or a vegetation baseline for the map. It does not infer numeric FWI from display colours; the place popup reads the provider display class. Weather context does not explain the provider index causally. Today is selected automatically using the viewer's timezone; current weather shows its provider valid timestamp and timezone. Forecast metadata, tiles and place weather cache for15minutes. Current conditions are model estimates, not on-site sensor readings. The daily Copernicus class is not an instantaneous weather measurement.

Recent observations are retained to show the 24-hour window, not for training. Caches are operational data. The annual background mosaic is imagery, not a live view.

FIRMS access uses a configured MAP_KEY, with provider quotas respected. Satellite delivery latency is measured after observation, not ignition. Low-confidence VIIRS detections are excluded; industrial heat sources may remain.

## Detector data and credits

Camera/image/video detection retains its trained detector. Training datasets were removed from this application checkout to save disk space; training/download source and evaluation evidence are retained separately from runtime. Sources include D-Fire (and associated paper), HPWREN, FESB and FireNet. Source links are listed in the project README; class mappings and layout are in configs/detection_data.yaml, and recorded evaluation reports are in docs/results. Those sources are not map risk-training inputs. Respect each source licence and attribution.

Map attributions: NASA FIRMS; European Union, Copernicus EMS/GWIS, ECMWF; Open-Meteo; EOX; OpenFreeMap and OpenStreetMap contributors; GeoNames.
