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
real detector outputs. The Alerts view documents local attempts with delivery disabled.
Streamlit's supported `client.toolbarMode` and `ui.hideTopBar` settings hide toolbar controls.
The GIF derives from the final 20 seconds of a Playwright recording, without source audio.

## Capture inventory

All seven PNG captures are 1440×900: `fire-danger.png`, `map-tunis.png`, `map-marseille.png`,
`image-inspector.png`, `video-studio.png`, `live-camera.png` and `alerts.png` under
`docs/screenshots/`. The camera uses a recorded stream, not a physical camera.
`demo.gif` is 20 seconds, 640×400, 5 fps, and 6,023,955 bytes (below 8 MB).
The capture source uses NASA's medium-resolution rendition. Annotations are actual model predictions.

## Author contribution

A phone screenshot of an actual Telegram photo alert is still required. Blur personal names,
chat identifiers and notifications. Physical-webcam acceptance and real Telegram delivery
are separate from the synthetic-camera demonstration.
