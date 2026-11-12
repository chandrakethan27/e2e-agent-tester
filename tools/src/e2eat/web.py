"""Launch the live run visualization (the Next.js app in web/) in a container that can only read runs/."""

from __future__ import annotations

import re
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Sequence

from .sandbox import Runner, runner_with_timeout

IMAGE = "e2eat-web:latest"
CONTAINER = "e2eat-web"
LABEL = "e2eat.web=1"
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PUBLISHED = re.compile(r"127\.0\.0\.1:(\d+)->3000")


def _check(port: int, run_id: str | None) -> None:
    if not 1 <= port <= 65535:
        raise ValueError(f"port {port} out of range")
    if run_id is not None and not _RUN_ID.match(run_id):
        raise ValueError(f"unsafe run id {run_id!r}")


def build_cmd(web_dir: Path) -> list[str]:
    return ["docker", "build", "--label", LABEL, "-t", IMAGE, str(web_dir)]


def run_cmd(runs_dir: Path, port: int, run_id: str | None) -> list[str]:
    _check(port, run_id)
    cmd = ["docker", "run", "-d", "--name", CONTAINER, "--label", LABEL,
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--memory", "512m",
           "-p", f"127.0.0.1:{port}:3000", "-v", f"{runs_dir}:/runs:ro", "-e", "RUNS_DIR=/runs"]
    if run_id:
        cmd += ["-e", f"DEFAULT_RUN_ID={run_id}"]
    return cmd + [IMAGE]


NODE_IMAGE = "node:22-alpine"


def lock_cmd(web_dir: Path) -> list[str]:
    """Regenerate web/package-lock.json inside a throwaway container, so no package manager ever runs on the host."""
    return ["docker", "run", "--rm", "--label", LABEL, "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "-v", f"{Path(web_dir).resolve()}:/app", "-w", "/app", NODE_IMAGE,
            "npm", "install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"]


def update_lockfile(web_dir: Path, runner: Runner = runner_with_timeout(600)) -> dict:
    _run(lock_cmd(web_dir), runner, "generating package-lock.json")
    lock = Path(web_dir) / "package-lock.json"
    if not lock.is_file():
        raise ValueError("npm finished but package-lock.json was not written")
    return {"lockfile": str(lock), "bytes": lock.stat().st_size}


def open_url(port: int, run_id: str | None) -> str:
    return f"http://127.0.0.1:{port}/" + (f"?run={run_id}" if run_id else "")


def _run(cmd: Sequence[str], runner: Runner, what: str) -> str:
    proc = runner(cmd)
    if proc.returncode != 0:
        raise ValueError(f"{what} failed: {(proc.stderr or proc.stdout).strip()[-600:]}")
    return proc.stdout.strip()


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def find_free_port(preferred: int, tries: int = 20, is_free: Callable[[int], bool] = port_is_free) -> int:
    for port in range(preferred, min(preferred + tries, 65536)):
        if is_free(port):
            return port
    raise ValueError(f"no free port in {preferred}-{preferred + tries - 1}; pass --port")


def running_port(runner: Runner) -> int | None:
    """Host port of the live view when its container is already running, else None."""
    proc = runner(["docker", "ps", "--filter", f"name=^{CONTAINER}$", "--filter", "status=running", "--format", "{{.Ports}}"])
    match = _PUBLISHED.search(proc.stdout or "") if proc.returncode == 0 else None
    return int(match[1]) if match else None


def status(runner: Runner = runner_with_timeout(30)) -> dict:
    port = running_port(runner)
    return {"running": port is not None, "port": port, "url": open_url(port, None) if port else None}


def wait_ready(url: str, timeout: float = 45.0, opener: Callable[..., object] = urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Poll the site's state endpoint until it answers, so the browser is never opened on a connection error."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with opener(url.split("?")[0] + "api/state", timeout=2) as response:  # type: ignore[attr-defined]
                if getattr(response, "status", 200) == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        if time.monotonic() >= deadline:
            return False
        sleep(1)


def start(
    runs_dir: Path,
    web_dir: Path,
    port: int,
    run_id: str | None,
    runner: Runner = runner_with_timeout(900),
    rebuild: bool = False,
    is_free: Callable[[int], bool] = port_is_free,
) -> dict:
    """Start the live view. A site that is already running (maybe for another session) is reused, not rebuilt or killed:
    it shows every run, and `?run=` selects one. A busy port moves to the next free one."""
    _check(port, run_id)
    existing = running_port(runner)
    if existing is not None and not rebuild:
        return {"url": open_url(existing, run_id), "container": CONTAINER, "port": existing, "reused": True}
    _run(build_cmd(web_dir), runner, "docker build of the web app")
    runner(["docker", "rm", "-f", CONTAINER])
    chosen = find_free_port(port, is_free=is_free)
    _run(run_cmd(runs_dir, chosen, run_id), runner, "starting the web container")
    return {"url": open_url(chosen, run_id), "container": CONTAINER, "port": chosen, "reused": False}


def stop(runner: Runner = runner_with_timeout(60)) -> None:
    runner(["docker", "rm", "-f", CONTAINER])
