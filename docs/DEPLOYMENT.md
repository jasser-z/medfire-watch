# Deployment

Use Python 3.11 and install `requirements.txt` with `-c constraints-py311.txt` in a virtual environment.
Store credentials in the process environment or ignored `.env`; `.env.example` lists variable names.
Explicit process variables take precedence over `.env`. Restart after editing credentials.

```sh
python scripts/run_app.py
```

Open [dashboard](http://127.0.0.1:8501); the [API](http://127.0.0.1:8000/health)
runs on port 8000. The launcher supports `--restart`, `--stop`, `--api-port` and
`--dashboard-port`. It checks process ownership before replacing local services.
Logs are in `logs/` (with automatic startup rotation for `logs/api.log` and `logs/dashboard.log`).
Runtime caches live under `data/satellite` and `data/fire_weather`; completed video results
under `runs/video_results` expire after `MEDFIRE_VIDEO_TTL_HOURS` (default 24h) from worker completion;
weather cache tiles/place files have a separate fixed 24-hour retention policy;
camera snapshots live under `runs/webcam_alerts`.

## Authentication and exposure boundaries

The launcher binds to `127.0.0.1` by default and rejects a remote bind without an API token.
Both launcher children and a directly started dashboard load `.env` without overriding process variables. Blank `MEDFIRE_API_TOKEN` is intended only for
trusted local development. Host allow-list validation is not a network firewall: a remote caller
can choose its Host header. Do not expose either service directly without the controls below.

Set a strong random `MEDFIRE_API_TOKEN` for API protection. All mutations and sensitive reads
(alerts, snapshot files, camera status/settings, source videos, job metadata, exports and OpenAPI/docs)
require either `X-MedFire-Token` or a valid browser session. Health and the explicitly listed
map/weather reads remain public. This is one shared operator privilege, without per-user resource ownership.

Native camera/video pages redirect to `/auth/login`. Enter the token in the password form;
`POST /auth/session` exchanges it for a signed, randomised, eight-hour HttpOnly/SameSite=Strict cookie.
The token is never inserted in frontend assets, query strings or local storage. Browser fetches,
range playback and downloads use the cookie automatically. HTTPS requests receive Secure cookies;
HTTP is supported for loopback development only. Rotate the token to revoke every session, or POST
`/auth/logout` to remove the current browser cookie. Cookie writes require an allowed Origin header;
header-authenticated scripts may omit Origin. Invalid cross-origin mutations are rejected.

Use the same hostname for the dashboard and API (for example, both `127.0.0.1`, not a mix of
localhost and 127.0.0.1). Different ports on that hostname work for cookies. Different sites/third-party
iframes need a same-site reverse-proxy deployment; do not weaken SameSite to bypass browser privacy controls.
Configure exact `MEDFIRE_ALLOWED_HOSTS` and `MEDFIRE_ALLOWED_ORIGINS`. No permissive CORS is enabled.

**Streamlit is a privileged backend client:** it attaches the API token on server-side requests.
The API login does not protect the Streamlit dashboard. A remotely accessible installation must
place both services behind an authenticated HTTPS gateway, prohibit direct access to their ports,
and restrict trusted forwarded headers to that gateway. Otherwise an unauthenticated dashboard visitor
can act with the server's API privilege. Add gateway login throttling, request/body size limits,
connection limits and disk quotas. FastAPI multipart parsing can spool input before the route's
size check. Application guards do not replace these ingress controls.

## Video lifecycle and concurrency

Run exactly one API worker. All job/session/Telegram coordination is process-local; multiple workers
or replicas cannot safely share these runtime directories. No job restart/resume is promised.

`MEDFIRE_MAX_VIDEO_JOBS` (default 2, range 1–16) counts atomic reservations from upload through
preparation, analysis, export and cleanup. Saturation returns 429 before preparation. Upload errors,
disconnects and a configurable body deadline (`MEDFIRE_VIDEO_UPLOAD_TIMEOUT_SECONDS`, default 300)
release the reservation. Body timeout returns 408. `configs/detection.yaml` limits bytes (1024 MiB)
and duration (600 seconds). Readable structure, finite metadata, at most 4K pixels and at most 240 fps
are required. Decode-time duration limits also cover understated frame-count metadata.

`MEDFIRE_MAX_STORED_VIDEO_JOBS` (default 64, range 1–4096) bounds registered active and retained jobs;
full storage returns 429 until expiry. This is not a byte-level disk quota. Retention runs every ten
minutes, skips active jobs and download leases, and ages terminal jobs from `finished_at`. Failed and
cancelled fileless state expires too. TTL zero expires terminal jobs at the next sweep. Cleanup is
idempotent and retries filesystem sharing errors. After restart there is no in-memory registry;
orphan artifact groups expire using their newest file mtime.

`POST /video-jobs/{id}/cancel` requests cooperative cancellation. Capacity remains reserved until the
worker acknowledges cancellation and closes resources. Analysis/encode queue waits detect dead or
stalled workers; an uninterruptible native codec/driver call may still require process restart.
Use a process/container resource boundary for untrusted media.

## Camera and Telegram state

Camera trackers are isolated by bounded `X-Camera-Session` IDs, expire after five idle minutes and
are capped by `MEDFIRE_MAX_CAMERA_SESSIONS` (default 64). At most two camera inference calls enter
simultaneously; overloaded or duplicate in-flight sessions return 429. The browser serializes capture
requests, times them out, clears stale boxes, supports Stop/restart, and releases tracks on page exit.
Snapshot reservations expire after eight seconds; the photo queue is bounded by count and bytes.

One persistent track generates one alert candidate until a detection gap or reset rearms it;
cooldown additionally suppresses candidates across tracks.
Camera cooldown overrides persist in `runs/alerts/camera_settings.json`. Reset removes the camera
timer, rearms persistence and invalidates queued old snapshots; history and other timers remain.
An in-flight Telegram request may finish after reset, but cannot restore the old wait. Concurrent
sends for one dedupe key are suppressed. Network/transient failures retry at most three times;
non-retryable HTTP errors and missing credentials do not retry. Telegram may accept a request even
if its response times out, so retries cannot guarantee exactly-once delivery. Snapshots and alert
history remain operator-managed and require storage monitoring; automatic video retention never deletes them.

## Dependency migration and reproducibility

The constrained Python 3.11 snapshot pins PyTorch 2.14.1 and torchvision 0.29.2, validated with real
CPU inference and automated checks. `constraints-py311.txt` fixes the tested package versions;
it is not a hashed, cross-platform lockfile. CI installs this snapshot and checks installed consistency,
Python/JS tests, syntax, formatting, documentation and OSV/npm dependency advisories.

The existing local CUDA environment still has torch 2.5.1+cu121 and torchvision 0.20.1+cu121.
It is outside the new requirements and has advisory findings. Do not treat a passing suite on that
environment as a dependency security clearance. Validate a matching, patched CUDA wheel pair and
NVIDIA driver in a separate environment before replacing it. Only load trusted checkpoints; the
application accepts media uploads, not model uploads. See [the engineering report](HARDENING_REPORT.md).

## Windows scheduled refresh

`scripts/refresh_world.py` fetches FIRMS observations and Copernicus metadata.
`scripts/install_daily_task.ps1` installs daily/logon refresh;
`scripts/install_world_task.ps1` installs hourly/logon refresh. Both use `pythonw.exe`
and write `logs/world_refresh.log`. They refresh map data only.
The API also runs its own worker; timing is in [architecture](ARCHITECTURE.md).

Check `/health`, `/world-map/data` and `/fire-weather/metadata`. Credentials,
network access and source availability determine map coverage. Windows timezone support
uses the included `tzdata` dependency. Browser, GPU and camera acceptance must run on the
target device; see [guide](GUIDE.md).


## Manual storage cleanup and video pause

`POST /video-jobs/{id}/pause` and `/resume` suspend and resume computation at frame/batch
boundaries. The existing `/cancel` ends the job. Paused jobs retain admission capacity and
remain active for retention. Cancellation wakes paused workers and closes media resources.

`GET /runtime-cache` reports generated disk files and active-job counts. `DELETE /runtime-cache`
removes terminal video groups (including cached detections), optionally clearing local snapshot
history/queued photos (`include_snapshots`, default true) and provider caches
(`include_provider_cache`, default true). These routes use the existing operator authentication.
Running/paused video jobs and active downloads are protected. Provider refreshes or sharing
violations can leave busy files for a later retry. Caches may refill as the app continues running.
The Streamlit **Storage & cleanup** panel adds a confirmation before deletion and clears its
server-side data cache afterwards. It preserves model/data artifacts, settings and diagnostic logs.
