from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
from medfire_watch.config import load_env

from dashboard.world_map import render_world_map

load_env()

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
    .alerts-intro {padding: 24px 28px; border: 1px solid #7896aa44; border-radius: 18px;
      background: linear-gradient(115deg, #173449, #0a1825); margin: 8px 0 18px;}
    .alerts-intro .kicker {font-size: .7rem; letter-spacing: .18em; color: #ffb474;}
    .alerts-intro h2 {margin: 6px 0; padding: 0; color: #f1f7fc; font-size: 1.9rem;}
    .alerts-intro p {color: #aac3d4; margin: 0; max-width: 780px;}
    .connection-status {display: flex; align-items: center; gap: 10px; min-height: 44px; color: #b8ccda;}
    .connection-dot {width: 8px; height: 8px; border-radius: 50%; background: #ffc277;
      box-shadow: 0 0 0 5px #ffc27712; flex-shrink: 0;}
    .connection-status.connected .connection-dot {background: #77dfbb; box-shadow: 0 0 0 5px #77dfbb12;}
    .st-key-alerts_toolbar {padding: 14px 18px; background: #0c1b29; border: 1px solid #7896aa33;
      border-radius: 14px; margin-bottom: 12px;}
    .st-key-alerts_toolbar button {border-radius: 10px; min-height: 44px; font-weight: 600;}
    .st-key-detect_telegram_chat button {color: #15212b; background: #ffb474; border-color: #ffb474;}
    .st-key-detect_telegram_chat button:hover {color: #15212b; background: #ffc38f; border-color: #ffc38f;}
    .st-key-delete_camera_history button {color: #ffb5aa; border-color: #ff827755; background: #ff827709;}
    .st-key-delete_camera_history button:hover {border-color: #ff8277; background: #ff827718;}
    .snapshot-empty {padding: 48px 24px; border: 1px dashed #7896aa55; border-radius: 16px;
      text-align: center; background: #0b192655; margin: 16px 0;}
    .snapshot-empty .symbol {color: #ffb474; font-size: 2rem; margin-bottom: 8px;}
    .snapshot-empty h3 {font-size: 1.2rem; margin: 0; padding: 0; color: #edf5fc;}
    .snapshot-empty p {color: #aac3d4; max-width: 540px; margin: 10px auto 0;}
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
    headers = dict(kwargs.pop("headers", None) or {})
    token = os.environ.get("MEDFIRE_API_TOKEN")
    if token:
        headers["X-MedFire-Token"] = token
    try:
        response = requests.request(method, f"{API_BASE_URL}{path}", headers=headers, timeout=(4, 90), **kwargs)
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
storage_panel = st.container()
pages = st.tabs(["Fire danger", "Live camera", "Alerts", "Test"])

with pages[0]:
    render_world_map(debug=debug_mode)

with pages[1]:
    st.subheader("Live camera")
    st.write(
        "The camera is rendered natively at its negotiated resolution and frame rate; "
        "detector frames are sent separately."
    )
    components.iframe(f"{PUBLIC_API_URL}/live-camera{'?debug=1' if debug_mode else ''}", height=940, scrolling=True)
    st.caption(
        "Automatic snapshots require confidence ≥50%, at least 1% frame area, and one second of overlapping detection."
    )


@st.cache_data(ttl=300)
def _load_snapshot(photo_name: str) -> bytes | None:
    req_headers = {}
    if token := os.environ.get("MEDFIRE_API_TOKEN"):
        req_headers["X-MedFire-Token"] = token
    try:
        response = requests.get(f"{API_BASE_URL}/alerts/snapshots/{photo_name}", headers=req_headers, timeout=10)
        if response.ok:
            return response.content
    except requests.RequestException:
        pass
    return None


with pages[2]:
    st.markdown(
        '<section class="alerts-intro"><div class="kicker">ALERT CENTER · TELEGRAM</div>'
        "<h2>Camera snapshots</h2><p>Follow fire and smoke snapshots from your live camera, "
        "check delivery results, and manage your Telegram connection.</p></section>",
        unsafe_allow_html=True,
    )
    status = api_request("GET", "/alerts")
    configured = bool(status and status.get("configured"))
    with st.container(key="alerts_toolbar"):
        connection_column, detect_column, delete_column = st.columns([3, 1.6, 1], vertical_alignment="center")
        with connection_column:
            if SHOWCASE_ALERT:
                connection_label, connection_class = "Historical alert preview", ""
            elif status is None:
                connection_label, connection_class = "Connection status unavailable", ""
            elif configured:
                connection_label, connection_class = "Telegram configured", " connected"
            else:
                connection_label, connection_class = "Telegram setup needed", ""
            st.markdown(
                f'<div class="connection-status{connection_class}"><span class="connection-dot"></span>'
                f"<strong>{connection_label}</strong></div>",
                unsafe_allow_html=True,
            )
        with detect_column:
            if st.button(
                "Re-detect Telegram chat" if configured else "Detect Telegram chat",
                key="detect_telegram_chat",
                type="primary",
                use_container_width=True,
                disabled=SHOWCASE_ALERT or status is None,
                help="Open your bot in Telegram and send a new message before detecting your chat.",
            ):
                with st.spinner("Finding your Telegram chat…"):
                    connected = api_request("POST", "/telegram/detect")
                if connected:
                    st.session_state.telegram_connection_notice = "Telegram chat connected successfully."
                    st.rerun()
        with delete_column:
            if st.button(
                "Delete all",
                key="delete_camera_history",
                use_container_width=True,
                disabled=SHOWCASE_ALERT or status is None,
                help="Clear local history and saved snapshots; Telegram messages remain.",
            ):
                st.session_state.confirm_delete_all = True

    if notice := st.session_state.pop("telegram_connection_notice", None):
        st.success(notice)
    if not SHOWCASE_ALERT:
        st.caption(
            "Need to reconnect? Open your Telegram bot, press Start or send a new message, then select Detect."
            if not configured
            else "New snapshots are sent to your configured Telegram chat. "
            "Re-detect after sending your bot a fresh message."
        )
    with st.container():
        if "confirm_delete_all" not in st.session_state:
            st.session_state.confirm_delete_all = False
        if st.session_state.confirm_delete_all:
            st.warning("Delete all local snapshots and delivery history? Messages in Telegram will remain.")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Confirm", key="delete_confirm_yes", type="primary"):
                    cleared = api_request("DELETE", "/alerts/history")
                    _load_snapshot.clear()
                    st.session_state.confirm_delete_all = False
                    if cleared is not None:
                        if cleared.get("remaining_snapshots"):
                            st.warning(
                                "History cleared. Some snapshots are busy; click Delete all again to remove them."
                            )
                        else:
                            st.success("Local snapshot history cleared.")
                    st.rerun()
            with col2:
                if st.button("Cancel", key="delete_confirm_no"):
                    st.session_state.confirm_delete_all = False
                    st.rerun()

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
        if result is None:
            return
        messages = result.get("messages", [])
        if not messages:
            st.markdown(
                '<div class="snapshot-empty"><div class="symbol">◎</div><h3>Ready for the first snapshot</h3>'
                "<p>Start Live camera to monitor for fire and smoke. Snapshot attempts and Telegram delivery "
                "results will appear here automatically.</p></div>",
                unsafe_allow_html=True,
            )
            return
        delivered = sum(bool(item.get("confirmed")) for item in messages)
        total_column, delivered_column, failed_column = st.columns(3)
        total_column.metric("Snapshot attempts", len(messages))
        delivered_column.metric("Delivered", delivered)
        failed_column.metric("Failed", len(messages) - delivered)
        st.caption("Recent snapshots · newest first · showing up to 20 attempts")
        for item in messages[:20]:
            with st.container(border=True):
                st.write(("Delivered" if item.get("confirmed") else "Failed") + " · " + item.get("sent_at_utc", ""))
                if item.get("photo_name"):
                    photo_bytes = _load_snapshot(item["photo_name"])
                    if photo_bytes:
                        st.image(photo_bytes, width=480)
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

with storage_panel.expander("Storage & cleanup"):
    st.write(
        "Free disk space used by processed videos, detection results, local snapshots "
        "and downloaded map/weather caches."
    )
    usage = api_request("GET", "/runtime-cache")
    if usage:
        stored = sum(group["bytes"] for group in usage["storage"].values())
        files = sum(group["files"] for group in usage["storage"].values())
        st.caption(
            f"Generated files: {files:,} · {stored / 1024**2:.1f} MiB · active video jobs: {usage['active_video_jobs']}"
        )
    snapshots = st.checkbox(
        "Include saved snapshots and local Telegram delivery history", value=True, key="clear_snapshots"
    )
    providers = st.checkbox("Include downloaded satellite and weather caches", value=True, key="clear_providers")
    st.caption(
        "Running/paused jobs and active downloads are protected. "
        "Model files, datasets, credentials and settings are kept. "
        "Telegram messages stay in Telegram. New camera alerts and map requests can create new files; "
        "stop the live camera first if you want storage to stay empty."
    )
    if notice := st.session_state.pop("cache_cleanup_notice", None):
        st.success(notice)
    if st.button("Clear generated data…", key="clear_runtime_data", disabled=usage is None):
        st.session_state.confirm_cache_cleanup = True
    if st.session_state.get("confirm_cache_cleanup"):
        st.warning("Permanently delete completed video results and the selected local data? This cannot be undone.")
        confirm, keep = st.columns(2)
        if confirm.button("Confirm cleanup", key="confirm_runtime_cleanup", type="primary"):
            result = api_request(
                "DELETE",
                "/runtime-cache",
                params={"include_snapshots": str(snapshots).lower(), "include_provider_cache": str(providers).lower()},
            )
            if result is not None:
                st.cache_data.clear()
                st.session_state.confirm_cache_cleanup = False
                st.session_state.cache_cleanup_notice = (
                    f"Removed {result['deleted_video_files']} video files, {result['deleted_snapshots']} snapshots, "
                    f"{result['deleted_attempts']} history entries and "
                    f"{result['deleted_provider_files']} provider cache files. "
                    f"Protected {result['active_video_jobs']} active video jobs. "
                    + (
                        "Some busy files were kept; retry after activity stops."
                        if result["busy_cache_entries"] or result["remaining_snapshots"]
                        else ""
                    )
                )
                st.rerun()
        if keep.button("Keep data", key="keep_runtime_data"):
            st.session_state.confirm_cache_cleanup = False
            st.rerun()
