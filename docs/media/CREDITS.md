# Media credits and capture

## NASA source

NASA Goddard Space Flight Center / Grace Weikert, FireSense prescribed-burn footage,
Fishlake National Forest, Utah, October 2023. The NASA library record identifies NASA GSFC
as the source and Grace Weikert as photographer; no third-party copyright is listed.
The selected segment is 118–130 seconds of the source, showing aerial fire and smoke
without faces. Source audio is omitted. Frames, boxes and UI captures are derived displays.

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

The script uses 1440×900 headless Chromium, separate local service ports, isolated alert
history, empty Telegram credentials and Chromium's fake-video-capture flag. It captures
real detector outputs. The Alerts view shows connection setup with an empty isolated history;
it does not claim a successful Telegram delivery. Camera screenshots precede delivery attempts.
Streamlit's supported `client.toolbarMode` and `ui.hideTopBar` settings hide toolbar controls.
Both GIFs derive from 20-second Playwright recordings, without source audio.
The map recording uses a capture-only JavaScript export to control the existing MapLibre camera;
provider data, geometry and application styling are real and unmodified.
The populated feed's empty-state message is checked using Chromium's computed styles.
City captures must contain rendered buildings with a camera pitch of at least 50 degrees.

## Capture inventory

All eight PNG captures are 1440×900: `fire-danger.png`, `satellite-detections.png`, `map-tunis.png`,
`map-marseille.png`, `image-inspector.png`, `video-studio.png`, `live-camera.png` and `alerts.png` under
`docs/screenshots/`. The camera uses a recorded stream, not a physical camera.
`demo.gif` shows live prediction; `earth-zoom.gif` shows the globe-to-Marseille approach and a 3D orbit.
Each is 20 seconds at 6 fps, below 8 MB. The encoder chooses 640, 560 or 480 pixels
in width to meet the size limit while preserving the full browser viewport's aspect ratio.
The capture source uses NASA's medium-resolution rendition. Annotations are actual model predictions.

| GIF | Dimensions | Duration | Bytes |
| --- | --- | --- | --- |
| `demo.gif` | 640×400 | 20 seconds | 6,989,315 |
| `earth-zoom.gif` | 480×300 | 20 seconds | 7,234,775 |

## Author contribution

`docs/screenshots/telegram-alert.png` is the Telegram screenshot supplied by Jasser Zormati.
It is included as supplied: the medfire-watch bot and annotated photo are visible, without
personal names, chat identifiers or phone notifications. The message timestamp is
2026-10-27T23:42:04+01:00, and the caption reports smoke confidence of 73%.
This screenshot documents a historical delivery separately from the automated capture run.
The underlying footage source has not been supplied; its attribution remains to be confirmed.
Physical-webcam acceptance is separate from the synthetic-camera demonstration.
