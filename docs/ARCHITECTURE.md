# Architecture

Streamlit provides four tabs: Fire danger, Live camera, Alerts and Test. FastAPI serves the map modules, satellite observations, weather metadata/tiles, place forecasts and camera/video detection endpoints.

NASA FIRMS -> data/satellite/world_hotspots.json -> MapLibre globe observation layer.
Copernicus GWIS -> short-lived weather metadata/tiles -> official fire-weather layer.
Open-Meteo -> cached current place forecasts -> click/search popup.
EOX/OpenFreeMap/GeoNames -> basemap, detail, buildings and place names.
Camera/image/video -> detection model -> annotated output -> queued Telegram snapshots.

The operational map has no local risk-training pipeline or training-data reads. Detector training and deployment remain separate from map forecasting.
