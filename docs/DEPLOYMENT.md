# Deployment

Use Python 3.11 and install `requirements.txt` in a virtual environment.
Store credentials in `.env` or `.streamlit/secrets.toml`; `.env.example` lists variable names.

```sh
python scripts/run_app.py
```

Open [dashboard](http://127.0.0.1:8501); the [API](http://127.0.0.1:8000/health)
runs on port 8000. The launcher supports `--restart`, `--stop`, `--api-port` and
`--dashboard-port`. It checks process ownership before replacing local services.
Logs are in `logs/` (with automatic startup rotation for `logs/api.log` and `logs/dashboard.log`).
Runtime caches live under `data/satellite` and `data/fire_weather`; completed video results
under `runs/video_results` and cache tiles are automatically swept after `MEDFIRE_VIDEO_TTL_HOURS` (default 24h);
camera snapshots live under `runs/webcam_alerts`.

## Security hardening

- **Host and Origin Protection**: By default, requests are restricted to loopback interfaces. Configure
  `MEDFIRE_ALLOWED_HOSTS` and `MEDFIRE_ALLOWED_ORIGINS` when hosting behind reverse proxies or external hostnames.
- **API Token**: Set `MEDFIRE_API_TOKEN` to require `X-MedFire-Token` on write, upload, and deletion endpoints.
- **Concurrent Video Limits**: Concurrent video jobs are throttled by `MEDFIRE_MAX_VIDEO_JOBS` (default 2)
  to preserve server memory and CPU/GPU resources. Extra requests receive HTTP 429.

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
