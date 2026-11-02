# v0.1.0 — Security, Performance & Documentation Audit

## Highlights

- **API Guard Middleware**: Host allow-list, cross-origin request validation, and optional
  token authentication via `X-MedFire-Token` for write endpoints.
- **Automated Resource Cleanup**: Background retention sweep pruning expired video results
  and fire-weather cache tiles according to a configurable TTL.
- **Per-Session Camera Tracking**: Browser camera sessions are isolated by
  `X-Camera-Session` identifier with dedicated cooldowns and memory budgets.
- **Video Pipeline Refactor**: `iter_video_detections` decomposed into modular worker
  threads and helpers with zero behavior change.
- **83% Test Coverage**: Expanded from 68 to 78 Python tests covering security, resource
  management, correctness, and performance modules.

## Security

- Host allow-list enforcing `127.0.0.1`, `localhost`, `[::1]`, and `MEDFIRE_ALLOWED_HOSTS`.
- Cross-origin validation for non-idempotent requests using `MEDFIRE_ALLOWED_ORIGINS`.
- Optional API token via `MEDFIRE_API_TOKEN` on mutation endpoints.
- Telegram chat auto-discovery rejects ambiguous multi-chat responses.
- Camera upload validates byte size and image dimensions before OpenCV decoding.
- XML parsing switched to `defusedxml` for Copernicus GWIS metadata.
- Assertions in GPU hardware module replaced with explicit `RuntimeError`.

## Resource Management

- Background retention sweep every 10 minutes for video results and weather cache.
- Concurrent video jobs capped at `MEDFIRE_MAX_VIDEO_JOBS` (default 2).
- Atomic temporary-file writes for fire-weather tiles.
- Coordinate rounding (2 decimals) in place weather cache keys.
- Uploaded source video files cleaned up on job completion or failure.

## Correctness

- CPU-bound YOLO inference moved off the async event loop via `run_in_threadpool`.
- Stable `"live_camera"` dedupe key for camera alert cooldowns.
- Per-session browser camera trackers with idle eviction.
- Single-sourced API version from package metadata.
- Correct `media_type` for video source endpoint based on file suffix.
- VIIRS low-confidence filter controllable with `MEDFIRE_INCLUDE_LOW_CONFIDENCE`.

## Performance

- Font caching via `lru_cache` in drawing module.
- Precomputed radian arrays for vectorized nearest-town lookups.
- File mtime-keyed caching for world hotspots and country data.
- Double-checked locking in fire-weather metadata (no lock during network fetch).
- Streamlit snapshot download caching with 300-second TTL.
- Startup log rotation and 120-second API readiness timeout.
- `MEDFIRE_SKIP_WARMUP` flag for faster test execution.

## Documentation

- README restructured with keyword-rich opening, synchronized English/French sections.
- Configuration table documenting all 10 environment variables.
- `CONTRIBUTING.md` with setup, test, and code style guidelines.
- `CHANGELOG.md` in Keep a Changelog format.
- Updated `docs/GUIDE.md`, `docs/ARCHITECTURE.md`, and `docs/DEPLOYMENT.md`.
- `docs/SCREENSHOTS.md` gallery with descriptive alt text on all images.
- Social preview image generated via `scripts/make_social_preview.py`.

## Breaking Changes

None. Default localhost behavior is unchanged with zero new configuration required.

