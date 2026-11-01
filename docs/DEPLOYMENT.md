# Deployment

Use Python 3.11 and the configured local environment. Keep credentials out of logs and source control.

```powershell
.\.venv\Scripts\python.exe scripts\08_run_all_local.py
```

API: http://127.0.0.1:8000. Dashboard: http://127.0.0.1:8501. Use the launcher's --restart option to replace existing local services.

## Refresh

`scripts/19_refresh_world.py` refreshes current NASA FIRMS observations and Copernicus weather metadata. `scripts/install_daily_task.ps1` installs daily/logon refresh; `scripts/install_world_task.ps1` installs hourly/logon refresh. Both use windowless pythonw.exe so scheduled refreshes do not open console windows; progress and failures are recorded in logs/world_refresh.log. Neither sends Telegram text digests. Weather metadata, tiles and current Open-Meteo place weather use 15-minute caches.

The browser follows its own timezone's current date without a date selector. It refreshes on open, every15minutes, at local midnight and on return to a visible/focused page. If today's forecast cannot be verified, the weather layer stays hidden with an unavailable/outdated warning. Place popups include timestamped current model estimates and today's summary; a ticking UI clock is not a weather observation. Windows installs require tzdata (included in project dependencies).

No risk-model artifact or training dataset is needed by the active API. Preserve models/detection, data/satellite, data/fire_weather, data/geospatial and camera alert snapshots. The map globe/style and camera/video pipeline remain in place.

Verify /health, /world-map/data and /fire-weather/metadata. Use the Fire danger map for observations/weather; Live camera and Test for detector processing; Alerts for snapshot delivery attempts.

The API runs a dedicated satellite refresh worker while it is running, checking once a minute and fetching NASA only when the10minute cache expires. Closed or throttled browser tabs do not pause this worker. Satellite delay/errors remain visible beneath the satellite controls rather than as a map-wide banner. Failed checks never advance the successful feed timestamp.
