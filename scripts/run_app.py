from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import psutil

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start the MedFire Watch API and Streamlit dashboard.")
    parser.add_argument(
        "--fast-dev", action="store_true", help="Validate launch prerequisites without starting services."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Local bind address.")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--dashboard-port", type=int, default=8501)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--restart", action="store_true", help="Restart this workspace's existing MedFire services.")
    action.add_argument("--stop", action="store_true", help="Stop this workspace's existing MedFire services.")
    return parser.parse_args()


def validate_launch(args: argparse.Namespace) -> None:
    if not 1 <= args.api_port <= 65535 or not 1 <= args.dashboard_port <= 65535:
        raise ValueError("Service ports must be between 1 and 65535.")
    if args.api_port == args.dashboard_port:
        raise ValueError("API and dashboard must use different ports.")
    required_files = (
        ROOT / "api" / "main.py",
        ROOT / "dashboard" / "app.py",
        ROOT / "configs" / "alerts.yaml",
    )
    missing = [path for path in required_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Local application files are missing: {missing}")
    for module in ("uvicorn", "streamlit"):
        if importlib.util.find_spec(module) is None:
            raise ModuleNotFoundError(f"Required application dependency is unavailable: {module}")
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def rotate_log_file(log_path: Path, max_bytes: int = 5 * 1024 * 1024, backup_count: int = 3) -> None:
    """Rotate log file on startup if it exceeds max_bytes."""
    if not log_path.is_file():
        return
    try:
        if log_path.stat().st_size >= max_bytes:
            for i in range(backup_count - 1, 0, -1):
                src = log_path.with_name(f"{log_path.name}.{i}")
                dst = log_path.with_name(f"{log_path.name}.{i + 1}")
                if src.is_file():
                    src.replace(dst)
            log_path.replace(log_path.with_name(f"{log_path.name}.1"))
    except OSError:
        pass


def start_process(command: list[str], log_path: Path, env: dict[str, str] | None = None) -> subprocess.Popen[bytes]:
    with log_path.open("ab") as log_file:
        return subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW) if os.name == "nt" else 0,
        )


def check_port_available(host: str, port: int) -> None:
    """Fail before launch when a different process already owns the requested port."""
    for family, socktype, protocol, _, address in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        with socket.socket(family, socktype, protocol) as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind(address)
            except OSError as exc:
                raise RuntimeError(
                    f"Cannot bind {host}:{port}. The port may already be in use; "
                    "stop the existing service or choose another port."
                ) from exc
            return
    raise RuntimeError(f"Cannot resolve a bind address for {host}:{port}.")


def port_owner(host: str, port: int) -> psutil.Process | None:
    addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    addresses.update({"0.0.0.0", "::"})
    for connection in psutil.net_connections(kind="tcp"):
        if (
            connection.status == psutil.CONN_LISTEN
            and connection.laddr.port == port
            and connection.laddr.ip in addresses
            and connection.pid
        ):
            return psutil.Process(connection.pid)
    return None


def is_workspace_service(process: psutil.Process, kind: str) -> bool:
    """Never take ownership based on a port or a Python executable name alone."""
    try:
        if Path(process.cwd()).resolve() != ROOT:
            return False
        command = process.cmdline()
        if kind == "api":
            return "uvicorn" in command and "api.main:app" in command
        return "streamlit" in command and any(
            Path(argument.replace("\\", "/")).name == "app.py"
            and (ROOT / argument).resolve() == ROOT / "dashboard" / "app.py"
            for argument in command
        )
    except (psutil.Error, OSError):
        return False


def service_healthy(url: str, api: bool = False) -> bool:
    try:
        with urlopen(url, timeout=3) as response:
            return response.status == 200 and (not api or json.loads(response.read()).get("status") == "ok")
    except (URLError, TimeoutError, ValueError):
        return False


def stop_workspace_services(services: list[psutil.Process]) -> None:
    roots: dict[int, psutil.Process] = {}
    for service in services:
        root = service
        for ancestor in service.parents():
            try:
                if Path(ancestor.cwd()).resolve() == ROOT and any(
                    (ROOT / arg).resolve() == Path(__file__).resolve() for arg in ancestor.cmdline()
                ):
                    root = ancestor
            except (psutil.Error, OSError):
                continue
        roots[root.pid] = root
    for root in roots.values():
        try:
            processes = [*reversed(root.children(recursive=True)), root]
        except psutil.NoSuchProcess:
            continue
        for process in processes:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(processes, timeout=8)
        for process in alive:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=3)


def handle_existing_services(args: argparse.Namespace) -> bool:
    """Return True when an existing-instance/stop request is fully handled."""
    owners = [
        (kind, port, port_owner(args.host, port))
        for kind, port in [("api", args.api_port), ("dashboard", args.dashboard_port)]
    ]
    for kind, port, owner in owners:
        if owner is not None and not is_workspace_service(owner, kind):
            logger.error("Port %s belongs to another application (PID %s); leaving it untouched.", port, owner.pid)
            raise SystemExit(1)
    services = [owner for _, _, owner in owners if owner is not None]
    if args.stop or args.restart:
        if services:
            stop_workspace_services(services)
            logger.info("Stopped this workspace's existing MedFire services.")
        elif args.stop:
            logger.info("No MedFire services are running on the requested ports.")
        return args.stop
    if not services:
        return False
    api_url = f"http://{args.host}:{args.api_port}"
    dashboard_url = f"http://{args.host}:{args.dashboard_port}"
    if (
        len(services) == 2
        and service_healthy(f"{api_url}/health", api=True)
        and service_healthy(f"{dashboard_url}/_stcore/health")
    ):
        logger.info("MedFire is already running. Open %s (API %s).", dashboard_url, api_url)
        logger.info("Use --restart to restart it or --stop to stop it.")
        return True
    logger.error("An incomplete or unhealthy MedFire instance is running. Run this command with --restart.")
    raise SystemExit(1)


def wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: float = 120.0) -> bytes:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited with status {process.returncode} before becoming ready.")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return response.read()
        except (URLError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"Service did not become ready at {url}: {last_error}")


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    # On Windows the venv executable can be a launcher with a Python child.
    # Stopping only the launcher leaves the actual server listening on the port.
    try:
        children = psutil.Process(process.pid).children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except psutil.NoSuchProcess:
                pass
        _, alive = psutil.wait_procs(children, timeout=5)
        for child in alive:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> None:
    args = parse_args()
    validate_launch(args)
    if args.fast_dev:
        logger.info("Fast-dev launch checks passed; no services were started.")
        return

    if handle_existing_services(args):
        return

    for port in (args.api_port, args.dashboard_port):
        try:
            check_port_available(args.host, port)
        except RuntimeError as exc:
            logger.error("%s", exc)
            raise SystemExit(1) from None

    api_url = f"http://{args.host}:{args.api_port}"
    dashboard_url = f"http://{args.host}:{args.dashboard_port}"
    api_log = LOG_DIR / "api.log"
    dashboard_log = LOG_DIR / "dashboard.log"
    rotate_log_file(api_log)
    rotate_log_file(dashboard_log)
    api_process: subprocess.Popen[bytes] | None = None
    dashboard_process: subprocess.Popen[bytes] | None = None
    try:
        api_process = start_process(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "api.main:app",
                "--host",
                args.host,
                "--port",
                str(args.api_port),
            ],
            api_log,
        )
        health_bytes = wait_for_http(f"{api_url}/health", api_process)
        health = json.loads(health_bytes)
        if health.get("status") != "ok":
            raise RuntimeError(f"API health check is degraded: {health}")
        logger.info("API ready at %s (PID %s).", api_url, api_process.pid)

        dashboard_env = os.environ.copy()
        dashboard_env["MEDFIRE_API_URL"] = api_url
        dashboard_process = start_process(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "dashboard/app.py",
                "--server.address",
                args.host,
                "--server.port",
                str(args.dashboard_port),
                "--server.headless",
                "true",
                "--browser.gatherUsageStats",
                "false",
            ],
            dashboard_log,
            env=dashboard_env,
        )
        wait_for_http(dashboard_url, dashboard_process)
        logger.info(
            "Dashboard ready at %s (PID %s); logs: %s and %s. Press Ctrl+C to stop.",
            dashboard_url,
            dashboard_process.pid,
            api_log,
            dashboard_log,
        )
        while api_process.poll() is None and dashboard_process.poll() is None:
            time.sleep(1)
        raise RuntimeError("API or dashboard exited unexpectedly; check the service logs.")
    except KeyboardInterrupt:
        logger.info("Stopping local services.")
    finally:
        stop_process(dashboard_process)
        stop_process(api_process)


if __name__ == "__main__":
    main()
