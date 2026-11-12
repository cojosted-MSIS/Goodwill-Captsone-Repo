"""Start a fresh mock HMIS and a fresh intake app for the demo and screenshot scripts.

Fresh matters: a mock HMIS left running from an earlier run still holds the same synthetic
clients and rejects them as possible duplicates. The app uses the rule-based stub unless REALLMS
is chosen, and an in-memory store unless given a file (the web demo uses a file, so its app server
can be stopped and started again). Server logs go to a temporary folder.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_loader import load_config  # noqa: E402


@dataclass
class Servers:
    app_url: str
    hmis_url: str
    logs: Path
    stop_app: Callable[[], None]  # really stops the app server (the demo's K key); the mock HMIS keeps running
    start_app: Callable[[], None]
    app_running: Callable[[], bool]


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_until_up(url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise RuntimeError(f"{url} did not start; see the server logs")


@contextmanager
def fresh_servers(app_port: int = 8000, parser: str = "rule_stub", model: str | None = None,
                  email_channel: bool = True, db: str = ":memory:", demo_reset: bool = False) -> Iterator[Servers]:
    """The email demo and the screenshots use the email channel and the demo-only staff views that show
    draft contents, so both are switched on by default here. The web demo turns them off and the demo reset on."""
    hmis_url = load_config().settings.hmis_base_url
    hmis_port = urlparse(hmis_url).port or 80
    for port in (hmis_port, app_port):
        if port_in_use(port):
            sys.exit(f"Port {port} is in use. Stop whatever is running there (an earlier mock HMIS or app) and retry.")
    logs = Path(tempfile.mkdtemp(prefix="intake-demo-"))
    env = {**os.environ, "INTAKE_PARSER": parser}
    app_cmd = [sys.executable, "-m", "app", "--port", str(app_port), "--db", db, "--parser", parser]
    if model:
        app_cmd += ["--model", model]
    if email_channel:
        app_cmd += ["--email-channel", "--draft-content-views"]
    if demo_reset:
        app_cmd.append("--demo-reset")
    app_url = f"http://127.0.0.1:{app_port}"
    hmis: subprocess.Popen | None = None
    app: subprocess.Popen | None = None

    def start_app() -> None:
        nonlocal app
        if app is None:
            app = subprocess.Popen(app_cmd, cwd=ROOT, env=env, stdout=open(logs / "app.log", "a"), stderr=subprocess.STDOUT)
            wait_until_up(f"{app_url}/api/v1/ping")

    def stop_app() -> None:
        nonlocal app
        if app is not None:
            app.terminate()
            try:
                app.wait(timeout=10)
            except subprocess.TimeoutExpired:
                app.kill()
            app = None

    try:
        hmis = subprocess.Popen([sys.executable, "-m", "mock_hmis", "--port", str(hmis_port)], cwd=ROOT, env=env,
                                stdout=open(logs / "mock_hmis.log", "w"), stderr=subprocess.STDOUT)
        start_app()
        wait_until_up(f"{hmis_url}/docs")
        yield Servers(app_url, hmis_url, logs, stop_app, start_app, lambda: app is not None)
    finally:
        stop_app()
        if hmis is not None:
            hmis.terminate()
            try:
                hmis.wait(timeout=10)
            except subprocess.TimeoutExpired:
                hmis.kill()
