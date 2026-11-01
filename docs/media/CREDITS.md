# Media credits and capture

## NASA source

NASA Goddard Space Flight Center / Grace Weikert, FireSense prescribed-burn footage,
Fishlake National Forest, Utah, October 2023. The NASA library record identifies NASA GSFC
as the source and Grace Weikert as photographer; no third-party copyright is listed.
Video playback uses seconds 118–130 (aerial flames). The simulated camera uses seconds
69–77 (forest-edge fire), and image inspection uses a frame at second 99 (distant smoke).
These scenes have no faces. Source audio is omitted. Boxes are actual detector output.

[NASA library record][nasa] · [NASA media guidelines](https://www.nasa.gov/nasa-brand-center/images-and-media/)

[nasa]: https://images.nasa.gov/details/NASAFIRESENSE_3840x2160_23.976fps_AAC_48kHz_Stereo_Progressive

NASA media use does not imply NASA endorsement. The original media and intermediate
recordings stay in ignored runtime storage; this repository publishes only selected UI captures.

## Map captures

EOX Sentinel-2 cloudless 2025 contains modified Copernicus Sentinel data 2025.
Credit EOX IT Services GmbH / EOxCloudless. Free imagery and adapted screenshots carry
CC BY-NC-SA 4.0 conditions. Map details: OpenFreeMap, © OpenMapTiles,
© OpenStreetMap contributors (ODbL). Place names: GeoNames. Countries: Natural Earth.
Weather: European Union / Copernicus EMS / GWIS / ECMWF and Open-Meteo.
Observations: NASA FIRMS / LANCE / VIIRS SNPP NRT.
[Full terms and provider links](../../THIRD_PARTY_NOTICES.md)

## Reproduce

Install the development requirements, then `python -m pip install playwright` and
`python -m playwright install chromium`. Supply only a license-cleared clip with no faces:

```sh
python scripts/capture_media.py --video path/to/cleared-fire-clip.mp4
```

Use `--camera-video` and `--image-video` with separate license-cleared scenes to avoid
repeating one frame across different features.

The script uses 1440×900 headless Chromium, separate local service ports, isolated alert
history, empty Telegram credentials and Chromium's fake-video-capture flag. It captures
real detector outputs. `MEDFIRE_SHOWCASE_ALERT=1` is set only in capture subprocesses to show
the author's supplied historical Telegram screenshot in a labelled, read-only card.
It does not insert delivery records, send messages or alter the actual user's alert history.
Normal application launches show actual delivery history. Camera screenshots precede delivery attempts.
Streamlit's supported `client.toolbarMode` and `ui.hideTopBar` settings hide toolbar controls.
The prediction GIF derives from a 20-second Playwright recording, without source audio.
The map GIF uses 240 fully loaded PNG captures at 12 fps, so network waits are excluded
from the animation. Official weather colours stay enabled throughout the journey.
The map capture uses a capture-only JavaScript export to control the existing MapLibre camera;
provider data, geometry and application styling are real and unmodified.
The populated feed's empty-state message is checked using Chromium's computed styles.
City captures must contain rendered buildings with a camera pitch of at least 50 degrees.

## Capture inventory

The automated map, image and video screenshots are 1440×900. The author supplied replacement
versions of `alerts.png` (1585×992) and `live-camera.png` (1586×992); these are included unchanged.
They supersede the automated captures of those views. The camera showcase uses a recorded
stream, not a physical camera. These supplied replacements are presentation assets;
they are not additional model-evaluation evidence.
`demo.gif` shows live prediction; `earth-weather-3d.gif` shows the globe-to-Marseille approach and a 3D orbit.
Each is 20 seconds and below 8 MB. Encoding avoids dithering to prevent patterned trails.
The weather animation keeps 12 fps; resolution and palette adapt to the size limit.
The capture source uses NASA's medium-resolution rendition. Annotations are actual model predictions.

| GIF | Dimensions | Duration | Bytes |
| --- | --- | --- | --- |
| `demo.gif` | 560×350, 4 fps | 20 seconds | 4,458,365 |
| `earth-weather-3d.gif` | 400×250, 12 fps during movement | 20 seconds | 6,908,127 |

## Author contribution

`docs/screenshots/telegram-alert.png` is the Telegram screenshot supplied by Jasser Zormati.
It is included as supplied: the medfire-watch bot and annotated photo are visible, without
personal names, chat identifiers or phone notifications. The message timestamp is
2026-10-27T23:42:04+01:00, and the caption reports smoke confidence of 73%.
This screenshot documents a historical delivery separately from the automated capture run.
The underlying footage source has not been supplied; its attribution remains to be confirmed.
Physical-webcam acceptance is separate from the synthetic-camera demonstration.
