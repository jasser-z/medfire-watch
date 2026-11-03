from __future__ import annotations

import importlib.util
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "local_launcher", Path(__file__).resolve().parents[1] / "scripts/run_app.py"
)
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def arguments(**changes):
    return Namespace(
        **{"host": "127.0.0.1", "api_port": 8000, "dashboard_port": 8501, "stop": False, "restart": False, **changes}
    )


def test_process_identity_requires_matching_workspace_and_service(tmp_path):
    process = SimpleNamespace(
        cwd=lambda: str(launcher.ROOT), cmdline=lambda: ["python", "-m", "uvicorn", "api.main:app"]
    )
    assert launcher.is_workspace_service(process, "api")
    assert not launcher.is_workspace_service(process, "dashboard")
    process.cwd = lambda: str(tmp_path)
    assert not launcher.is_workspace_service(process, "api")


def test_repeated_start_reuses_healthy_instance_without_stopping_or_spawning(monkeypatch, caplog):
    monkeypatch.setattr(launcher, "port_owner", lambda *args: SimpleNamespace(pid=123))
    monkeypatch.setattr(launcher, "is_workspace_service", lambda *args: True)
    monkeypatch.setattr(launcher, "service_healthy", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        launcher, "stop_workspace_services", lambda *args: pytest.fail("Existing services were stopped")
    )
    with caplog.at_level("INFO"):
        assert launcher.handle_existing_services(arguments())
    assert "already running" in caplog.text
    assert "http://127.0.0.1:8501" in caplog.text


def test_restart_refuses_unrelated_listener_before_stopping_anything(monkeypatch):
    monkeypatch.setattr(launcher, "port_owner", lambda *args: SimpleNamespace(pid=123))
    monkeypatch.setattr(launcher, "is_workspace_service", lambda process, kind: kind == "api")
    monkeypatch.setattr(launcher, "stop_workspace_services", lambda *args: pytest.fail("A process was stopped"))
    with pytest.raises(SystemExit) as error:
        launcher.handle_existing_services(arguments(restart=True))
    assert error.value.code == 1


def test_stop_is_idempotent_when_nothing_is_running(monkeypatch):
    monkeypatch.setattr(launcher, "port_owner", lambda *args: None)
    assert launcher.handle_existing_services(arguments(stop=True))
    assert not launcher.handle_existing_services(arguments())


def test_partial_instance_requires_explicit_restart(monkeypatch):
    monkeypatch.setattr(launcher, "port_owner", lambda host, port: SimpleNamespace(pid=123) if port == 8000 else None)
    monkeypatch.setattr(launcher, "is_workspace_service", lambda *args: True)
    with pytest.raises(SystemExit):
        launcher.handle_existing_services(arguments())
    stopped = []
    monkeypatch.setattr(launcher, "stop_workspace_services", lambda processes: stopped.extend(processes))
    assert not launcher.handle_existing_services(arguments(restart=True))
    assert [process.pid for process in stopped] == [123]


def test_rotate_log_file(tmp_path: Path) -> None:
    log_file = tmp_path / "test.log"
    # Small file not rotated
    log_file.write_text("hello", encoding="utf-8")
    launcher.rotate_log_file(log_file, max_bytes=100)
    assert log_file.is_file()
    assert not (tmp_path / "test.log.1").exists()

    # Exceeding file rotated
    log_file.write_text("x" * 200, encoding="utf-8")
    launcher.rotate_log_file(log_file, max_bytes=100)
    assert (tmp_path / "test.log.1").is_file()


def test_launcher_loads_env_before_building_both_service_environments(tmp_path, monkeypatch):
    import os
    (tmp_path / ".env").write_text("MEDFIRE_API_TOKEN=isolated-launcher-token\n", encoding="utf-8-sig")
    monkeypatch.setattr(launcher, "ROOT", tmp_path)
    # Track the key even when it was initially absent: dotenv itself writes os.environ.
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "before-test")
    monkeypatch.delenv("MEDFIRE_API_TOKEN", raising=False)
    monkeypatch.setattr(launcher, "parse_args", lambda: Namespace(fast_dev=True))
    observed = []
    monkeypatch.setattr(launcher, "validate_launch", lambda args: observed.append(os.getenv("MEDFIRE_API_TOKEN")))
    launcher.main()
    assert observed == ["isolated-launcher-token"]


def test_launcher_rejects_remote_bind_without_token(monkeypatch):
    monkeypatch.setenv("MEDFIRE_API_TOKEN", "")
    with pytest.raises(ValueError, match="Remote binding requires"):
        launcher.validate_launch(arguments(host="0.0.0.0"))
