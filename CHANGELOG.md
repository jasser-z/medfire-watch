# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Engineering hardening — 2026-11-02

- Reserve video admission before upload/preparation; protect active jobs and downloads during retention.
- Protect sensitive reads and add expiring HttpOnly browser sessions for native media clients.
- Bound camera sessions, queue byte reservations and retained video jobs; add cancellation and deadlines.
- Coordinate Telegram sends/reset, rearm camera persistence, redact HTTP errors and classify retries.
- Validate media/settings, preserve image orientation, reject invalid boxes and correct satellite cache keys.
- Pin a patched CPU model dependency pair; add constrained installs and CI advisory/syntax checks.
- See [engineering verification and remaining limits](docs/HARDENING_REPORT.md).

## [Unreleased]

### Added
- Live camera cooldown controls: persist a 0–1440 minute interval and reset the current wait without deleting history.
- Responsive Alerts toolbar with Telegram detection beside Delete all, configuration status and delivery totals.
- API guard middleware in `api/main.py` enforcing host allow-lists (`127.0.0.1`, `localhost`, `[::1]`, and `MEDFIRE_ALLOWED_HOSTS`) and cross-origin request validation for non-idempotent endpoints.
- Optional token authentication via `X-MedFire-Token` header when `MEDFIRE_API_TOKEN` is configured.
- Automated retention sweep in `medfire_watch/retention.py` pruning expired video results and fire-weather tile caches according to `MEDFIRE_VIDEO_TTL_HOURS`.
- Concurrency limiting for video analysis jobs (`MEDFIRE_MAX_VIDEO_JOBS`), responding with HTTP 429 when saturated.
- `MEDFIRE_SKIP_WARMUP` environment flag to bypass heavy YOLO model weight loading during development and test execution.
- Per-session browser camera tracking (`X-Camera-Session`) with idle session eviction after 5 minutes and a 256 MB queue byte budget.
- Dedicated `camera_cooldown_minutes` setting (default 5 minutes) in `configs/alerts.yaml`.
- Atomic temporary-file-and-replace writes for cached fire weather danger tiles in `medfire_watch/fire_weather.py`.
- Safe XML parsing using `defusedxml` for Copernicus GWIS metadata requests.
- Streamlit snapshot caching (`@st.cache_data`) and confirmation dialog before deleting alert snapshot history.
- Startup log rotation for `logs/api.log` and `logs/dashboard.log` in `scripts/run_app.py`.
- Comprehensive test suites (`test_phase1_security.py`, `test_phase2_retention.py`, `test_phase3_correctness.py`, `test_phase4_coverage.py`), expanding test coverage to 83% across 78 tests.

### Changed
- Moved CPU-bound YOLO detection inference in `/detect` off FastAPI's async event loop into Starlette's threadpool.
- Refactored `iter_video_detections` in `medfire_watch/video.py` into dedicated worker threads (`VideoFrameReader`, `VideoFrameEncoder`) and modular helper functions.
- Single-sourced API version from package metadata (`importlib.metadata.version`) with fallback.
- Centralized video limit fallbacks and live alert threshold configuration in `api/services.py` and `configs/detection.yaml`.
- Implemented double-checked locking in `fire_weather.metadata()` so network requests no longer block concurrent readers.
- Cached geospatial radian arrays and GeoNames place lookups using `functools.lru_cache`.
- Cached country boundaries and label layer JSON responses keyed by file modification time.
- Increased launcher API readiness check timeout to 120 seconds in `scripts/run_app.py`.

### Fixed
- Make map-route tests independent of NASA credentials and local satellite caches; use recent fixture timestamps.
- Require optional API authentication on all mutation methods, including cooldown PUT requests.
- Send a unique camera session header from each browser page to isolate persistence tracking.
- Isolate alert-manager test settings from local runtime overrides.
- Fixed Telegram chat auto-discovery (`detect_chat`) to reject ambiguous responses when multiple private chat IDs exist, requiring manual specification.
- Fixed live camera upload handling to validate byte length against `MAX_UPLOAD_BYTES` and inspect image dimensions with PIL prior to full OpenCV decoding.
- Added support for `MEDFIRE_INCLUDE_LOW_CONFIDENCE` to control VIIRS low-confidence hotspot filtering.
- Prevented disk leaks by cleaning up uploaded source video files upon job completion or failure unless retained for native playback.
- Replaced raw assertions in `medfire_watch/video_hardware.py` with explicit `RuntimeError` exceptions.

