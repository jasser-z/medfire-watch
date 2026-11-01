from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components

from dashboard.world_map import render_world_map

API_BASE_URL = os.environ.get("MEDFIRE_API_URL", "http://127.0.0.1:8000").rstrip("/")
PUBLIC_API_URL = os.environ.get("MEDFIRE_PUBLIC_API_URL", API_BASE_URL).rstrip("/")
SHOWCASE_ALERT = os.environ.get("MEDFIRE_SHOWCASE_ALERT") == "1"

st.set_page_config(page_title="MedFire Watch", layout="wide")
st.markdown(
    """<style>
    :root {--medfire-accent: #ffb474;}
    .block-container {padding-top: 4.25rem; padding-bottom: 1rem; max-width: 100%;}
    [data-testid="stHeader"] {background: #07101bf0; height: 3rem;}
    [data-testid="stAppViewContainer"] {background: radial-gradient(ellipse at 85% 0%, #132b3c 0%, #07101b 60%);}
    .medfire-brand {display: flex; align-items: center; gap: 12px; font-size: 1.05rem;
      font-weight: 750; letter-spacing: .16em; color: #f2f7fb; margin-bottom: .25rem;}
    .medfire-brand span {color: #ff925d; text-shadow: 0 0 18px #ff634c66;}
    .medfire-brand small {font-size: .6rem; color: #8ba8bb; letter-spacing: .18em;
      border-left: 1px solid #456; padding-left: 12px;}
    [data-baseweb="tab-list"] {gap: 10px; padding: 4px 0 8px; min-height: 54px; overflow-y: visible;}
    [data-baseweb="tab"] {height: 44px; min-height: 44px; padding: 10px 18px;
      border-radius: 10px; transition: background .2s, box-shadow .2s;}
    [data-baseweb="tab"] p {line-height: 1.5; margin: 0;}
    [data-baseweb="tab"]:hover {background: #193040;}
    [data-baseweb="tab"][aria-selected="true"] {background: #233343;
      box-shadow: inset 0 0 0 1px #7695aa33; color: #ffc38f;}
    [data-baseweb="tab-panel"] {padding-top: .6rem;}
    [data-testid="stFileUploader"] {border: 1px solid #7896aa44;
      border-radius: 14px; padding: 12px; background: #10202e;}
    .test-intro {padding: 22px 26px; margin: 4px 0 16px; border: 1px solid #7896aa44;
      border-radius: 18px; background: linear-gradient(120deg, #18364a, #0a1724); box-shadow: 0 15px 40px #0003;}
    .test-intro .kicker {font-size: .68rem; letter-spacing: .2em; color: #ffb474;}
    .test-intro h2 {font-size: 1.8rem; padding: 6px 0; margin: 0; color: #f1f7fc;}
    .test-intro p {color: #aac3d4; margin: 0; max-width: 760px;}
    .test-intro, .medfire-brand {animation: medfire-enter .5s ease both;}
    @keyframes medfire-enter {from {opacity: 0; transform: translateY(8px);} to {opacity: 1; transform: none;}}
    @media(max-width: 700px) {.block-container {padding: 3.75rem 1rem 1rem;}
      .medfire-brand small {display: none;} [data-baseweb="tab"] {padding: 10px 11px;}}
    @media(prefers-reduced-motion: reduce) {*, *::before, *::after {
      animation: none !important; transition: none !important;}}
    </style>"""
    '<div class="medfire-brand"><span>◉</span> MEDFIRE WATCH '
    "<small>EARTH · VISION · OBSERVATION</small></div>",
    unsafe_allow_html=True,
)


def api_request(method: str, path: str, **kwargs):
    try:
        response = requests.request(method, f"{API_BASE_URL}{path}", timeout=(4, 90), **kwargs)
    except requests.RequestException as exc:
        st.error(f"The MedFire API could not be reached ({type(exc).__name__}).")
        return None
    if not response.ok:
        detail = "The API request failed."
        try:
            detail = str(response.json().get("detail", detail))
        except ValueError:
            pass
        st.error(f"API error {response.status_code}: {detail}")
        return None
    try:
        return response.json()
    except ValueError:
        st.error("The API returned an unreadable response.")
        return None


debug_mode = str(st.query_params.get("debug", "")) == "1"
pages = st.tabs(["Fire danger", "Live camera", "Alerts", "Test"])

with pages[0]:
    render_world_map(debug=debug_mode)

with pages[1]:
    st.subheader("Live camera")
    st.write(
        "The camera is rendered natively at its negotiated resolution and frame rate; "
        "detector frames are sent separately."
    )
    components.iframe(f"{PUBLIC_API_URL}/live-camera{'?debug=1' if debug_mode else ''}", height=760, scrolling=False)
    st.caption(
        "Automatic snapshots require confidence ≥50%, at least 1% frame area, and one second of overlapping detection."
    )

with pages[2]:
    heading_column, delete_column = st.columns([4, 1], vertical_alignment="center")
    with heading_column:
        st.subheader("Camera snapshots")
    with delete_column:
        if st.button(
            "Delete all",
            key="delete_camera_history",
            disabled=SHOWCASE_ALERT,
            help="Clear local history and saved snapshots; Telegram messages remain.",
        ):
            cleared = api_request("DELETE", "/alerts/history")
            if cleared is not None:
                if cleared.get("remaining_snapshots"):
                    st.warning("History cleared. Some snapshots are busy; click Delete all again to remove them.")
                else:
                    st.success("Local snapshot history cleared.")
    st.write("Track the snapshots sent by the live camera, including delivery failures.")
    status = api_request("GET", "/alerts")
    if status and not status.get("configured") and not SHOWCASE_ALERT:
        st.info("Open your Telegram bot, press Start, then connect your chat here.")
        if st.button("Connect Telegram chat"):
            connected = api_request("POST", "/telegram/detect")
            if connected:
                st.success("Telegram chat connected.")

    @st.fragment(run_every=3)
    def camera_history():
        if SHOWCASE_ALERT:
            with st.container(border=True):
                photo, details = st.columns([1, 1.5], gap="large")
                with photo:
                    st.image(Path(__file__).parents[1] / "docs/screenshots/telegram-alert.png", width=403)
                with details:
                    st.markdown("### Recorded Telegram photo alert")
                    st.write("27 October 2026 · 23:42:04 UTC+01:00")
                    st.metric("Smoke confidence", "73%")
                    st.write("Fire and smoke boxes accompany the camera snapshot in Telegram.")
                    st.caption("Historical example · Telegram screenshot supplied by the author.")
            return
        result = api_request("GET", "/alerts/log")
        messages = result.get("messages", []) if result else []
        if not messages:
            st.info("No live-camera snapshot attempts have been recorded yet.")
        for item in messages[:20]:
            with st.container(border=True):
                st.write(("Delivered" if item.get("confirmed") else "Failed") + " · " + item.get("sent_at_utc", ""))
                if item.get("photo_name"):
                    response = requests.get(f"{API_BASE_URL}/alerts/snapshots/{item['photo_name']}", timeout=10)
                    if response.ok:
                        st.image(response.content, width=480)
                if item.get("confirmed"):
                    st.caption(f"Telegram message {item.get('message_id')}")
                else:
                    st.error(item.get("reason", "Snapshot delivery failed."))

    camera_history()
    if debug_mode:
        st.code(
            json.dumps({"api_base": API_BASE_URL, "debug": True, "camera_alerts_only": True}, indent=2), language="json"
        )

with pages[3]:
    st.markdown(
        """<section class="test-intro"><div class="kicker">DETECTION LAB · TEST</div>
    <h2>A closer look at fire and smoke.</h2><p>Play a video in its original quality, inspect live detection overlays,
    or check a single image. Use Live camera for monitored Telegram snapshots.</p></section>""",
        unsafe_allow_html=True,
    )
    video_tab, image_tab = st.tabs(["Video studio", "Image inspector"])
    with video_tab:
        components.iframe(f"{PUBLIC_API_URL}/video-test{'?debug=1' if debug_mode else ''}", height=790, scrolling=True)
        st.caption("Upload limits are shown in Video studio. Fullscreen keeps the video and boxes together.")
    with image_tab:
        upload_column, help_column = st.columns([2, 1], gap="large")
        with upload_column:
            uploaded = st.file_uploader(
                "Choose a photo (JPEG/PNG, up to 10 MiB and 25 megapixels)",
                type=["jpg", "jpeg", "png"],
                key="image_test",
            )
            if uploaded is not None:
                st.image(uploaded.getvalue(), caption="Original image", width="stretch")
                if st.button("Inspect for fire and smoke", type="primary"):
                    with st.spinner("Inspecting image…"):
                        result = api_request(
                            "POST", "/detect", files={"image": (uploaded.name, uploaded.getvalue(), uploaded.type)}
                        )
                    if result:
                        st.image(
                            base64.b64decode(result["annotated_image_base64"]),
                            caption="Detection result",
                            width="stretch",
                        )
        with help_column:
            st.markdown("### Image inspector")
            st.write("Upload a JPG, PNG or JPEG to view the original and the annotated result.")
            st.caption(
                "Predicted fire and smoke boxes are model estimates. "
                "Reflections, clouds and haze can be mistaken for smoke or fire."
            )
    if debug_mode:
        st.code(
            json.dumps(
                {"api_base": API_BASE_URL, "debug": True, "video_limit": "configured by detection.yaml"},
                indent=2,
            ),
            language="json",
        )
