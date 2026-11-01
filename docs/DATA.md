# Data

| Source | Purpose | Cache |
| --- | --- | --- |
| NASA FIRMS VIIRS SNPP NRT | Last 24 hours of thermal observations | `data/satellite/world_hotspots.json` |
| Copernicus EMS / GWIS / ECMWF | Official daily fire-weather classes | `data/fire_weather` |
| Open-Meteo | Current model estimates and today's local summary | `data/fire_weather/place_weather` |
| EOX Sentinel-2 cloudless 2025 | Annual satellite mosaic | Remote tiles |
| OpenFreeMap / OpenStreetMap / OpenMapTiles | Streets, names and buildings | Remote tiles |
| GeoNames | Place search and nearest town | `data/geospatial/places.json` |
| Natural Earth | Country boundaries and labels | `data/geospatial/country_*.json` |

FIRMS requests use a private MAP_KEY. Low-confidence VIIRS observations are filtered.
The place popup reads the provider's displayed danger class rather than estimating numeric
FWI from colours. Open-Meteo supplies temperature, humidity, wind and precipitation with
provider validity times and the viewer's timezone. Refresh timing is in
[architecture](ARCHITECTURE.md); interpretation is in [limits](LIMITATIONS.md).

## Detector datasets

Training combines D-Fire fire/smoke images and Pyro-SDIS smoke/negative images using
class IDs 0 = fire and 1 = smoke. Source split lists and class mapping are verified before
merging; D-Fire's official test split is held out. Runtime uses the deployed checkpoint
and three geospatial catalogues; training datasets are downloaded separately.

D-Fire includes HPWREN, FESB and FireNet material. Original rights apply independently
of the collection license. [Third-party notices](../THIRD_PARTY_NOTICES.md) records
provider terms, attribution and unresolved permissions. [Training](TRAINING.md) describes
reproduction, and [results](results/detection_final_metrics.json) contains split metrics.
