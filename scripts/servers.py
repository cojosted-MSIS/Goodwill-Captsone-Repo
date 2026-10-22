"""Start a fresh mock HMIS and a fresh intake app for the demo and screenshot scripts.

Fresh matters: a mock HMIS left running from an earlier run still holds the same synthetic
clients and rejects them as possible duplicates. The app uses an in-memory store and the
rule-based stub unless REALLMS is chosen. Server logs go to a temporary folder.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_loader import load_config  # noqa: E402


@dataclass(frozen=True)
class Servers:
    app_url: str
    hmis_url: str
    logs: Path


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
def fresh_servers(app_port: int = 8000, parser: str = "rule_stub", model: str | None = None) -> Iterator[Servers]:
    hmis_url = load_config().settings.hmis_base_url
    hmis_port = urlparse(hmis_url).port or 80
    for port in (hmis_port, app_port):
        if port_in_use(port):
            sys.exit(f"Port {port} is in use. Stop whatever is running there (an earlier mock HMIS or app) and retry.")
    logs = Path(tempfile.mkdtemp(prefix="intake-demo-"))
    env = {**os.environ, "INTAKE_PARSER": parser}
    app_cmd = [sys.executable, "-m", "app", "--port", str(app_port), "--db", ":memory:", "--parser", parser]
    if model:
        app_cmd += ["--model", model]
    procs = []
    try:
        procs.append(subprocess.Popen([sys.executable, "-m", "mock_hmis", "--port", str(hmis_port)], cwd=ROOT, env=env,
                                      stdout=open(logs / "mock_hmis.log", "w"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen(app_cmd, cwd=ROOT, env=env,
                                      stdout=open(logs / "app.log", "w"), stderr=subprocess.STDOUT))
        app_url = f"http://127.0.0.1:{app_port}"
        wait_until_up(f"{app_url}/demo/scenarios")
        wait_until_up(f"{hmis_url}/docs")
        yield Servers(app_url, hmis_url, logs)
    finally:
        for p in procs:
            p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
