# Source audit — 2026-11-01

The retained UI is Fire danger, Live camera, Alerts and Test. API handlers were traced against the HTML/JavaScript and Streamlit callers; Python modules and dependencies were inspected. Optional detector-training code is retained for reproducibility, not loaded by the app. Evaluation plots are evidence, not input datasets.

## Removed code

- Regional risk-alert settings, watched regions/zones and risk threshold configuration/API.
- Blocking NDJSON video request path and superseded direct job-start route.
- MJPEG viewer endpoint/queues and per-frame JPEG encoding, old preview files/endpoint, unused standalone player route.
- Five-second wait for a viewer that current native playback never creates; unused preview/callback/pacing options in export.
- Legacy WebRTC camera implementation (earlier cleanup), duplicate webcam diagnostic command and broken map-validation script.
- Unused webcam-noise filter, export callback, alternate-backend dependency extra, database/SMTP configuration and obsolete container experiment service.
- Removed container deployment files; the supported setup is Python plus a local virtual environment. CI smoke exercises the real app instead of a dummy health route.

## Retained runtime flows

- Map: satellite observations, provider weather classes, selected-place weather/geocoding, globe/labels/buildings and guide.
- Camera: native browser capture, detector, persistence/IoU and queued Telegram photos.
- Test: image inference; native video playback with detection metadata, seek prioritisation and full-resolution annotated export.
- Alerts: camera photo delivery history, connection status, chat setup and local history deletion.

Static inspection cannot prove that every possible dynamic path is unused or correct. Route-retirement checks and surviving-flow regressions support these removals. Physical webcam/browser acceptance still requires the target machine.

## Source inventory

| File | Purpose |
| --- | --- |
| api/main.py | Active application |
| api/__init__.py | Active application |
| alerts/manager.py | Active application |
| alerts/__init__.py | Active application |
| dashboard/app.py | Active application |
| dashboard/camera_coordinates.mjs | Active application |
| dashboard/earth_watch.mjs | Active application |
| dashboard/fire_weather_layer.mjs | Active application |
| dashboard/live_camera.html | Active application |
| dashboard/map_logic.mjs | Active application |
| dashboard/map_style.mjs | Active application |
| dashboard/satellite_map.html | Active application |
| dashboard/video_player.html | Active application |
| dashboard/world_map.py | Active application |
| dashboard/__init__.py | Active application |
| medfire_watch/browser_camera.py | Active application |
| medfire_watch/config.py | Active application |
| medfire_watch/coordinates.py | Active application |
| medfire_watch/detection.py | Optional detector training/reproduction |
| medfire_watch/detection_data.py | Optional detector training/reproduction |
| medfire_watch/drawing.py | Active application |
| medfire_watch/fire_weather.py | Active application |
| medfire_watch/live_alert.py | Active application |
| medfire_watch/map_assets.py | Active application |
| medfire_watch/map_information.py | Active application |
| medfire_watch/place_danger.py | Active application |
| medfire_watch/secrets.py | Active application |
| medfire_watch/video.py | Active application |
| medfire_watch/video_analysis.py | Active application |
| medfire_watch/video_hardware.py | Active application |
| medfire_watch/world_hotspots.py | Active application |
| medfire_watch/__init__.py | Active application |
| models/__init__.py | Active application |
| scripts/00_check_env.py | Installation/maintenance |
| scripts/01_download_detection_data.py | Optional detector training/reproduction |
| scripts/02_verify_detection_data.py | Optional detector training/reproduction |
| scripts/03_train_detection.py | Optional detector training/reproduction |
| scripts/08_run_all_local.py | Installation/maintenance |
| scripts/10_merge_detection_data.py | Optional detector training/reproduction |
| scripts/11_evaluate_detection.py | Optional detector training/reproduction |
| scripts/19_refresh_world.py | Installation/maintenance |
| scripts/20_download_countries.py | Installation/maintenance |
| scripts/26_download_places.py | Installation/maintenance |
| scripts/51_finish_cleanup.ps1 | Installation/maintenance |
| scripts/check_ui_syntax.mjs | Installation/maintenance |
| scripts/install_daily_task.ps1 | Installation/maintenance |
| scripts/install_world_task.ps1 | Installation/maintenance |
| scripts/__init__.py | Installation/maintenance |
| tests/camera_coordinates.test.mjs | Regression test |
| tests/fire_weather_today.test.mjs | Regression test |
| tests/fullscreen.test.mjs | Regression test |
| tests/map_logic.test.mjs | Regression test |
| tests/test_api_services.py | Regression test |
| tests/test_browser_camera.py | Regression test |
| tests/test_camera_fullscreen.py | Regression test |
| tests/test_camera_only_alerts.py | Regression test |
| tests/test_clear_camera_history.py | Regression test |
| tests/test_detection_data.py | Regression test |
| tests/test_fire_weather.py | Regression test |
| tests/test_forecast_visibility.py | Regression test |
| tests/test_launcher.py | Regression test |
| tests/test_live_alert.py | Regression test |
| tests/test_manual_digest.py | Regression test |
| tests/test_map_assets.py | Regression test |
| tests/test_map_video_followup.py | Regression test |
| tests/test_place_danger.py | Regression test |
| tests/test_project.py | Regression test |
| tests/test_secrets.py | Regression test |
| tests/test_video_detection.py | Regression test |
| tests/test_video_seek_analysis.py | Regression test |
| tests/test_world_confidence.py | Regression test |
