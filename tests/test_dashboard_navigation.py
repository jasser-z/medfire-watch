from __future__ import annotations

from pathlib import Path

from api.routers.video import local_video_test


def test_local_playback_starts_before_prepared_prediction_request():
    html = local_video_test()
    assert "/video-test/app.mjs" in html
    html = (Path(__file__).parents[1] / "dashboard/video_player.mjs").read_text(encoding="utf-8")
    assert "URL.createObjectURL(file)" in html
    assert html.index("v.play().catch") < html.index("fetch('/video-inputs/' + input.input_id + '/predict'")
    assert "stage.requestFullscreen()" in html


def test_requested_navigation_order_and_removed_page():
    source = (Path(__file__).resolve().parents[1] / "dashboard" / "app.py").read_text(encoding="utf-8")
    assert 'st.tabs(["Fire danger", "Live camera", "Alerts", "Test"])' in source
    assert "How well does it work" not in source


def test_live_camera_uses_native_video_not_streamlit_webrtc():
    app = (Path(__file__).resolve().parents[1] / "dashboard" / "app.py").read_text(encoding="utf-8")
    page = (Path(__file__).resolve().parents[1] / "dashboard" / "live_camera.html").read_text(encoding="utf-8")
    assert "/live-camera/app.mjs" in page
    page += (Path(__file__).parents[1] / "dashboard/live_camera.mjs").read_text(encoding="utf-8")
    assert "streamlit_webrtc" not in app
    assert "components.iframe(f\"{PUBLIC_API_URL}/live-camera{'?debug=1'" in app
    assert "navigator.mediaDevices.getUserMedia" in page
    assert "frameRate: { ideal: 30 }" in page
    assert "alert_id" in page


def test_map_has_observed_layer_menu_and_no_automatic_orbit():
    page = (Path(__file__).resolve().parents[1] / "dashboard" / "satellite_map.html").read_text(encoding="utf-8")
    assert "Satellite heat detections" in page
    assert 'id="time"' not in page
    assert 'id="replay"' not in page
    assert "requestAnimationFrame(orbit)" not in page
    assert "Pause orbit" not in page
