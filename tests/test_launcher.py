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
