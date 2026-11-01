# Model card

## Camera, image and video detector

The deployed fire/smoke detector remains unchanged in models/detection. The deployed model is a YOLOv8s fire/smoke detector. Recorded evaluation reports under docs/results and the video benchmark document describe measured results; no retraining or new accuracy claim accompanies documentation changes. Runtime confidence is selected on validation (about0.298); camera photo alerts additionally require confidence0.5, minimum box area and elapsed-time persistence. See README.md for the recorded split-level results.

## Map service

The map uses NASA satellite observations, official Copernicus/GWIS fire-weather forecasts and Open-Meteo local forecast context. It has no locally trained ignition model or vegetation-baseline feature. A weather-danger class is not the probability that a new fire starts; a satellite heat detection is not a confirmed wildfire.

The dated satellite background, place labels and 3D buildings are cartography. Forecast resolution is limited by the source rather than map zoom.

## Saved confusion matrix provenance

The retained official-test PR curve reports mean AP50 0.747. The saved confusion matrix includes substantial unmatched/background detections; its confidence/matching settings were not stored alongside that PNG. Its raw counts must not be presented as precision/recall at the deployment threshold or as the current persistence-based camera alert performance. The project retains the plot for transparency and does not derive a new metric from it. Fresh evaluation would require restoring the original data and an explicit evaluation protocol.
