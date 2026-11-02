# Limits

- Satellite heat observations can be delayed, obscured by cloud or caused by industrial heat.
  They do not confirm wildfire incidents or perimeters; missing markers do not establish safety.
- VIIRS "low" confidence hotspots are intentionally filtered out by default (`medfire_watch/world_hotspots.py`)
  to minimize false positives from sun glint, industrial flaring, and sensor noise. To include low-confidence
  observations on the satellite map, set the environment variable `MEDFIRE_INCLUDE_LOW_CONFIDENCE=1`.
- Fire-weather danger describes conditions, not calibrated ignition probability.
  Forecast resolution follows the provider grid; zoom and Open-Meteo model estimates
  do not refine the Copernicus class. The EOX 2025 mosaic is dated imagery.
- Reflections, haze, clouds, small flames and domain shifts can cause false or missed detections.
  Camera coverage, connectivity and Telegram delivery constrain alerts. See the
  [model card](MODEL_CARD.md) for evaluation and protocol gaps.
- Automated checks do not establish webcam compatibility, negotiated frame rate,
  browser latency or fullscreen performance on every device. Variable-frame-rate export
  timestamps are not fully supported; speeds are in [benchmarks](VIDEO_BENCHMARK.md).
- This local research application supports investigation and requires emergency-service
  verification. It provides no worldwide seconds-from-ignition guarantee.
