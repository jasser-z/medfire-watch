# Complete setup and user guide

Follow these steps from a fresh checkout. Training is optional: the supplied checkpoint
is sufficient to run image, video and camera detection.

## 1. Prerequisites and checkout

Install Git and Python **3.11**. Internet access is needed for installation and map providers.
A webcam is optional for image/video tests. NVIDIA hardware is optional; CPU inference works.
Node.js is needed only for JavaScript development checks, not ordinary application use.

```sh
git clone https://github.com/jasser-z/medfire-watch.git
cd medfire-watch
```

Check that `models/detection/weights/best.pt` and `data/geospatial/` are present.
Run every command below from this repository directory.

## 2. Install in a virtual environment

Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Copy the template only once: do not overwrite an existing `.env` containing your keys.
These commands use the environment interpreter directly, so activation is not required.
In the remaining commands, `python` means `.venv\Scripts\python.exe` on Windows or
`.venv/bin/python` on Linux/macOS. Dependencies can take several minutes to download.

## 3. Request and configure the NASA FIRMS key

1. Open the official [FIRMS MAP_KEY request page](https://firms.modaps.eosdis.nasa.gov/api/map_key/).
2. Choose **Get MAP_KEY**, enter your email address and submit the request.
3. Retrieve the key sent to your email. Check spam if necessary.
4. Open the repository's `.env` in a text editor. Paste the key after `FIRMS_MAP_KEY=`.
5. Save the file as `.env`, not `.env.txt`. Keep it in the repository root, beside `README.md`.

Use a **FIRMS MAP_KEY**, not an api.nasa.gov general-purpose API key. NASA's request page
also provides a key-status check. Do not paste your key into screenshots, GitHub issues or chat.

Your local file should have this structure; replace placeholders with your own values:

```dotenv
FIRMS_MAP_KEY=YOUR_FIRMS_MAP_KEY
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Weather forecasts and basemap providers do not use this NASA key. It enables retrieval
of satellite heat observations. Satellite points represent observations, not confirmed incidents.

## 4. Create and configure the Telegram bot

1. In Telegram, open the official [BotFather](https://t.me/BotFather).
   Follow [Telegram's bot creation instructions](https://core.telegram.org/bots/features#botfather).
2. Send `/newbot` and follow its prompts for a display name and unique bot username.
3. Copy the bot token returned by BotFather into your local `.env` after `TELEGRAM_BOT_TOKEN=`.
4. Open **your new bot**, not BotFather, using the link provided by BotFather.
5. Press **Start** and send `/start` from the Telegram account that should receive the photos.
6. Leave `TELEGRAM_CHAT_ID=` empty for now. The app can discover and save it in step 6 below.

A bot token is a secret credential. If exposed, revoke/regenerate it through BotFather
and update `.env`. Do not use someone else's bot token or commit your local file.

```dotenv
FIRMS_MAP_KEY=YOUR_FIRMS_MAP_KEY
TELEGRAM_BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID=
```

For this initial setup, use a private conversation with your bot. If you already know the
correct recipient chat ID, you can enter it directly instead of automatic discovery.

## 5. Launch the project

Windows PowerShell:

```powershell
.venv\Scripts\python.exe scripts/run_app.py
```

Linux/macOS:

```sh
.venv/bin/python scripts/run_app.py
```

Open [the dashboard](http://127.0.0.1:8501) in your browser.
Check [API health](http://127.0.0.1:8000/health): status should be `ok` and
`detection_model_ready` should be `true`. Telegram may still be `not_configured` until
its chat is connected. Model initialisation and first provider requests may take time.
The launcher writes diagnostic logs under `logs/`.

## 6. Connect Telegram and verify the complete flow

1. In the dashboard, open **Alerts** and select **Connect Telegram chat**.
2. The API reads the bot's recent updates and saves the discovered recipient to
   `TELEGRAM_CHAT_ID` in `.env`. It should report that the chat is connected.
3. If no chat is found, send a fresh `/start` to your bot and try again.
   Avoid running another program that consumes this bot's updates during setup.
4. Open **Fire danger**. Wait for the feed timestamp and observation count; check
   [satellite data](http://127.0.0.1:8000/world-map/data) if the map cannot retrieve observations.
5. Open **Test** and inspect a license-cleared image or video to verify model inference.
6. Open **Live camera**, allow browser camera permission, then select **Start camera**.
   Use a safely displayed fire/smoke clip for testing; do not create a fire.
7. A qualifying persistent camera detection queues an annotated photo. Confirm the photo
   arrives in your Telegram conversation and that **Alerts** records the attempt.

Photos are sent from **Live camera**, not the image/video Test pages. A box alone does not
trigger a photo: camera alerts require confidence at least 50%, box area at least 1%,
one second of overlapping same-class detection, and the configured delivery/cooldown rules.
A Telegram error is recorded as a failure, not successful delivery.

If you edit credentials while services are running, restart them to reload configuration:

```sh
python scripts/run_app.py --restart
```

To stop the project's services:

```sh
python scripts/run_app.py --stop
```

## 7. Diagnose setup problems

| Symptom | Action |
| --- | --- |
| Wrong Python version | Recreate `.venv` with Python 3.11 and reinstall requirements. |
| Module not found | Use the same `.venv` interpreter for installation and launch. |
| NASA key missing/invalid | Verify the FIRMS key, `.env` filename and root location; save and restart. |
| No fresh satellite data | Check key status, network/provider availability and `logs/`; do not treat missing data as safety. |
| Bot not configured | Check token and chat ID; restart after manual edits. |
| No Telegram chat found | Send `/start` to your own bot, then retry Connect Telegram chat. |
| Telegram delivery fails | Check bot credentials, recipient, connectivity and whether the bot is blocked. |
| Camera unavailable | Allow browser permission and use localhost; check whether another app owns the camera. |
| Boxes but no photo | Check persistence, confidence, box area, cooldown and delivery history. |
| Port already in use | Use `--restart` for this project's services or select other ports. |

Optional environment diagnostics:

```sh
python scripts/check_env.py --fast-dev
```

This diagnostic checks CUDA too; a CUDA warning on a CPU-only system does not by itself
mean image detection is unusable. See [deployment](DEPLOYMENT.md) for refresh scheduling,
[limits](LIMITATIONS.md) for interpretation and [training](TRAINING.md) for optional retraining.

## Fire danger

Search a country or town and right-click a place for current weather and today's summary.
Heat observations default to 24 hours; controls offer 1, 3, 6, 12 or 24 hours.
The globe entrance animation runs on initial loading; tab switching preserves the view.
Weather follows the viewer's date and timezone. When today's forecast cannot be verified,
the weather layer is hidden with an unavailable/outdated warning.
Satellite freshness and retrieval errors appear beneath its controls.

## Live camera and alerts

Use **Alert cooldown (minutes)** below the camera to choose a wait between camera alerts
(0–1440 minutes). Select **Save interval** to apply it immediately and keep it after restart;
0 disables the wait. **Reset current wait** allows the next qualifying camera detection to
send without changing the saved interval or deleting history. It does not send a photo by itself.
Saved overrides live in the ignored `runs/alerts/camera_settings.json`; otherwise the YAML
default applies. Other alert cooldowns are unaffected.

Allow browser camera permission and press Start camera. Negotiated dimensions and fps
appear beside the detector update rate. Fullscreen includes video, boxes and status.
Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` locally. Open the bot, press Start,
and use Connect Telegram chat if needed. Alerts lists attempts and confirmed delivery.
Delete all includes a confirmation prompt before clearing local history and snapshots;
existing Telegram messages stay in Telegram.

Camera alerts use a dedicated `camera_cooldown_minutes` setting (default 5 minutes in
`configs/alerts.yaml`) separate from the 60-minute cooldown of other alerts. Multiple
browser tabs maintain isolated detection sessions via `X-Camera-Session` tracking with
a 5-minute idle eviction and a 256 MB memory budget.

## Configuration variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `FIRMS_MAP_KEY` | None | NASA FIRMS MAP_KEY for 24-hour satellite heat observations |
| `TELEGRAM_BOT_TOKEN` | None | Telegram bot token from BotFather |
| `TELEGRAM_CHAT_ID` | None | Telegram recipient chat ID for alert dispatch |
| `MEDFIRE_API_TOKEN` | None | Optional secret token requiring `X-MedFire-Token` header on write endpoints |
| `MEDFIRE_ALLOWED_HOSTS` | None | Extra comma-separated allowed Host headers beyond localhost/127.0.0.1 |
| `MEDFIRE_ALLOWED_ORIGINS` | None | Extra comma-separated allowed origins for cross-origin mutation requests |
| `MEDFIRE_VIDEO_TTL_HOURS` | `24` | Hours to retain completed video analysis results and weather cache tiles |
| `MEDFIRE_MAX_VIDEO_JOBS` | `2` | Maximum concurrent video processing jobs before returning HTTP 429 |
| `MEDFIRE_INCLUDE_LOW_CONFIDENCE` | `0` | Set to `1` to include low-confidence VIIRS satellite hotspots |
| `MEDFIRE_SKIP_WARMUP` | `0` | Set to `1` to bypass heavy YOLO inference warmup during launch/tests |

## Image and video inspection

Test contains Video studio and Image inspector. Images accept JPEG/PNG up to 10 MiB and
25 megapixels, matching the API. Video uploads go directly to FastAPI and accept configured
limits of 1,024 MiB, 600 seconds and 4K. Playback uses source quality; boxes follow the
analysed frame and the timeline shows analysis progress. Seeking gives that region priority.
Download the annotated export when processing finishes. Image/video tests do not send
Telegram photos; Live camera does.

## Development

Install `requirements-dev.txt`, then `npm ci`. Run `ruff check .`, `pytest -q` and `npm test`.
CI also reports Python and JavaScript coverage. `npm run format` formats browser assets.
See [training](TRAINING.md), [deployment](DEPLOYMENT.md) and [demo](DEMO.md).
