from __future__ import annotations

import json
from pathlib import Path

import api.main as api
from alerts.manager import AlertManager


def test_camera_log_filters_text_sends_before_limiting(tmp_path: Path) -> None:
    manager = AlertManager(state_path=tmp_path / "state.json")
    rows = [{"sent_at_utc": "2026-10-27", "kind": "live_camera", "confirmed": True, "photo_name": "alert_a.jpg"}]
    rows += [{"sent_at_utc": "2026-10-28", "kind": "daily_digest", "confirmed": True}] * 120
    manager.log_path.write_text("\n".join(json.dumps(row) for row in rows))
    result = api.alert_log(manager)
    assert len(result["messages"]) == 1
    assert result["messages"][0]["photo_name"] == "alert_a.jpg"


def test_fullscreen_uses_shared_stage_not_native_video() -> None:
    player = api.local_video_test()
    assert "stage.requestFullscreen()" in player
    assert "v.requestFullscreen()" not in player
    assert 'id="v" controls' not in player
    assert "Math.min(w/vw,h/vh)" in player
