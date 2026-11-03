from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest


def test_storage_panel_requires_confirmation_and_preserves_selected_options(monkeypatch):
    calls = []
    usage = {"storage": {"videos": {"bytes": 1024, "files": 2}}, "active_video_jobs": 1}

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/runtime-cache"):
            data = (
                usage
                if method == "GET"
                else {
                    **usage,
                    "deleted_video_files": 2,
                    "deleted_provider_files": 0,
                    "deleted_snapshots": 1,
                    "deleted_attempts": 1,
                    "remaining_snapshots": 0,
                    "busy_cache_entries": 0,
                }
            )
        elif url.endswith("/alerts/log"):
            data = {"messages": []}
        else:
            data = {"configured": False}
        return SimpleNamespace(ok=True, json=lambda: data)

    monkeypatch.setattr("requests.request", request)
    monkeypatch.setenv("MEDFIRE_API_URL", "http://isolated-test")
    monkeypatch.setenv("MEDFIRE_PUBLIC_API_URL", "http://isolated-test")
    app = AppTest.from_file(Path(__file__).parents[1] / "dashboard" / "app.py").run(timeout=30)
    assert not app.exception
    app.checkbox(key="clear_providers").uncheck().run()
    app.button(key="clear_runtime_data").click().run()
    assert not app.exception
    assert app.session_state["confirm_cache_cleanup"]
    assert not any(method == "DELETE" for method, _, _ in calls)
    app.button(key="confirm_runtime_cleanup").click().run()
    assert not app.exception
    deletions = [kwargs for method, url, kwargs in calls if method == "DELETE" and url.endswith("/runtime-cache")]
    assert len(deletions) == 1
    assert deletions[0]["params"] == {"include_snapshots": "true", "include_provider_cache": "false"}
    assert not app.session_state["confirm_cache_cleanup"]
    assert any("Removed 2 video files" in message.value for message in app.success)
