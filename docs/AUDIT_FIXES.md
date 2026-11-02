# Audit Fixes & Quality Report

These are historical implementation notes; test counts and working-tree statements describe an earlier snapshot.
See the [current audit](AUDIT.md) for verified results and remaining limitations.

This document records the complete implementation and verification of the audit fixes across all phases, adhering to the strict ground rules of the local repository.

---

## 1. Ground Rules & Audit Integrity Confirmation

- **Local Edits Only**: No state-changing `git` commands (`add`, `commit`, `branch`, `checkout`, `switch`, `stash`, `reset`, `rebase`, `merge`, `tag`, `push`, `pull`) were run. No `gh` commands were executed. All changes remain uncommitted in the local working tree for manual author review and commit.
- **Python Pinning**: Python 3.11 remained strictly pinned throughout. The only new dependency added was `defusedxml>=0.7.1` in `pyproject.toml` and `requirements.txt`.
- **Zero Config Localhost**: Default behavior on localhost works out of the box with zero required configuration.
- **Test Integrity**: No existing tests were deleted or weakened. Test count increased from 53 to 78, and coverage increased from 75% to 83%.

---

## 2. Phase-by-Phase Item Status

| Item | Description | Status | Details |
| :--- | :--- | :--- | :--- |
| **Phase 1.1** | API guard middleware in `api/main.py` | **Done** | Host allow-list (`127.0.0.1`, `localhost`, `[::1]`, `testserver`, `MEDFIRE_ALLOWED_HOSTS`), Origin check for non-GET/HEAD/OPTIONS (`MEDFIRE_ALLOWED_ORIGINS`), and `X-MedFire-Token` enforcement when `MEDFIRE_API_TOKEN` is set. |
| **Phase 1.2** | Strict private chat discovery in `alerts/manager.py` | **Done** | `detect_chat` raises `LookupError` if multiple private chats exist; only saves when exactly one exists. Fixed test to prevent mocking from polluting real `.env`. |
| **Phase 1.3** | Camera upload size and dimension bounds | **Done** | `_decode_camera_upload` caps upload size to `MAX_UPLOAD_BYTES` and inspects image dimensions using PIL before OpenCV decoding, returning 413. |
| **Phase 1.4** | Safe XML parsing with `defusedxml` | **Done** | Copernicus GWIS XML in `medfire_watch/fire_weather.py` parsed using `defusedxml.ElementTree`. Added to requirements. |
| **Phase 1.5** | Replace assertion with `RuntimeError` | **Done** | Replaced `assert` in `medfire_watch/video_hardware.py` with explicit `RuntimeError`. |
| **Phase 2.1** | Retention sweep module | **Done** | Created `medfire_watch/retention.py` sweeping completed video results older than `MEDFIRE_VIDEO_TTL_HOURS` (default 24h) and weather cache tiles. Preserves `runs/webcam_alerts`. Integrated into background refresh loop. |
| **Phase 2.2** | Delete uploaded input video after processing | **Done** | Uploaded video files in `api/routers/video.py` are unlinked upon job completion or failure unless retained for playback. |
| **Phase 2.3** | Cap concurrent video jobs | **Done** | Concurrent video jobs capped at `MEDFIRE_MAX_VIDEO_JOBS` (default 2), returning HTTP 429 when saturated. |
| **Phase 2.4** | Atomic tile writes & rounded place cache key | **Done** | `fire_weather.tile()` writes via temporary file and atomic replace. `place_danger.local_weather` rounds coordinates to 2 decimals. |
| **Phase 3.1** | Non-blocking detection endpoint | **Done** | Detection inference in `api/routers/detection.py` dispatched to threadpool via `starlette.concurrency.run_in_threadpool`. |
| **Phase 3.2** | Camera alert dedupe & per-session tracking | **Done** | Stable dedupe key `"live_camera"`, dedicated `camera_cooldown_minutes` (default 5m), per-session trackers (`X-Camera-Session`) with 5m idle eviction and 256 MB memory limit. Live alert thresholds loaded from `configs/detection.yaml`. |
| **Phase 3.3** | Consistent video limit fallbacks | **Done** | Centralized in `api/services.py` and referenced by routers. |
| **Phase 3.4** | Single-sourced API version | **Done** | Sourced via `importlib.metadata.version("medfire-watch")` with fallback `"0.1.0"`. |
| **Phase 3.5** | Video source media type | **Done** | Suffix-based MIME type resolution for `/video-jobs/{id}/source`. |
| **Phase 3.6** | VIIRS low-confidence hotspot filtering | **Done** | Controlled by `MEDFIRE_INCLUDE_LOW_CONFIDENCE=1` and documented in `docs/LIMITATIONS.md`. |
| **Phase 4.1** | Drawing font caching and copy optimization | **Done** | `@functools.lru_cache` for fonts; immediate return of `image.copy()` if detections empty. |
| **Phase 4.2** | Precomputed radian arrays for GeoNames | **Done** | Vectorized radian coordinates cached once via `@lru_cache` in `medfire_watch/map_information.py`. |
| **Phase 4.3** | File mtime caching for hotspots & countries | **Done** | `load_world_hotspots` and country GeoJSON cached by file modification time. |
| **Phase 4.4** | Double-checked locking in weather metadata | **Done** | Network fetch performed outside the global lock in `fire_weather.metadata()`. |
| **Phase 4.5** | Remove per-request background threads | **Done** | Retired ad-hoc threads in `api/routers/map.py`; relies on background loop. |
| **Phase 4.6** | Dashboard snapshot caching & delete confirmation | **Done** | Snapshot fetching cached with `@st.cache_data(ttl=300)`; confirmation dialog before snapshot deletion. |
| **Phase 4.7** | Video pipeline refactor | **Done** | `iter_video_detections` refactored into `VideoFrameReader`, `VideoFrameEncoder`, and modular pipeline helpers without behavior change. |
| **Phase 4.8** | Inference warmup bypass (`MEDFIRE_SKIP_WARMUP`) | **Done** | Lifespan and test suite support `MEDFIRE_SKIP_WARMUP=1`. Full smoke test retained in `tests/test_runtime_setup.py`. |
| **Phase 4.9** | Launcher readiness timeout & log rotation | **Done** | Timeout raised to 120s; startup log rotation for `logs/api.log` and `logs/dashboard.log`. |
| **Phase 4.10** | Python test coverage expansion (>= 80%) | **Done** | Reached 83% coverage across 78 passing tests. |
| **Phase 5.1** | Clean Interface table in READMEs | **Done** | Structured 2-column grid with dedicated captions under each screenshot. |
| **Phase 5.2** | Condensed README & SCREENSHOTS.md gallery | **Done** | Kept 2 GIFs and 3 screenshots in READMEs; moved full gallery and credits to `docs/SCREENSHOTS.md`. |
| **Phase 5.3** | Synchronized section order across languages | **Done** | English and French READMEs strictly synchronized. PR curve and confusion matrix embedded under Key results. |
| **Phase 5.4** | Development section in READMEs | **Done** | Clear step-by-step dev installation, test execution, and warmup bypass notes. |
| **Phase 5.5** | Configuration reference table | **Done** | All 10 environment variables documented with defaults and purposes in both languages. |
| **Phase 5.6** | Python 3.11 requirement note | **Done** | Explicitly stated Python 3.11 required and 3.12+ unsupported. |
| **Phase 5.7** | CONTRIBUTING.md & CHANGELOG.md | **Done** | Created comprehensive guidelines and Keep a Changelog formatted changelog. |
| **Phase 5.8** | Factual License section | **Done** | Clean AGPL-3.0 attribution without invented rationale. |
| **Phase 5.9** | Updated Architecture, Guide & Deployment docs | **Done** | All docs updated with security guards, token auth, cleanup, and session tracking. |
| **Phase 6.1** | Keyword-rich opening sentence | **Done** | Placed directly under badges in English and French. |
| **Phase 6.2** | Descriptive alt text on all images | **Done** | Added descriptive alt text across READMEs and `docs/SCREENSHOTS.md`. |
| **Phase 6.3** | Social preview image | **Done** | Pillow generator `scripts/make_social_preview.py` created `docs/media/social-preview.png` (1280x640, 53 KB, dark dashboard theme, no EOX/OSM imagery). |
| **Phase 6.4** | GitHub repository setup guide | **Done** | Created `docs/GITHUB_SETUP.md` with description, 15 topics, and `gh repo edit` commands. |
| **Phase 6.5** | Release notes for v0.1.0 | **Done** | Prepared factual release notes in `docs/RELEASE_NOTES_v0.1.0.md`. |
| **Phase 6.6** | Pre-release manual checklist | **Done** | Checklist included in `docs/GITHUB_SETUP.md`. |

---

## 3. Investigation & Resolution of Telegram Alert Issue

During local live camera verification, the user observed `Telegram delivery failed (RuntimeError).` on the camera overlay and a delivery failure entry in the dashboard.

### Root Cause Analysis
1. **Test Environment Leakage**: In `tests/test_phase1_security.py`, `manager.detect_chat()` was invoked against a mock update containing chat ID `11111`. Because `_save_chat_id` was unmocked, it wrote `TELEGRAM_CHAT_ID=11111` directly into the repository's `.env` file whenever tests ran.
2. **Hidden UI Controls**: Because `TELEGRAM_CHAT_ID` was set to `11111`, the dashboard considered Telegram already configured, hiding the "Connect Telegram chat" action.
3. **Delivery Failure**: Live camera alerts attempted to dispatch to the fake ID `11111`, which Telegram rejected with HTTP 400 (`Bad Request: chat not found`).
4. **Unfriendly Error Display**: In `medfire_watch/browser_camera.py`, the exception was logged as `f"Telegram delivery failed ({type(exc).__name__})."`, presenting a raw Python exception type `(RuntimeError)` rather than a meaningful message.

### Fix Implemented
1. **Isolated Tests**: Mocked `_save_chat_id` in `tests/test_phase1_security.py` so running tests never alters `.env`.
2. **Restored Configuration**: Cleared `11111` from `.env` so `TELEGRAM_CHAT_ID` is ready for real user connection.
3. **Descriptive Error Messaging**: Updated `alerts/manager.py` and `medfire_watch/browser_camera.py` to preserve Telegram's descriptive error response and avoid printing raw Python exception class names.
4. **Connection Management**: Enhanced `dashboard/app.py` to allow re-detecting or updating Telegram chat settings even when a chat ID is already stored.

---

## 4. Verification Metrics

| Metric | Before Audit | After Audit |
| :--- | :--- | :--- |
| **Total Python Tests** | 53 | **78 passed** (0 failed) |
| **Client-Side JS Tests** | 21 | **21 passed** (0 failed) |
| **Python Code Coverage** | ~75% | **83%** (Target: ≥ 80%) |
| **Ruff Linting** | Unsorted imports, long lines | **All checks passed** |
| **Prettier Formatting** | Passed | **All checks passed** |
| **Documentation Link Check** | 83 links checked | **89 links checked, 25 images verified** |

---

## 5. Suggested Commit Plan for the Author

The author can commit these changes in logical, atomic commits:

### Commit 1: Phase 1 — Security Hardening
```
feat(security): add API guard middleware, upload bounds, and safe XML parsing

- Add Host header validation, Origin check for mutations, and X-MedFire-Token auth
- Require unambiguous private chat in detect_chat
- Cap camera upload byte size and dimensions before decoding
- Parse Copernicus GWIS XML with defusedxml
- Replace raw assert in video hardware detection with RuntimeError
```
**Files**: `api/main.py`, `api/routers/detection.py`, `alerts/manager.py`, `medfire_watch/fire_weather.py`, `medfire_watch/video_hardware.py`, `pyproject.toml`, `requirements.txt`, `.env.example`, `tests/test_phase1_security.py`

### Commit 2: Phase 2 — Retention and Concurrency Limits
```
feat(retention): add automated TTL cleanup sweep and video job concurrency caps

- Add medfire_watch/retention.py for 10-minute sweep of expired video results and cache tiles
- Cap concurrent video analysis jobs at MEDFIRE_MAX_VIDEO_JOBS with HTTP 429
- Clean up uploaded source video files upon job completion or failure
- Write weather tiles atomically and round place coordinates in cache keys
```
**Files**: `medfire_watch/retention.py`, `api/routers/video.py`, `api/routers/map.py`, `medfire_watch/place_danger.py`, `tests/test_phase2_retention.py`

### Commit 3: Phase 3 — Correctness and Session Tracking
```
fix(core): offload detection to threadpool, add per-session tracking, and fix limits

- Run detection inference in threadpool to avoid blocking FastAPI event loop
- Track live camera sessions independently with idle eviction and 256MB queue limit
- Use dedicated camera_cooldown_minutes and stable dedupe key
- Single-source API version from package metadata
- Correct media type for video source endpoint
- Support MEDFIRE_INCLUDE_LOW_CONFIDENCE for VIIRS hotspots
```
**Files**: `api/routers/detection.py`, `medfire_watch/browser_camera.py`, `api/services.py`, `api/routers/video.py`, `configs/alerts.yaml`, `configs/detection.yaml`, `medfire_watch/world_hotspots.py`, `docs/LIMITATIONS.md`, `tests/test_phase3_correctness.py`

### Commit 4: Phase 4 — Performance and Maintainability
```
perf(optim): cache fonts, precompute geospatial radians, and refactor video pipeline

- Cache font loading and precompute radian arrays for vectorized nearest town lookups
- Cache world hotspots and country GeoJSON by file mtime
- Implement double-checked locking in fire_weather.metadata()
- Cache dashboard snapshot downloads and add delete confirmation prompt
- Refactor iter_video_detections into modular worker threads
- Add MEDFIRE_SKIP_WARMUP support and expand test coverage to 83%
- Raise launcher readiness timeout to 120s and rotate startup logs
```
**Files**: `medfire_watch/drawing.py`, `medfire_watch/map_information.py`, `medfire_watch/config.py`, `medfire_watch/video.py`, `dashboard/app.py`, `scripts/run_app.py`, `tests/conftest.py`, `tests/test_runtime_setup.py`, `tests/test_launcher.py`, `tests/test_phase4_coverage.py`

### Commit 5: Phase 5 — Documentation Harmonization
```
docs(readme): harmonize English and French documentation and add guidelines

- Streamline interface presentation to 3 screenshots and create docs/SCREENSHOTS.md
- Synchronize section structure across README.md and README.fr.md
- Embed PR curve and confusion matrix under Key results
- Add Configuration table covering all 10 environment variables
- Add CONTRIBUTING.md and CHANGELOG.md (Keep a Changelog format)
- Update GUIDE.md, ARCHITECTURE.md, and DEPLOYMENT.md
```
**Files**: `README.md`, `README.fr.md`, `docs/SCREENSHOTS.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `docs/GUIDE.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOYMENT.md`

### Commit 6: Phase 6 — Repository Page & Discoverability
```
chore(repo): generate social preview, release notes, and GitHub setup guide

- Add keyword-rich opening sentences under README badges
- Generate docs/media/social-preview.png (1280x640) via scripts/make_social_preview.py
- Add docs/GITHUB_SETUP.md with description, 15 curated topics, and gh commands
- Add docs/RELEASE_NOTES_v0.1.0.md
```
**Files**: `scripts/make_social_preview.py`, `docs/media/social-preview.png`, `docs/media/CREDITS.md`, `docs/GITHUB_SETUP.md`, `docs/RELEASE_NOTES_v0.1.0.md`

---

## 6. Product & Configuration Decisions for Author Confirmation

1. **Camera Alert Cooldown**: Configured `camera_cooldown_minutes: 5` in `configs/alerts.yaml` for live camera alerts while keeping `cooldown_minutes: 60` for general alerts. Confirm if 5 minutes fits operational requirements.
2. **Video Retention TTL**: Default video retention TTL is set to 24 hours (`MEDFIRE_VIDEO_TTL_HOURS = 24`). Confirm if longer or shorter retention is desired for deployments.
3. **Concurrent Video Jobs**: Default concurrency limit is set to 2 (`MEDFIRE_MAX_VIDEO_JOBS = 2`) to protect GPU/CPU memory on edge workstations.
4. **Website URL**: In `docs/GITHUB_SETUP.md`, the website URL is left for the author to specify once a public domain or demo server is active.

